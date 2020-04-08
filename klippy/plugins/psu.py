# Support for Power management.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging,collections
import part

ATTRS = ("volt", "power", "pin_pg")

# TODO 
class Dummy(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self, hal, node)
        logging.warning("(%s) tcontrol.Dummy", node.name)
    def configure():
        if self.ready:
            return
        self.ready = True

class Object(part.Object):
    def configure(self):
        if self.ready:
            return 
        self.ready = True

def load_tree_node(hal, node, parts):
    used_parts = set()
    # add new part group
    hal.add_pgroup("psu")
    # adding node to printing tree
    hal.tree.printer.children["power"] = node
    # remove printer part listing
    hal.tree.printer.attrs.pop("psu")
    # remove part from spares
    used_parts.add(node.name)
    return used_parts

def load_node_object(hal, node):
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)

