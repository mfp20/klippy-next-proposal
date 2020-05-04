# Sensors base class.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from text import msg
from error import KError as error
import tree
logger = logging.getLogger(__name__)

class Object(tree.Part):
    def __init__(self, name, hal):
        super().__init__(name, hal = hal)
        self.metaconf["type"] = {"t":"str"}
        # min operating temperature #TODO move in a better location, so that EVERY part have one of those
        self.metaconf["temp_min"] = {"t":"float", "default":-273.0}
        # max operating temperature
        self.metaconf["temp_max"] = {"t":"float", "default":400.0}
        # sensor probe
        self.probe = None
        # last sensor value
        self.value = 0.
        # last sensor update
        self.last = None
    def read(self):
        return self.value

