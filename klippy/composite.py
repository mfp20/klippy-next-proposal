# Printer composited part base class.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from messaging import msg
from messaging import Kerr as error
import part

class Object(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self,hal,node)
    def children_bygroup(self, group):
        return self.node.children_list(group+" ")
    def children_bytype(self, group, typ):
        parts = list()
        for p in self.children_bygroup(group):
            if "type" in p.attrs:
                if p.attrs["type"] == typ:
                    parts.append(p)
        return parts
    def children_deep_bygroup(self, group):
        return root.children_deep(group+" ", list(), self.node)
    def children_deep_bytype(self, group, typ):
        parts = list()
        for p in self.children_deep_bygroup(group):
            if "type" in p.attrs:
                if p.attrs["type"] == typ:
                    parts.append(p)
        return parts
    def build(self, indent = 1):
        # for each child
        for c in self.node.children_list():
            # build its children
            if hasattr(c.object, "build") and callable(c.object.build):
                if c.name not in self.hal.ready_composite:
                    logging.debug("\t"*indent + "(build) %s", c.name)
                    c.object.build(indent+1)
            # configure its leaves
            if hasattr(c.object, "configure") and callable(c.object.configure):
                if c.name not in self.hal.ready_part:
                    logging.debug("\t"*indent + "(configure) %s", c.name)
                    c.object.configure()
                    self.hal.ready_part.append(self.node.name)
        # init self
        if hasattr(self.node.object, "init") and callable(self.node.object.init):
            logging.debug("\t"*indent + "(init) %s", self.node.name)
            self.node.object.init()
            self.hal.ready_composite.append(self.node.name)

