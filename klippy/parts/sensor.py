# Sensors support base class.
#
# Each sensor have:
# - "probe": the actual raw sensor, can be an MCU_* item (ex: endstops) or anything else (ex: thermometers)
# - "value": the sensor raw value
# - "read()": on some sensors (ex: endstops) triggers a "value" update and returns value, on polled sensors (ex: thermometers) it returns the last value
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import part

class Object(part.Object):
    def __init__(self,hal,node):
        part.Object.__init__(self, hal, node)
        self.metaconf["type"] = {"t":"str"}
        # min operating temperature #TODO move in a better location, so that EVERY part have one of those
        self.metaconf["temp_min"] = {"t":"float", "default":-273.0}
        # max operating temperature
        self.metaconf["temp_max"] = {"t":"float", "default":400.0}
        # pin
        self.probe = None
        self.value = 0.
        self.last = None
    def read(self):
        return self.value

