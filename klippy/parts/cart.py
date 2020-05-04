# Cart composite.
#
# Copyright (C) 2018-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from text import msg
from error import KError as error
import tree
logger = logging.getLogger(__name__)

class PrinterHeaterBed:
    def __init__(self, config):
        self.printer = config.get_printer()
        pheater = self.printer.lookup('heater')
        self.heater = pheater.setup_heater(config, 'B')
        self.get_status = self.heater.get_status
        self.stats = self.heater.stats
        # Register commands
        gcode = self.printer.lookup('gcode')
        gcode.register_command("M140", self.cmd_M140)
        gcode.register_command("M190", self.cmd_M190)
    def cmd_M140(self, params, wait=False):
        # Set Bed Temperature
        gcode = self.printer.lookup('gcode')
        temp = gcode.get_float('S', params, 0.)
        toolhead = self.printer.lookup('toolhead')
        self.heater.set_temp(temp)
        if wait and temp:
            gcode.wait_for_temperature(self.heater)
    def cmd_M190(self, params):
        # Set Bed Temperature and Wait
        self.cmd_M140(params, wait=True)

ATTRS = ("type",)

class Dummy(tree.Composite):
    def __init__(self, name, hal):
        super().__init__(name, hal = hal)
        logger.warning("(%s) cart.Dummy", name)
    def _init():
        if self.ready:
            return
        self.ready = True

class Object(tree.Composite):
    def __init__(self, name, hal):
        super().__init__(name, hal = hal)
    def _init(self):
        if self.ready:
            return
        self.ready = True

def load_node(name, hal, cparser):
    return Object(name, hal)

