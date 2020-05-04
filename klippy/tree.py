# - Node base class := {name, children}.
# - Part class(node).
# - Composite part class(part).
# - Root(composite).
# - Builder:    create printer tree
#               assemble hw parts into composite parts,
# 
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, collections, configparser, importlib
from text import msg
from error import KError as error
import util
logger = logging.getLogger(__name__)

class Node:
    def __init__(self, name, children = None):
        self._name = name
        if children:
            self._children = children
        else:
            self._children = collections.OrderedDict()
    def name(self):
        "Return the full name, ie: 'group id'."
        return self._name
    def group(self):
        "Return the group part of name."
        return self.name().split(" ")[0]
    def id(self):
        "Return the id part of name."
        parts = self.name().split(" ")
        if len(parts) > 1:
            return parts[1]
        else:
            logger.warning("'%s' doesn't have a group in name.", self.name())
            return parts[0]
    def parent(self, childname, root):
        "Return node's parent."
        if not root: root = self
        for cn in root._children.keys():
           if cn.startswith(childname): return root
           ccn = root._children[cn].parent(childname, root._children[cn])
           if ccn: return ccn
        return None
    def parent_bygroup(self, group, root):
        "Return the first ancestor having the given group."
        if not root: root = self
        parentnode = self.parent(root,self.name())
        while not parentnode.name().startswith(parentgroup):
            logger.warning("TODO PARENT_BYGROUP: %s", parentnode.name())
            if parentnode.name() == "printer":
                return None
            parentnode = parentnode.parent(root,parentnode.name())
        return parentnode
    def child_add(self, node):
        "Add new child."
        self._children[node.name()] = node
    def child(self, name):
        "Get child by name."
        return self._children[name]
    def child_deep(self, name, root = None):
        "Get first child (deep recursion) which name starts with given name."
        if not root: root = self
        if root.name().startswith(name): 
            return root
        for child in root._children.values():
           n = child.child_deep(name, child)
           if n: return n
        return None
    def child_move(self, name, newparentname, root = None):
        "Move child to another parent."
        if not root: root = self
        child = root.child_del(name, root)
        if child:
            newparent = root.child_get_first(newparentname)
            if newparent:
                newparent.children[name] = child
                return True
        return False
    def child_del(self, name, root = None):
        "Delete child."
        if not root: root = self
        parent = root.parent(root, name)
        if parent:
            return parent.children.pop(name)
        return None
    def children(self, name = None):
        "List shallow children."
        if name:
            cl = list()
            for c in self._children.values():
                if c.name().startswith(name):
                    cl.append(c)
            return cl
        else:
            return self._children.values()
    def children_bygroup(self, group):
        "Return a list of shallow children with given group."
        return self.children(group+" ")
    def children_bytype(self, group, typ):
        "Return a lst of shallow children with given type."
        parts = list()
        for p in self.children_bygroup(group):
            if p._type == typ:
                parts.append(p)
        return parts
    def children_deep(self, l = list(), root = None):
        "Return a list of deep children."
        if not root: root = self
        if not l: l.append(root)
        for child in root.children():
            l.append(child)
            self.children_deep(l, child)
        return l
    def children_deep_byname(self, name, l, root = None):
        "List deep children having the given name."
        if not root: root = self
        if root.name().startswith(name):
            if not l:
                l.append(root)
        for child in root.children():
            if child.name().startswith(name):
                l.append(child)
            child.children_deep_byname(name, l, child)
        return l
    def children_deep_bygroup(self, group):
        return self.children_deep_byname(group+" ", list(), self)
    def children_deep_bytype(self, group, typ):
        parts = list()
        for p in self.children_deep_bygroup(group):
            if p._type == typ:
                parts.append(p)
        return parts
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
    #
    # plus := [module,, attrs, {children | deep}, details]
    def show(self, indent = 0, plus = ""):
        "Return formatted information about this node."
        options = plus.split(",")
        txt = ""
        startline = "\t"*indent
        newline = "\n"
        # add header
        if "details" in options:
            txt = txt + startline + "---" + newline
        # node name, module and
        txt = txt + startline + "* " + self.name().upper().ljust(30, " ")
        if "module" in options:
            # TODO
            if self.module:
                txt = txt + " | " + str(str(self.module).split(" ")[1] + " (" + str(self.module).split(" ")[3][:-1]).ljust(15, " ") + ")"
            else:
                txt = txt + " | no module".ljust(15, " ")
        if "object" in options:
            # TODO
            txt = txt + " | " + str(self).split(" ")[0][1:].ljust(15, " ")
        txt = txt + newline
        if "attrs" in options and hasattr(self, "_show_attrs"):
            # TODO
            txt = txt + self._show_attrs(indent)
        # special nodes, print details: printer events, gcode commands, ...
        if "details" in options and hasattr(self, "_show_details"):
            txt = txt + self._show_details(indent)
        # show children
        if "children" in options:
            if len(self._children) < 1: 
                txt = txt + startline + "\t* none" + newline
                return txt
            for k in self._children.keys():
                txt = txt + startline + "\t* "+ k + newline
        elif "deep" in options:
            for node in self._children.values():
                txt = txt + node.show(indent+1, plus)
        #
        return txt

class Part(Node):
    # holds node attrs, later converted into vars
    metaconf = collections.OrderedDict()
    def __init__(self, name, children = None, hal = None):
        super().__init__(name, children)
        self.hal = hal
        self.pin = {}
        self.real = True
        self.ready = False
    def _meta_add(self, name, value):
        "Add named value as's var."
        if hasattr(self, name):
            raise error("Attr exists. Please check option name '%s' for '%s'", name, self.name())
        else:
            setattr(self, name, value)
    # validate and create attrs
    def _meta_check_default(self, template):
        if "default" in template:
            return True
        return False
    def _meta_check_minmax(self, template, value):
        if "minval" in template:
            if value < template["minval"]:
                return True
        if "maxval" in template:
            if value > template["maxval"]:
                return True
        return False
    def _meta_check_abovebelow(self, template, value):
        if "above" in template:
            if value <= template["above"]:
                return True
        if "below" in template:
            if value >= template["below"]:
                return True
        return False
    def _meta_check_choice(self, template, value):
        if value in template["choices"]:
            return False
        return True
    def meta_conf(self, cparser):
        "Convert all node attrs to vars."
        for a in self.metaconf:
            # convert var references in values, if a var reference is given as value for another var
            for m in self.metaconf[a].items():
                if isinstance(m[1], str) and m[1].startswith("self."):
                    self.metaconf[a][m[0]] = getattr(self, m[1].split(".", 1)[1])
            #
            if a in cparser.options(self.name()):
                if self.metaconf[a]["t"] == "bool":
                    if isinstance(cparser.get(self.name(), a), str) and cparser.get(self.name(), a).startswith("self."):
                        value = bool(getattr(self, cparser.get(self.name(), a).split(".", 1)[1]))
                    else:
                        value = bool(cparser.get(self.name(), a))
                elif self.metaconf[a]["t"] == "int":
                    if isinstance(cparser.get(self.name(), a), str) and cparser.get(self.name(), a).startswith("self."):
                        value = int(getattr(self, cparser.get(self.name(), a).split(".", 1)[1]))
                    else:
                        value = int(cparser.get(self.name(), a))
                    if self._meta_check_minmax(self.metaconf[a], value):
                        raise error("Value '%s' exceed min/max for option '%s' in node '%s'." % (value, a, self.name))
                elif self.metaconf[a]["t"] == "float":
                    if isinstance(cparser.get(self.name(), a), str) and cparser.get(self.name(), a).startswith("self."):
                        value = float(getattr(self, cparser.get(self.name(), a).split(".", 1)[1]))
                    else:
                        value = float(cparser.get(self.name(), a))
                    if self._meta_check_minmax(self.metaconf[a], value):
                        raise error("Value '%s' exceed min/max for option '%s' in node '%s'." % (value, a, self.name))
                    if self._meta_check_abovebelow(self.metaconf[a], value):
                        raise error("Value '%s' above/below maximum/minimum for option '%s' in node '%s'." % (value, a, self.name))
                elif self.metaconf[a]["t"] == "str":
                    if isinstance(cparser.get(self.name(), a), str) and cparser.get(self.name(), a).startswith("self."):
                        value = str(getattr(self, cparser.get(self.name(), a).split(".", 1)[1]))
                    else:
                        value = str(cparser.get(self.name(), a))
                elif self.metaconf[a]["t"] == "choice":
                    if isinstance(cparser.get(self.name(), a), str) and cparser.get(self.name(), a).startswith("self."):
                        value = getattr(self, cparser.get(self.name(), a).split(".", 1)[1])
                    else:
                        value = cparser.get(self.name(), a)
                    if value == "none" or value == "None":
                        value = None
                    if self._meta_check_choice(self.metaconf[a], value):
                        raise error("Value '%s' is not a choice for option '%s' in node '%s'." % (value, a, self.name()))
                else:
                    raise error("Unknown option type '%s' in template, for node '%s'" % (a, self.name()))
            else:
                if self._meta_check_default(self.metaconf[a]):
                    value = self.metaconf[a]["default"]
                else:
                    logger.warning("Option '%s' is mandatory for node '%s'" % (a, self.name()))
                    self.real = False
            # each attr is converted into an method
            self._meta_add("_"+a, value)
        # cleanup
        self.metaconf.clear()
        # TODO remove any use of self.attrs after init, to clear the var here
        #del(self.attrs)

class Composite(Part):
    def __init__(self, name, children = None, hal = None):
        super().__init__(name, children, hal)
    def _build(self, indent = 1):
        "Build the composite."
        # for each child
        for c in self.children():
            # build its children
            if hasattr(c, "_build") and callable(c._build):
                c._build(indent+1)
            # configure its leaves
            if hasattr(c, "_configure") and callable(c._configure):
                c._configure()
        # init self
        if hasattr(self, "_init") and callable(self._init):
            self._init()

class Root(Composite):
    "Tree topology."
    def __init__(self, name, hal): 
        super().__init__(name, hal = hal)
        self.spare = Node("spare")
    def node(self, name):
        "Return the named node."
        return self.child_deep(name)
    def node_add(self, parentname, child):
        "Add child to parentname node."
        self.child_deep(parentname).children[child.name()] = child
    def node_del(self, name):
        "Delete the named node."
        return self.parent(None, name).children.pop(name)
    def node_move(self, name, newparentname):
        "Move the named node to newparentname node."
        self.node_add(newparentname, self.node_del(name))
    def node_spare(self, name):
        "Move the named node to spares for later use."
        self.spare.children[name] = self.node_del(name)
    def node_show(self, name, indent = 0, plus = ""):
        "Return a string describing the named node."
        return self.node(name).show(indent, plus)
    def show_tree(self, indent = 0):
        "Return a string containing the tree topology (with spares)."
        return self.show(indent, "deep") + "\n" + self.spare.show(indent, "deep")

class Config:
    "Config file parser and manager."
    def __init__(self, hal):
        logger.debug("- Reading config file.")
        self.hal = hal
        self._parser = configparser.SafeConfigParser()
    def read(self):
        self._parser.read(self.hal.get_printer().get_args().config_file)
    def sections(self, startswith = None, exclude = None):
        if startswith:
            return [s for s in self._parser.sections() if s.startswith(startswith)]
        elif exclude:
            l = self._parser.sections()
            for e in exclude:
                l = [s for s in l if not s.startswith(e)]
            return l
        else:
            return self._parser.sections()
    def group(self, section):
        return section.split(" ")[0]
    def id(self, section):
        parts = section.split(" ")
        if len(parts) == 2:
            return parts[1]
        else:
            return parts[0]
    def get(self, section, option):
        return self._parser.get(section, option)
    def options(self, section):
        return self._parser.options(section)
    def items(self, section):
        return self._parser.items(section)
    def show_section(self, section):
        logger.info('Section:%s', section)
        logger.info('\tOptions:%s', self.options(section))
        for name, value in self.items(section):
            logger.info('\t%s = %s' % (name, value))
        logger.info('')
    def show(self):
        for section in self.sections():
            self.show_section(section)
    def write(self):
        pass

class Builder:
    "Tree and parts builder."
    def __init__(self, hal, cparser):
        self.hal = hal
        parts = collections.OrderedDict()
        partnames_to_remove = set()
        # collect parts
        logger.debug("- Building printer tree.")
        for p in self.hal.pgroups:
            for s in cparser.sections(p+" "):
                parts[s] = self.hal.obj_load(cparser, s)
        # collect plugins as parts
        for m in cparser.sections(exclude=["printer"]+self.hal.pgroups+self.hal.cgroups):
            #parts[m] = self._try_load_module(cparser, m)
            pass
        # collect composites
        composites = collections.OrderedDict()
        for p in self.hal.cgroups:
            for s in cparser.sections(p+" "):
                composites[s] = self.hal.obj_load(cparser, s, parts, composites)
        # dump spare composites in parts
        for c in composites:
            parts[c] = composites[c]
        del(composites)
        # adding parts and composites nodes to printer root.
        for a in cparser.options("printer"):
            if a in self.hal.pgroups or a in self.hal.cgroups:
                if a == "mcu":
                    for n in cparser.get("printer", a).split(","):
                        self.hal.get_controller().register_part(parts[a+" "+n])
                        self.hal.get_controller().child_add(parts.pop(a+" "+n))
                else:
                    for n in cparser.get("printer", a).split(","):
                        self.hal.get_printer().child_add(parts.pop(a+" "+n))
            elif a == "toolhead":
                for n in cparser.get("printer", a).split(","):
                    partnames_to_remove = partnames_to_remove.union(self.hal._compose_toolhead(a+" "+n, cparser, parts))
        # adding virtual pins
        for p in parts:
            if p.startswith("virtual "):
                self.hal.get_controller().register_part(parts[p])
                self.hal.get_controller().child_add(parts[p])
                partnames_to_remove.add(p)
        # adding plugins nodes
        for m in cparser.sections(exclude=["printer"]+self.hal.pgroups+self.hal.cgroups):
            if m in parts:
                partnames_to_remove = partnames_to_remove.union(parts[m].load_tree_node(self.hal, parts[m], parts))
        # cleanup
        for i in partnames_to_remove:
            if i in parts:
                parts.pop(i)
        # save leftover parts to spares
        for i in parts:
            self.hal.get_printer().spare.child_add(parts[i])
        del(parts)
        logger.debug(self.hal.get_printer().show_tree())
        #
        logger.debug("- Configuring parts.")
        # build/configure (if needed) each printer shallow children
        for node in self.hal.get_printer().children():
            if node.name() != "hal" and node.name() != "reactor" and not node.name().startswith("kinematic "):
                # build printer's children
                if hasattr(node, "_build") and callable(node._build):
                    node._build()
                # configure printer's leaves
                if hasattr(node, "_configure") and callable(node._configure):
                    node._configure()
        # configure toolhead(s)
        for t in self.hal.get_printer().children_deep_byname("toolhead ", list()): 
            t._build()
        # init kinematics
        for k in self.hal.get_printer().children_deep_byname("kinematic ", list()):
            k._init()
        # last check before linkings with "register()"
        for node in self.hal.get_printer().children_deep(list(), self.hal.get_printer()):
            if node.name() != 'printer' and hasattr(node, "ready"):
                if not node.ready:
                    logger.debug("\t %s NOT READY. Moving to spares.", node.name())
                    # TODO fix line, move from root to spare
                    self.hal.get_printer().spare.child_add(node.parent(node.name(), self.hal.get_printer()).children.pop(node.name()))
            else:
                if node.name() != "printer":
                    logger.debug("\t %s NOT READY. Moving to spares.", node.name())
                    # TODO fix line, move from root to spare
                    self.hal.get_printer().spare.child_add(node.parent(node.name(), self.hal.get_printer()).children.pop(node.name()))
        # for each node, run.register() (if any)
        logger.debug("- Registering events and commands.")
        for node in self.hal.get_printer().children_deep(list(), self.hal.get_printer()):
            if hasattr(node, "_register") and callable(node._register):
                node._register()
        # load printer's sniplets, development code to be tested
        logger.debug("- Autoloading extra printlets.")
        #self.hal._try_autoload_printlets()
        #logger.debug(self.show("printer", plus="attrs,details,deep"))

