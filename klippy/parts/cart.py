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

ATTRS = ()

class Dummy(composite.Object):
    def __init__(self, hal, cnode):
        logging.warning("Dummy: %s", cnode.name)
        self.hal = hal
        self.node = cnode

class Object(composite.Object):
    def init(self):
        if self.ready:
            return
        self.ready = True

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

