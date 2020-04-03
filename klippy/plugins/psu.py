# Support for Power management.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging,collections
import part

attrs = ("volt", "power", "pin_pg")

class Dummy(part.Object):
    def __init__(self, hal, node):
        logging.warning("Dummy:__init__:%s", node.name)
        part.Object(self, hal, node)

class Object(part.Object):
    pass

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
    config_ok = True
    for a in node.module.attrs:
        if a not in node.attrs:
            config_ok = False
            break
    if config_ok:
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal, node)

