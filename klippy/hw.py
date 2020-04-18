# Hardware Abstraction Layer. "Pickled".
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, os, sys, collections, importlib, cPickle as pickle
from StringIO import StringIO

from messaging import msg
from messaging import Kerr as error
import tree, commander, controller, timing, temperature, instrument
from parts import *

class Manager:
    def __init__(self, printer_tree):
        self.tree = printer_tree
        # known parts and composites
        self.pgroups = ["mcu", "virtual", "sensor", "stepper", "heater", "cooler", "nozzle"]
        self.cgroups = ["tool", "cart", "rail"]
        # mcu count
        self.mcu_count = 0
        #
        self.ready = True
    def node(self, name):
        if name == "printer":
            return self.tree.printer
        elif name == "hal":
            return self
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
        else:
            return self.tree.printer.object.node(name)
    def add_pgroup(self, pgroup):
        self.pgroups.append(pgroup)
    def add_cgroup(self, cgroup):
        self.cgroups.append(cgroup)
    # objects
    def obj(self, name):
        return self.node(name).object
    def obj_load(self, name):
        node = self.node(name)
        node.object = node.module.load_node_object(self, node)
        node.attrs2obj()
    def obj_save(self, obj):
        out_s = StringIO()
        pickle.dump(obj, out_s)
        out_s.flush()
        return out_s.getvalue()
    def obj_restore(self, obj):
        in_s = StringIO(obj)
        return pickle.load(in_s)
    #
    def _try_autoload_printlets(self):
        path = os.path.join(os.path.dirname(__file__), "printlets")
        for file in os.listdir(path):
            if file.endswith(".py") and not file.startswith("__init__"):
                mod = importlib.import_module("printlets." + file.split(".")[0])
                init_func = getattr(mod, "load_printlet", None)
                #logging.debug("printlets.%s %s", file.split(".")[0], init_func)
                if init_func is not None:
                    return init_func(self)
                return None
    def load_tree_objects(self):
        #logging.debug(self.show("printer", plus="module,deep"))
        logging.debug("- Loading printer objects.")
        self.obj_load("commander")
        self.obj_load("controller")
        self.obj_load("timing")
        self.obj_load("temperature")
        # for each node, create its object
        for node in self.tree.printer.children_deep(list(), self.tree.printer):
            if not node.object:
                # load object and check
                if hasattr(node.module, "load_node_object") and callable(node.module.load_node_object):
                    self.obj_load(node.name)
                if not node.object:
                    parent = node.parent(self.tree.printer, node.name)
                    logging.warning("\t\t- CAN'T LOAD '..:%s:%s'. Moving to spares.", node.parent(self.tree.printer, node.name).name, node.name)
                    self.tree.spare.children[node.name] = parent.children.pop(node.name)
        # build/configure (if needed) each printer shallow children
        #logging.debug(self.show("printer", plus="object,deep"))
        logging.debug("- Building and configuring objects.")
        for name,node in self.tree.printer.children.items():
            if node.name != "reactor" \
                    and node.name != "commander" \
                    and node.name != "hal" \
                    and node.name != "controller" \
                    and not node.name.startswith("kinematic "):
                if node.object:
                    # build printer's children
                    if hasattr(node.object, "_build") and callable(node.object._build):
                        node.object._build()
                    # configure printer's leaves
                    if hasattr(node.object, "configure") and callable(node.object.configure):
                        node.object.configure()
                else:
                    logging.debug("(ERROR) %s, no object", node.name)
        # configure toolhead(s)
        for t in self.tree.printer.children_deep_byname("toolhead ", list()): 
            if isinstance(t.object, instrument.Object):
                t.object._build()
            else:
                t.object.init()
        # init kinematics
        for k in self.tree.printer.children_deep_byname("kinematic ", list()):
            k.object.init()
        # last check before linking objects with "register()"
        for node in self.tree.printer.children_deep(list(), self.tree.printer):
            if hasattr(node.object, "ready"):
                if not node.object.ready:
                    logging.debug("\t %s NOT READY. Moving to spares.", node.name)
                    self.tree.spare.children[node.name] = node.parent(self.tree.printer, node.name).children.pop(node.name)
            else:
                if node.name != "printer":
                    logging.debug("\t %s NOT READY. Moving to spares.", node.name)
                    self.tree.spare.children[node.name] = node.parent(self.tree.printer, node.name).children.pop(node.name)
        # for each node, run object.register() (if any)
        logging.debug("- Registering events and commands.")
        for node in self.tree.printer.children_deep(list(), self.tree.printer):
            if hasattr(node.object, "register") and callable(node.object.register):
                node.object.register()
        # load printer's sniplets, development code to be tested
        logging.debug("- Autoloading extra printlets.")
        self._try_autoload_printlets()
        #logging.debug(self.show("printer", plus="attrs,details,deep"))
    # wrappers
    def get_printer(self):
        return self.node("printer").object
    def get_reactor(self):
        return self.node("reactor").object
    def get_commander(self):
        return self.node("commander").object
    def get_controller(self):
        return self.node("controller").object
    def get_timing(self):
        return self.node("timing").object
    def get_temperature(self):
        return self.node("temperature").object
    def get_hal(self):
        return self.node("hal").object
    def get_toolhead(self, name = None):
        if name:
            return self.obj("toolhead "+name)
        else:
            logging.warning("(FIXME) No toolhead selected, returning first toolhead in tree")
            self.tree.printer.child_get_first("toolhead ")
            return thnode.children["gcode "+thnode.id()].object
    def get_toolhead_child(self, child):
        parent = child.parent(self.tree.printer, child.name)
        if parent.name.startswith("toolhead "):
            return parent.object
        else:
            if parent.name == "printer":
                return None
            return self.get_toolhead_child(parent)
    def get_gcode(self, name = None):
        if name:
            return self.obj("gcode "+name)
        else:
            logging.warning("(FIXME) No toolhead selected, returning first gcode in tree")
            thnode = self.tree.printer.child_get_first("toolhead ")
            return thnode.children["gcode "+thnode.id()].object
    def get_gcode_child(self, child):
        parent = child.parent(self.tree.printer, child.name)
        if parent.name.startswith("toolhead "):
            return parent.children["gcode "+parent.name.split(" ")[1]].object
        else:
            if parent.name == "printer":
                return parent.children["commander"].object
            return self.get_gcode_child(parent)
    def get_kinematic(self, name = None):
        if name:
            return self.node("kinematic "+name).object
        else:
            logging.warning("(FIXME) No toolhead selected, returning first kinematic in tree")
            thnode = self.tree.printer.child_get_first("toolhead ")
            return thnode.children["kinematic "+thnode.id()].object
    def get_kinematic_child(self, child):
        parent = child.parent(self.tree.printer, child.name)
        if parent.name.startswith("kinematic "):
            return parent.object
        else:
            if parent.name == "printer":
                return None
            return self.get_kinematic_child(parent)
    def cleanup(self): 
        self.get_commander().cleanup()
        self.get_controller().cleanup()
        self.get_timing().cleanup()
        self.get_temperature().cleanup()
