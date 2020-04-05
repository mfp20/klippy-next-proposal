# Dummy Kinematics.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import composite

class Object(composite.Object):
    def __init__(self, hal, node):
        composite.Object.__init__(self,hal, node)
        logging.warning("kinematics.dummy.Object:__init__():%s", self.node.name)
    def init(self):
        self.ready = True

