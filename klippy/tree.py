# Define a printer node := {name, attrs, children, module, object} and a printer tree := {printer, spare}
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import collections, logging
from messaging import msg
from messaging import Kerr as error

class PrinterNode:
    def __init__(self, name, attrs = None, children = None):
        self.name = name
        self.attrs = collections.OrderedDict()
        self.children = collections.OrderedDict()
        self.module = None
        self.object = None
    def group(self):
        return self.name.split(" ")[0]
    def id(self):
        parts = self.name.split(" ")
        if len(parts) > 1:
            return parts[1]
        else:
            logging.warning("'%s' doesn't have group.", self.name)
            return parts[0]
    def parent(self, root, childname):
        if not root: root = self
        for cn in root.children.keys():
           if cn.startswith(childname): return root
           ccn = root.children[cn].parent(root.children[cn], childname)
           if ccn: return ccn
        return None
    # attrs needed for object __init__
    def attrs_check(self, attrs = None):
        if self.module:
            if attrs:
                myattrs = "ATTRS_"+attrs.upper()
            else:
                myattrs = "ATTRS"
            if hasattr(self.module, myattrs):
                for a in getattr(self.module, myattrs):
                    if a not in self.attrs:
                        if self.name:
                            logging.warning("AttrsCheck: no option '%s' for node '%s'.", a, self.name)
                        return False
            else:
                if self.name:
                    logging.warning("AttrsCheck: no attrs for node '%s'.", self.name)
                return False
        else:
            if self.name:
                logging.warning("AttrsCheck: no module for node '%s'.", self.name)
            return False
        return True
    # set attr
    def attr_set(self, key, value):
        self.attrs[key] = value
    # get attr
    def attr(self, attr):
        #logging.warning("ATTR_GET: '%s' ATTR %s", self.name, attr)
        try:
            return self.attrs[attr]
        except Exception as e:
            logging.info("\tEXCEPTION! '%s' - '%s'", self.name, attr)
            logging.info(self.attrs)
            return "|||noattr|||"
    # validate and create attrs
    def attr_check_default(self, template):
        if "default" in template:
            return True
        return False
    def attr_check_minmax(self, template, value):
        if "minval" in template:
            if value < template["minval"]:
                return True
        if "maxval" in template:
            if value > template["maxval"]:
                return True
        return False
    def attr_check_abovebelow(self, template, value):
        if "above" in template:
            if value <= template["above"]:
                return True
        if "below" in template:
            if value >= template["below"]:
                return True
        return False
    def attr_check_choice(self, template, value):
        if value in template["choices"]:
            return False
        return True
    # load node attrs as object's attrs
    def _name2ref(self, name, value):
        #logging.info("SET '%s' to '%s'", name, value)
        if hasattr(self.object, name):
            raise error("Attr exists. Please check option name '%s' for '%s'", name, self.name)
        else:
            setattr(self.object, name, value)
        #logging.info("\t'%s' is '%s'", name, getattr(self.object, name))
    def attrs2obj(self):
        if hasattr(self, "attrs"): 
            for a in self.object.metaconf:
                # convert var references in values, if a var reference is given as value for another var
                for m in self.object.metaconf[a].items():
                    if isinstance(m[1], str) and m[1].startswith("self."):
                        self.object.metaconf[a][m[0]] = getattr(self.object, m[1].split(".", 1)[1])
                #
                if a in self.attrs:
                    if self.object.metaconf[a]["t"] == "bool":
                        if isinstance(self.attr(a), str) and self.attr(a).startswith("self."):
                            value = bool(getattr(self.object, self.attr(a).split(".", 1)[1]))
                        else:
                            value = bool(self.attr(a))
                    elif self.object.metaconf[a]["t"] == "int":
                        if isinstance(self.attr(a), str) and self.attr(a).startswith("self."):
                            value = int(getattr(self.object, self.attr(a).split(".", 1)[1]))
                        else:
                            value = int(self.attr(a))
                        if self.attr_check_minmax(self.object.metaconf[a], value):
                            raise error("Value '%s' exceed min/max for option '%s' in node '%s'." % (value, a, self.name))
                    elif self.object.metaconf[a]["t"] == "float":
                        if isinstance(self.attr(a), str) and self.attr(a).startswith("self."):
                            value = float(getattr(self.object, self.attr(a).split(".", 1)[1]))
                        else:
                            value = float(self.attr(a))
                        if self.attr_check_minmax(self.object.metaconf[a], value):
                            raise error("Value '%s' exceed min/max for option '%s' in node '%s'." % (value, a, self.name))
                        if self.attr_check_abovebelow(self.object.metaconf[a], value):
                            raise error("Value '%s' above/below maximum/minimum for option '%s' in node '%s'." % (value, a, self.name))
                    elif self.object.metaconf[a]["t"] == "str":
                        if isinstance(self.attr(a), str) and self.attr(a).startswith("self."):
                            value = str(getattr(self.object, self.attr(a).split(".", 1)[1]))
                        else:
                            value = str(self.attr(a))
                    elif self.object.metaconf[a]["t"] == "choice":
                        if isinstance(self.attr(a), str) and self.attr(a).startswith("self."):
                            value = getattr(self.object, self.attr(a).split(".", 1)[1])
                        else:
                            value = self.attr(a)
                        if value == "none" or value == "None":
                            value = None
                        if self.attr_check_choice(self.object.metaconf[a], value):
                            raise error("Value '%s' is not a choice for option '%s' in node '%s'." % (value, a, self.name))
                    else:
                        raise error("Unknown option type '%s' in template, for node '%s'" % (a, self.name))
                else:
                    if self.attr_check_default(self.object.metaconf[a]):
                        value = self.object.metaconf[a]["default"]
                    else:
                        raise error("Option '%s' is mandatory for node '%s'" % (a, self.name))
                # each attr is converted into an object method
                self._name2ref("_"+a, value)
            # cleanup
            self.object.metaconf.clear()
            # TODO remove any use of self.attrs after init, to clear the var here
            #del(self.attrs)
    # add new child
    def child_set(self, node):
        self.children[node.name] = node
    # get child by name
    def child_get(self, name):
        return self.children[name]
    # get first child (deep recursion) which name starts with "name"
    def child_get_first(self, name, root = None):
        if not root: root = self
        if root.name.startswith(name): 
            return root
        for child in root.children.values():
           n = child.child_get_first(name, child)
           if n: return n
        return None
    # move child to another parent
    def child_move(self, name, newparentname, root = None):
        if not root: root = self
        child = root.child_del(name, root)
        if child:
            newparent = root.child_get_first(newparentname)
            if newparent:
                newparent.children[name] = child
                return True
        return False
    # delete child
    def child_del(self, name, root = None):
        if not root: root = self
        parent = root.parent(root, name)
        if parent:
            return parent.children.pop(name)
        return None
    # list shallow children
    def children_list(self, name = None):
        if name:
            cl = list()
            for c in self.children.values():
                if c.name.startswith(name):
                    cl.append(c)
            return cl
        else:
            return self.children.values()
    # list deep children
    def children_deep(self, l = list(), root = None):
        if not root: root = self
        if not l: l.append(root)
        for name, child in root.children.items():
            l.append(child)
            self.children_deep(l, child)
        return l
    # list deep children which name starts with "name"
    def children_deep_byname(self, name, l, root = None):
        if not root: root = self
        if root.name.startswith(name):
            if not l:
                l.append(root)
        for child in root.children.values():
            if child.name.startswith(name):
                l.append(child)
            child.children_deep_byname(name, l, child)
        return l
    # list shallow children names
    def children_names(self, node = None):
        if not node: node = self
        return node.children.keys()
    # list deep children names
    def children_names_deep(self, l = list(), root = None):
        if not root: root = self
        if not l: l.append(root.name)
        for child in root.children.values():
            l.append(child.name)
            self.children_names_deep(l, child)
        return l
    # methods to collect formatted information about the node
    def show_details_printer(self, node = None, indent = 0):
        if node == None: node = self
        txt = "\t"*(indent+1) + "--------------------- (events)\n"
        for e in sorted(node.object.event_handlers):
            methparts = str(node.object.event_handlers[e]).split(".",1)[1].split("instance", 1)[0].split(" ")
            meth = methparts[2] + "." + methparts[0]
            txt = txt + str('\t' * (indent+1) + "- " + str(e).ljust(30, " ") + meth[1:] + "\n")
        return txt
    def show_details_hal(self, node = None, indent = 0):
        if node == None: node = self
        txt = "\t"*(indent+1) + "----------------- (tree nodes)\n"
        node = self.children_deep()
        nodedict = {}
        for n in node:
            nodedict[n.name] = n
        for n in sorted(nodedict):
            txt = txt + '\t' * (indent+1) + "- " + str(n).ljust(20, " ") + " " + str(nodedict[n].object).split(" ")[0][1:] + "\n"
        return txt
    def show_details_reactor(self, node = None, indent = 0):
        if node == None: node = self
        # timers
        txt = "\t"*(indent+1) + "--------------------- (timers)\n"
        for t in sorted(node.object._timers):
            txt = txt + '\t' * (indent+1) + "- " + str(t).ljust(20, " ") + "\n"
        # callbacks
        txt = "\t"*(indent+1) + "------------------ (callbacks)\n"
        for c in sorted(node.object._pipe_fds):
            txt = txt + '\t' * (indent+1) + "- " + str(c).ljust(20, " ") + "\n"
        # file descriptors
        txt = "\t"*(indent+1) + "------------------------ (FDs)\n"
        for n in sorted(node.object._fds):
            txt = txt + '\t' * (indent+1) + "- " + str(n).ljust(5, " ") + ": " + str(node.object._fds[n]).split(" ")[2] + "\n"
        # greenlets
        #txt = "\t"*(indent+1) + "------------------ (greenlets)\n"
        #for g in sorted(node.object._greenlets):
        #    txt = txt + '\t' * (indent+1) + "- " + str(g.run).ljust(20, " ") + "\n"
        return txt
    def show_details_commander(self, node = None, indent = 0):
        if node == None: node = self
        txt = "\t"*(indent+2) + "------------------- (commands)\n"
        for cmd in sorted(node.object.command_handler.keys()):
            txt = txt + str('\t' * (indent+2) + "- " + str(cmd).ljust(20, " ")) 
            if cmd in node.object.ready_only:
                txt = txt + " (ready only)"
            txt = txt + "\n"
        for cmder in node.object.commander:
            txt = txt + str('\t' * (indent+1) + "- " + str(cmder).ljust(20, " ")+"\n")
            txt = txt + "\t"*(indent+2) + "------------------- (commands)\n"
            for cmd in sorted(node.object.commander[cmder].command_handler.keys()):
                txt = txt + str('\t' * (indent+2) + "- " + str(cmd).ljust(20, " ")) 
                if cmd in node.object.commander[cmder].ready_only:
                    txt = txt + " (ready only)"
                txt = txt + "\n"
        return txt
    def show_details_controller(self, node = None, indent = 0):
        if node == None: node = self
        txt = "\t"*(indent+1) + "\t(part)\t\t\t(pin type)\t\t\t(used pin)\n"
        used = []
        for kind in [node.object.virtual, 
                node.object.endstop, 
                node.object.thermometer, 
                node.object.hygrometer, 
                node.object.barometer, 
                node.object.filament, 
                node.object.stepper, 
                node.object.heater,
                node.object.cooler]:
            for part in sorted(kind):
                for pin in sorted(kind[part].pin):
                    used.append((part, pin, kind[part].pin[pin]))
        for part, pin, obj in sorted(used):
            txt = txt + "\t" * (indent+1) + "- " + part.ljust(20, " ") + " " + str(obj).split(" ")[0][1:].ljust(40, " ") + " " + pin + "\n"
        return txt
    def show_details_timing(self, node = None, indent = 0):
        return ""
    def show_details_temperature(self, node = None, indent = 0):
        return ""
    def show_details_mcu(self, node = None, indent = 0):
        if node == None: node = self
        txt = ""
        # registered serial handlers
        if len(node.object.mcu._serial.handlers) > 0:
            txt = txt + "\t"*(indent+1) + "------------ (serial handlers)\n"
            txt = txt + "\t"*indent + "\t(name, oid)\t\t(callback)\n"
            for h in sorted(node.object.mcu._serial.handlers):
                hparts = str(node.object.mcu._serial.handlers[h]).split(" ")
                hname = hparts[2]
                txt = txt + str("\t" * indent + "\t" + str(h).ljust(20, " ") + "\t" + hname + "\n")
        # available pins and their config
        matrix = node.object.pins.get_matrix()
        if len(matrix) > 0:
            txt = txt + "\t"*(indent+1) + "------------------- (all pins)\n"
            txt = txt + "\t"*indent + "\t(pin)\t(alias)\t(pull)\t(invert)\t(used)\n"
            for p in sorted(matrix):
                if not p[2]:
                    p[2] = False
                txt = txt + str("\t" * indent + "\t  " + str(p[0]) + "\t" + str(p[1]) + "\t" + str(p[3]) + "\t" + str(p[4]) + "\t\t" + str(p[2]) + "\n")
        txt = txt + "\t"*(indent+1) + "------------------------------\n"
        return txt
    # return formatted information about node, additional information:
    # [module, object, attrs, {children | deep}, details]
    def show(self, node = None, indent = 0, plus = ""):
        if node == None: node = self
        options = plus.split(",")
        txt = ""
        startline = "\t"*indent
        newline = "\n"
        # add header
        if "details" in options:
            txt = txt + startline + "---" + newline
        # node name, module and object
        txt = txt + startline + "* " + node.name.upper().ljust(30, " ")
        if "module" in options:
            if node.module:
                txt = txt + " | " + str(str(node.module).split(" ")[1] + " (" + str(node.module).split(" ")[3][:-1]).ljust(15, " ") + ")"
            else:
                txt = txt + " | no module".ljust(15, " ")
        if "object" in options:
            if node.object:
                txt = txt + " | " + str(node.object).split(" ")[0][1:].ljust(15, " ")
            else:
                if node.name != "spares":
                    txt = txt + " | no object".ljust(15, " ")
        txt = txt + newline
        # show attrs
        if "attrs" in options:
            if node.attrs:
                maxlen = len(max(node.attrs.keys(), key=len))
                for key, value in node.attrs.items():
                    txt = txt + startline + "  - " + str(key).ljust(maxlen, " ") + ": " + str(value) + newline
        # special nodes, print details: printer events, gcode commands, ...
        if "details" in options:
            if node.name == "printer" and node.object:
                txt = txt + self.show_details_printer(node, indent)
            elif node.name == "hal" and node.object:
                txt = txt + self.show_details_hal(node, indent)
            elif node.name == "reactor" and node.object:
                txt = txt + self.show_details_reactor(node, indent)
            elif node.name == "commander" and node.object:
                txt = txt + self.show_details_commander(node, indent)
            elif node.name == "controller" and node.object:
                txt = txt + self.show_details_controller(node, indent)
            elif node.name == "timing" and node.object:
                txt = txt + self.show_details_timing(node, indent)
            elif node.name == "temperature" and node.object:
                txt = txt + self.show_details_temperature(node, indent)
            elif node.name.startswith("mcu ") and node.object:
                txt = txt + self.show_details_mcu(node, indent)
        # show children
        if "children" in options:
            if len(node.children) < 1: 
                txt = txt + startline + "\t* none" + newline
                return txt
            for k in node.children.keys():
                txt = txt + startline + "\t* "+ k + newline
        elif "deep" in options:
            for key, value in node.children.items():
                txt = txt + self.show(value, indent+1, plus)
        #
        return txt

class PrinterTree:
    def __init__(self): 
        self.printer = PrinterNode("printer")
        self.spare = PrinterNode("spares")
    def show(self, indent = 0):
        return self.printer.show(None, indent, "deep") + "\n" + self.spare.show(None, indent, "deep")

