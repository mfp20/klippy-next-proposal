# Printer composited parts.
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from messaging import msg
from messaging import Kerr as error
import composite

ATTRS = ("type", "filament_diameter", "min_extrude_temp")

class Dummy(composite.Object):
    def __init__(self, hal, node):
        composite.Object.__init__(self, hal, node)
        logging.warning("parts.extruder.Dummy.__init__():%s", self.node.name)

class Object(composite.Object):
    def init(self):
        if self.ready:
            return
        self.ready = True
    def register(self):
        pass

def load_node_object(hal, node):
    config_ok = True
    for a in node.module.ATTRS:
        if a not in node.attrs:
            config_ok = False
            break
    if config_ok:
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal, node)

