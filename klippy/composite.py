# Printer composited part base class.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import part

class Object(part.Object):
    def subs(self, root):
        return root.list_children_deep(list(), root)
    def sub_group(self, root, group):
        return root.get_many_deep(group+" ", list(), root)
    def sub_group_type(self, r, g, t):
        parts = list()
        for p in self.sub_group(r, g):
            if "type" in p.attrs:
                if p.attrs["type"] == t:
                    parts.append(p)
        return parts
    def build(self, indent = 1):
        # for each child
        for c in self.node.list_children():
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

