# - Printer Main:   tree nodes helpers,
#                   run,
#                   manage events,
#                   manage loop exit/restart/reconf.
# - Printer Composer:   create printer tree
#                       assemble hw parts into composite parts,
#                       adds module references to nodes,
#                       manages tree.
# 
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import sys, os, time, logging, collections, importlib
from messaging import msg
from messaging import Kerr as error
import configfile, tree, hw, reactor, homing, msgproto

# printer.Main := {tree, hardware abstraction layer, reactor}
class Main:
    def __init__(self, input_fd, bglogger, start_args, exit_codes):
        self.input_fd = input_fd
        self.bglogger = bglogger
        self.args = start_args
        self.ecodes = exit_codes
        self.tree = None
        self.hal = None
        # attrs
        self.status_message = msg("startup")
        self.is_shutdown = False
        self.run_result = None
        self.event_handlers = {}
    #
    # nodes
    def node(self, name):
        return self.tree.printer.child_get_first(name)
    def node_add(self, parentname, childname):
        self.node(parentname).child_set(tree.PrinterNode(childname))
    def node_del(self, name):
        self.n.child_del(name)
    def node_move(self, name, newparentname):
        self.n.child_move(name, newparentname)
    #
    # attrs
    def attr(self, nodename, attrname):
        return self.node(nodename).attrs[attrname]
    def attr_add(self, nodename, attrname, value):
        self.node(nodename).attr_set(attrname, value)
    #
    # node/tree show
    def show(self, nodename, indent=0, plus = "attrs,children"):
        return self.node(nodename).show(None, indent, plus)
    def show_tree(self, indent=0):
        return self.tree.show(indent)
    #
    # set printer status
    def _set_status(self, message):
        logging.info("SET_STATUS: %s", message)
        if self.status_message in (msg("ready"), msg("startup")):
            self.status_message = message
        if (message != msg("ready") and self.args.get('input_debug') is not None):
            self.shutdown('error')
    #
    # reactor task
    def _connect(self, eventtime):
        # identify mcu and complete controller init
        try:
            self.event_send("klippy:mcu_identify")
            logging.debug(self.hal.tree.printer.show(plus="attrs,details,deep")+self.hal.tree.spare.show(plus="deep"))
            # if command line options requested the printer console,
            # a lock is placed in order to give the console
            # a chance to investigate the mcu before the printer connects.
            # Console user must issue the "continue" command to resume
            # normal operations.
            start_args = self.get_args()
            if 'console' in start_args:
                start_args['console'].acquire()
            # exec connect handlers
            for cb in self.event_handlers.get("klippy:connect", []):
                if self.status_message is not msg("startup"):
                    return
                cb()
        except (configfile.error, error) as e:
            logging.exception("Config error")
            self._set_status("%s%s" % (str(e), msg("restart")))
            return
        except msgproto.error as e:
            logging.exception("Protocol error")
            self._set_status("%s%s" % (str(e), msg("errorproto")))
            return
        except error as e:
            logging.exception("MCU error during connect")
            self._set_status("%s%s" % (str(e), msg("errormcuconnect")))
            return
        except Exception as e:
            logging.exception("Unhandled exception during connect")
            self._set_status("Internal error during connect: %s\n%s" % (str(e), msg("restart"),))
            return
        # exec ready handlers
        try:
            self._set_status(msg("ready"))
            for cb in self.event_handlers.get("klippy:ready", []):
                if self.status_message is not msg("ready"):
                    return
                cb()
        except Exception as e:
            logging.exception("Unhandled exception during ready callback")
            self.call_shutdown("Internal error during ready callback: %s" % (str(e),))
        systime = time.time()
        logging.info("* Init complete at %s (%.1f %.1f)", time.asctime(time.localtime(systime)), time.time(), self.hal.get_reactor().monotonic())
    #
    # process cfg file, build printer tree, enqueue _connect()
    def setup(self):
        # setup printer tree
        self.tree = tree.PrinterTree()
        self.n = self.tree.printer
        self.n.module = sys.modules[__name__]
        self.n.object = self
        # init hal
        self.hal = hw.Manager(self.tree)
        self.n.child_set(tree.PrinterNode("hal"))
        self.n.children["hal"].module = sys.modules[__name__]
        self.n.children["hal"].object = self.hal
        # setup basic nodes
        self.node_add("printer", "reactor")
        self.node_add("printer", "commander")
        self.node_add("printer", "controller")
        self.node_add("controller", "timing")
        self.node_add("controller", "temperature")
        # add basic modules
        for n in ["reactor", "commander", "controller", "timing", "temperature"]:
            self.hal.node(n).module = importlib.import_module(n)
        # init reactor
        self.n.children["reactor"].object = reactor.Reactor(self.hal, self.hal.node("reactor"))
        #
        # open and read config
        pconfig = configfile.PrinterConfig(self.hal)
        # parse config
        config = pconfig.read_main_config()
        if self.bglogger is not None:
            pconfig.log_config(config)
        # validate that there are no undefined parameters in the config file
        #pconfig.check_unused_options(config, self.hal)
        # turn config into a printer tree
        Composer(config, self.hal)
        # enqueue self._connect in reactor's task queue
        self.hal.get_reactor().register_callback(self._connect)
        # load printer objects
        self.hal.load_tree_objects()
        return False
    # register local commands
    def register(self):
        self.hal.get_commander().register_commands(self)
    # called from __main__ loop
    def run(self):
        systime = time.time()
        monotime = self.hal.get_reactor().monotonic()
        logging.info("* Init printer at %s (%.1f %.1f)", time.asctime(time.localtime(systime)), systime, monotime)
        # main reactor loop
        try:
            # enters reactor's loop ( note: first command is printer's _connect() )
            self.hal.get_reactor().run()
        except:
            logging.exception("Unhandled exception during run")
            return "error"
        # restart flags
        try:
            self.event_send("klippy:disconnect")
        except:
            logging.exception("Unhandled exception during post run")
            return "error"
        return self.run_result
    #
    # events management
    def event_register_handler(self, event, callback):
        self.event_handlers.setdefault(event, []).append(callback)
    def event_send(self, event, *params):
        return [cb(*params) for cb in self.event_handlers.get(event, [])]
    # any part can call this method to shut down the printer
    # when the method is called, printer.Main spread the shutdown message
    # to other parts with registered event handler
    def call_shutdown(self, message):
        # single shutdown guard
        if self.is_shutdown:
            return
        self.is_shutdown = True
        #
        self._set_status("%s %s" % (message, msg("shutdown")))
        for cb in self.event_handlers.get("klippy:shutdown", []):
            try:
                cb()
            except:
                logging.exception("Exception during shutdown handler")
    # same of call_shutdown(), but called from another thread
    def call_shutdown_async(self, message):
        self.hal.get_reactor().register_async_callback((lambda e: self.call_shutdown(message)))
    #
    # misc helpers
    def get_args(self):
        return self.args
    #
    def get_status(self):
        return self.status_message
    #
    def set_rollover_info(self, name, info, log=True):
        if log:
            logging.info(info)
        if self.bglogger is not None:
            self.bglogger.set_rollover_info(name, info)
    # close the running printer
    def shutdown(self, reason):
        logging.info("SHUTDOWN (%s)", reason)
        if reason == 'exit':
            pass
        elif reason == 'error':
            pass
        elif reason == 'restart':
            pass
        elif reason == 'restart_mcu':
            pass
        elif reason == 'reconf':
            pass
        else:
            raise error("Unknown shutdown reason (%s)." % reason)
        if self.run_result is None:
            self.run_result = reason
        # terminate reactor loop
        self.hal.get_reactor().end()
    # called from __main__ loop
    def cleanup(self, reason):
        logging.info("CLEANUP (%s)", reason)
        if reason == 'exit':
            pass
        elif reason == 'error':
            pass
        elif reason == 'restart':
            # TODO: in order to avoid reconfiguring, reactor must be revisited
            #       to allow for resetting it without the need to re-register everything.
            #self.n.children["reactor"].object = reactor.Reactor(self.hal, self.hal.node("reactor")) 
            pass
        elif reason == 'reconf':
            self.tree = None
            self.hal.get_reactor().cleanup()
            self.hal.cleanup()
            self.hal = None
            self.status_message = msg("startup")
            self.is_shutdown = False
            self.run_result = None
            self.event_handlers = {}
        else:
            raise error("Unknown exit reason (%s).", reason)
        return reason
    #
    # commands
    def _cmd__SHOW_PRINTER(self, params):
        "Shows the printer's tree. Full details."
        self.hal.get_commander().respond_info(self.tree.printer.show(plus="attrs,details,deep")+self.tree.spare.show(plus="deep"), log=False)
    def _cmd__SHOW_PRINTER_TREE(self, params):
        "Shows the printer's topology."
        self.hal.get_commander().respond_info(self.tree.show(), log=False)
    def _cmd__SHOW_PRINTER_STATUS(self, params):
        "Shows the printer's status."
        self.hal.get_commander().respond_info(str(self.get_status()), log=False)

# tree and parts composer
class Composer:
    def __init__(self, config, hal):
        logging.debug("- Composing printer tree.")
        self.hal = hal
        self.pgroups = self.hal.pgroups
        self.cgroups = self.hal.cgroups
        partnames_to_remove = set()
        # read parts
        parts = collections.OrderedDict()
        for p in self.pgroups:
            for s in config.get_prefix_sections(p+" "):
                part = self._mknode(s.get_name())
                for k in s.fileconfig.options(s.get_name()):
                    part.attr_set(k, s.get(k))
                if p == "mcu":
                    part.module = importlib.import_module("controller")
                elif p == "virtual":
                    part.module = importlib.import_module("controller")
                elif p == "sensor":
                    part.module = importlib.import_module("parts.sensors."+config.getsection(s.get_name()).get("type"))
                elif p == "stepper" or p == "servo" or p == "heater" or p == "cooler":
                    part.module = importlib.import_module("parts.actuators." + p)
                else:
                    part.module = importlib.import_module("parts." + p)
                parts[part.name] = part
        # read plugins
        for m in config.get_prefix_extra_sections(self.pgroups+self.cgroups):
            part = self._mknode(m.get_name())
            for k in m.fileconfig.options(m.get_name()):
                part.attrs[k] = m.get(k)
            part.module = self._try_load_module(config, m.get_name())
            if part.module:
                parts[part.name] = part
        # assemble composites
        composites = collections.OrderedDict()
        for p in self.cgroups:
            for s in config.get_prefix_sections(p+" "):
                c = self.compose(self._mknode(s.get_name()), config, parts, composites)
                if p == "rail" or p == "cart":
                    c.module = importlib.import_module("parts."+p)
                elif p == "tool":
                    c.module = importlib.import_module("parts."+config.getsection(s.get_name()).get("type"))
                composites[s.get_name()] = c
        # dump spare composites in parts
        for c in composites:
            parts[c] = composites[c]
        del(composites)
        # adding parts and composites nodes.
        for a in config.getsection("printer").fileconfig.options("printer"):
            if a in self.pgroups or a in self.cgroups:
                if a == "mcu":
                    for n in config.getsection("printer").get(a).split(","):
                        self.hal.node("controller").children[a+" "+n] = parts.pop(a+" "+n)
                else:
                    for n in config.getsection("printer").get(a).split(","):
                        self.hal.tree.printer.children[a+" "+n] = parts.pop(a+" "+n)
            elif a == "toolhead":
                for n in config.getsection("printer").get(a).split(","):
                    partnames_to_remove = partnames_to_remove.union(self.compose_toolhead(config.get_prefix_sections(a+" "+n)[0], parts))
            else:
                self.hal.tree.printer.attrs[a] = config.get(a)
        # adding virtual pins
        for p in parts:
            if p.startswith("virtual "):
                self.hal.node("controller").children[p] = parts.pop(p)
        # adding plugins nodes
        for m in config.get_prefix_extra_sections(self.pgroups+self.cgroups):
            if m.get_name() in parts:
                partnames_to_remove = partnames_to_remove.union(parts[m.get_name()].module.load_tree_node(self.hal, parts[m.get_name()], parts))
        # cleanup
        for i in partnames_to_remove:
            if i in parts:
                parts.pop(i)
        # save leftover parts to spares
        for i in parts:
            self.hal.tree.spare.children[i] = parts.pop(i)
    def _mknode(self, name):
        return tree.PrinterNode(name)
    def _try_load_module(self, config, section):
        module_parts = section.split()
        module_name = module_parts[0]
        py_name = os.path.join(os.path.dirname(__file__), "plugins", module_name + ".py")
        py_dirname = os.path.join(os.path.dirname(__file__), "plugins", module_name, "__init__.py")
        if not os.path.exists(py_name) and not os.path.exists(py_dirname):
            logging.warning(msg(("noexist1", py_name)))
            return None
        return importlib.import_module('plugins.' + module_name)
    def compose(self, composite, config, parts, composites):
        section = config.get_prefix_sections(composite.name)
        for o in config.fileconfig.options(composite.name):
            if o in self.pgroups:
                for p in section[0].get(o).split(","):
                    if p != "none":
                        if o+" "+p in parts:
                            composite.child_set(parts.pop(o+" "+p))
            elif o == "sensor_min" or o == "sensor_max" or o == "sensor_level":
                for p in section[0].get(o).split(","):
                    if "sensor "+p in parts:
                        composite.child_set(parts.pop("sensor "+p))
                    composite.attr_set(o, section[0].get(o))
            elif o not in self.cgroups:
                composite.attr_set(o, section[0].get(o))
            else:
                for p in section[0].get(o).split(","):
                    if p != "none":
                        if o+" "+p in composites:
                            composite.child_set(self.compose(composites.pop(o+" "+p), config, parts, composites))
        return composite
    def compose_toolhead(self, config, parts):
        name = config.get_name()
        # kinematic is the toolhead's root
        knode = self._mknode("kinematic "+name.split(" ")[1])
        ktype = config.getsection(name).get("kinematics")
        knode.module = importlib.import_module('kinematics.' + ktype)
        knode.attr_set("type", ktype)
        self.hal.tree.printer.child_set(knode)
        # toolhead node is kinematic's child
        toolhead = self._mknode(name)
        toolhead.module = importlib.import_module("instrument")
        for a in config.getsection(name).fileconfig.options(name):
            toolhead.attrs[a] = config.getsection(name).get(a)
        knode.child_set(toolhead)
        # gcode node is toolhead's child
        gnode = self._mknode("gcode "+name.split(" ")[1])
        gnode.module = self.hal.node("commander").module
        toolhead.child_set(gnode)
        # build toolhead rails and carts
        return knode.module.load_tree_node(self.hal, knode, parts)

