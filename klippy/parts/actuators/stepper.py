# Printer stepper support
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, math
from messaging import msg
from messaging import Kerr as error
import chelper, homing
from parts import actuator

# Interface to low-level mcu and chelper code
class MCU_stepper:
    def __init__(self, name, step_pin_params, dir_pin_params, step_dist, units_in_radians = False):
        self._name = name
        self._step_dist = step_dist
        self._units_in_radians = units_in_radians
        self._mcu = step_pin_params['chip']
        self._oid = oid = self._mcu.create_oid()
        self._mcu.register_config_callback(self._build_config)
        self._step_pin = step_pin_params['pin']
        self._invert_step = step_pin_params['invert']
        if dir_pin_params['chip'] is not self._mcu:
            raise self._mcu.get_printer().config_error("Stepper dir pin must be on same mcu as step pin")
        self._dir_pin = dir_pin_params['pin']
        self._invert_dir = dir_pin_params['invert']
        self._mcu_position_offset = self._tag_position = 0.
        self._min_stop_interval = 0.
        self._reset_cmd_id = self._get_position_cmd = None
        self._active_callbacks = []
        ffi_main, self._ffi_lib = chelper.get_ffi()
        self._stepqueue = ffi_main.gc(self._ffi_lib.stepcompress_alloc(oid), self._ffi_lib.stepcompress_free)
        self._mcu.register_stepqueue(self._stepqueue)
        self._stepper_kinematics = None
        self._itersolve_generate_steps = self._ffi_lib.itersolve_generate_steps
        self._itersolve_check_active = self._ffi_lib.itersolve_check_active
        self._trapq = ffi_main.NULL
    def get_mcu(self):
        return self._mcu
    def get_name(self, short=False):
        if short and self._name.startswith("stepper "):
            return self._name.split(" ")[1]
        return self._name
    # get/set if distances in radians instead of millimeters
    def units_in_radians(self, value = False):
        if value:
            self._units_in_radians = True
        else:
            return self._units_in_radians
    def _dist_to_time(self, dist, start_velocity, accel):
        # Calculate the time it takes to travel a distance with constant accel
        time_offset = start_velocity / accel
        return math.sqrt(2. * dist / accel + time_offset**2) - time_offset
    def set_max_jerk(self, max_halt_velocity, max_accel):
        # Calculate the firmware's maximum halt interval time
        last_step_time = self._dist_to_time(self._step_dist, max_halt_velocity, max_accel)
        second_last_step_time = self._dist_to_time(2. * self._step_dist, max_halt_velocity, max_accel)
        self._min_stop_interval = second_last_step_time - last_step_time
    def setup_itersolve(self, alloc_func, *params):
        ffi_main, ffi_lib = chelper.get_ffi()
        sk = ffi_main.gc(getattr(ffi_lib, alloc_func)(*params), ffi_lib.free)
        self.set_stepper_kinematics(sk)
    def _build_config(self):
        max_error = self._mcu.get_max_stepper_error()
        min_stop_interval = max(0., self._min_stop_interval - max_error)
        self._mcu.add_config_cmd("config_stepper oid=%d step_pin=%s dir_pin=%s min_stop_interval=%d invert_step=%d" % 
            (self._oid, self._step_pin, self._dir_pin, self._mcu.seconds_to_clock(min_stop_interval), self._invert_step))
        self._mcu.add_config_cmd("reset_step_clock oid=%d clock=0" % (self._oid,), is_init=True)
        step_cmd_id = self._mcu.lookup_command_id("queue_step oid=%c interval=%u count=%hu add=%hi")
        dir_cmd_id = self._mcu.lookup_command_id("set_next_step_dir oid=%c dir=%c")
        self._reset_cmd_id = self._mcu.lookup_command_id("reset_step_clock oid=%c clock=%u")
        self._get_position_cmd = self._mcu.lookup_query_command("stepper_get_position oid=%c", "stepper_position oid=%c pos=%i", oid=self._oid)
        self._ffi_lib.stepcompress_fill(self._stepqueue, self._mcu.seconds_to_clock(max_error), self._invert_dir, step_cmd_id, dir_cmd_id)
    def get_oid(self):
        return self._oid
    def get_step_dist(self):
        return self._step_dist
    def is_dir_inverted(self):
        return self._invert_dir
    def calc_position_from_coord(self, coord):
        return self._ffi_lib.itersolve_calc_position_from_coord(
            self._stepper_kinematics, coord[0], coord[1], coord[2])
    def set_position(self, coord):
        opos = self.get_commanded_position()
        sk = self._stepper_kinematics
        self._ffi_lib.itersolve_set_position(sk, coord[0], coord[1], coord[2])
        self._mcu_position_offset += opos - self.get_commanded_position()
    def get_commanded_position(self):
        sk = self._stepper_kinematics
        return self._ffi_lib.itersolve_get_commanded_pos(sk)
    def get_mcu_position(self):
        mcu_pos_dist = self.get_commanded_position() + self._mcu_position_offset
        mcu_pos = mcu_pos_dist / self._step_dist
        if mcu_pos >= 0.:
            return int(mcu_pos + 0.5)
        return int(mcu_pos - 0.5)
    def get_tag_position(self):
        return self._tag_position
    def set_tag_position(self, position):
        self._tag_position = position
    def set_stepper_kinematics(self, sk):
        old_sk = self._stepper_kinematics
        self._stepper_kinematics = sk
        if sk is not None:
            self._ffi_lib.itersolve_set_stepcompress(sk, self._stepqueue, self._step_dist)
        return old_sk
    def note_homing_end(self, did_trigger=False):
        ret = self._ffi_lib.stepcompress_reset(self._stepqueue, 0)
        if ret:
            raise error("Internal error in stepcompress")
        data = (self._reset_cmd_id, self._oid, 0)
        ret = self._ffi_lib.stepcompress_queue_msg(
            self._stepqueue, data, len(data))
        if ret:
            raise error("Internal error in stepcompress")
        if not did_trigger or self._mcu.is_fileoutput():
            return
        params = self._get_position_cmd.send([self._oid])
        mcu_pos_dist = params['pos'] * self._step_dist
        if self._invert_dir:
            mcu_pos_dist = -mcu_pos_dist
        self._mcu_position_offset = mcu_pos_dist - self.get_commanded_position()
    def set_trapq(self, tq):
        if tq is None:
            ffi_main, self._ffi_lib = chelper.get_ffi()
            tq = ffi_main.NULL
        self._ffi_lib.itersolve_set_trapq(self._stepper_kinematics, tq)
        old_tq = self._trapq
        self._trapq = tq
        return old_tq
    def add_active_callback(self, cb):
        self._active_callbacks.append(cb)
    def generate_steps(self, flush_time):
        # Check for activity if necessary
        if self._active_callbacks:
            ret = self._itersolve_check_active(self._stepper_kinematics,
                                               flush_time)
            if ret:
                cbs = self._active_callbacks
                self._active_callbacks = []
                for cb in cbs:
                    cb(ret)
        # Generate steps
        ret = self._itersolve_generate_steps(self._stepper_kinematics,
                                             flush_time)
        if ret:
            raise error("Internal error in stepcompress")
    def is_active_axis(self, axis):
        return self._ffi_lib.itersolve_is_active_axis(
            self._stepper_kinematics, axis)

# tracking of shared stepper enable pins
class MCU_stepper_enable:
    def __init__(self, mcu_enable, enable_count):
        self.mcu_enable = mcu_enable
        self.enable_count = enable_count
        self.is_dedicated = True
    def set_enable(self, print_time):
        if not self.enable_count:
            self.mcu_enable.set_digital(print_time, 1)
        self.enable_count += 1
    def set_disable(self, print_time):
        self.enable_count -= 1
        if not self.enable_count:
            self.mcu_enable.set_digital(print_time, 0)

# enable line tracking for each stepper motor
# TODO
class StepperEnableLine:
    def __init__(self, stepper):
        self.stepper = stepper
        self.callbacks = []
        self.is_enabled = False
        self.stepper.add_active_callback(self.motor_enable)
        self.pin = None
    def register_pin(self, hal, pin):
        # no pin
        if pin is None:
            # No enable line (stepper always enabled)
            self.pin = MCU_stepper_enable(None, 9999)
            self.pin.is_dedicated = False
            return self.pin.mcu_enable
        # register pin
        pin_params = hal.get_controller().pin_register(pin, can_invert=True, share_type="stepper_enable")
        # check pin sharing
        self.pin = pin_params.get('class')
        if self.pin is not None:
            # shared enable line
            self.pin.is_dedicated = False
            return self.pin.mcu_enable
        # setup pin
        mcu_enable = pin_params["chip"].setup_pin("out_digital", pin_params)
        mcu_enable.setup_max_duration(0.)
        # setup pin sharing
        self.pin = pin_params['class'] = MCU_stepper_enable(mcu_enable, 0)
        return self.pin.mcu_enable
    def register_state_callback(self, callback):
        self.callbacks.append(callback)
    def motor_enable(self, print_time):
        if not self.is_enabled:
            for cb in self.callbacks:
                cb(print_time, True)
            self.pin.set_enable(print_time)
            self.is_enabled = True
    def motor_disable(self, print_time):
        if self.is_enabled:
            # Enable stepper on future stepper movement
            for cb in self.callbacks:
                cb(print_time, False)
            self.pin.set_disable(print_time)
            self.is_enabled = False
            self.stepper.add_active_callback(self.motor_enable)
    def is_motor_enabled(self):
        return self.is_enabled
    def has_dedicated_enable(self):
        return self.pin.is_dedicated

#
# Stepper object
#

BUZZ_DISTANCE = 1.
BUZZ_VELOCITY = BUZZ_DISTANCE / .250
BUZZ_RADIANS_DISTANCE = math.radians(1.)
BUZZ_RADIANS_VELOCITY = BUZZ_RADIANS_DISTANCE / .250
STALL_TIME = 0.100
ENDSTOP_SAMPLE_TIME = .000015
ENDSTOP_SAMPLE_COUNT = 4

class Dummy(actuator.Object):
    def __init__(self, hal, node):
        actuator.Object.__init__(self, hal, node)
        logging.warning("(%s) stepper.Dummy", self.name)
    def configure():
        if self.ready:
            return
        # TODO 
        self.ready = True

# TODO was ManualStepper AND ForceMove
# Now every stepper is "manual" until some kinematics registers to start a print.
# When kinematics take over the stepper, it become "managed".
# Managed steppers can be "force moved"; this breaks kinematics (ie: interrupt the print) 
# and the stepper goes back to "manual stepper" state.
class Object(actuator.Object):
    def __init__(self, hal, node):
        actuator.Object.__init__(self, hal, node)
        self.metaconf["pin_step"] = {"t":"str"}
        self.metaconf["pin_dir"] = {"t":"str"}
        self.metaconf["pin_enable"] = {"t":"str", "default": None}
        self.metaconf["step_distance"] = {"t":"float", "above":0.}
        # manual stepper
        self.metaconf["endstop_pin"] = {"t":"str", "default": None}
        self.metaconf["velocity"] = {"t":"float", "default":5., "above":0.}
        self.metaconf["accel"] = {"t":"float", "default":0., "minval":0.}
        #
        self.pin = {}
    def configure(self):
        if self.ready:
            return
        # move pins
        self.step_pin_params = self.hal.get_controller().pin_register(self._pin_step, can_invert=True)
        self.dir_pin_params = self.hal.get_controller().pin_register(self._pin_dir, can_invert=True)
        self.actuator = MCU_stepper(self.name, self.step_pin_params, self.dir_pin_params, self._step_distance)
        self.pin[self._pin_step] = self.pin[self._pin_dir] = self.actuator
        # enable pin
        self.enable = StepperEnableLine(self.actuator)
        pin_enable = self.enable.register_pin(self.hal, self._pin_enable)
        if pin_enable:
            self.pin[self._pin_enable] = pin_enable

        # Register STEPPER_BUZZ command
        #force_move = printer.try_load_module(config, 'force_move')
        #force_move.register_stepper(mcu_stepper)

        # register part
        self.hal.get_controller().register_part(self.node())
        #
        self.ready = True
    def register(self):
        pass
    # calculate a move's accel_t, cruise_t, and cruise_v
    def _calc_move_time(self, dist, speed, accel):
        axis_r = 1.
        if dist < 0.:
            axis_r = -1.
            dist = -dist
        if not accel or not dist:
            return axis_r, 0., dist / speed, speed
        max_cruise_v2 = dist * accel
        if max_cruise_v2 < speed**2:
            speed = math.sqrt(max_cruise_v2)
        accel_t = speed / accel
        accel_decel_d = accel_t * speed
        cruise_t = (dist - accel_decel_d) / speed
        return axis_r, accel_t, cruise_t, speed

    # setup iterative solver for manual stepper
    def manual_solver(self):
        ffi_main, ffi_lib = chelper.get_ffi()
        self.trapq = ffi_main.gc(ffi_lib.trapq_alloc(), ffi_lib.trapq_free)
        self.trapq_append = ffi_lib.trapq_append
        self.trapq_free_moves = ffi_lib.trapq_free_moves
        #
        self.rail.setup_itersolve('cartesian_stepper_alloc', 'x')
        self.rail.set_trapq(self.trapq)
        self.rail.set_max_jerk(9999999.9, 9999999.9)
    # was ManualStepper.__init__
    def manual_setup(self):
        if self._endstop_pin is not None:
            self.can_home = True
            self.rail = stepper.PrinterRail(config, need_position_minmax=False, default_position_endstop=0.)
            self.steppers = self.rail.get_steppers()
        else:
            self.can_home = False
            self.rail = stepper.PrinterStepper(config)
            self.steppers = [self.rail]
        self.velocity = self._velocity
        self.accel = self._accel
        self.next_cmd_time = 0.
        self.manual_solver()
    # setup iterative solver for managed stepper
    def managed_solver(self):
        ffi_main, ffi_lib = chelper.get_ffi()
        self.trapq = ffi_main.gc(ffi_lib.trapq_alloc(), ffi_lib.trapq_free)
        self.trapq_append = ffi_lib.trapq_append
        self.trapq_free_moves = ffi_lib.trapq_free_moves
        #
        self.stepper_kinematics = ffi_main.gc(ffi_lib.cartesian_stepper_alloc('x'), ffi_lib.free)
        ffi_lib.itersolve_set_trapq(self.stepper_kinematics, self.trapq)
    # was ForceMove.__init__ 
    def managed_setup(self):
        self.steppers = {}
        self.managed_solver()

    # MANUAL_STEPPER
    def sync_print_time(self):
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        if self.next_cmd_time > print_time:
            toolhead.dwell(self.next_cmd_time - print_time)
        else:
            self.next_cmd_time = print_time
    def do_enable(self, enable):
        self.sync_print_time()
        stepper_enable = self.printer.lookup_object('stepper_enable')
        if enable:
            for s in self.steppers:
                se = stepper_enable.lookup_enable(s.get_name())
                se.motor_enable(self.next_cmd_time)
        else:
            for s in self.steppers:
                se = stepper_enable.lookup_enable(s.get_name())
                se.motor_disable(self.next_cmd_time)
        self.sync_print_time()
    def do_set_position(self, setpos):
        self.rail.set_position([setpos, 0., 0.])
    def do_move(self, movepos, speed, accel, sync=True):
        self.sync_print_time()
        cp = self.rail.get_commanded_position()
        dist = movepos - cp
        axis_r, accel_t, cruise_t, cruise_v = force_move._calc_move_time(dist, speed, accel)
        self.trapq_append(self.trapq, self.next_cmd_time, accel_t, cruise_t, accel_t, cp, 0., 0., axis_r, 0., 0., 0., cruise_v, accel)
        self.next_cmd_time = self.next_cmd_time + accel_t + cruise_t + accel_t
        self.rail.generate_steps(self.next_cmd_time)
        self.trapq_free_moves(self.trapq, self.next_cmd_time + 99999.9)
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.note_kinematic_activity(self.next_cmd_time)
        if sync:
            self.sync_print_time()
    def do_homing_move(self, movepos, speed, accel, triggered, check_trigger):
        if not self.can_home:
            raise self.gcode.error("No endstop for this manual stepper")
        # Notify start of homing/probing move
        endstops = self.rail.get_endstops()
        self.printer.send_event("homing:homing_move_begin", [es for es, name in endstops])
        # Start endstop checking
        self.sync_print_time()
        endstops = self.rail.get_endstops()
        for mcu_endstop, name in endstops:
            min_step_dist = min([s.get_step_dist() for s in mcu_endstop.get_steppers()])
            mcu_endstop.home_start(self.next_cmd_time, ENDSTOP_SAMPLE_TIME, ENDSTOP_SAMPLE_COUNT, min_step_dist / speed, triggered=triggered)
        # Issue move
        self.do_move(movepos, speed, accel)
        # Wait for endstops to trigger
        error = None
        for mcu_endstop, name in endstops:
            did_trigger = mcu_endstop.home_wait(self.next_cmd_time)
            if not did_trigger and check_trigger and error is None:
                error = "Failed to home %s: Timeout during homing" % (name,)
        # Signal homing/probing move complete
        try:
            self.printer.send_event("homing:homing_move_end", [es for es, name in endstops])
        except CommandError as e:
            if error is None:
                error = str(e)
        self.sync_print_time()
        if error is not None:
            raise homing.CommandError(error)

    # FORCE_MOVE
    def register_stepper(self, stepper):
        name = stepper.get_name()
        self.steppers[name] = stepper
    def lookup_stepper(self, name):
        if name not in self.steppers:
            raise self.printer.config_error("Unknown stepper %s" % (name,))
        return self.steppers[name]
    def force_enable(self, stepper):
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        stepper_enable = self.printer.lookup_object('stepper_enable')
        enable = stepper_enable.lookup_enable(stepper.get_name())
        was_enable = enable.is_motor_enabled()
        if not was_enable:
            enable.motor_enable(print_time)
            toolhead.dwell(STALL_TIME)
        return was_enable
    def restore_enable(self, stepper, was_enable):
        if not was_enable:
            toolhead = self.printer.lookup_object('toolhead')
            toolhead.dwell(STALL_TIME)
            print_time = toolhead.get_last_move_time()
            stepper_enable = self.printer.lookup_object('stepper_enable')
            enable = stepper_enable.lookup_enable(stepper.get_name())
            enable.motor_disable(print_time)
            toolhead.dwell(STALL_TIME)
    def move_force(self, stepper, dist, speed, accel=0.):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.flush_step_generation()
        prev_sk = stepper.set_stepper_kinematics(self.stepper_kinematics)
        stepper.set_position((0., 0., 0.))
        axis_r, accel_t, cruise_t, cruise_v = self._calc_move_time(dist, speed, accel)
        print_time = toolhead.get_last_move_time()
        self.trapq_append(self.trapq, print_time, accel_t, cruise_t, accel_t, 0., 0., 0., axis_r, 0., 0., 0., cruise_v, accel)
        print_time = print_time + accel_t + cruise_t + accel_t
        stepper.generate_steps(print_time)
        self.trapq_free_moves(self.trapq, print_time + 99999.9)
        stepper.set_stepper_kinematics(prev_sk)
        toolhead.note_kinematic_activity(print_time)
        toolhead.dwell(accel_t + cruise_t + accel_t)
    def _lookup_stepper(self, params):
        name = self.gcode.get_str('STEPPER', params)
        if name not in self.steppers:
            raise self.gcode.error("Unknown stepper %s" % (name,))
        return self.steppers[name]

ATTRS = ("type", "step_distance")
ATTRS_PINS = ("pin_step", "pin_dir", "pin_enable")
ATTRS_I2C = ("pin_sda", "pin_scl", "addr")
ATTRS_SPI = ("pin_miso", "pin_mosi", "pin_sck", "pin_cs")
def load_node_object(hal, node):
    if node.attrs_check():
        if node.attrs["type"] == "pins":
            if node.attrs_check("pins"):
                node.object = Object(hal, node)
                return node.object
        elif node.attrs["type"] == "i2c":
            if node.attrs_check("i2c"):
                node.object = Object(hal, node)
                return node.object
        elif node.attrs["type"] == "spi":
            if node.attrs_check("spi"):
                node.object = Object(hal, node)
                return node.object
    node.object = Dummy(hal,node)
    return node.object

