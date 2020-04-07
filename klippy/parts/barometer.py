# Barometers support class.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import sensor

attrs = ("type", "pin")

class Object(sensor.Object):
    def configure(self):
        pass

def load_node_object(hal, node):
    node.object = Object(hal, node)

