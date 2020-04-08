# Example plugin.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
# 
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Init procedure:
# 1. user runs Klippy
# 2. klippy, reads config and starts composer
# 3. composer, assembles parts, create the tree root and basic printer's facilities, then loads all the modules. All plugins are added as "part". All nodes have a module.
# 4. composer, calls load_tree_node(hal, node) for each and all modules having such method. All nodes are in place.
# 5. hal, calls load_node_object() for each and all nodes having such method in their module. All nodes have a bare minimum object (ie: self.hal and self.node).
# 6. hal, calls build() for each and all printer's shallow children composites having such method in their module, as well as configure() for simple parts.
# 7. hal, calls build() for each toolhead's branch, and build() configures/inits every (deep) children. Then each toolhead is init'ed as well.
#    All parts and composites are ready.
# 8. hal, calls init() for each kinematic node. Printer knows what and how to move.
# 9. hal, calls register() for each and all instantiated in-tree objects having such method. All events and commands are registered to their own managers.
# 11. Init is over. Klippy goes back in control and will soon start accepting jobs... 
#
# Available hooks in each plugin file, in sequence:
#   1. load_tree_node(), called from Composer.
#   2. load_node_object(), called from HAL.
#   3. configure() OR init(), called from HAL.
#   4. register(), called from HAL.

# import logging to be able to output debug messages
import logging
# import part to inherit its methods
import part

# mandatory options for this module configuration section
# note: it's a python tuple! ie: in case of no options must write "tuple()", in case of single option remember to place a comma at the end within the parenthesis
ATTRS = ("option1",)

# Dummy, the dummy object to be called if the attrs check fails.
# It must have (about) the same methods found in the real object.
class Dummy(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self, hal, node)
        logging.warning("(%s) example_plugin.Dummy", node.name)
    def configure(self):
        pass
    def init(self):
        pass
    def register(self):
        pass

# Object, the real object.
#   - for a simple part use: "class Object(part.Object):"
#   - for a composite part use: "class Object(composite.Object):"
class Object(part.Object):

    # simple parts and composite parts might need to call the parent's __init__, ex: "part.Object.__init__(self, hal, node)"
    # note: the same applies for Dummy
    def __init__(self, hal, node):
        part.Object.__init__(self, hal, node)

    # simple parts only
    def configure(self):
        logging.debug("(%s) configure()", self.node.name)
        if self.ready:
            return
        self.ready = True

    # composite parts only
    #def init(self):
    #    logging.debug("(%s) init()", self.node.name)
    #    if self.ready:
    #        return
    #    self.ready = True

    # place here events and commands to be registered
    # not recommended: place here anything couldn't be done before
    def register(self):
        logging.debug("(%s) register()", self.node.name)

def load_tree_node(hal, node, parts):
    # used_parts are removed from the parts pool after all plugins are processed (ie: plugins can use the same part multiple times)
    logging.debug("(%s) load_tree_node()", node.name)
    used_parts = set()
    # add new part to HAL parts groups
    hal.add_pgroup("example_plugin")
    # adding node as printer's child (or any other node's child)
    # note: don't need to be added. You can do any tree manipulation here.
    hal.tree.printer.child_set(node)
    # add part for postponed removal from spares.
    # note: you don't need to remove it. Can leave the obect here for later removal (from "spares", not from "printer").
    used_parts.add(node.name)
    return used_parts

def load_node_object(hal, node):
    logging.debug("(%s) load_node_object()", node.name)
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)

