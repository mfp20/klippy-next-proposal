# Printer simple part base class.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import tree

class Object(tree.PrinterNode):
    def __init__(self, hal, node):
        self.hal = hal
        self.node = node
    def check_attrs(self):
        if self.node.module:
            if hasattr(self.node.module, "attrs"):
                for a in self.node.module.attrs:
                    if a not in self.node.attrs:
                        return False
            else:
                return False
        else:
            return False
        return True

