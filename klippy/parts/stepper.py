# Printer stepper support
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, math
from messaging import msg
from messaging import Kerr as error
import part, chelper

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
        if short and self._name.startswith('stepper_'):
            return self._name[8:]
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
        self._mcu.add_config_cmd(
            "config_stepper oid=%d step_pin=%s dir_pin=%s"
            " min_stop_interval=%d invert_step=%d" % (self._oid, self._step_pin, self._dir_pin, self._mcu.seconds_to_clock(min_stop_interval), self._invert_step))
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
            self._ffi_lib.itersolve_set_stepcompress(
                sk, self._stepqueue, self._step_dist)
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

#
# Stepper object
#

ATTRS = ("type", "step_distance")
ATTRS_PINS = ("pin_step", "pin_dir", "pin_enable")
ATTRS_I2C = ("pin_sda", "pin_scl", "addr")
ATTRS_SPI = ("pin_miso", "pin_mosi", "pin_sck", "pin_cs")

class Dummy(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self, hal, node)
        logging.warning("(%s) stepper.Dummy", node.name)
    def configure():
        if self.ready:
            return
        # TODO 
        self.ready = True

# Helper code to build a stepper object from hal
class Object(part.Object):
    def configure(self):
        if self.ready:
            return
        self.step_pin_params = self.hal.get_controller().pin_register(self.node.attr_get("pin_step"), can_invert=True)
        self.dir_pin_params = self.hal.get_controller().pin_register(self.node.attr_get("pin_dir"), can_invert=True)
        self.step_dist = self.node.attr_get_float("step_distance", above=0.)
        self.stepper = MCU_stepper(self.node.name, self.step_pin_params, self.dir_pin_params, self.step_dist)
        # Support for stepper enable pin handling
        #stepper_enable = printer.try_load_module(config, 'stepper_enable')
        #stepper_enable.register_stepper(mcu_stepper, self.node.get('enable_pin', None))
        # Register STEPPER_BUZZ command
        #force_move = printer.try_load_module(config, 'force_move')
        #force_move.register_stepper(mcu_stepper)
        self.ready = True

def load_node_object(hal, node):
    if node.attrs_check():
        if node.attrs["type"] == "pins":
            if node.attrs_check("pins"):
                node.object = Object(hal, node)
                return
        elif node.attrs["type"] == "i2c":
            if node.attrs_check("i2c"):
                node.object = Object(hal, node)
                return
        elif node.attrs["type"] == "spi":
            if node.attrs_check("spi"):
                node.object = Object(hal, node)
                return
    node.object = Dummy(hal,node)

#
# Utility for manually moving a stepper for diagnostic purposes
#
# TODO
BUZZ_DISTANCE = 1.
BUZZ_VELOCITY = BUZZ_DISTANCE / .250
BUZZ_RADIANS_DISTANCE = math.radians(1.)
BUZZ_RADIANS_VELOCITY = BUZZ_RADIANS_DISTANCE / .250
STALL_TIME = 0.100

# Calculate a move's accel_t, cruise_t, and cruise_v
def calc_move_time(dist, speed, accel):
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

class ForceMove:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.steppers = {}
        # Setup iterative solver
        ffi_main, ffi_lib = chelper.get_ffi()
        self.trapq = ffi_main.gc(ffi_lib.trapq_alloc(), ffi_lib.trapq_free)
        self.trapq_append = ffi_lib.trapq_append
        self.trapq_free_moves = ffi_lib.trapq_free_moves
        self.stepper_kinematics = ffi_main.gc(ffi_lib.cartesian_stepper_alloc('x'), ffi_lib.free)
        ffi_lib.itersolve_set_trapq(self.stepper_kinematics, self.trapq)
        # Register commands
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('STEPPER_BUZZ', self.cmd_STEPPER_BUZZ, desc=self.cmd_STEPPER_BUZZ_help)
        if config.getboolean("enable_force_move", False):
            self.gcode.register_command('FORCE_MOVE', self.cmd_FORCE_MOVE, desc=self.cmd_FORCE_MOVE_help)
            self.gcode.register_command('SET_KINEMATIC_POSITION', self.cmd_SET_KINEMATIC_POSITION, desc=self.cmd_SET_KINEMATIC_POSITION_help)
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
    def manual_move(self, stepper, dist, speed, accel=0.):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.flush_step_generation()
        prev_sk = stepper.set_stepper_kinematics(self.stepper_kinematics)
        stepper.set_position((0., 0., 0.))
        axis_r, accel_t, cruise_t, cruise_v = calc_move_time(dist, speed, accel)
        print_time = toolhead.get_last_move_time()
        self.trapq_append(self.trapq, print_time, accel_t, cruise_t, accel_t,
                          0., 0., 0., axis_r, 0., 0., 0., cruise_v, accel)
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
    cmd_STEPPER_BUZZ_help = "Oscillate a given stepper to help id it"
    def cmd_STEPPER_BUZZ(self, params):
        stepper = self._lookup_stepper(params)
        logging.info("Stepper buzz %s", stepper.get_name())
        was_enable = self.force_enable(stepper)
        toolhead = self.printer.lookup_object('toolhead')
        dist, speed = BUZZ_DISTANCE, BUZZ_VELOCITY
        if stepper.units_in_radians():
            dist, speed = BUZZ_RADIANS_DISTANCE, BUZZ_RADIANS_VELOCITY
        for i in range(10):
            self.manual_move(stepper, dist, speed)
            toolhead.dwell(.050)
            self.manual_move(stepper, -dist, speed)
            toolhead.dwell(.450)
        self.restore_enable(stepper, was_enable)
    cmd_FORCE_MOVE_help = "Manually move a stepper; invalidates kinematics"
    def cmd_FORCE_MOVE(self, params):
        stepper = self._lookup_stepper(params)
        distance = self.gcode.get_float('DISTANCE', params)
        speed = self.gcode.get_float('VELOCITY', params, above=0.)
        accel = self.gcode.get_float('ACCEL', params, 0., minval=0.)
        logging.info("FORCE_MOVE %s distance=%.3f velocity=%.3f accel=%.3f",
                     stepper.get_name(), distance, speed, accel)
        self.force_enable(stepper)
        self.manual_move(stepper, distance, speed, accel)
    cmd_SET_KINEMATIC_POSITION_help = "Force a low-level kinematic position"
    def cmd_SET_KINEMATIC_POSITION(self, params):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.get_last_move_time()
        curpos = toolhead.get_position()
        x = self.gcode.get_float('X', params, curpos[0])
        y = self.gcode.get_float('Y', params, curpos[1])
        z = self.gcode.get_float('Z', params, curpos[2])
        logging.info("SET_KINEMATIC_POSITION pos=%.3f,%.3f,%.3f", x, y, z)
        toolhead.set_position([x, y, z, curpos[3]], homing_axes=(0, 1, 2))
        self.gcode.reset_last_position()

# Support for enable pins on stepper motor drivers
#
# Copyright (C) 2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

DISABLE_STALL_TIME = 0.100

# Tracking of shared stepper enable pins
class StepperEnablePin:
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

# Enable line tracking for each stepper motor
class EnableTracking:
    def __init__(self, printer, stepper, pin):
        self.stepper = stepper
        self.callbacks = []
        self.is_enabled = False
        self.stepper.add_active_callback(self.motor_enable)
        if pin is None:
            # No enable line (stepper always enabled)
            self.enable = StepperEnablePin(None, 9999)
            self.enable.is_dedicated = False
            return
        ppins = printer.lookup_object('pins')
        pin_params = ppins.lookup_pin(pin, can_invert=True,
                                      share_type='stepper_enable')
        self.enable = pin_params.get('class')
        if self.enable is not None:
            # Shared enable line
            self.enable.is_dedicated = False
            return
        mcu_enable = pin_params['chip'].setup_pin('digital_out', pin_params)
        mcu_enable.setup_max_duration(0.)
        self.enable = pin_params['class'] = StepperEnablePin(mcu_enable, 0)
    def register_state_callback(self, callback):
        self.callbacks.append(callback)
    def motor_enable(self, print_time):
        if not self.is_enabled:
            for cb in self.callbacks:
                cb(print_time, True)
            self.enable.set_enable(print_time)
            self.is_enabled = True
    def motor_disable(self, print_time):
        if self.is_enabled:
            # Enable stepper on future stepper movement
            for cb in self.callbacks:
                cb(print_time, False)
            self.enable.set_disable(print_time)
            self.is_enabled = False
            self.stepper.add_active_callback(self.motor_enable)
    def is_motor_enabled(self):
        return self.is_enabled
    def has_dedicated_enable(self):
        return self.enable.is_dedicated

# Global stepper enable line tracking
class PrinterStepperEnable:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.enable_lines = {}
        self.printer.register_event_handler("gcode:request_restart", self._handle_request_restart)
        # Register M18/M84 commands
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command("M18", self.cmd_M18)
        self.gcode.register_command("M84", self.cmd_M18)
        self.gcode.register_command("SET_STEPPER_ENABLE", self.cmd_SET_STEPPER_ENABLE, desc = self.cmd_SET_STEPPER_ENABLE_help)
    def register_stepper(self, stepper, pin):
        name = stepper.get_name()
        self.enable_lines[name] = EnableTracking(self.printer, stepper, pin)
    def motor_off(self):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.dwell(DISABLE_STALL_TIME)
        print_time = toolhead.get_last_move_time()
        for el in self.enable_lines.values():
            el.motor_disable(print_time)
        self.printer.send_event("stepper_enable:motor_off", print_time)
        toolhead.dwell(DISABLE_STALL_TIME)
        logging.debug('; Max time of %f', print_time)
    def motor_debug_enable(self, stepper=None, enable=1):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.dwell(DISABLE_STALL_TIME)
        print_time = toolhead.get_last_move_time()
        if stepper in self.enable_lines:
            el = self.enable_lines.get(stepper, "")
            if enable:
                el.motor_enable(print_time)
                logging.info("%s has been manually enabled", stepper)
            else:
                el.motor_disable(print_time)
                logging.info("%s has been manually disabled", stepper)
        else:
            self.gcode.respond_info('SET_STEPPER_ENABLE: Invalid stepper "%s"'
                                % (stepper))
        toolhead.dwell(DISABLE_STALL_TIME)
        logging.debug('; Max time of %f', print_time)
    def _handle_request_restart(self, print_time):
        self.motor_off()
    def cmd_M18(self, params):
        # Turn off motors
        self.motor_off()
    cmd_SET_STEPPER_ENABLE_help = "Enable/disable individual stepper by name"
    def cmd_SET_STEPPER_ENABLE(self, params):
        stepper_name = self.gcode.get_str('STEPPER', params, None)
        stepper_enable = self.gcode.get_int('ENABLE', params, 1)
        self.motor_debug_enable(stepper_name, stepper_enable)
    def lookup_enable(self, name):
        if name not in self.enable_lines:
            raise self.printer.config_error("Unknown stepper '%s'" % (name,))
        return self.enable_lines[name]

def load_config(config):
    return PrinterStepperEnable(config)
# Support for a manual controlled stepper
#
# Copyright (C) 2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import stepper, homing, force_move, chelper

ENDSTOP_SAMPLE_TIME = .000015
ENDSTOP_SAMPLE_COUNT = 4

class ManualStepper:
    def __init__(self, config):
        self.printer = config.get_printer()
        if config.get('endstop_pin', None) is not None:
            self.can_home = True
            self.rail = stepper.PrinterRail(
                config, need_position_minmax=False, default_position_endstop=0.)
            self.steppers = self.rail.get_steppers()
        else:
            self.can_home = False
            self.rail = stepper.PrinterStepper(config)
            self.steppers = [self.rail]
        self.velocity = config.getfloat('velocity', 5., above=0.)
        self.accel = config.getfloat('accel', 0., minval=0.)
        self.next_cmd_time = 0.
        # Setup iterative solver
        ffi_main, ffi_lib = chelper.get_ffi()
        self.trapq = ffi_main.gc(ffi_lib.trapq_alloc(), ffi_lib.trapq_free)
        self.trapq_append = ffi_lib.trapq_append
        self.trapq_free_moves = ffi_lib.trapq_free_moves
        self.rail.setup_itersolve('cartesian_stepper_alloc', 'x')
        self.rail.set_trapq(self.trapq)
        self.rail.set_max_jerk(9999999.9, 9999999.9)
        # Register commands
        stepper_name = config.get_name().split()[1]
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_mux_command('MANUAL_STEPPER', "STEPPER", stepper_name, self.cmd_MANUAL_STEPPER, desc=self.cmd_MANUAL_STEPPER_help)
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
        axis_r, accel_t, cruise_t, cruise_v = force_move.calc_move_time(
            dist, speed, accel)
        self.trapq_append(self.trapq, self.next_cmd_time,
                          accel_t, cruise_t, accel_t,
                          cp, 0., 0., axis_r, 0., 0.,
                          0., cruise_v, accel)
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
        self.printer.send_event("homing:homing_move_begin",
                                [es for es, name in endstops])
        # Start endstop checking
        self.sync_print_time()
        endstops = self.rail.get_endstops()
        for mcu_endstop, name in endstops:
            min_step_dist = min([s.get_step_dist()
                                 for s in mcu_endstop.get_steppers()])
            mcu_endstop.home_start(
                self.next_cmd_time, ENDSTOP_SAMPLE_TIME, ENDSTOP_SAMPLE_COUNT,
                min_step_dist / speed, triggered=triggered)
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
            self.printer.send_event("homing:homing_move_end",
                                    [es for es, name in endstops])
        except CommandError as e:
            if error is None:
                error = str(e)
        self.sync_print_time()
        if error is not None:
            raise homing.CommandError(error)
    cmd_MANUAL_STEPPER_help = "Command a manually configured stepper"
    def cmd_MANUAL_STEPPER(self, params):
        if 'ENABLE' in params:
            self.do_enable(self.gcode.get_int('ENABLE', params))
        if 'SET_POSITION' in params:
            setpos = self.gcode.get_float('SET_POSITION', params)
            self.do_set_position(setpos)
        sync = self.gcode.get_int('SYNC', params, 1)
        homing_move = self.gcode.get_int('STOP_ON_ENDSTOP', params, 0)
        speed = self.gcode.get_float('SPEED', params, self.velocity, above=0.)
        accel = self.gcode.get_float('ACCEL', params, self.accel, minval=0.)
        if homing_move:
            movepos = self.gcode.get_float('MOVE', params)
            self.do_homing_move(movepos, speed, accel,
                                homing_move > 0, abs(homing_move) == 1)
        elif 'MOVE' in params:
            movepos = self.gcode.get_float('MOVE', params)
            self.do_move(movepos, speed, accel, sync)
        elif 'SYNC' in params and sync:
            self.sync_print_time()

def load_config_prefix(config):
    return ManualStepper(config)
