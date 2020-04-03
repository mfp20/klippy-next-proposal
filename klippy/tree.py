# Define a printer node := {name, attrs, children, module, object} and a printer tree := {printer, spare}
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import collections, logging

class sentinel:
    pass

class PrinterNode:
    def __init__(self, name, attrs = None, children = None):
        self.name = name
        self.attrs = collections.OrderedDict()
        self.children = collections.OrderedDict()
        self.module = None
        self.object = None
    def set_attr(self, key, value):
        self.attrs[key] = value
    def get(self, attr, default = sentinel):
        if attr in self.attrs:
            return self.attrs[attr]
        else:
            return default
    def get_int(self, attr, default = sentinel, minval=None, maxval=None):
        # TODO: enforce minval and maxval
        if attr in self.attrs:
            return int(self.attrs[attr])
        else:
            return default
    def get_float(self, attr, default=sentinel, minval=None, maxval=None, above=None, below=None):
        # TODO: enforce minval, maxval, above, below
        if attr in self.attrs:
            return float(self.attrs[attr])
        else:
            return default
    def get_boolean(self, attr, default=sentinel):
        if attr in self.attrs:
            return bool(self.attrs[attr])
        else:
            return default
    def get_choice(self, attr, choices, default=sentinel):
        c = self.get(attr, default)
        if c in choices:
            return choices[c]
        # TODO: enforce choices
        #else:
            #return default
    def set_child(self, node):
        self.children[node.name] = node
    def get_child(self, name):
        return self.children[name]
    def get_first_deep(self, name, root = None):
        if not root: root = self
        if root.name.startswith(name): return root
        for child in root.children.values():
           n = child.get_first_deep(name, child)
           if n: return n
        return None
    def get_many_deep(self, name, l, root = None):
        if not root: root = self
        if root.name.startswith(name):
            if not l:
                l.append(root)
        for child in root.children.values():
            if child.name.startswith(name):
                l.append(child)
            child.get_many_deep(name, l, child)
        return l
    def get_parent(self, childname, root = None):
        if not root: root = self
        for cn in root.children.keys():
           if cn.startswith(childname): return root
           ccn = root.children[cn].get_parent(childname)
           if ccn: return ccn
        return None
    def del_node(self, name, root = None):
        if not root: root = self
        parent = root.get_parent(name)
        if parent:
            return parent.children.pop(name)
        return None
    def move_node(self, name, newparentname, root = None):
        if not root: root = self
        child = root.del_node(name)
        if child:
            newparent = root.get_first_deep(newparentname)
            if newparent:
                newparent.children[name] = child
                return True
        return False
    def list_children(self, node = None):
        if not node: node = self
        return node.children.values()
    def list_children_names(self, node = None):
        if not node: node = self
        return node.children.keys()
    def list_children_deep(self, l = list(), root = None):
        if not root: root = self
        if not l: l.append(root)
        for name, child in root.children.items():
            l.append(child)
            self.list_children_deep(l, child)
        return l
    def list_children_names_deep(self, l = list(), root = None):
        if not root: root = self
        if not l: l.append(root.name)
        for child in root.children.values():
            l.append(child.name)
            self.list_children_names_deep(l, child)
        return l
    def show(self, node = None, indent=0):
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
    def show_printer_events(self, node = None, indent = 0):
        if node == None: node = self
        txt = ""
        for e,c in sorted(node.events.items()):
            txt = txt + str('\t' * (indent+1) + "(event) " + str(e).ljust(30, " ") + str(c) + "\n")
        return txt
    def show_commander(self, node = None, indent = 0):
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
    def show_hal_parts(self, node = None, indent = 0):
        if node == None: node = self
        txt = ""
        partlist = self.list_children_names_deep()
        partlist = list(dict.fromkeys(partlist))
        partlist.sort()
        for partname in sorted(partlist):
            txt = txt + str('\t' * (indent+1) + "(node) " + str(partname) + "\n")
        return txt
    def show_pins_active(self, node = None, indent = 0):
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
    def show_pins_all(self, node = None, indent = 0):
        if node == None: node = self
        txt = ""
        matrix = node.object.pin.matrix()
        if len(matrix) > 0:
            txt = txt + "\t"*(indent+1) + "------------------- (all pins)\n"
            txt = txt + "\t"*indent + "\t(pin)\t(alias)\t(task)\t(pull)\t(invert)\n"
            for p in sorted(matrix):
                txt = txt + str("\t" * indent + "\t  " + str(p[0]) + "\t" + str(p[1]) + "\t" + str(p[2]) + "\t" + str(p[3]) + "\t" + str(p[4]) + "\n")
            txt = txt + "\t"*(indent+1) + "------------------------------\n"
        return txt
    def show_deep(self, node = None, indent = 0, plus = ""):
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
        # add attrs
        if node.attrs:
            maxlen = len(max(node.attrs.keys(), key=len))
            for key, value in node.attrs.items():
                txt = txt + str('\t' * (indent+1) + "" + str(key).ljust(maxlen, " ") + ": " + str(value) + "\n")
        # special nodes, print misc info: printer events, gcode commands, ...
        if node.name == "printer" and node.object:
            txt = txt + self.show_printer_events(node, indent)
        elif node.name == "commander" and node.object:
            txt = txt + self.show_commander(node, indent)
        elif node.name == "hal" and node.object:
            txt = txt + self.show_hal_parts(node, indent)
        elif node.name == "controller" and node.object:
            txt = txt + self.show_pins_active(node, indent)
        elif node.name.startswith("mcu ") and node.object:
            txt = txt + self.show_pins_all(node, indent)
        # add children
        for key, value in node.children.items():
            txt = txt + self.show_deep(value, indent+1, plus)
        return txt

class PrinterTree:
    def __init__(self):
        self.printer = PrinterNode("printer")
        self.printer.events = collections.OrderedDict()
        self.spare = PrinterNode("spares")
    def show(self, indent = 0, plus = ""):
        return self.printer.show_deep(self.printer, indent, plus) + "\n" + self.printer.show_deep(self.spare, indent, plus)
    cmd_SHOW_PRINTER_help = "Shows the printer tree and some additional info in console."
    def cmd_SHOW_PRINTER(self):
        self.respond_info("\n".join(self.show(2, plus = "object")), log=False)

