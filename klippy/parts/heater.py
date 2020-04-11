# Heater support file.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import part

ATTRS = ("type", "pin",)

# TODO
class Dummy(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self,hal,node)
        logging.warning("(%s) heater.Dummy", self.name)
    def configure(self):
        if self.ready:
            return
        logging.warning("(%s) heater.configure: TODO dummy MCU_digital_out and MCU_pwm", self.get_name())
        self.ready = True

class Object(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self,hal,node)
        self.metaconf["type"] = {"t":"str"}
        self.metaconf["pin"] = {"t":"str"}
        self.metaconf["power_max"] = {"t":"float", "default":1., "above":0., "maxval":1.}
        # pwm min and max
        self.metaconf["min"] = {"t":"float", "default":0., "minval":0.}
        self.metaconf["max"] = {"t":"float", "default":1., "maxval":1., "above":"self._min"}
        # min operating temperature #TODO move in a better location, so that EVERY part have one of those
        self.metaconf["temp_min"] = {"t":"float", "default":-273.0}
        # max operating temperature
        self.metaconf["temp_max"] = {"t":"float", "default":400.0}
    def configure(self):
        if self.ready:
            return
        tcnode = self.node().parent(self.hal.tree.printer, self.name)
        gov = tcnode.object._control
        self.max_power = self._power_max
        if gov == "watermark" and self.max_power == 1.:
            self.pin = self.hal.get_controller().pin_setup("digital_out", self._pin)
        else:
            self.pin = self.hal.get_controller().pin_setup("pwm", self._pin)
        self.hal.get_controller().register_part(self.node())
        self.ready = True

def load_node_object(hal, node):
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)

