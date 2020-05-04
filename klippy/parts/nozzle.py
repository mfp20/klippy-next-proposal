# Support for nozzles.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import tree

# TODO 
class Dummy(tree.Part):
    def __init__(self, name, hal):
        super().__init__(name, hal = hal)
        logger.warning("(%s) nozzle.Dummy", name)
    def _configure():
        if self.ready:
            return
        self.ready = True

class Object(tree.Part):
    def __init__(self, name, hal):
        super().__init__(name, hal = hal)
        self.metaconf["diameter"] = {"t":"float", "above":0.}
    def _configure(self):
        self.ready = True

ATTRS = ("diameter",)
def load_node(name, hal, cparser):
    return Object(name, hal)

