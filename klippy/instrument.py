# Code for coordinating events on the printer toolhead
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

# Common suffixes: _d is distance (in mm), _v is velocity (in
#   mm/second), _v2 is velocity squared (mm^2/s^2), _t is time (in
#   seconds), _r is ratio (scalar between 0.0 and 1.0)

import logging, math
from text import msg
from error import KError as error
import tree, chelper
from kinematics import cartesian
from parts import extruder

# Class to track each move request
class Move:
    def __init__(self, toolhead, start_pos, end_pos, speed):
        self.toolhead = toolhead
        self.start_pos = tuple(start_pos)
        self.end_pos = tuple(end_pos)
        self.accel = toolhead.max_accel
        self.timing_callbacks = []
        velocity = min(speed, toolhead.max_velocity)
        self.is_kinematic_move = True
        self.axes_d = axes_d = [end_pos[i] - start_pos[i] for i in (0, 1, 2, 3)]
        self.move_d = move_d = math.sqrt(sum([d*d for d in axes_d[:3]]))
        if move_d < .000000001:
            # Extrude only move
            self.end_pos = (start_pos[0], start_pos[1], start_pos[2],
                            end_pos[3])
            axes_d[0] = axes_d[1] = axes_d[2] = 0.
            self.move_d = move_d = abs(axes_d[3])
            inv_move_d = 0.
            if move_d:
                inv_move_d = 1. / move_d
            self.accel = 99999999.9
            velocity = speed
            self.is_kinematic_move = False
        else:
            inv_move_d = 1. / move_d
        self.axes_r = [d * inv_move_d for d in axes_d]
        self.min_move_t = move_d / velocity
        # Junction speeds are tracked in velocity squared.  The
        # delta_v2 is the maximum amount of this squared-velocity that
        # can change in this move.
        self.max_start_v2 = 0.
        self.max_cruise_v2 = velocity**2
        self.delta_v2 = 2.0 * move_d * self.accel
        self.max_smoothed_v2 = 0.
        self.smooth_delta_v2 = 2.0 * move_d * toolhead.max_accel_to_decel
    def limit_speed(self, speed, accel):
        speed2 = speed**2
        if speed2 < self.max_cruise_v2:
            self.max_cruise_v2 = speed2
            self.min_move_t = self.move_d / speed
        self.accel = min(self.accel, accel)
        self.delta_v2 = 2.0 * self.move_d * self.accel
        self.smooth_delta_v2 = min(self.smooth_delta_v2, self.delta_v2)
    def calc_junction(self, prev_move):
        if not self.is_kinematic_move or not prev_move.is_kinematic_move:
            return
        # Allow extruder to calculate its maximum junction
        extruder_v2 = self.toolhead.extruder.calc_junction(prev_move, self)
        # Find max velocity using "approximated centripetal velocity"
        axes_r = self.axes_r
        prev_axes_r = prev_move.axes_r
        junction_cos_theta = -(axes_r[0] * prev_axes_r[0]
                               + axes_r[1] * prev_axes_r[1]
                               + axes_r[2] * prev_axes_r[2])
        if junction_cos_theta > 0.999999:
            return
        junction_cos_theta = max(junction_cos_theta, -0.999999)
        sin_theta_d2 = math.sqrt(0.5*(1.0-junction_cos_theta))
        R = (self.toolhead.junction_deviation * sin_theta_d2
             / (1. - sin_theta_d2))
        # Approximated circle must contact moves no further away than mid-move
        tan_theta_d2 = sin_theta_d2 / math.sqrt(0.5*(1.0+junction_cos_theta))
        move_centripetal_v2 = .5 * self.move_d * tan_theta_d2 * self.accel
        prev_move_centripetal_v2 = (.5 * prev_move.move_d * tan_theta_d2
                                    * prev_move.accel)
        # Apply limits
        self.max_start_v2 = min(
            R * self.accel, R * prev_move.accel,
            move_centripetal_v2, prev_move_centripetal_v2,
            extruder_v2, self.max_cruise_v2, prev_move.max_cruise_v2,
            prev_move.max_start_v2 + prev_move.delta_v2)
        self.max_smoothed_v2 = min(
            self.max_start_v2
            , prev_move.max_smoothed_v2 + prev_move.smooth_delta_v2)
    def set_junction(self, start_v2, cruise_v2, end_v2):
        # Determine accel, cruise, and decel portions of the move distance
        half_inv_accel = .5 / self.accel
        accel_d = (cruise_v2 - start_v2) * half_inv_accel
        decel_d = (cruise_v2 - end_v2) * half_inv_accel
        cruise_d = self.move_d - accel_d - decel_d
        # Determine move velocities
        self.start_v = start_v = math.sqrt(start_v2)
        self.cruise_v = cruise_v = math.sqrt(cruise_v2)
        self.end_v = end_v = math.sqrt(end_v2)
        # Determine time spent in each portion of move (time is the
        # distance divided by average velocity)
        self.accel_t = accel_d / ((start_v + cruise_v) * 0.5)
        self.cruise_t = cruise_d / cruise_v
        self.decel_t = decel_d / ((end_v + cruise_v) * 0.5)

LOOKAHEAD_FLUSH_TIME = 0.250

# Class to track a list of pending move requests and to facilitate
# "look-ahead" across moves to reduce acceleration between moves.
class MoveQueue:
    def __init__(self, toolhead):
        self.toolhead = toolhead
        self.queue = []
        self.junction_flush = LOOKAHEAD_FLUSH_TIME
    def reset(self):
        del self.queue[:]
        self.junction_flush = LOOKAHEAD_FLUSH_TIME
    def set_flush_time(self, flush_time):
        self.junction_flush = flush_time
    def get_last(self):
        if self.queue:
            return self.queue[-1]
        return None
    def flush(self, lazy=False):
        self.junction_flush = LOOKAHEAD_FLUSH_TIME
        update_flush_count = lazy
        queue = self.queue
        flush_count = len(queue)
        # Traverse queue from last to first move and determine maximum
        # junction speed assuming the robot comes to a complete stop
        # after the last move.
        delayed = []
        next_end_v2 = next_smoothed_v2 = peak_cruise_v2 = 0.
        for i in range(flush_count-1, -1, -1):
            move = queue[i]
            reachable_start_v2 = next_end_v2 + move.delta_v2
            start_v2 = min(move.max_start_v2, reachable_start_v2)
            reachable_smoothed_v2 = next_smoothed_v2 + move.smooth_delta_v2
            smoothed_v2 = min(move.max_smoothed_v2, reachable_smoothed_v2)
            if smoothed_v2 < reachable_smoothed_v2:
                # It's possible for this move to accelerate
                if (smoothed_v2 + move.smooth_delta_v2 > next_smoothed_v2
                    or delayed):
                    # This move can decelerate or this is a full accel
                    # move after a full decel move
                    if update_flush_count and peak_cruise_v2:
                        flush_count = i
                        update_flush_count = False
                    peak_cruise_v2 = min(move.max_cruise_v2, (
                        smoothed_v2 + reachable_smoothed_v2) * .5)
                    if delayed:
                        # Propagate peak_cruise_v2 to any delayed moves
                        if not update_flush_count and i < flush_count:
                            mc_v2 = peak_cruise_v2
                            for m, ms_v2, me_v2 in reversed(delayed):
                                mc_v2 = min(mc_v2, ms_v2)
                                m.set_junction(min(ms_v2, mc_v2), mc_v2
                                               , min(me_v2, mc_v2))
                        del delayed[:]
                if not update_flush_count and i < flush_count:
                    cruise_v2 = min((start_v2 + reachable_start_v2) * .5
                                    , move.max_cruise_v2, peak_cruise_v2)
                    move.set_junction(min(start_v2, cruise_v2), cruise_v2
                                      , min(next_end_v2, cruise_v2))
            else:
                # Delay calculating this move until peak_cruise_v2 is known
                delayed.append((move, start_v2, next_end_v2))
            next_end_v2 = start_v2
            next_smoothed_v2 = smoothed_v2
        if update_flush_count or not flush_count:
            return
        # Generate step times for all moves ready to be flushed
        self.toolhead._process_moves(queue[:flush_count])
        # Remove processed moves from the queue
        del queue[:flush_count]
    def add_move(self, move):
        self.queue.append(move)
        if len(self.queue) == 1:
            return
        move.calc_junction(self.queue[-2])
        self.junction_flush -= move.min_move_t
        if self.junction_flush <= 0.:
            # Enough moves have been queued to reach the target flush time.
            self.flush(lazy=True)

# toolhead stepper-enable line tracking
DISABLE_STALL_TIME = 0.100
class StepperEnableToolhead:
    def __init__(self, hal, toolhead, gcode):
        self.hal = hal
        self.toolhead = toolhead
        self.gcode = gcode
        self.enable_line = {}
    def register_stepper(self, name, line):
        if line:
            self.enable_line[name] = line
        else:
            self.enable_line.pop(name)
    # turn off all toolhead's steppers
    def off(self):
        self.toolhead.dwell(DISABLE_STALL_TIME)
        print_time = self.toolhead.get_last_move_time()
        for el in self.enable_line:
            self.enable_line[el].motor_disable(print_time)
        self.hal.get_printer().event_send("steppertracker:"+self.toolhead.name+":motor_off", print_time)
        self.toolhead.dwell(DISABLE_STALL_TIME)
        logging.debug('; Max time of %f', print_time)
    # switch on/off the given stepper(s)
    def debug_switch(self, stepper=None, enable=1):
        self.toolhead.dwell(DISABLE_STALL_TIME)
        print_time = self.toolhead.get_last_move_time()
        if stepper in self.enable_line:
            el = self.enable_line.get(stepper, "")
            if enable:
                el.motor_enable(print_time)
                logging.info("%s has been manually enabled", stepper)
            else:
                el.motor_disable(print_time)
                logging.info("%s has been manually disabled", stepper)
        else:
            self.gcode.respond_info('STEPPER_SWITCH: Invalid stepper "%s"' % (stepper))
        self.toolhead.dwell(DISABLE_STALL_TIME)
        logging.debug('; Max time of %f', print_time)
    def lookup_enable(self, name):
        if name not in self.enable_line:
            raise error("Unknown stepper '%s'" % (name,))
        return self.enable_line[name]

# toolhead

MIN_KIN_TIME = 0.100
MOVE_BATCH_TIME = 0.500
DRIP_SEGMENT_TIME = 0.050
DRIP_TIME = 0.100
class DripModeEndSignal(Exception):
    pass

class Dummy(tree.Composite):
    def __init__(self, name, hal):
        super().__init__(name, hal)
        logging.warning("(%s) instrument.Dummy", name)
    def _init(self):
        if self.ready:
            return
        self.ready = True
    def register(self):
        pass
    def move(self, newpos, speed):
        pass
    def get_position(self):
        pass

# Main code to track events (and their timing) on the printer toolhead
class Toolhead(tree.Composite):
    def __init__(self, name, hal):
        super().__init__(name, hal = hal)
        #
        self.metaconf["max_velocity"] = {"t":"float", "above":0.}
        self.metaconf["max_accel"] = {"t":"float", "above":0.}
        self.metaconf["max_accel_to_decel"] = {"t":"float", "default":"self._max_accel", "above":0.}
        self.metaconf["square_corner_velocity"] = {"t":"float", "default":5., "minval":0.}
        self.metaconf["max_z_velocity"] = {"t":"float", "default":"self._max_velocity", "above":0., "maxval":"self._max_velocity"}
        self.metaconf["max_z_accel"] = {"t":"float", "default":"self._max_accel", "above":0., "maxval":"self._max_accel"}
        #
        self.metaconf["buffer_time_low"] = {"t":"float", "default":1.000, "above":0.}
        self.metaconf["buffer_time_high"] = {"t":"float", "default":2.000, "above":"self._buffer_time_low"}
        self.metaconf["buffer_time_start"] = {"t":"float", "default":0.250, "above":0.}
        self.metaconf["move_flush_time"] = {"t":"float", "default":0.050, "above":0.}
    def _init(self):
        if self.ready:
            return
        self.kin = self.hal.get_kinematic(self.id())
        self.gcode = self.hal.get_gcode(self.id())
        # stepper enable line tracker
        self.stepper_linetracker = StepperEnableToolhead(self.hal, self, self.gcode)
        for s in self.children_deep_bygroup("stepper"):
            self.stepper_linetracker.register_stepper(s.name, s.enable)
        self.hal.get_controller().stepper_linetracker.register_tracker(self.name, self.stepper_linetracker)
        #
        self.all_mcus = self.hal.get_controller().mcu_list()
        self.mcu = self.all_mcus[0]
        self.can_pause = True
        if self.mcu.is_fileoutput():
            self.can_pause = False
        self.move_queue = MoveQueue(self)
        self.commanded_pos = [0., 0., 0., 0.]
        # Velocity and acceleration control
        self.requested_accel_to_decel = self._max_accel_to_decel
        self.max_accel_to_decel = self.requested_accel_to_decel
        self.config_max_velocity = self._max_velocity
        self.config_max_accel = self._max_accel
        self.config_square_corner_velocity = self._square_corner_velocity
        self.junction_deviation = 0.
        self._calc_junction_deviation()
        # Print time tracking
        self.print_time = 0.
        self.special_queuing_state = "Flushed"
        self.need_check_stall = -1.
        self.flush_timer = self.hal.get_reactor().timer_register(self._flush_handler)
        self.move_queue.set_flush_time(self._buffer_time_high)
        self.last_print_start_time = 0.
        self.idle_flush_print_time = 0.
        self.print_stall = 0
        self.drip_completion = None
        # Kinematic step generation scan window time tracking
        self.kin_flush_delay = 0.
        self.kin_flush_times = []
        self.last_kin_flush_time = self.last_kin_move_time = 0.
        # Setup iterative solver
        ffi_main, ffi_lib = chelper.get_ffi()
        self.trapq = ffi_main.gc(ffi_lib.trapq_alloc(), ffi_lib.trapq_free)
        self.trapq_append = ffi_lib.trapq_append
        self.trapq_free_moves = ffi_lib.trapq_free_moves
        self.step_generators = []
        # set default tool
        tools = [t for t in self.children_deep_bytype("tool", "extruder")]
        if tools:
            for t in tools:
                t.install(self)
            self.set_extruder(tools[0], 0.)
        else:
            self.set_extruder(extruder.Dummy(self.hal, None), 0.)
        self.extruder.setup_pressure_advance()
        # Load some default modules
        #self.printer.try_load_module(config, "idle_timeout")
        #self.printer.try_load_module(config, "statistics")
        #self.printer.try_load_module(config, "manual_probe")
        #self.printer.try_load_module(config, "tuning_tower")
        self.ready = True
    def register(self):
        self.hal.get_printer().event_register_handler("klippy:shutdown", self._event_handle_shutdown)
        #
        self.gcode.register_commands(self)
   # Print time tracking
    def _update_move_time(self, next_print_time):
        batch_time = MOVE_BATCH_TIME
        kin_flush_delay = self.kin_flush_delay
        lkft = self.last_kin_flush_time
        while 1:
            self.print_time = min(self.print_time + batch_time, next_print_time)
            sg_flush_time = max(lkft, self.print_time - kin_flush_delay)
            for sg in self.step_generators:
                sg(sg_flush_time)
            free_time = max(lkft, sg_flush_time - kin_flush_delay)
            self.trapq_free_moves(self.trapq, free_time)
            self.extruder.update_move_time(free_time)
            mcu_flush_time = max(lkft, sg_flush_time - self._move_flush_time)
            for m in self.all_mcus:
                m.flush_moves(mcu_flush_time)
            if self.print_time >= next_print_time:
                break
    def _calc_print_time(self):
        curtime = self.hal.get_reactor().monotonic()
        est_print_time = self.mcu.estimated_print_time(curtime)
        kin_time = max(est_print_time + MIN_KIN_TIME, self.last_kin_flush_time)
        kin_time += self.kin_flush_delay
        min_print_time = max(est_print_time + self.buffer_time_start, kin_time)
        if min_print_time > self.print_time:
            self.print_time = self.last_print_start_time = min_print_time
            self.printer.event_send("toolhead:sync_print_time", curtime, est_print_time, self.print_time)
    def _process_moves(self, moves):
        # Resync print_time if necessary
        if self.special_queuing_state:
            if self.special_queuing_state != "Drip":
                # Transition from "Flushed"/"Priming" state to main state
                self.special_queuing_state = ""
                self.need_check_stall = -1.
                self.hal.get_reactor().update_timer(self.flush_timer, self.hal.get_reactor().NOW)
            self._calc_print_time()
        # Queue moves into trapezoid motion queue (trapq)
        next_move_time = self.print_time
        for move in moves:
            if move.is_kinematic_move:
                self.trapq_append(
                    self.trapq, next_move_time,
                    move.accel_t, move.cruise_t, move.decel_t,
                    move.start_pos[0], move.start_pos[1], move.start_pos[2],
                    move.axes_r[0], move.axes_r[1], move.axes_r[2],
                    move.start_v, move.cruise_v, move.accel)
            if move.axes_d[3]:
                self.extruder.move(next_move_time, move)
            next_move_time = (next_move_time + move.accel_t
                              + move.cruise_t + move.decel_t)
            for cb in move.timing_callbacks:
                cb(next_move_time)
        # Generate steps for moves
        if self.special_queuing_state:
            self._update_drip_move_time(next_move_time)
        self._update_move_time(next_move_time)
        self.last_kin_move_time = next_move_time
    def flush_step_generation(self):
        # Transition from "Flushed"/"Priming"/main state to "Flushed" state
        self.move_queue.flush()
        self.special_queuing_state = "Flushed"
        self.need_check_stall = -1.
        self.hal.get_reactor().timer_update(self.flush_timer, self.hal.get_reactor().NEVER)
        self.move_queue.set_flush_time(self._buffer_time_high)
        self.idle_flush_print_time = 0.
        flush_time = self.last_kin_move_time + self.kin_flush_delay
        self.last_kin_flush_time = max(self.last_kin_flush_time, flush_time)
        self._update_move_time(max(self.print_time, self.last_kin_flush_time))
    def _flush_lookahead(self):
        if self.special_queuing_state:
            return self.flush_step_generation()
        self.move_queue.flush()
    def get_last_move_time(self):
        self._flush_lookahead()
        if self.special_queuing_state:
            self._calc_print_time()
        return self.print_time
    def _check_stall(self):
        eventtime = self.hal.get_reactor().monotonic()
        if self.special_queuing_state:
            if self.idle_flush_print_time:
                # Was in "Flushed" state and got there from idle input
                est_print_time = self.mcu.estimated_print_time(eventtime)
                if est_print_time < self.idle_flush_print_time:
                    self.print_stall += 1
                self.idle_flush_print_time = 0.
            # Transition from "Flushed"/"Priming" state to "Priming" state
            self.special_queuing_state = "Priming"
            self.need_check_stall = -1.
            self.hal.get_reactor().update_timer(self.flush_timer, eventtime + 0.100)
        # Check if there are lots of queued moves and stall if so
        while 1:
            est_print_time = self.mcu.estimated_print_time(eventtime)
            buffer_time = self.print_time - est_print_time
            stall_time = buffer_time - self._buffer_time_high
            if stall_time <= 0.:
                break
            if not self.can_pause:
                self.need_check_stall = self.hal.get_reactor().NEVER
                return
            eventtime = self.hal.get_reactor().pause(eventtime + min(1., stall_time))
        if not self.special_queuing_state:
            # In main state - defer stall checking until needed
            self.need_check_stall = (est_print_time + self._buffer_time_high
                                     + 0.100)
    def _flush_handler(self, eventtime):
        try:
            print_time = self.print_time
            buffer_time = print_time - self.mcu.estimated_print_time(eventtime)
            if buffer_time > self.buffer_time_low:
                # Running normally - reschedule check
                return eventtime + buffer_time - self.buffer_time_low
            # Under ran low buffer mark - flush lookahead queue
            self.flush_step_generation()
            if print_time != self.print_time:
                self.idle_flush_print_time = self.print_time
        except:
            logging.exception("Exception in flush_handler")
            self.printer.call_shutdown("Exception in flush_handler")
        return self.hal.get_reactor().NEVER
    # Movement commands
    def get_position(self):
        return list(self.commanded_pos)
    def set_position(self, newpos, homing_axes=()):
        self.flush_step_generation()
        self.trapq_free_moves(self.trapq, self.hal.get_reactor().NEVER)
        self.commanded_pos[:] = newpos
        self.kin.set_position(newpos, homing_axes)
    def move(self, newpos, speed):
        move = Move(self, self.commanded_pos, newpos, speed)
        if not move.move_d:
            return
        if move.is_kinematic_move:
            self.kin.check_move(move)
        if move.axes_d[3]:
            self.extruder.check_move(move)
        self.commanded_pos[:] = move.end_pos
        self.move_queue.add_move(move)
        if self.print_time > self.need_check_stall:
            self._check_stall()
    def dwell(self, delay):
        next_print_time = self.get_last_move_time() + max(0., delay)
        self._update_move_time(next_print_time)
        self._check_stall()
    def wait_moves(self):
        self._flush_lookahead()
        eventtime = self.hal.get_reactor().monotonic()
        while (not self.special_queuing_state
               or self.print_time >= self.mcu.estimated_print_time(eventtime)):
            if not self.can_pause:
                break
            eventtime = self.hal.get_reactor().pause(eventtime + 0.100)
    def set_extruder(self, extruder, extrude_pos):
        self.extruder = extruder
        self.commanded_pos[3] = extrude_pos
    def get_extruder(self):
        return self.extruder
    # Homing "drip move" handling
    def _update_drip_move_time(self, next_print_time):
        flush_delay = DRIP_TIME + self._move_flush_time + self.kin_flush_delay
        while self.print_time < next_print_time:
            if self.drip_completion.test():
                raise DripModeEndSignal()
            curtime = self.hal.get_reactor().monotonic()
            est_print_time = self.mcu.estimated_print_time(curtime)
            wait_time = self.print_time - est_print_time - flush_delay
            if wait_time > 0. and self.can_pause:
                # Pause before sending more steps
                self.drip_completion.wait(curtime + wait_time)
                continue
            npt = min(self.print_time + DRIP_SEGMENT_TIME, next_print_time)
            self._update_move_time(npt)
    def drip_move(self, newpos, speed, drip_completion):
        # Transition from "Flushed"/"Priming"/main state to "Drip" state
        self.move_queue.flush()
        self.special_queuing_state = "Drip"
        self.need_check_stall = self.hal.get_reactor().NEVER
        self.hal.get_reactor().update_timer(self.flush_timer, self.hal.get_reactor().NEVER)
        self.move_queue.set_flush_time(self._buffer_time_high)
        self.idle_flush_print_time = 0.
        self.drip_completion = drip_completion
        # Submit move
        try:
            self.move(newpos, speed)
        except homing.CommandError as e:
            self.flush_step_generation()
            raise
        # Transmit move in "drip" mode
        try:
            self.move_queue.flush()
        except DripModeEndSignal as e:
            self.move_queue.reset()
            self.trapq_free_moves(self.trapq, self.hal.get_reactor().NEVER)
        # Exit "Drip" state
        self.flush_step_generation()
    # Misc commands
    def stats(self, eventtime):
        for m in self.all_mcus:
            m.check_active(self.print_time, eventtime)
        buffer_time = self.print_time - self.mcu.estimated_print_time(eventtime)
        is_active = buffer_time > -60. or not self.special_queuing_state
        if self.special_queuing_state == "Drip":
            buffer_time = 0.
        return is_active, "print_time=%.3f buffer_time=%.3f print_stall=%d" % (
            self.print_time, max(buffer_time, 0.), self.print_stall)
    def check_busy(self, eventtime):
        est_print_time = self.mcu.estimated_print_time(eventtime)
        lookahead_empty = not self.move_queue.queue
        return self.print_time, est_print_time, lookahead_empty
    def get_status(self, eventtime):
        print_time = self.print_time
        estimated_print_time = self.mcu.estimated_print_time(eventtime)
        last_print_start_time = self.last_print_start_time
        buffer_time = print_time - estimated_print_time
        if buffer_time > -1. or not self.special_queuing_state:
            status = "Printing"
        else:
            status = "Ready"
        res = dict(self.kin.get_status(eventtime))
        res.update({ 'status': status, 'print_time': print_time,
                     'estimated_print_time': estimated_print_time,
                     'extruder': self.extruder.get_name(),
                     'position': homing.Coord(*self.commanded_pos),
                     'printing_time': print_time - last_print_start_time })
        return res
    def _event_handle_shutdown(self):
        self.can_pause = False
        self.move_queue.reset()
    def get_kinematics(self):
        return self.kin
    def get_trapq(self):
        return self.trapq
    def register_step_generator(self, handler):
        self.step_generators.append(handler)
    def note_step_generation_scan_time(self, delay, old_delay=0.):
        self.flush_step_generation()
        cur_delay = self.kin_flush_delay
        if old_delay:
            self.kin_flush_times.pop(self.kin_flush_times.index(old_delay))
        if delay:
            self.kin_flush_times.append(delay)
        new_delay = max(self.kin_flush_times + [0.])
        self.kin_flush_delay = new_delay
    def register_lookahead_callback(self, callback):
        last_move = self.move_queue.get_last()
        if last_move is None:
            callback(self.get_last_move_time())
            return
        last_move.timing_callbacks.append(callback)
    def note_kinematic_activity(self, kin_time):
        self.last_kin_move_time = max(self.last_kin_move_time, kin_time)
    def get_max_velocity(self):
        return self._max_velocity, self._max_accel
    def get_max_axis_halt(self):
        # Determine the maximum velocity a cartesian axis could halt
        # at due to the junction_deviation setting.  The 8.0 was
        # determined experimentally.
        return min(self._max_velocity, math.sqrt(8. * self.junction_deviation * self._max_accel))
    def _calc_junction_deviation(self):
        scv2 = self._square_corner_velocity**2
        self.junction_deviation = scv2 * (math.sqrt(2.) - 1.) / self._max_accel
        self.max_accel_to_decel = min(self.requested_accel_to_decel, self._max_accel)
    def cmd_SET_VELOCITY_LIMIT(self, params):
        'Set default acceleration.'
        print_time = self.get_last_move_time()
        gcode = self.node.get_gcode(self.node.id())
        max_velocity = gcode.get_float('VELOCITY', params, self.max_velocity, above=0.)
        max_accel = gcode.get_float('ACCEL', params, self.max_accel, above=0.)
        square_corner_velocity = gcode.get_float('SQUARE_CORNER_VELOCITY', params, self.square_corner_velocity, minval=0.)
        self.requested_accel_to_decel = gcode.get_float('ACCEL_TO_DECEL', params, self.requested_accel_to_decel, above=0.)
        self.max_velocity = min(max_velocity, self.config_max_velocity)
        self.max_accel = min(max_accel, self.config_max_accel)
        self.square_corner_velocity = min(square_corner_velocity, self.config_square_corner_velocity)
        self._calc_junction_deviation()
        msg = ("max_velocity: %.6f\n"
               "max_accel: %.6f\n"
               "max_accel_to_decel: %.6f\n"
               "square_corner_velocity: %.6f"
               % (max_velocity, max_accel, self.requested_accel_to_decel, square_corner_velocity))
        self.printer.set_rollover_info("toolhead", "toolhead: %s" % (msg,))
        gcode.respond_info(msg, log=False)
    def cmd_POSITION_GET(self, params):
        'Get current position.'
        if self.toolhead is None:
            self.cmd_default(params)
            return
        kin = self.toolhead.get_kinematics()
        steppers = kin.get_steppers()
        mcu_pos = " ".join(["%s:%d" % (s.get_name(), s.get_mcu_position()) for s in steppers])
        for s in steppers:
            s.set_tag_position(s.get_commanded_position())
        stepper_pos = " ".join(["%s:%.6f" % (s.get_name(), s.get_tag_position()) for s in steppers])
        kin_pos = " ".join(["%s:%.6f" % (a, v) for a, v in zip("XYZ", kin.calc_tag_position())])
        toolhead_pos = " ".join(["%s:%.6f" % (a, v) for a, v in zip("XYZE", self.toolhead.get_position())])
        gcode_pos = " ".join(["%s:%.6f"  % (a, v) for a, v in zip("XYZE", self.last_position)])
        base_pos = " ".join(["%s:%.6f"  % (a, v) for a, v in zip("XYZE", self.base_position)])
        homing_pos = " ".join(["%s:%.6f"  % (a, v) for a, v in zip("XYZ", self.homing_position)])
        self.respond_info("mcu: %s\n"
                          "stepper: %s\n"
                          "kinematic: %s\n"
                          "toolhead: %s\n"
                          "gcode: %s\n"
                          "gcode base: %s\n"
                          "gcode homing: %s"
                          % (mcu_pos, stepper_pos, kin_pos, toolhead_pos, gcode_pos, base_pos, homing_pos))
    def cmd_POSITION_FORCE(self, params):
        'Force a low-level kinematic position.'
        self.get_last_move_time()
        curpos = self.get_position()
        x = self.gcode.get_float('X', params, curpos[0])
        y = self.gcode.get_float('Y', params, curpos[1])
        z = self.gcode.get_float('Z', params, curpos[2])
        logging.warning("POSITION_FORCE pos=%.3f,%.3f,%.3f", x, y, z)
        self.set_position([x, y, z, curpos[3]], homing_axes=(0, 1, 2))
        self.gcode.reset_last_position()
    def cmd_STEPPER_SWITCH(self, params):
        'Enable/disable individual stepper by name.'
        stepper_name = self.gcode.get_str('STEPPER', params, None)
        stepper_enable = self.gcode.get_int('ENABLE', params, 1)
        self.stepper_linetracker.debug_switch(stepper_name, stepper_enable)

ATTRS = ("x", "y", "z", "max_velocity", "max_accel", "max_z_velocity", "max_z_accel")
def load_node(name, hal, cparser):
    #if node.attrs_check():
    node = Toolhead(name, hal)
    #else:
    #    node = Dummy(hal, node)
    #    # force dummy kinematic too
    #    knode = node.parent(hal.tree.printer, node.name)
    #    knode = cartesian.Dummy(hal, knode)
    return node
