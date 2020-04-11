# Hydrometer support class.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import sensor

ATTRS = ("type", "pin")

# TODO 
class Dummy(sensor.Object):
    def __init__(self, hal, node):
        sensor.Object.__init__(self, hal, node)
        logging.warning("(%s) barometer.Dummy", node.name)
    def configure():
        if self.ready:
            return
        self.ready = True

class Object(sensor.Object):
    def configure(self):
        pass

def load_node_object(hal, node):
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)

