# Hardware Abstraction Layer. "Pickled".
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, sys, cPickle as pickle
from StringIO import StringIO

from messaging import msg
from messaging import Kerr as error
import tree, reactor, commander, controller, timing, temperature, instrument
from parts import *

class Manager:
    def __init__(self, printermod, printerobj):
        self.tree = tree.PrinterTree()
        self.tree.printer.module = printermod
        self.tree.printer.object = printerobj
        self.tree.printer.child_set(tree.PrinterNode("hal"))
        self.tree.printer.children["hal"].module = sys.modules[__name__]
        self.tree.printer.children["hal"].object = self
        self.tree.printer.child_set(tree.PrinterNode("reactor"))
        self.get_node("reactor").object = reactor.Reactor(self, self.get_node("reactor"))
        self.pgroups = ["mcu", "sensor", "stepper", "heater", "cooler", "nozzle"]
        self.cgroups = ["tool", "cart", "rail"]
        self.mcu_count = 0
    def register(self):
        self.get_commander().register_command('SHOW_PRINTER', self.tree.cmd_SHOW_PRINTER, desc=self.tree.cmd_SHOW_PRINTER_help)
    def add_pgroup(self, pgroup):
        self.pgroups.append(pgroup)
    def add_cgroup(self, cgroup):
        self.cgroups.append(cgroup)
    def load_tree_objects(self):
        #logging.debug(self.show(plus="module,object"))
        logging.info("- Loading printer objects.")
        # load commander
        self.get_node("commander").object = self.get_node("commander").module.Dispatch(self, self.get_node("commander"))
        # load controller
        controller.load_node_object(self, self.get_node("controller"))
        # load clock
        timing.load_node_object(self, self.get_node("timing"))
        # load thermal controller
        temperature.load_node_object(self, self.get_node("temperature"))
        # for each node, create its object
        for node in self.tree.printer.children_deep(list(), self.tree.printer):
            if not node.object:
                # load object and check
                if hasattr(node.module, "load_node_object") and callable(node.module.load_node_object):
                    node.module.load_node_object(self, node)
                if not node.object:
                    logging.warning("\t\t- CAN'T LOAD: ..:%s:%s", node.node_get_parent(self.tree.printer, node.name).name, node.name)
        #logging.debug(self.show())
        # build/configure (if needed) each printer shallow children
        logging.info("- Building and configuring objects.")
        for name,node in self.tree.printer.children.items():
            if node.name != "reactor" \
                    and node.name != "commander" \
                    and node.name != "hal" \
                    and node.name != "controller" \
                    and not node.name.startswith("kinematic "):
                if node.object:
                    # build printer's children
                    if hasattr(node.object, "build") and callable(node.object.build):
                        #logging.debug("BUILD: %s", node.name)
                        node.object.build()
                    # configure printer's leaves
                    if hasattr(node.object, "configure") and callable(node.object.configure):
                        #logging.debug("CONFIGURE: %s", node.name)
                        node.object.configure()
                else:
                    logging.debug("(ERROR) %s, no object", node.name)
        # configure toolhead(s)
        for t in self.tree.printer.children_deep_byname("toolhead ", list()): 
            #logging.debug("BUILD %s", t.name)
            if isinstance(t.object, instrument.Object):
                t.object.build()
            else:
                t.object.init()
        # init kinematics
        for k in self.tree.printer.children_deep_byname("kinematic ", list()):
            #logging.debug("INIT %s %s", k.name, k.object)
            k.object.init()
        # last check
        for node in self.tree.printer.children_deep(list(), self.tree.printer):
            if hasattr(node.object, "ready"):
                if not node.object.ready:
                    logging.debug("\t %s NOT READY.", node.name)
            else:
                if node.name != "printer":
                    logging.debug("\t %s NOT READY.", node.name)
        #logging.debug(self.show())
        logging.info("- Registering events and commands.")
        # for each node, run object.register()
        for node in self.tree.printer.children_deep(list(), self.tree.printer):
            if hasattr(node.object, "register") and callable(node.object.register):
                node.object.register()
        #logging.debug(self.show())
    def get_node(self, name):
        if name == "printer":
            return self.tree.printer
        elif name == "reactor":
            return self.tree.printer.children["reactor"]
        elif name == "commander":
            return self.tree.printer.children["commander"]
        elif name == "controller":
            return self.tree.printer.children["controller"]
        elif name == "timing":
            return self.tree.printer.children["controller"].children["timing"]
        elif name == "temperature":
            return self.tree.printer.children["controller"].children["temperature"]
        elif name == "hal":
            return self
        else:
            return self.tree.printer.child_get_first(name)
    def attr_set(self, nodename, attrname, value):
        self.get_node(nodename).attr_set(attrname, value)
    def get_attr(self, nodename, attrname):
        return self.get_node(nodename).attrs[attrname]
    def get_object(self, name):
        return get_node(name).object
    def get_printer(self):
        return self.get_node("printer").object
    def get_reactor(self):
        return self.get_node("reactor").object
    def get_commander(self):
        return self.get_node("commander").object
    def get_controller(self):
        return self.get_node("controller").object
    def get_timing(self):
        return self.get_node("timing").object
    def get_temperature(self):
        return self.get_node("temperature").object
    def get_hal(self):
        return self.get_node("hal").object
    def get_toolhead(self, name = None):
        if name:
            return self.get_node("toolhead "+name).object
        else:
            logging.warning("(FIXME) No toolhead selected, returning first toolhead in tree")
            self.tree.printer.child_get_first("toolhead ")
            return thnode.children["gcode "+thnode.get_id()].object
    def get_gcode(self, name = None):
        if name:
            return self.get_node("gcode "+name).object
        else:
            logging.warning("(FIXME) No toolhead selected, returning first gcode in tree")
            thnode = self.tree.printer.child_get_first("toolhead ")
            return thnode.children["gcode "+thnode.get_id()].object
    def get_kinematic(self, name = None):
        if name:
            return self.get_node("kinematic "+name).object
        else:
            logging.warning("(FIXME) No toolhead selected, returning first kinematic in tree")
            thnode = self.tree.printer.child_get_first("toolhead ")
            return thnode.children["kinematic "+thnode.get_id()].object
    def del_node(self, name):
        self.tree.printer.del_node(name)
    def move_node(self, name, newparentname):
        self.tree.printer.move_node(name, newparentname)
    def freeze_object(self, obj):
        out_s = StringIO()
        pickle.dump(obj, out_s)
        out_s.flush()
        return out_s.getvalue()
    def unfreeze_object(self, obj):
        in_s = StringIO(obj)
        return pickle.load(in_s)
    def show(self, indent=2, plus = "object"):
        return self.tree.show(indent, plus)
    def ready(self):
        logging.debug(self.show())

