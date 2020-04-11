# Printer simple part base class.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, collections
from messaging import msg
from messaging import Kerr as error

class Object():
    metaconf = collections.OrderedDict()
    def __init__(self, hal, node):
        self.hal = hal
        if node:
            if not hasattr(self, "name"):
                self.name = node.name
        else:
            if not hasattr(self, "name"):
                self.name = "object anonymous"
        self.ready = False
    def _show_methods(self):
        logging.info("NODE '%s' OBJ '%s'", self.node().name, self)
        for m in sorted([method_name for method_name in dir(self) if callable(getattr(self, method_name))]):
            logging.info("\tMETHOD: %s", m)
        for a in sorted(vars(self)):
            logging.info("\tVAR: %s VALUE %s", a, getattr(self, a))
    def group(self):
        return self.name.split(" ")[0]
    def id(self):
        return self.name.split(" ")[1]
    def node(self):
        return self.hal.node(self.name)
