# Assemble hw parts into composite parts. Adds module references to nodes.
# 
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import sys, os, time, logging, collections, importlib
from messaging import msg
from messaging import Kerr as error
import configfile, hw, tree, homing, msgproto

class Composer:
    def __init__(self, config, hal):
        self.hal = hal
        logging.info("- Composing printer tree.")
        self.pgroups = hal.pgroups
        self.cgroups = hal.cgroups
        partnames_to_remove = set()
        # read parts
        parts = collections.OrderedDict()
        for p in self.pgroups:
            for s in config.get_prefix_sections(p+" "):
                part = tree.PrinterNode(s.get_name())
                for k in s.fileconfig.options(s.get_name()):
                    for a in s.get(k).split(","):
                        if a != "none":
                            part.attr_set(k, a)
                if p == "mcu":
                    part.module = importlib.import_module("controller")
                elif p == "sensor":
                    part.module = importlib.import_module("parts."+config.getsection(s.get_name()).get("type"))
                elif p == "cooler":
                    part.module = importlib.import_module("parts."+config.getsection(s.get_name()).get("type"))
                else:
                    part.module = importlib.import_module("parts." + p)
                parts[part.name] = part
        # read plugins
        for m in config.get_prefix_extra_sections(self.pgroups+self.cgroups):
            part = tree.PrinterNode(m.get_name())
            for k in m.fileconfig.options(m.get_name()):
                part.attrs[k] = m.get(k)
            part.module = config.get_printer().try_load_module(config, m.get_name())
            if part.module:
                parts[part.name] = part
        # assemble composites
        composites = collections.OrderedDict()
        for p in self.cgroups:
            for s in config.get_prefix_sections(p+" "):
                c = self.compose(tree.PrinterNode(s.get_name()), config, parts, composites)
                if p == "rail" or p == "cart":
                    c.module = importlib.import_module("parts."+p)
                elif p == "tool":
                    c.module = importlib.import_module("parts."+config.getsection(s.get_name()).get("type"))
                composites[s.get_name()] = c
        # dump spare composites in parts
        for c in composites:
            parts[c] = composites[c]
        del(composites)
        # build tree: basic modules and parts
        hal.get_node("printer").child_set(tree.PrinterNode("commander"))
        hal.get_node("printer").child_set(tree.PrinterNode("controller"))
        hal.get_node("controller").child_set(tree.PrinterNode("timing"))
        hal.get_node("controller").child_set(tree.PrinterNode("temperature"))
        for n in ["reactor", "commander", "controller", "timing", "temperature"]:
            hal.get_node(n).module = importlib.import_module(n)
        # adding parts and composites nodes.
        for a in config.getsection("printer").fileconfig.options("printer"):
            if a in self.pgroups or a in self.cgroups:
                if a == "mcu":
                    for n in config.getsection("printer").get(a).split(","):
                        hal.get_node("controller").children[a+" "+n] = parts.pop(a+" "+n)
                else:
                    for n in config.getsection("printer").get(a).split(","):
                        hal.tree.printer.children[a+" "+n] = parts.pop(a+" "+n)
            elif a == "toolhead":
                for n in config.getsection("printer").get(a).split(","):
                    partnames_to_remove = partnames_to_remove.union(self.compose_toolhead(config.get_prefix_sections(a+" "+n)[0], parts))
            else:
                hal.tree.printer.attrs[a] = config.get(a)
        # adding plugins nodes
        for m in config.get_prefix_extra_sections(self.pgroups+self.cgroups):
            if m.get_name() in parts:
                partnames_to_remove = partnames_to_remove.union(parts[m.get_name()].module.load_tree_node(hal, parts[m.get_name()], parts))
        # cleanup
        for i in partnames_to_remove:
            if i in parts:
                parts.pop(i)
        # save spares
        for i in parts:
            hal.tree.spare.children[i] = parts.pop(i)
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
        knode = tree.PrinterNode("kinematic "+name.split(" ")[1])
        knode.module = importlib.import_module('kinematics.' + config.getsection(name).get("kinematics"))
        toolhead = tree.PrinterNode(name)
        toolhead.module = importlib.import_module("instrument")
        toolhead.child_set(tree.PrinterNode("gcode "+name.split(" ")[1]))
        toolhead.children["gcode "+name.split(" ")[1]].module = self.hal.get_node("commander").module
        for a in config.getsection(name).fileconfig.options(name):
            toolhead.attrs[a] = config.getsection(name).get(a)
        knode.child_set(toolhead)
        return knode.module.load_tree_node(self.hal, knode, parts)

# klippy main app

class Main:
    config_error = configfile.error
    command_error = homing.CommandError
    def __init__(self, input_fd, bglogger, start_args):
        self.input_fd = input_fd
        self.bglogger = bglogger
        self.start_args = start_args
        self.hw = hw.Manager(sys.modules[__name__], self)
        self.reactor = self.hw.get_reactor()
        self.reactor.register_callback(self._connect)
        self.state_message = msg("startup")
        self.is_shutdown = False
        self.run_result = None
        self.event_handlers = {}
    def register(self):
        self.hw.get_commander().register_command("SAVE_CONFIG", self.cmd_SAVE_CONFIG, desc=self.cmd_SAVE_CONFIG_help)
    def get_start_args(self):
        return self.start_args
    def get_reactor(self):
        return self.reactor
    def get_state_message(self):
        return self.state_message
    def _set_state(self, message):
        if self.state_message in (msg("ready"), msg("startup")):
            self.state_message = message
        if (message != msg("ready") and self.start_args.get('debuginput') is not None):
            self.request_exit('error_exit')
    def set_rollover_info(self, name, info, log=True):
        if log:
            logging.info(info)
        if self.bglogger is not None:
            self.bglogger.set_rollover_info(name, info)
    def try_load_module(self, config, section):
        module_parts = section.split()
        module_name = module_parts[0]
        py_name = os.path.join(os.path.dirname(__file__), "plugins", module_name + ".py")
        py_dirname = os.path.join(os.path.dirname(__file__), "plugins", module_name, "__init__.py")
        if not os.path.exists(py_name) and not os.path.exists(py_dirname):
            logging.warning(msg(("noexist1", py_name)))
            return None
        return importlib.import_module('plugins.' + module_name)
    def _read_config(self):
        pconfig = configfile.PrinterConfig(self.hw)
        config = pconfig.read_main_config()
        if self.bglogger is not None:
            pconfig.log_config(config)
        # Validate that there are no undefined parameters in the config file
        #pconfig.check_unused_options(config, self.hw)
        # turn config into a printer tree
        Composer(config, self.hw)
        # load printer objects
        self.hw.load_tree_objects()
        self.hw.register_ec()
    def _connect(self, eventtime):
        try:
            # parse config
            self._read_config()
            logging.info("* Init complete.")
            # ready to connect
            self.send_event("klippy:mcu_identify")
            for cb in self.event_handlers.get("klippy:connect", []):
                if self.state_message is not msg("startup"):
                    return
                cb()
        except (self.config_error, error) as e:
            logging.exception("Config error")
            self._set_state("%s%s" % (str(e), msg("restart")))
            return
        except msgproto.error as e:
            logging.exception("Protocol error")
            self._set_state("%s%s" % (str(e), msg("errorproto")))
            return
        except error as e:
            logging.exception("MCU error during connect")
            self._set_state("%s%s" % (str(e), msg("errormcuconnect")))
            return
        except Exception as e:
            logging.exception("Unhandled exception during connect")
            self._set_state("Internal error during connect: %s\n%s" % (str(e), msg("restart"),))
            return
        try:
            self._set_state(msg("ready"))
            for cb in self.event_handlers.get("klippy:ready", []):
                if self.state_message is not msg("ready"):
                    return
                cb()
        except Exception as e:
            logging.exception("Unhandled exception during ready callback")
            self.invoke_shutdown("Internal error during ready callback: %s" % (
                str(e),))
    def run(self):
        systime = time.time()
        monotime = self.reactor.monotonic()
        logging.info("Init printer at %s (%.1f %.1f)", time.asctime(time.localtime(systime)), systime, monotime)
        # Enter main reactor loop
        try:
            self.reactor.run()
        except:
            logging.exception("Unhandled exception during run")
            return "error_exit"
        # Check restart flags
        run_result = self.run_result
        try:
            if run_result == 'firmware_restart':
                for m in self.hw.get_controller().list_mcus():
                    m.microcontroller_restart()
            self.send_event("klippy:disconnect")
        except:
            logging.exception("Unhandled exception during post run")
        return run_result
    def invoke_shutdown(self, message):
        if self.is_shutdown:
            return
        self.is_shutdown = True
        self._set_state("%s%s" % (message, msg("shutdown")))
        for cb in self.event_handlers.get("klippy:shutdown", []):
            try:
                cb()
            except:
                logging.exception("Exception during shutdown handler")
    def invoke_async_shutdown(self, message):
        self.reactor.register_async_callback(
            (lambda e: self.invoke_shutdown(message)))
    def register_event_handler(self, event, callback):
        self.event_handlers.setdefault(event, []).append(callback)
        self.hw.tree.printer.events[event] = callback
    def send_event(self, event, *params):
        return [cb(*params) for cb in self.event_handlers.get(event, [])]
    def request_exit(self, result):
        if self.run_result is None:
            self.run_result = result
        self.reactor.end()

    # moved from configfile (to remove configfile dependancy from gcode)
    def _disallow_include_conflicts(self, regular_data, cfgname, gcode):
        config = self._build_config_wrapper(regular_data, cfgname)
        for section in self.autosave.fileconfig.sections():
            for option in self.autosave.fileconfig.options(section):
                if config.fileconfig.has_option(section, option):
                    message = "SAVE_CONFIG section '%s' option '%s' conflicts with included value" % (section, option)
                    raise gcode.error(message)
    cmd_SAVE_CONFIG_help = "Overwrite config file and restart"
    def cmd_SAVE_CONFIG(self, params):
        if not self.autosave.fileconfig.sections():
            return
        gcode = self.hw.get_gcode()
        # Create string containing autosave data
        autosave_data = self._build_config_string(self.autosave)
        lines = [('#*# ' + l).strip()
                 for l in autosave_data.split('\n')]
        lines.insert(0, "\n" + AUTOSAVE_HEADER.rstrip())
        lines.append("")
        autosave_data = '\n'.join(lines)
        # Read in and validate current config file
        cfgname = self.get_start_args()['config_file']
        try:
            data = self._read_config_file(cfgname)
            regular_data, old_autosave_data = self._find_autosave_data(data)
            config = self._build_config_wrapper(regular_data, cfgname)
        except error as e:
            message = "Unable to parse existing config on SAVE_CONFIG"
            logging.exception(message)
            raise gcode.error(message)
        regular_data = self._strip_duplicates(regular_data, self.autosave)
        self._disallow_include_conflicts(regular_data, cfgname, gcode)
        data = regular_data.rstrip() + autosave_data
        # Determine filenames
        datestr = time.strftime("-%Y%m%d_%H%M%S")
        backup_name = cfgname + datestr
        temp_name = cfgname + "_autosave"
        if cfgname.endswith(".cfg"):
            backup_name = cfgname[:-4] + datestr + ".cfg"
            temp_name = cfgname[:-4] + "_autosave.cfg"
        # Create new config file with temporary name and swap with main config
        logging.info("SAVE_CONFIG to '%s' (backup in '%s')",
                     cfgname, backup_name)
        try:
            f = open(temp_name, 'wb')
            f.write(data)
            f.close()
            os.rename(cfgname, backup_name)
            os.rename(temp_name, cfgname)
        except:
            message = "Unable to write config file during SAVE_CONFIG"
            logging.exception(message)
            raise gcode.error(message)
        # Request a restart
        gcode.request_restart('restart')

