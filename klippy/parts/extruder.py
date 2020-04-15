# Code for handling printer extruders.
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, math
from messaging import msg
from messaging import Kerr as error
import composite, chelper

class Dummy(composite.Object):
    def __init__(self, hal, node):
        composite.Object.__init__(self, hal, node)
        logging.warning("(%s) extruder.Dummy", node.name)
    def init(self):
        if self.ready:
            return
        self.ready = True
    def register(self):
        pass
    def setup_pressure_advance(self):
        pass
    def update_move_time(self, flush_time):
        pass
    def check_move(self, move):
        raise homing.EndstopMoveError(move.end_pos, "Extrude when no extruder present")
    def calc_junction(self, prev_move, move):
        return move.max_cruise_v2
    def get_name(self):
        return ""
    def get_heater(self):
        raise homing.CommandError("Extruder not configured")

class Object(composite.Object):
    def __init__(self, hal, node):
        composite.Object.__init__(self, hal, node)
        self.metaconf["filament_diameter"] = {"t":"float", "minval":0.}
        self.metaconf["sharing_tool"] = {"t":"str", "default":None}
        self.metaconf["max_extrude_cross_section"] = {"t":"float", "default":None, "above":0.}
        self.metaconf["max_extrude_only_velocity"] = {"t":"float", "default":None, "above":0.}
        self.metaconf["max_extrude_only_accel"] = {"t":"float", "default":None, "above":0.}
        self.metaconf["max_extrude_only_distance"] = {"t":"float", "default":50., "minval":0.}
        self.metaconf["instantaneous_corner_velocity"] = {"t":"float", "default":1., "minval":0.}
        self.metaconf["pressure_advance"] = {"t":"float", "default":0., "minval":0.}
        self.metaconf["pressure_advance_smooth_time"] = {"t":"float", "default":0.040, "above":0., "maxval":0.200}
    def init(self):
        if self.ready:
            return
        self.gcode = self.hal.get_gcode_child(self.node())
        self.gcode_id = "T%d" % self.hal.get_commander().mk_gcode_id()
        # (multi)stepper list
        self.stepper = [s.object for s in self.children_bygroup("stepper")]
        # heater and nozzle, and heater sharing (ex: e3d cyclop "shares" heater and nozzle with 2 steppers for dual filament extrusion)
        if self._sharing_tool is None:
            self.heater = [h.object for h in self.children_bytype("tool", "tcontrol")]
            self.nozzle = [n.object for n in self.children_bygroup("nozzle")]
        else:
            stool = self.hal.node(self._sharing_tool)
            self.heater = [h.object for h in stool.children_bytype("tool", "tcontrol")]
            self.nozzle = [n.object for n in stool.children_bygroup("nozzle")]
        # setup extruding geometry
        self.nozzle_diameter = self.nozzle[0]._diameter
        self.filament_area = math.pi * (self._filament_diameter * .5)**2
        def_max_cross_section = 4. * self.nozzle_diameter**2
        def_max_extrude_ratio = def_max_cross_section / self.filament_area
        if self._max_extrude_cross_section:
            self.max_extrude_ratio = self._max_extrude_cross_section / self.filament_area
        else:
            self.max_extrude_ratio = def_max_cross_section / self.filament_area
        logging.info("Extruder '%s', max_extrude_ratio=%.6f", self.node().name, self.max_extrude_ratio)
        self.ready = True
    def install(self, toolhead):
        self.toolhead = toolhead
        # setup extruding speed
        max_velocity, max_accel = self.toolhead.get_max_velocity()
        if self._max_extrude_only_velocity:
            self.max_e_velocity = self._max_extrude_only_velocity
        else:
            self.max_e_velocity = max_velocity * self.max_extrude_ratio
        if self._max_extrude_only_accel:
            self.max_e_accel = self._max_extrude_only_accel
        else:
            self.max_e_accel = max_accel * self.max_extrude_ratio
        # setup iterative solver
        ffi_main, ffi_lib = chelper.get_ffi()
        self.trapq = ffi_main.gc(ffi_lib.trapq_alloc(), ffi_lib.trapq_free)
        self.trapq_append = ffi_lib.trapq_append
        self.trapq_free_moves = ffi_lib.trapq_free_moves
        self.sk_extruder = ffi_main.gc(ffi_lib.extruder_stepper_alloc(), ffi_lib.free)
        # dual-stepper support
        for s in self.stepper:
            s.actuator.set_max_jerk(9999999.9, 9999999.9)
            s.actuator.set_stepper_kinematics(self.sk_extruder)
            s.actuator.set_trapq(self.trapq)
            self.toolhead.register_step_generator(s.actuator.generate_steps)
        # setup pressure advance
        self.extruder_set_smooth_time = ffi_lib.extruder_set_smooth_time
    def setup_pressure_advance(self):
        self._set_pressure_advance(self._pressure_advance, self._pressure_advance_smooth_time)
    def register(self):
        #self.gcode.register_mux_command("M572", "EXTRUDER", None, self.cmd_default_M572, desc=self.cmd_M572_help)
        #self.gcode.register_mux_command("M572", "EXTRUDER", self.name, self.cmd_M572, desc=self.cmd_M572_help)
        #self.gcode.register_mux_command("ACTIVATE_EXTRUDER", "EXTRUDER", self.name, self.cmd_ACTIVATE_EXTRUDER, desc=self.cmd_ACTIVATE_EXTRUDER_help)
        pass
    def update_move_time(self, flush_time):
        self.trapq_free_moves(self.trapq, flush_time)
    def _set_pressure_advance(self, pressure_advance, smooth_time):
        old_smooth_time = self._pressure_advance_smooth_time
        if not self._pressure_advance:
            old_smooth_time = 0.
        new_smooth_time = smooth_time
        if not pressure_advance:
            new_smooth_time = 0.
        self.toolhead.note_step_generation_scan_time(new_smooth_time * .5, old_delay=old_smooth_time * .5)
        self.extruder_set_smooth_time(self.sk_extruder, new_smooth_time)
        self._pressure_advance = pressure_advance
        self._pressure_advance_smooth_time = smooth_time
    def get_status(self, eventtime):
        return dict(self.heater.get_status(eventtime), pressure_advance=self._pressure_advance, smooth_time=self._pressure_advance_smooth_time)
    def get_name(self):
        return self.name
    def get_heater(self):
        return self.heater
    def get_trapq(self):
        return self.trapq
    def stats(self, eventtime):
        return self.heater.stats(eventtime)
    def check_move(self, move):
        axis_r = move.axes_r[3]
        if not self.heater.can_extrude:
            raise homing.EndstopError(
                "Extrude below minimum temp\n"
                "See the 'min_extrude_temp' config option for details")
        if (not move.axes_d[0] and not move.axes_d[1]) or axis_r < 0.:
            # Extrude only move (or retraction move) - limit accel and velocity
            if abs(move.axes_d[3]) > self._max_extrude_only_distance:
                raise homing.EndstopError(
                    "Extrude only move too long (%.3fmm vs %.3fmm)\n"
                    "See the 'max_extrude_only_distance' config"
                    " option for details" % (move.axes_d[3], self._max_extrude_only_distance))
            inv_extrude_r = 1. / abs(axis_r)
            move.limit_speed(self.max_e_velocity * inv_extrude_r, self.max_e_accel * inv_extrude_r)
        elif axis_r > self.max_extrude_ratio:
            if move.axes_d[3] <= self.nozzle_diameter * self.max_extrude_ratio:
                # Permit extrusion if amount extruded is tiny
                return
            area = axis_r * self.filament_area
            logging.debug("Overextrude: %s vs %s (area=%.3f dist=%.3f)", axis_r, self.max_extrude_ratio, area, move.move_d)
            raise homing.EndstopError(
                "Move exceeds maximum extrusion (%.3fmm^2 vs %.3fmm^2)\n"
                "See the 'max_extrude_cross_section' config option for details"
                % (area, self.max_extrude_ratio * self.filament_area))
    def calc_junction(self, prev_move, move):
        diff_r = move.axes_r[3] - prev_move.axes_r[3]
        if diff_r:
            return (self._instantaneous_corner_velocity / abs(diff_r))**2
        return move.max_cruise_v2
    def move(self, print_time, move):
        axis_r = move.axes_r[3]
        accel = move.accel * axis_r
        start_v = move.start_v * axis_r
        cruise_v = move.cruise_v * axis_r
        pressure_advance = 0.
        if axis_r > 0. and (move.axes_d[0] or move.axes_d[1]):
            pressure_advance = self._pressure_advance
        # Queue movement (x is extruder movement, y is pressure advance)
        self.trapq_append(self.trapq, print_time,
                          move.accel_t, move.cruise_t, move.decel_t,
                          move.start_pos[3], 0., 0.,
                          1., pressure_advance, 0.,
                          start_v, cruise_v, accel)
    cmd_M572_help = "Set or report extruder pressure advance"
    def cmd_default_M572(self, params):
        extruder = self.printer.lookup_object('toolhead').get_extruder()
        extruder.cmd_M572(params)
    def cmd_M572(self, params):
        pressure_advance = self.gcode.get_float('ADVANCE', params, self._pressure_advance, minval=0.)
        smooth_time = self.gcode.get_float('SMOOTH_TIME', params, self._pressure_advance_smooth_time, minval=0., maxval=.200)
        self._set_pressure_advance(pressure_advance, smooth_time)
        msg = ("pressure_advance: %.6f\n"
               "pressure_advance_smooth_time: %.6f" % (pressure_advance, smooth_time))
        self.printer.set_rollover_info(self.name, "%s: %s" % (self.name, msg))
        self.gcode.respond_info(msg, log=False)
    cmd_ACTIVATE_EXTRUDER_help = "Change the active extruder"
    def cmd_ACTIVATE_EXTRUDER(self, params):
        if self.toolhead.get_extruder() is self:
            self.gcode.respond_info("Extruder %s already active" % (self.name))
            return
        self.gcode.respond_info("Activating extruder %s" % (self.name))
        self.toolhead.flush_step_generation()
        self.toolhead.set_extruder(self, self.stepper.get_commanded_position())
        self.printer.send_event("extruder:activate_extruder")

ATTRS = ("filament_diameter", "min_extrude_temp")
def load_node_object(hal, node):
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)
    return node.object

