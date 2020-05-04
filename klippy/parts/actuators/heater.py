# Heater support.
# 
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from text import msg
from error import KError as error
from parts import actuator
logger = logging.getLogger(__name__)

# TODO
class Dummy(actuator.Object):
    def __init__(self, name, hal):
        super().__init__(name, hal)
        logger.warning("(%s) heater.Dummy", self.name)
    def _configure(self):
        if self.ready:
            return
        logger.warning("(%s) heater.configure: TODO dummy MCU_digital_out and MCU_pwm", self.get_name())
        self.ready = True

class Object(actuator.Object):
    def __init__(self, name, hal):
        super().__init__(name, hal)
        self.metaconf["type"] = {"t":"str"}
        self.metaconf["pin"] = {"t":"str"}
        self.metaconf["power_max"] = {"t":"float", "default":1., "above":0., "maxval":1.}
        # pwm min and max
        self.metaconf["min"] = {"t":"float", "default":0., "minval":0.}
        self.metaconf["max"] = {"t":"float", "default":1., "maxval":1., "above":"self._min"}
    def _configure(self):
        if self.ready:
            return
        tcnode = self.parent(self.name(), self.hal.get_printer())
        gov = tcnode._control
        self.max_power = self._power_max
        if gov == "watermark" and self.max_power == 1.:
            self.pin[self._pin] = self.hal.get_controller().pin_setup("out_digital", self._pin)
        else:
            self.pin[self._pin] = self.hal.get_controller().pin_setup("out_pwm", self._pin)
        #
        self.hal.get_controller().register_part(self)
        #
        self.ready = True

ATTRS = ("type", "pin",)
def load_node(name, hal, cparser = None):
    #if node.attrs_check():
    node = Object(name, hal)
    #else:
    #    node = Dummy(hal,node)
    return node

