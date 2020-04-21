# Printer simple part base class.
#
# Each part have:
# - pin: dict of pins used
# - _show_methods(): developer utility to check available methods of an instance
# - group(): returns the first part of its own name := "group id"
# - id(): returns the second part of its own name := "group id"
# - node(): returns its own node (if any)
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
                self.name = "anonymous object"
        #
        self.pin = {}
        #
        self.ready = False
    def group(self):
        return self.name.split(" ")[0]
    def id(self):
        return self.name.split(" ")[1]
    def node(self):
        return self.hal.node(self.name)

