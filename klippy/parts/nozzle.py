# Example simple "part" stub file.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import part

ATTRS = ("diameter",)

# TODO 
class Dummy(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self, hal, node)
        logging.warning("(%s) nozzle.Dummy", node.name)
    def configure():
        if self.ready:
            return
        self.ready = True

class Object(part.Object):
    def configure(self):
        self.ready = True

def load_node_object(hal, node):
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)
    return node.object

