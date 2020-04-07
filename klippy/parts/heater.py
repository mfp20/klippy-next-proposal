# Heater support file.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import part

ATTRS = ("type", "pin",)

class Dummy(part.Object):
    def configure(self):
        pass

class Object(part.Object):
    def configure(self):
        if self.ready:
            return
        tcnode = self.node.node_get_parent(self.hal.tree.printer, self.node.name)
        gov = tcnode.attr_get_choice("control", {"watermark": "watermark", "pid": "pid"})
        self.max_power = self.node.attr_get_float("power_max", default=1., above=0., maxval=1.)
        if gov == "watermark" and self.max_power == 1.:
            self.pin = self.hal.get_controller().pin_setup("digital_out", self.node.attr_get("pin"))
        else:
            self.pin = self.hal.get_controller().pin_setup("pwm", self.node.attr_get("pin"))
        self.ready = True

def load_node_object(hal, node):
    node.object = Object(hal, node)

