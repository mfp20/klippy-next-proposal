# Hardware Abstraction Layer. "Pickled".
#
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, os, sys, collections, importlib, inspect, pickle
from io import StringIO
from text import msg
from error import KError as error
import tree, process, commander, controller, timing, temperature
logger = logging.getLogger(__name__)

class Manager(tree.Part):
    def __init__(self, root):
        super().__init__("hal", hal = self)
        self.master = root
        # known parts and composites
        self.pgroups = ["mcu", "virtual", "sensor", "stepper", "heater", "cooler", "nozzle"]
        self.cgroups = ["tool", "cart", "rail"]
        self.mcu_count = 0
        #
        # add hal default children
        self.child_add(timing.load_node("timing", self))
        self.child_add(temperature.load_node("temperature", self))
        self.child_add(controller.load_node("controller", self))
        self.child_add(commander.load_node("commander", self))
        self.ready = True
    def _show_details(self, indent = 0):
        "Return formatted details about hardware abstraction layer node."
        txt = "\t"*(indent+1) + "----------------- (tree nodes)\n"
        node = self.children_deep()
        nodedict = {}
        for n in node:
            nodedict[n.name] = n
        for n in sorted(nodedict):
            txt = txt + '\t' * (indent+1) + "- " + str(n).ljust(20, " ") + " " + str(nodedict[n]).split(" ")[0][1:] + "\n"
        return txt
    def add_pgroup(self, pgroup):
        self.pgroups.append(pgroup)
    def add_cgroup(self, cgroup):
        self.cgroups.append(cgroup)
    #s
    def _load_plugin(self, config, section):
        module_parts = section.split()
        module_name = module_parts[0]
        py_name = os.path.join(os.path.dirname(__file__), "plugins", module_name + ".py")
        py_dirname = os.path.join(os.path.dirname(__file__), "plugins", module_name, "__init__.py")
        if not os.path.exists(py_name) and not os.path.exists(py_dirname):
            logger.warning(msg(("noexist1", py_name)))
            return None
        return importlib.import_module('plugins.' + module_name)
    #
    def _load_printlets(self):
        path = os.path.join(os.path.dirname(__file__), "printlets")
        for file in os.listdir(path):
            if file.endswith(".py") and not file.startswith("__init__"):
                mod = importlib.import_module("printlets." + file.split(".")[0])
                init_func = getattr(mod, "load_printlet", None)
                #logger.debug("printlets.%s %s", file.split(".")[0], init_func)
                if init_func is not None:
                    return init_func(self)
                return None
    def _compose(self, composite, cparser, parts, composites):
        "Compose a composite part, nesting it's children."
        name = composite.name()
        for o in cparser.options(name):
            if o in self.pgroups:
                for p in cparser.get(name, o).split(","):
                    if p != "none":
                        if o+" "+p in parts:
                            composite.child_add(parts.pop(o+" "+p))
            elif o == "sensor_min" or o == "sensor_max" or o == "sensor_level":
                for p in cparser.get(name, o).split(","):
                    if "sensor "+p in parts:
                        composite.child_add(parts.pop("sensor "+p))
            elif o not in self.cgroups:
                pass
            else:
                for p in cparser.get(name, o).split(","):
                    if p != "none":
                        if o+" "+p in composites:
                            composite.child_add(self._compose(composites.pop(o+" "+p), cparser, parts, composites))
        return composite
    def _compose_toolhead(self, name, cparser, parts):
        "Compose a toolhead, creating it's kinematic and gcode, then nesting it's children."
        # kinematic is the toolhead's root
        ktype = cparser.get(name, 'kinematics')
        kmod = importlib.import_module('kinematics.' + ktype)
        knode = kmod.load_node('kinematic '+name.split(" ")[1], self.hal, cparser)
        self.master.child_add(knode)
        # toolhead node is kinematic's child
        tmod = importlib.import_module('instrument')
        toolhead = tmod.load_node(name, self.hal, cparser)
        toolhead.meta_conf(cparser)
        # gcode node is toolhead's child
        gmod = importlib.import_module('commander')
        gnode = gmod.load_node("gcode "+name.split(" ")[1], self.hal, cparser)
        knode.child_add(gnode)
        knode.child_add(toolhead)
        # build toolhead rails and carts
        return kmod.build_toolhead(self.hal, knode, toolhead, cparser, parts)
    def obj_load(self, cparser, name, parts = None, composites = None):
        group = name.split(" ")[0]
        ident = name.split(" ")[1]
        if group == 'mcu' or group == 'virtual':
            module = importlib.import_module('controller')
        elif group == 'sensor':
            module = importlib.import_module("parts.sensors."+cparser.get(name,"type"))
        elif group == 'stepper' or group == 'servo' or group == 'heater' or group == 'cooler':
            module = importlib.import_module("parts.actuators." + group)
        elif group == "rail" or group == "cart":
            module = importlib.import_module("parts."+group)
        elif group == "tool":
            module = importlib.import_module("parts."+cparser.get(name,"type"))
        else:
            module = importlib.import_module("parts." + group)
        if group in self.pgroups:
            obj = module.load_node(name, self, cparser)
        elif group in self.cgroups:
            obj = self._compose(module.load_node(name, self, cparser), cparser, parts, composites)
        else:
            raise error("Unknown group '%s'", group)
        obj.meta_conf(cparser)
        return obj
    def obj(self, name):
        if name == "printer":
            return self.master
        elif name == "hal":
            return self
        elif name == "reactor":
            return self.master.child("reactor")
        elif name == "timing":
            return self.child("timing")
        elif name == "temperature":
            return self.child("temperature")
        elif name == "commander":
            return self.child("commander")
        elif name == "controller":
            return self.child("controller")
        else:
            return self.master.node(name)
    def obj_save(self, obj):
        out_s = StringIO()
        pickle.dump(obj, out_s)
        out_s.flush()
        return out_s.getvalue()
    def obj_restore(self, obj):
        in_s = StringIO(obj)
        return pickle.load(in_s)
    def obj_is_part(self, obj):
        if eval("tree.Part") in inspect.getmro(obj.__class__):
            return True
        return False
    def obj_is_composite(self, obj):
        if eval("tree.Composite") in inspect.getmro(obj.__class__):
            return True
        return False
    # wrappers
    def get_printer(self):
        return self.obj("printer")
    def get_reactor(self):
        return self.obj("reactor")
    def get_commander(self):
        return self.obj("commander")
    def get_controller(self):
        return self.obj("controller")
    def get_timing(self):
        return self.obj("timing")
    def get_temperature(self):
        return self.obj("temperature")
    def get_hal(self):
        return self
    def get_toolhead(self, name = None):
        if name:
            return self.obj("toolhead "+name)
        else:
            logger.warning("(FIXME) No toolhead selected, returning first toolhead in tree")
            return self.master.child_get_first("toolhead ")
    def get_toolhead_child(self, child):
        parent = child.parent(self.master, child.name())
        if parent.name().startswith("toolhead "):
            return parent
        else:
            if parent.name() == "printer":
                return None
            return self.get_toolhead_child(parent)
    def get_gcode(self, name = None):
        if name:
            return self.obj("gcode "+name)
        else:
            logger.warning("(FIXME) No toolhead selected, returning first gcode in tree")
            thnode = self.master.child_get_first("toolhead ")
            return thnode.children["gcode "+thnode.id()]
    def get_gcode_child(self, child):
        parent = child.parent(child.name(), self.master)
        if parent.name().startswith("toolhead "):
            return parent.child_deep("gcode "+parent.name().split(" ")[1])
        else:
            if parent.name() == "printer":
                return parent.child_deep("commander")
            return self.get_gcode_child(parent)
    def get_kinematic(self, name = None):
        if name:
            return self.obj("kinematic "+name)
        else:
            logger.warning("(FIXME) No toolhead selected, returning first kinematic in tree")
            thnode = self.master.child_deep("toolhead ")
            return thnode.child("kinematic "+thnode.id())
    def get_kinematic_child(self, child):
        parent = child.parent(child.name(), self.master)
        if parent.name().startswith("kinematic "):
            return parent
        else:
            if parent.name() == "printer":
                return None
            return self.get_kinematic_child(parent)
    def cleanup(self): 
        self.get_commander().cleanup()
        self.get_controller().cleanup()
        self.get_timing().cleanup()
        self.get_temperature().cleanup()

