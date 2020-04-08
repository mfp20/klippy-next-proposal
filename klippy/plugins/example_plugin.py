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
# 5. hal, calls load_node_object() for each and all nodes having such method in their module. All nodes have a bare minimum object.
# 6. hal, calls build() for each and all composites having such method in their module. Printer's shallow children first, toolhead after.
# 7. build(), calls configure() for each and all leaves having such method in their module. All simple parts are ready. 
# 8. hal, calls init() for each and all composites having such method in their module. All composites are ready.
# 9. hal, calls register() for each and all instantiated in-tree objects having such method. All events and commands are registered to their own managers.
# 10. Init is over. Klippy goes back in control and will start accepting jobs... 

# mandatory options for this module configuration section
# note: it's a python tuple! ie: in case of no options must write "tuple()", in case of single option remember to place a comma at the end within the parenthesis
ATTRS = ("option1",)

# simple part: class ExampleModule(part.Object):
# composite part: class ExampleModule(composite.Object):
class ExampleModule:
    # simple parts and composite parts don't need __init__, it's inherited
    def __init__(self, hal, node):
        pass
    # simple parts only
    def configure(self):
        pass
    # composite parts only
    def init(self):
        pass
    # place here events and commands to be registered
    def register(self):
        pass

def load_tree_node(hal, node, parts):
    # used_parts are removed from the parts pool after all extra modules are processed (ie: extra modules can use the same part multiple times)
    used_parts = list()
    # ...
    return used_parts

def load_node_object(hal, node):
    node.object = ExampleModule(hal, node)

