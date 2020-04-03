# Printer composited parts.
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, collections
import composite

attrs = ("position_min", "position_endstop_min", "position_max")

class error(Exception):
    pass

class Dummy(composite.Object):
    def __init__(self, hal, rnode):
        logging.warning("Dummy: %s", rnode.name)
        self.hal = hal
        self.node = rnode
    def get(self, need_position_minmax=True, default_position_endstop=None, units_in_radians=False):
        self.stepper_units_in_radians = units_in_radians
        self.steppers = []
        self.endstops = []
        # TODO
        return self

# A motor control "rail" with one (or more) steppers and one (or more) endstops.
class Object(composite.Object):
    def init(self):
        pass
    def get(self, need_position_minmax=True, default_position_endstop=None, units_in_radians=False):
        self.stepper_units_in_radians = units_in_radians
        self.steppers = []
        self.endstops = []
        # steppers
        for s in self.node.object.sub_group(self.node, "stepper"):
            self.steppers.append(s.object.get(self.stepper_units_in_radians))
        # endstops
        for e in ["sensor_min", "sensor_max", "sensor_level"]:
            if e in self.node.attrs:
                en = self.node.get_first_deep("sensor "+self.node.attrs[e])
                if en:
                    self.endstops.append(en.object.get(e, en.attrs["pin"], self.steppers))
                else:
                    self.endstops.append((None, e))
            else:
                self.endstops.append((None, e))
        mcu_stepper = self.steppers[0]
        self.get_commanded_position = mcu_stepper.get_commanded_position
        self.get_tag_position = mcu_stepper.get_tag_position
        self.set_tag_position = mcu_stepper.set_tag_position
        self.calc_position_from_coord = mcu_stepper.calc_position_from_coord
        # Primary endstop position
        mcu_endstop = self.endstops[0][0]
        if hasattr(mcu_endstop, "get_position_endstop"):
            self.position_endstop = mcu_endstop.get_position_endstop()
        elif default_position_endstop is None:
            self.position_endstop = self.node.get_float('position_endstop')
        else:
            self.position_endstop = self.node.get_float('position_endstop', default_position_endstop)
        # Axis range
        if need_position_minmax:
            self.position_min = self.node.get_float('position_min', 0.)
            self.position_max = self.node.get_float('position_max', above=self.position_min)
        else:
            self.position_min = 0.
            self.position_max = self.position_endstop
        if (self.position_endstop < self.position_min or self.position_endstop > self.position_max):
            pass
            #raise config.error(
            #    "position_endstop in section '%s' must be between"
            #    " position_min and position_max" % config.get_name())
        # Homing mechanics
        self.homing_speed = self.node.get_float('homing_speed', 5.0, above=0.)
        self.second_homing_speed = self.node.get_float('second_homing_speed', self.homing_speed/2., above=0.)
        self.homing_retract_speed = self.node.get_float('homing_retract_speed', self.homing_speed, above=0.)
        self.homing_retract_dist = self.node.get_float('homing_retract_dist', 5., minval=0.)
        self.homing_positive_dir = self.node.get_boolean('homing_positive_dir', None)
        if self.homing_positive_dir is None:
            axis_len = self.position_max - self.position_min
            if self.position_endstop <= self.position_min + axis_len / 4.:
                self.homing_positive_dir = False
            elif self.position_endstop >= self.position_max - axis_len / 4.:
                self.homing_positive_dir = True
            else:
                pass
                #raise config.error(
                #    "Unable to infer homing_positive_dir in section '%s'" % (config.get_name(),))
        return self
    def get_range(self):
        return self.position_min, self.position_max
    def get_homing_info(self):
        homing_info = collections.namedtuple('homing_info', [
            'speed', 'position_endstop', 'retract_speed', 'retract_dist',
            'positive_dir', 'second_homing_speed'])(
                self.homing_speed, self.position_endstop,
                self.homing_retract_speed, self.homing_retract_dist,
                self.homing_positive_dir, self.second_homing_speed)
        return homing_info
    def get_steppers(self):
        return list(self.steppers)
    def get_endstops(self):
        return list(self.endstops)
    def setup_itersolve(self, alloc_func, *params):
        for stepper in self.steppers:
            stepper.setup_itersolve(alloc_func, *params)
    def generate_steps(self, flush_time):
        for stepper in self.steppers:
            stepper.generate_steps(flush_time)
    def set_trapq(self, trapq):
        for stepper in self.steppers:
            stepper.set_trapq(trapq)
    def set_max_jerk(self, max_halt_velocity, max_accel):
        for stepper in self.steppers:
            stepper.set_max_jerk(max_halt_velocity, max_accel)
    def set_position(self, coord):
        for stepper in self.steppers:
            stepper.set_position(coord)

def load_node_object(hal, node):
    config_ok = True
    for a in node.module.attrs:
        if a not in node.attrs:
            config_ok = False
            break
    if config_ok:
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal, node)
