# Code for handling the kinematics of cartesian robots
#
# Copyright (C) 2016-2019   Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020        Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import hw, composite, instrument
from kinematics.dummy import Object as Dummy

class Object(composite.Object):
    def __init__(self,hal,node):
        composite.Object.__init__(self,hal,node)
        #self.metaconf[
    def init(self):
        if self.ready:
            return
        thnode = self.child_get_first("toolhead "+self.id())
        toolhead = thnode.object
        # setup rails
        self.dual_carriage_axis = None
        self.dual_carriage_rails = []
        railnodes = dict()
        for a in ["x", "y", "z"]:
            rr = list()
            for r in thnode.attrs[a].split(","):
                rr.append(thnode.child_get_first("rail "+r))
            railnodes[a] = rr
        self.rails = [railnodes["x"][0].object, railnodes["y"][0].object, railnodes["z"][0].object]
        for rail, axis in zip(self.rails, "xyz"):
            rail.setup_itersolve("cartesian_stepper_alloc", axis)
        for s in self.get_steppers():
            s.set_trapq(toolhead.get_trapq())
            toolhead.register_step_generator(s.generate_steps)
        # setup boundary checks
        self.max_velocity, self.max_accel = toolhead.get_max_velocity()
        self.max_z_velocity = thnode.object._max_z_velocity
        self.max_z_accel = thnode.object._max_z_accel
        self.limits = [(1.0, -1.0)] * 3
        # setup stepper max halt velocity
        self.max_halt_velocity = toolhead.get_max_axis_halt()
        self.rails[0].set_max_jerk(self.max_halt_velocity, self.max_accel)
        self.rails[1].set_max_jerk(self.max_halt_velocity, self.max_accel)
        self.rails[2].set_max_jerk(min(self.max_halt_velocity, self.max_z_velocity), self.max_accel)
        # setup dual-cart (if any)
        dc_axis = None
        if hasattr(self, "_dual-cart"):
            dc_axis = self._dual-cart
        if dc_axis:
            self.dual_carriage_axis = {'x': 0, 'y': 1}[dc_axis]
            dc_rail = railnodes[dc_axis][1].object
            # setup dual stepper
            dc_rail.setup_itersolve('cartesian_stepper_alloc', dc_axis)
            for s in dc_rail.get_steppers():
                toolhead.register_step_generator(s.generate_steps)
            dc_rail.set_max_jerk(self.max_halt_velocity, self.max_accel)
            self.dual_carriage_rails = [self.rails[self.dual_carriage_axis], dc_rail]
        self.ready = True
    def register(self):
        self.hal.get_printer().register_event_handler("stepper_enable:motor_off", self._motor_off)
        if hasattr(self, "_dual-cart"):
            self.hal.get_gcode(self.id()).register_command('SET_DUAL_CARRIAGE', self.cmd_SET_DUAL_CARRIAGE, desc=self.cmd_SET_DUAL_CARRIAGE_help)
    def get_steppers(self):
        rails = self.rails
        if self.dual_carriage_axis is not None:
            dca = self.dual_carriage_axis
            rails = rails[:dca] + self.dual_carriage_rails + rails[dca+1:]
        return [s for rail in rails for s in rail.get_steppers()]
    def calc_tag_position(self):
        return [rail.get_tag_position() for rail in self.rails]
    def set_position(self, newpos, homing_axes):
        for i, rail in enumerate(self.rails):
            rail.set_position(newpos)
            if i in homing_axes:
                self.limits[i] = rail.get_range()
    def note_z_not_homed(self):
        # Helper for Safe Z Home
        self.limits[2] = (1.0, -1.0)
    def _home_axis(self, homing_state, axis, rail):
        # Determine movement
        position_min, position_max = rail.get_range()
        hi = rail.get_homing_info()
        homepos = [None, None, None, None]
        homepos[axis] = hi.position_endstop
        forcepos = list(homepos)
        if hi.positive_dir:
            forcepos[axis] -= 1.5 * (hi.position_endstop - position_min)
        else:
            forcepos[axis] += 1.5 * (position_max - hi.position_endstop)
        # Perform homing
        homing_state.home_rails([rail], forcepos, homepos)
    def home(self, homing_state):
        # Each axis is homed independently and in order
        for axis in homing_state.get_axes():
            if axis == self.dual_carriage_axis:
                dc1, dc2 = self.dual_carriage_rails
                altc = self.rails[axis] == dc2
                self._activate_carriage(0)
                self._home_axis(homing_state, axis, dc1)
                self._activate_carriage(1)
                self._home_axis(homing_state, axis, dc2)
                self._activate_carriage(altc)
            else:
                self._home_axis(homing_state, axis, self.rails[axis])
    def _motor_off(self, print_time):
        self.limits = [(1.0, -1.0)] * 3
    def _check_endstops(self, move):
        end_pos = move.end_pos
        for i in (0, 1, 2):
            if (move.axes_d[i]
                and (end_pos[i] < self.limits[i][0]
                     or end_pos[i] > self.limits[i][1])):
                if self.limits[i][0] > self.limits[i][1]:
                    raise homing.EndstopMoveError(
                        end_pos, "Must home axis first")
                raise homing.EndstopMoveError(end_pos)
    def check_move(self, move):
        limits = self.limits
        xpos, ypos = move.end_pos[:2]
        if (xpos < limits[0][0] or xpos > limits[0][1]
            or ypos < limits[1][0] or ypos > limits[1][1]):
            self._check_endstops(move)
        if not move.axes_d[2]:
            # Normal XY move - use defaults
            return
        # Move with Z - update velocity and accel for slower Z axis
        self._check_endstops(move)
        z_ratio = move.move_d / abs(move.axes_d[2])
        move.limit_speed(
            self.max_z_velocity * z_ratio, self.max_z_accel * z_ratio)
    def get_status(self, eventtime):
        axes = [a for a, (l, h) in zip("xyz", self.limits) if l <= h]
        return { 'homed_axes': "".join(axes) }
    # Dual carriage support
    def _activate_carriage(self, carriage):
        toolhead = self.hal.get_toolhead()
        toolhead.flush_step_generation()
        dc_rail = self.dual_carriage_rails[carriage]
        dc_axis = self.dual_carriage_axis
        self.rails[dc_axis].set_trapq(None)
        dc_rail.set_trapq(toolhead.get_trapq())
        self.rails[dc_axis] = dc_rail
        pos = toolhead.get_position()
        pos[dc_axis] = dc_rail.get_commanded_position()
        toolhead.set_position(pos)
        if self.limits[dc_axis][0] <= self.limits[dc_axis][1]:
            self.limits[dc_axis] = dc_rail.get_range()
    cmd_SET_DUAL_CARRIAGE_help = "Set which carriage is active"
    def cmd_SET_DUAL_CARRIAGE(self, params):
        gcode = self.hal.get_gcode()
        carriage = gcode.get_int('CARRIAGE', params, minval=0, maxval=1)
        self._activate_carriage(carriage)
        gcode.reset_last_position()

def load_tree_node(hal, knode, parts):
    used_parts = set()
    thnode = knode.child_get_first("toolhead ")
    for a in thnode.attrs:
        if a == "x":
            for r in thnode.attrs[a].split(","):
                if "rail "+r in parts:
                    thnode.children[parts["rail "+r].name] = parts["rail "+r]
                    used_parts.add("rail "+r)
            if len(thnode.attrs[a].split(",")) > 1:
                knode.attrs["dual-cart"] = a
        elif a == "y":
            for r in thnode.attrs[a].split(","):
                if "rail "+r in parts:
                    thnode.children[parts["rail "+r].name] = parts["rail "+r]
                    used_parts.add("rail "+r)
            if len(thnode.attrs[a].split(",")) > 1:
                knode.attrs["dual-cart"] = a
        elif a == "z":
            for r in thnode.attrs[a].split(","):
                if "rail "+r in parts:
                    thnode.children[parts["rail "+r].name] = parts["rail "+r]
                    used_parts.add("rail "+r)
            if len(thnode.attrs[a].split(",")) > 1:
                knode.attrs["dual-cart"] = a
        elif a in hal.pgroups or a in hal.cgroups:
            for p in thnode.attrs[a].split(","):
                thnode.children[parts[a+" "+p].name] = parts[a+" "+p]
    return used_parts

ATTRS = ("type",)
def load_node_object(hal, node):
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)
    return node.object

