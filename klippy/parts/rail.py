# Printer composited parts.
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, collections
from messaging import msg
from messaging import Kerr as error
import composite

ATTRS = ("position_min", "position_max")

# TODO 
class Dummy(composite.Object):
    def __init__(self, hal, node):
        composite.Object.__init__(self, hal, node)
        logging.warning("(%s) rail.Dummy", node.name)
    def init():
        if self.ready:
            return
        self.ready = True
    def register(self):
        pass

# A motor control "rail" with one (or more) steppers and one (or more) endstops.
class Object(composite.Object):
    def init(self):
        if self.ready:
            return
        self.steppers = []
        self.endstops = []
        self.need_position_minmax = True
        self.default_position_endstop = None
        # steppers
        for s in self.node.object.children_bygroup("stepper"):
            self.steppers.append(s.object.stepper)
        # endstops
        for e in ["sensor_min", "sensor_max", "sensor_level"]:
            if e in self.node.attrs:
                en = self.node.child_get_first("sensor "+self.node.attrs[e])
                if en:
                    for s in self.steppers:
                        en.object.sensor.add_stepper(s)
                    self.endstops.append((en.object.sensor, e))
                    #query_endstops = printer.try_load_module(config, 'query_endstops')
                    #query_endstops.register_endstop(mcu_endstop, name)
                else:
                    self.endstops.append((None, e))
            else:
                self.endstops.append((None, e))
        mcu_stepper = self.steppers[0]
        self.get_commanded_position = mcu_stepper.get_commanded_position
        self.get_tag_position = mcu_stepper.get_tag_position
        self.set_tag_position = mcu_stepper.set_tag_position
        self.calc_position_from_coord = mcu_stepper.calc_position_from_coord
        self.setup_homing()
        self.ready = True
        return self
    def register(self):
        pass
    def setup_position_endstop(self, default_position_endstop = None):
        self.default_position_endstop = default_position_endstop
        mcu_endstop = self.endstops[0][0]
        if hasattr(mcu_endstop, "get_position_endstop"):
            self.position_endstop = mcu_endstop.get_position_endstop()
        elif default_position_endstop is None:
            self.position_endstop = self.node.attr_get_float("position_endstop_min")
        else:
            self.position_endstop = self.node.attr_get_float("position_endstop_min", default=default_position_endstop)
    def setup_axis_range(self, need_position_minmax = True, default_position_endstop = None):
        self.need_position_minmax = need_position_minmax
        self.setup_position_endstop(default_position_endstop)
        if need_position_minmax:
            self.need_position_minmax = True
            self.position_min = self.node.attr_get_float('position_min', default=0.)
            self.position_max = self.node.attr_get_float('position_max', above=self.position_min)
        else:
            self.need_position_minmax = False
            self.position_min = 0.
            self.position_max = self.position_endstop
        if (self.position_endstop < self.position_min or self.position_endstop > self.position_max):
            raise error("position_endstop in section '%s' must be between position_min and position_max" % self.node.name)
    # delta/rotarydelta printers kinematic need to call this after rail init to set need_position_minmax and default_position_endstop
    def setup_homing(self, need_position_minmax = True, default_position_endstop = None):
        self.setup_axis_range(need_position_minmax, default_position_endstop)
        self.homing_speed = self.node.attr_get_float('homing_speed', default=5.0, above=0.)
        self.second_homing_speed = self.node.attr_get_float('second_homing_speed', default=self.homing_speed/2., above=0.)
        self.homing_retract_speed = self.node.attr_get_float('homing_retract_speed', default=self.homing_speed, above=0.)
        self.homing_retract_dist = self.node.attr_get_float('homing_retract_dist', default=5., minval=0.)
        self.homing_positive_dir = self.node.attr_get('homing_positive_dir', True, default=False)
        if self.homing_positive_dir is None:
            axis_len = self.position_max - self.position_min
            if self.position_endstop <= self.position_min + axis_len / 4.:
                self.homing_positive_dir = False
            elif self.position_endstop >= self.position_max - axis_len / 4.:
                self.homing_positive_dir = True
            else:
                raise error("Unable to infer homing_positive_dir in section '%s'" % (self.node.name,))
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
    def get_endstops_status(self):
        # TODO
        print_time = self.printer.lookup_object('toolhead').get_last_move_time()
        last_state = [(name, mcu_endstop.query_endstop(print_time)) for mcu_endstop, name in self.endstops]
        return {'last_query': {name: value for name, value in last_state}}
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
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)


