# Heater support file.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import part

attrs = ("type", "pin",)

class Object(part.Object):
    def configure(self):
        pass

def load_node_object(hal, node):
    node.object = Object(hal, node)
