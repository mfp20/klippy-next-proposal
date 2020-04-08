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
    def get_group(self):
        return self.name.split(" ")[0]
    def get_id(self):
        return self.name.split(" ")[1]
    # set attr
    def attr_set(self, key, value):
        self.attrs[key] = value
    # get attr, with default fallback, return a boolean if requested
    # TODO test the boolean part
    def attr_get(self, attr, boolean = False, default = None):
        if attr in self.attrs:
            if boolean:
                return bool(self.attrs[attr])
            else:
                return self.attrs[attr]
        else:
            if default != None:
                return default
            else:
                return str("")
    # get attr, with default fallback, limited amount of choices
    def attr_get_choice(self, attr, choices, default = None):
        if None in choices:
            choices["None"] = "None"
            choices["none"] = "none"
        if default:
            c = self.attr_get(attr, False, default)
        else:
            c = self.attr_get(attr)
        if c in choices:
            return choices[c]
        else:
            raise error("Choice '%s' for option '%s' in node '%s' is not a valid choice" % (c, attr, self.name))
    # get attr, int, with default fallback, with conditions
    def attr_get_int(self, attr, minval = None, maxval = None, default = None):
        if attr in self.attrs:
            v = int(self.attrs[attr])
            if minval:
                if v < minval:
                    raise error("Option '%s' in node '%s' must have minimum of %s" % (attr, self.name, minval))
            if maxval:
                if v > maxval:
                    raise error("Option '%s' in node '%s' must have maximum of %s" % (attr, self.name, maxval))
            return v
        else:
            if default != None:
                return int(default)
            else:
                raise error("Unable to parse option '%s' in node '%s'" % (attr, self.name))
    # get attr, float, with default fallback, with conditions
    def attr_get_float(self, attr, minval = None, maxval = None, above = None, below = None, default = None):
        if attr in self.attrs:
            v = float(self.attrs[attr])
            if minval:
                if v < minval:
                    raise error("Option '%s' in node '%s' must have minimum of %s" % (attr, self.name, minval))
            if maxval:
                if v > maxval:
                    raise error("Option '%s' in node '%s' must have maximum of %s" % (attr, self.name, maxval))
            if above:
                if v <= above:
                    raise error("Option '%s' in node '%s' must be above %s" % (attr, self.name, above))
            if below:
                if v >= below:
                    raise error("Option '%s' in node '%s' must be below %s" % (attr, self.name, below))
            return v
        else:
            if default != None:
                return float(default)
            else:
                raise error("Unable to parse option '%s' in node '%s'" % (attr, self.name))
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
                            logging.warning("No option '%s' for node %s", a, self.name)
                        return False
            else:
                if self.name:
                    logging.warning("No attrs for node '%s'", self.name)
                return False
        else:
            if self.name:
                logging.warning("No module for node '%s'", self.name)
            return False
        return True
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
        child = root.del_node(name)
        if child:
            newparent = root.child_get_first(newparentname)
            if newparent:
                newparent.children[name] = child
                return True
        return False
    # delete child
    def child_del(self, name, root = None):
        if not root: root = self
        parent = root.parent_get(name)
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
    # get parent
    def node_get_parent(self, root, childname):
        if not root: root = self
        for cn in root.children.keys():
           if cn.startswith(childname): return root
           ccn = root.children[cn].node_get_parent(root.children[cn], childname)
           if ccn: return ccn
        return None
    def node_show(self, node = None, indent=0):
        if node == None: node = self
        txt = "\t" * indent + "---\n"
        txt = txt + "\t" * indent + "* " + node.name.upper() + "\n"
        for key, value in node.attrs.items():
            txt = txt + "\t" * (indent+1) + "- " + str(key) + ": " + str(value) + "\n"
        if len(node.children) < 1: 
            txt = txt + "\t" * (indent+2) + "* none\n"
            return txt
        for k in node.children.keys():
            txt = txt + "\t" * (indent+2) + "* "+k + "\n"
        return txt
    def node_show_printer(self, node = None, indent = 0):
        if node == None: node = self
        txt = ""
        for e,c in sorted(node.events.items()):
            txt = txt + str('\t' * (indent+1) + "(event) " + str(e).ljust(30, " ") + str(c) + "\n")
        return txt
    def node_show_commander(self, node = None, indent = 0):
        if node == None: node = self
        txt = ""
        for cmd in sorted(node.object.command_handler.keys()):
            txt = txt + str('\t' * (indent+2) + "(command) " + str(cmd).ljust(20, " ")) 
            if cmd in node.object.ready_only:
                txt = txt + " (ready only)"
            txt = txt + "\n"
        for cmder in node.object.commander:
            txt = txt + str('\t' * (indent+1) + "- " + str(cmder).ljust(20, " ")+"\n")
            for cmd in sorted(node.object.commander[cmder].command_handler.keys()):
                txt = txt + str('\t' * (indent+2) + "(command) " + str(cmd).ljust(20, " ")) 
                if cmd in node.object.commander[cmder].ready_only:
                    txt = txt + " (ready only)"
                txt = txt + "\n"
        return txt
    def node_show_hal(self, node = None, indent = 0):
        if node == None: node = self
        txt = ""
        partlist = self.children_names_deep()
        partlist = list(dict.fromkeys(partlist))
        partlist.sort()
        for partname in sorted(partlist):
            txt = txt + str('\t' * (indent+1) + "(node) " + str(partname) + "\n")
        return txt
    def node_show_controller(self, node = None, indent = 0):
        if node == None: node = self
        txt = "\t"*(indent+1) + "---------------- (active pins)\n"
        matrix = node.object.pin_matrix_active()
        for b in sorted(matrix):
            txt = txt + str('\t' * (indent+1) + "- board " + b + ":"+ "\t(pin)" + "(pull)" + "(invert)" + "\n")
            if len(matrix[b]) == 0:
                txt = txt + str('\t' * (indent+3) + "\tnone\n")
            else:
                for p in sorted(matrix[b]): 
                    txt = txt + str('\t' * (indent+2) + "\t  " + str(matrix[b][p]["pin"]) + "\t" + str(matrix[b][p]["pullup"]) + "\t" + str(matrix[b][p]["invert"]) + "\n")
        return txt
    def node_show_mcu(self, node = None, indent = 0):
        if node == None: node = self
        txt = ""
        matrix = node.object.pin.matrix()
        # registered serial handlers
        if len(node.object.mcu._serial.handlers) > 0:
            txt = txt + "\t"*(indent+1) + "------------ (serial handlers)\n"
            txt = txt + "\t"*indent + "\t(name, oid)\t\t(callback)\n"
            for h in sorted(node.object.mcu._serial.handlers):
                txt = txt + str("\t" * indent + "\t" + str(h).ljust(20, " ") + "\t" + str(node.object.mcu._serial.handlers[h]) + "\n")
        # available pins and their config
        if len(matrix) > 0:
            txt = txt + "\t"*(indent+1) + "------------------- (all pins)\n"
            txt = txt + "\t"*indent + "\t(pin)\t(alias)\t(task)\t(pull)\t(invert)\n"
            for p in sorted(matrix):
                txt = txt + str("\t" * indent + "\t  " + str(p[0]) + "\t" + str(p[1]) + "\t" + str(p[2]) + "\t" + str(p[3]) + "\t" + str(p[4]) + "\n")
            txt = txt + "\t"*(indent+1) + "------------------------------\n"
        return txt
    def node_show_deep(self, node = None, indent = 0, plus = ""):
        if node == None: node = self
        # add header
        txt = str("\t" * indent + "---\n")
        # node name, if requested collect module and object
        plustxt = ""
        for p in plus.split(","):
            if p == "module":
                if node.module:
                    plustxt = plustxt+" | "+str(node.module)
                else:
                    plustxt = plustxt+" | no module"
            elif p == "object":
                if node.object:
                    plustxt = plustxt+" | "+str(node.object)
                elif node.name:
                    if node.name != "spares":
                        plustxt = plustxt+" | no object"
            elif p == "attrs":
                if node.attrs:
                    plustxt = plustxt+" | "+str(node.attrs)
                else:
                    plustxt = plustxt+" | no attrs"
            elif p == "children":
                if node.children:
                    plustxt = plustxt+" | "+str(node.children)
                else:
                    plustxt = plustxt+" | no children"
        txt = txt + str('\t' * indent + "|  * " + node.name.upper().ljust(15, " ") + " " + plustxt + "\n")
        # show attrs
        if node.attrs:
            maxlen = len(max(node.attrs.keys(), key=len))
            for key, value in node.attrs.items():
                txt = txt + str('\t' * (indent+1) + "" + str(key).ljust(maxlen, " ") + ": " + str(value) + "\n")
        # special nodes, print misc info: printer events, gcode commands, ...
        if node.name == "printer" and node.object:
            txt = txt + self.node_show_printer(node, indent)
        elif node.name == "commander" and node.object:
            txt = txt + self.node_show_commander(node, indent)
        elif node.name == "hal" and node.object:
            txt = txt + self.node_show_hal(node, indent)
        elif node.name == "controller" and node.object:
            txt = txt + self.node_show_controller(node, indent)
        elif node.name.startswith("mcu ") and node.object:
            txt = txt + self.node_show_mcu(node, indent)
        # show children
        for key, value in node.children.items():
            txt = txt + self.node_show_deep(value, indent+1, plus)
        return txt

class PrinterTree:
    def __init__(self):
        self.printer = PrinterNode("printer")
        self.printer.events = collections.OrderedDict()
        self.spare = PrinterNode("spares")
    def show(self, indent = 0, plus = ""):
        return self.printer.node_show_deep(self.printer, indent, plus) + "\n" + self.printer.node_show(self.spare, indent)
    cmd_SHOW_PRINTER_help = "Shows the printer tree and some additional info in console."
    def cmd_SHOW_PRINTER(self):
        self.respond_info("\n".join(self.show(2, plus = "object")), log=False)

