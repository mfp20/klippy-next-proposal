# Support for cart composite part.
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from messaging import msg
from messaging import Kerr as error
import composite

ATTRS = ()

class Dummy(composite.Object):
    def __init__(self, hal, node):
        composite.Object.__init__(self, hal, node)
        logging.warning("(%s) cart.Dummy", node.name)
    def init():
        if self.ready:
            return
        self.ready = True

class Object(composite.Object):
    def init(self):
        if self.ready:
            return
        self.ready = True

def load_node_object(hal, node):
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)

