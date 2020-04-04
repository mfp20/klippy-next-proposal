# Printer simple part base class.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from messaging import msg
from messaging import Kerr as error

class Object():
    def __init__(self, hal, node):
        self.hal = hal
        self.node = node

