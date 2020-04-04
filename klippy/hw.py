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

class sentinel:
    pass

class Manager:
    def __init__(self, printermod, printerobj):
        self.tree = tree.PrinterTree()
        self.tree.printer.module = printermod
        self.tree.printer.object = printerobj
        self.tree.printer.set_child(tree.PrinterNode("hal"))
        self.tree.printer.children["hal"].module = sys.modules[__name__]
        self.tree.printer.children["hal"].object = self
        self.tree.printer.set_child(tree.PrinterNode("reactor"))
        self.get_node("reactor").object = reactor.Reactor(self, self.get_node("reactor"))
        self.pgroups = ["mcu", "sensor", "stepper", "heater", "cooler", "nozzle"]
        self.cgroups = ["rail", "tool", "cart"]
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
        logging.debug("\tcommander")
        self.get_node("commander").object = self.get_node("commander").module.Dispatch(self, self.get_node("commander"))
        # load controller
        logging.debug("\tcontroller")
        controller.load_node_object(self, self.get_node("controller"))
        # load clock
        logging.debug("\ttiming")
        timing.load_node_object(self, self.get_node("timing"))
        # load thermal controller
        logging.debug("\ttemperature")
        temperature.load_node_object(self, self.get_node("temperature"))
        # for each node, create its object
        for node in self.tree.printer.list_children_deep(list(), self.tree.printer):
            if not node.object:
                # load object and check
                if hasattr(node.module, "load_node_object") and callable(node.module.load_node_object):
                    logging.debug("\t%s", node.name)
                    node.module.load_node_object(self, node)
                    if not node.object:
                        logging.warning("     - CAN'T LOAD: ..:%s:%s", node.get_parent(node).name, node.name)
        # for each printer shallow children, build/configure (if needed)
        logging.info("- Building and configuring printer's children.")
        self.ready_part = list()
        self.ready_composite = list()
        for name,node in self.tree.printer.children.items():
            if node.name != "reactor" \
                    and node.name != "commander" \
                    and node.name != "hal" \
                    and node.name != "controller" \
                    and not node.name.startswith("toolhead"):
                if node.object:
                    # build printer's children
                    if hasattr(node.object, "build") and callable(node.object.build):
                        if node.name not in self.ready_composite:
                            logging.debug("\t(build) %s", node.name)
                            node.object.build()
                    # configure printer's leaves
                    if hasattr(node.object, "configure") and callable(node.object.configure):
                        if node.name not in self.ready_part:
                            logging.debug("\t(configure) %s", node.name)
                            node.object.configure()
                            self.ready_part.append(node.name)
                else:
                    logging.debug("(ERROR) %s, no object", node.name)
        # configure toolhead(s)
        for t in self.tree.printer.get_many_deep("toolhead ", list()): 
            t.children["gcode "+t.name.split(" ")[1]].object = t.children["gcode "+t.name.split(" ")[1]].module.Gcode(self, t.children["gcode "+t.name.split(" ")[1]])
            if isinstance(t.object, instrument.Object):
                logging.info("- Building and configuring %s", t.name)
                t.object.build()
        del(self.ready_part)
        del(self.ready_composite)
        #logging.debug(self.show())
    def register_ec(self):
        logging.info("- Registering events and commands.")
        # for each node, run object.register()
        for node in self.tree.printer.list_children_deep(list(), self.tree.printer):
            if hasattr(node.object, "register") and callable(node.object.register):
                logging.debug("\t%s", node.name)
                node.object.register()
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
            return self.tree.printer.get_first_deep(name)
    def set_attr(self, nodename, attrname, value):
        self.get_node(nodename).set_attr(attrname, value)
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
    def get_gcode(self, name = None):
        if name:
            return self.get_node("gcode "+name).object
        else:
            logging.warning("(FIXME) No toolhead selected, returning first gcode in tree")
            thnode = self.tree.printer.get_first_deep("toolhead ")
            return thnode.children["gcode "+thnode.name.split(" ")[1]].object
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
            self.tree.printer.get_first_deep("toolhead ")
            return thnode.children["gcode "+thnode.name.split(" ")[1]].object
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

