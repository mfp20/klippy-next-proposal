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
    def _build(self, indent = 1):
        # for each child
        for c in self.node().children_list():
            # build its children
            if hasattr(c.object, "_build") and callable(c.object._build):
                c.object._build(indent+1)
            # configure its leaves
            if hasattr(c.object, "configure") and callable(c.object.configure):
                c.object.configure()
        # init self
        if hasattr(self, "init") and callable(self.init):
            #logging.debug("\t"*indent + "(init) %s", self.name)
            self.init()
    def parent_bygroup(self, parentgroup):
        parentnode = self.node().parent(self.hal.node("printer"),self.node().name)
        while not parentnode.name.startswith(parentgroup):
            logging.warning("TODO PARENT_BYGROUP: %s", parentnode.name)
            if parentnode.name == "printer":
                return None
            parentnode = parentnode.parent(self.hal.node("printer"),parentnode.name)
        return parentnode
    def child_get_first(self, name, root = None):
        return self.node().child_get_first(name, self.node())
    def children(self):
        return self.node().children_list(self.name)
    def children_bygroup(self, group):
        return self.node().children_list(group+" ")
    def children_bytype(self, group, typ):
        parts = list()
        for p in self.children_bygroup(group):
            if "type" in p.attrs:
                if p.attrs["type"] == typ:
                    parts.append(p)
        return parts
    def children_deep_bygroup(self, group):
        return self.node().children_deep_byname(group+" ", list(), self.node())
    def children_deep_bytype(self, group, typ):
        parts = list()
        for p in self.children_deep_bygroup(group):
            if "type" in p.attrs:
                if p.attrs["type"] == typ:
                    parts.append(p)
        return parts

