# Read, parse, dispatch and execute commands
#
# Gcode info at:
# - https://reprap.org/wiki/G-code
#
# Copyright (C) 2016-2019 Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2018 Alec Plumb <alec@etherwalker.com>
# Copyright (C) 2019 Aleksej Vasiljkovic <achmed21@gmail.com>
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, re, collections, os, threading
from messaging import msg
from messaging import Kerr as error
import part, composite, console

class sentinel:
    pass

class CommandApi:
    def __init__(self):
        self.root = {}
    def _graft(self, cmd, root):
        'graft/remove/replace one command in the cmd tree'
        for w in cmd.keys():
            #print "_GRAFT: %s" % w
            if w in root.keys():
                # need further investigation
                if "_obj_" in cmd[w]:
                    # cmd[w] is a leaf, so we must check the existing entry for parameter/removal/shorty/replace
                    if "_obj_" in root[w]:
                        # root[w] is a leaf too, need further investigation
                        if cmd[w]["_obj_"]:
                            # _obj_ exist, so we need to check the name inside the _obj_
                            if "name" in cmd[w]["_obj_"][0]:
                                # new cmd have a parameter
                                i = 0
                                for obj in root[w]["_obj_"]:
                                    if "name" in obj:
                                        if obj["name"] == cmd[w]["_obj_"][0]["name"]:
                                            # replace
                                            #print "\tREPLACE %s" % obj
                                            root[w]["_obj_"][i] = cmd[w]["_obj_"][0]
                                            return root
                                    i = i + 1
                                # nothing to replace, so we can add
                                #print "\tINNEST GRAFT %s" % cmd[w]["_obj_"][0]
                                root[w]["_obj_"].append(cmd[w]["_obj_"][0])
                            else:
                                # replace
                                #print "\tREPLACE WHOLE _obj_ %s" % root[w]
                                root[w]["_obj_"] = cmd[w]["_obj_"]
                        else:
                            # _obj_ == None, it's a removal
                            #print "\tREMOVAL %s" % root[w]
                            root.pop(w)
                    else:
                        # shorty graft (ie: catch all when no further arg is given)
                        #print "\tSHORTY GRAFT %s" % cmd[w]["_obj_"]
                        root[w]["_obj_"] = cmd[w]["_obj_"]
                else:
                    # cmd[w] isn't a leaf node, so we must search for inner graft point
                    #print "\tDEEP IN"
                    root[w] = self._graft(cmd[w], root[w])
            else:
                # root doesn't have this cmd, so we can graft
                #print "\tOUTEST GRAFT %s" % cmd[w]
                root[w] = cmd[w]
        return root
    def add(self, name, handler, ident = None, ready=False, desc=None):
        'prepare a command _obj_ and call grafting method'
        parts = [part for part in name.split("_") if part != ""]
        cmd = {}
        cmdstr = ""
        root = cmd
        for p in parts:
            root[p.lower()] = {}
            root = root[p.lower()]
            cmdstr = cmdstr + " " + p.lower()
        if handler:
            if ident:
                root["_obj_"] = [{"name":str(ident), "handler":handler, "ready":ready, "help":desc}]
            else:
                root["_obj_"] = [{"handler":handler, "ready":ready, "help":desc}]
        else:
            root["_obj_"] = None
        self.root = self._graft(cmd, self.root)
    def completion(self, text, line):
        'completion tailored for cmd.Cmd complete_* method'
        #print "\n\nTEXT |"+text+"|"
        #print "LINE |"+line+"|"
        parts = line.split(" ")
        # remove prefix
        prefix = parts.pop(0)
        #print "PARTS %s %s" % (len(parts), parts)
        opts = []
        # we have a word to check, let's search for the leaf
        leaf = self.root
        i = 0
        lname = "root"
        for p in parts:
            if p in leaf.keys():
                # p is a sub, go inside
                leaf = leaf[p]
                lname = p
                i = i + 1
        cparts = parts[:i]
        aparts = parts[i:]
        #print "LEAF ("+lname+") COMMAND ("+str(cparts)+") ARG ("+str(aparts)+")"
        #
        opts = []
        # nodes
        if len(aparts) > 0:
            if len(aparts[0]) > 0:
                for c in leaf.keys():
                    if c.startswith(aparts[0]):
                        if c != "_obj_":
                            opts.append(c)
            else:
                for c in leaf.keys():
                    if c != "_obj_":
                        opts.append(c)
        # leaves
        if len(aparts) > 0:
            if len(aparts[0]) > 0:
                if "_obj_" in leaf:
                    for o in leaf["_obj_"]:
                        if "name" in o:
                            if o["name"].startswith(aparts[0]):
                                opts.append(" ".join(o["name"].split(" ")[len(aparts)-1:]))
            else:
                if "_obj_" in leaf:
                    for o in leaf["_obj_"]:
                        if "name" in o:
                            opts.append(o["name"])
        return opts
    def call(self, arg):
        'find and invoke commands handlers'
        #print "\nLINE: %s" % arg
        parts = arg.split(" ")
        #print "\t%s PARTS %s" % (len(parts), parts)
        if len(parts[0]) > 0:
            # search the leaf, then elaborate
            leaf = self.root
            i = 0
            for p in parts:
                if p in leaf.keys():
                    # not a leaf, go inside
                    leaf = leaf[p]
                    i = i + 1
                    continue
            command = " ".join(parts[:i]).strip()
            arg = " ".join(parts[i:]).strip()
            print "COMMAND ("+command+") ARG ("+arg+")"
            if len(parts[i:]) == 0:
                if "_obj_" in leaf:
                    for o in leaf["_obj_"]:
                        if "name" not in o:
                            #print "HANDLER: %s" % o
                            return o["handler"](None)
                    print "Command error: %s" % command
                else:
                    print "Command incomplete: %s" % command
            else:
                if "_obj_" in leaf:
                    for o in leaf["_obj_"]:
                        if "name" in o:
                            if o["name"] == arg:
                                #print "HANDLER: %s, ARG: %s" % (o,arg)
                                return o["handler"](arg)
                    print "Wrong command args '%s'" % arg
                else:
                    print "Command incomplete: %s" % command
    def show(self, root = None, indent = 1):
        "show the command's path"
        if root == None: root = self.root
        for c in root:
            if c == "_obj_":
                print c+" "+str(root[c])
                pass
            else:
                print str(" "*indent) + c
                self.show(root[c], indent+1)

# test functions, can be removed
def testcmd(arg=None):
    print "RECEIVED ARG: '%s'" % str(arg)
def mktestcmd():
    cmd = CommandApi()
    cmd.add("JUSTIFIED_OPTION", testcmd, None, ready=False, desc="JUSTIFIED_OPTION")
    #
    cmd.add("JUST_A_TEST_OF_OPTION", testcmd, None, ready=False, desc="JUST_A_TEST_OF_OPTION")
    #
    cmd.add("JUST_TWO_TEST_FOR_OPTIONS", testcmd, None, ready=False, desc="JUST_TWO_TEST_FOR_OPTIONS")
    # test manipulation
    cmd.add("JUST_TWO_ATTEMPTS", testcmd, None, ready=False, desc="JUST_TWO_ATTEMPTS")
    # replace
    cmd.add("JUST_TWO_ATTEMPTS", testcmd, None, ready=False, desc="JUST_TWO_ATTEMPTS (REPLACE)")
    # removal
    cmd.add("JUST_TWO_ATTEMPTS", None, None, ready=False, desc="JUST TWO ATTEMPTS (REMOVAL)")
    # re-added
    cmd.add("JUST_TWO_ATTEMPTS", testcmd, None, ready=False, desc="JUST_TWO_ATTEMPTS")
    # same, with arg
    cmd.add("JUST_TWO_ATTEMPTS", testcmd, "12", ready=False, desc="JUST TWO ATTEMPTS 12 (ARG)")
    # same, with arg, duplicate
    cmd.add("JUST_TWO_ATTEMPTS", testcmd, "12", ready=False, desc="JUST TWO ATTEMPTS 12 (DUPLICATE)")
    #
    cmd.add("JUST_TWO_TRIES", testcmd, None, ready=False, desc="JUST TWO TRIES")
    # shorty
    cmd.add("JUST_TWO", testcmd, None, ready=False, desc="JUST_TWO (shorty)")
    return cmd

# commander, base class
class Object(part.Object):
    respond_types = { 'echo': 'echo:', 'command': '//', 'error' : '!!'}
    extended_r = re.compile(
        r'^\s*(?:N[0-9]+\s*)?'
        r'(?P<cmd>[a-zA-Z_][a-zA-Z0-9_]+)(?:\s+|$)'
        r'(?P<args>[^#*;]*?)'
        r'\s*(?:[#*;].*)?$')
    def __init__(self, hal, node):
        part.Object.__init__(self,hal,node)
        self.metaconf["default_type"] = {"t": "choice", "choices": self.respond_types, "default": "echo"}
        self.metaconf["default_prefix"] = {"t": "str", "default": "self._default_type"}
        #
        self.printer = self.hal.get_printer()
        self.mutex = self.hal.get_reactor().mutex()
        # input handling
        self.input_log = collections.deque([], 50)
        # command handling
        self.command_handler = {}
        self.command_help = {}
        self.ready_only = {}
        self.command = {}
        self.cmdroot = CommandApi()
    # command and params, parsing and manipulation
    def _is_traditional_gcode(self, cmd):
        # A "traditional" g-code command is a letter and followed by a number
        try:
            cmd = cmd.upper().split()[0]
            val = float(cmd[1:])
            return cmd[0].isupper() and cmd[1].isdigit()
        except:
            return False
    def _get_extended_params(self, params):
        m = self.extended_r.match(params['#original'])
        if m is None:
            raise error("Malformed command '%s'" % (params['#original'],))
        eargs = m.group('args')
        try:
            eparams = [earg.split('=', 1) for earg in shlex.split(eargs)]
            eparams = { k.upper(): v for k, v in eparams }
            eparams.update({k: params[k] for k in params if k.startswith('#')})
            return eparams
        except ValueError as e:
            raise error("Malformed command '%s'" % (params['#original'],))
    def get_str(self, name, params, default=sentinel, parser=str, minval=None, maxval=None, above=None, below=None):
        if name not in params:
            if default is self.sentinel:
                raise error("Error on '%s': missing %s" % (params['#original'], name))
            return default
        try:
            value = parser(params[name])
        except:
            raise error("Error on '%s': unable to parse %s" % (params['#original'], params[name]))
        if minval is not None and value < minval:
            raise error("Error on '%s': %s must have minimum of %s" % (params['#original'], name, minval))
        if maxval is not None and value > maxval:
            raise error("Error on '%s': %s must have maximum of %s" % (params['#original'], name, maxval))
        if above is not None and value <= above:
            raise error("Error on '%s': %s must be above %s" % (params['#original'], name, above))
        if below is not None and value >= below:
            raise error("Error on '%s': %s must be below %s" % (params['#original'], name, below))
        return value
    def get_int(self, name, params, default=sentinel, minval=None, maxval=None):
        return self.get_str(name, params, default, parser=int, minval=minval, maxval=maxval)
    def get_float(self, name, params, default=sentinel, minval=None, maxval=None, above=None, below=None):
        return self.get_str(name, params, default, parser=float, minval=minval, maxval=maxval, above=above, below=below)
    # (un)register command
    def register_commands(self, obj, ident=None, cmdr=None):
        # TODO check extended params ???
        #if not self._is_traditional_gcode(cmd):
        #    origfunc = func
        #    func = lambda params: origfunc(self._get_extended_params(params))
        #
        if not cmdr: cmdr = self
        for m in sorted([method_name for method_name in dir(obj) if method_name.startswith("_cmd__") and not method_name.endswith("_aliases")]):
            name = m.replace("_cmd__", "").lower().strip()
            ro = False
            if m.endswith("_ready_only"):
                ro = True
                name = name.replace("_ready_only", "")
            cmdr.cmdroot.add(name, getattr(obj, m), ident, ro, getattr(obj, m).__doc__)
            for a in getattr(obj, m + '_aliases', []):
                name = a.replace("_cmd__", " ").lower().strip()
                cmdr.cmdroot.add(name, getattr(obj, m), ident, ro, getattr(obj, m).__doc__)
    # scripts support
    def get_mutex(self):
        return self.mutex
    def run_script_from_command(self, script):
        prev_need_ack = self.need_ack
        try:
            self._process_commands(script.split('\n'), need_ack=False)
        finally:
            self.need_ack = prev_need_ack
    def run_script(self, script):
        with self.mutex:
            self._process_commands(script.split('\n'), need_ack=False)
    #
    def cleanup(self):
        pass
    #
    # base commands
    def _cmd__IGNORE(self, params):
        'Just silently accepted.'
        # Commands that are just silently accepted
        pass
    def _cmd__ECHO(self, params):
        'Echo a command.'
        self.respond_info(params['#original'], log=False)
    def _cmd__UNKNOWN(self, params):
        'Echo an unknown command.'
        self.respond_info(params['#original'], log=False)

# commander, commands receiver and dispatcher
class Dispatch(Object):
    RETRY_TIME = 0.100
    args_r = re.compile('([A-Z_]+|[A-Z*/])')
    m112_r = re.compile('^(?:[nN][0-9]+)?\s*[mM]112(?:\s|$)')
    def __init__(self, hal, node):
        Object.__init__(self, hal, node)
        #
        self.fd = self.printer.input_fd
        # input handling
        self.is_processing_data = False
        self.is_fileinput = not not self.printer.get_args().get("input_debug")
        self.fd_handle = None
        if not self.is_fileinput:
            self.fd_handle = self.hal.get_reactor().register_fd(self.fd, self._process_data)
        self.partial_input = ""
        self.pending_commands = []
        self.bytes_read = 0
        # command handling
        self.is_printer_ready = False
        self.commander = {}
        self.tool = 0
        self.ready = True
    # command console thread runner
    def _console_run(self):
        self.console.cmdloop()
    #
    def register(self):
        # special register_commands
        for m in sorted([method_name for method_name in dir(self) if method_name.startswith("_cmd__") and not method_name.endswith("_aliases")]):
            name = m.replace("_cmd__", "").lower().strip()
            ro = False
            if m.endswith("_ready_only"):
                name = name.replace("_ready_only", "")
                ro = True
            pcmd = ["show_part", "show_part_full"]
            ccmd = ["show_composite", "show_composite_full"]
            for n in self.hal.node("printer").children_deep(list()):
                if name in ccmd and self.hal.is_composite(n.object):
                    self.cmdroot.add(name, getattr(self, m), n.name, ro, getattr(self, m).__doc__)
                elif name in pcmd and self.hal.is_part(n.object) and not self.hal.is_composite(n.object):
                    self.cmdroot.add(name, getattr(self, m), n.name, ro, getattr(self, m).__doc__)
            if name not in pcmd and name not in ccmd:
                self.cmdroot.add(name, getattr(self, m), self.name, ro, getattr(self, m).__doc__)
                for a in getattr(self, m + '_aliases', []):
                    name = a.replace("_cmd__", " ").lower().strip()
                    self.cmdroot.add(name, getattr(self, m), self.name, ro, getattr(self, m).__doc__)
        #
        self.printer.event_register_handler("klippy:ready", self._event_handle_ready)
        self.printer.event_register_handler("klippy:shutdown", self._event_handle_shutdown)
        self.printer.event_register_handler("klippy:disconnect", self._event_handle_disconnect)
        # spawn a thread to run printer's interactive console
        self.start_args = self.hal.get_printer().get_args()
        if 'console' in self.start_args:
            self.console = console.DispatchShell(self.hal, self.node(), self.cmdroot, self.start_args['console'])
            self._console_th = threading.Thread(name="console", target=self._console_run)
            self._console_th.start()
            logging.debug("- Klippy command console started.")
    #
    # event handlers
    def _event_handle_ready(self):
        self.is_printer_ready = True
        #
        if self.is_fileinput and self.fd_handle is None:
            self.fd_handle = self.hal.get_reactor().register_fd(self.fd, self._process_data)
        # respond
        self._respond_state("Ready")
    def _dump_debug(self):
        out = []
        out.append("- Dumping commander input %d blocks" % (len(self.input_log),))
        for eventtime, data in self.input_log:
            out.append("\tRead %f: %s\n" % (eventtime, repr(data)))
        for c in self.commander:
            out.append(self.commander[c]._dump_debug())
        logging.info("\n".join(out))
    def _event_handle_disconnect(self):
        self._respond_state("Disconnect")
    def _event_handle_shutdown(self):
        if not self.is_printer_ready:
            return
        self.is_printer_ready = False
        self._dump_debug()
        if self.is_fileinput:
            self.printer.shutdown('error')
        # respond
        self._respond_state("Shutdown")
    # (un)register a child commander
    def register_commander(self, name, commander):
        if commander == None:
            self.commander.pop(name)
        commander.respond = self.respond
        commander.respond_info = self.respond_info
        commander.respond_error = self.respond_error
        self.commander[name] = commander
    def mk_gcode_id(self):
        self.tool = self.tool + 1
        return (self.tool-1)
    # request restart
    def request_restart(self, result):
        if self.is_printer_ready:
            print_time = self.toolhead.get_last_move_time()
            self.printer.event_send("commander:request_restart", print_time)
            self.toolhead.dwell(0.500)
            self.toolhead.wait_moves()
        self.printer.shutdown(result)
    # Parse input into commands
    def _process_commands(self, commands, need_ack=True):
        for line in commands:
            # parse: ignore comments and leading/trailing spaces
            line = origline = line.strip()
            cpos = line.find(';')
            if cpos >= 0:
                line = line[:cpos]
            # parse: break command into parts
            parts = self.args_r.split(line.upper())[1:]
            params = { parts[i]: parts[i+1].strip() for i in range(0, len(parts), 2) }
            params['#original'] = origline
            if parts and parts[0] == 'N':
                # skip line number at start of command
                del parts[:2]
            if not parts:
                # treat empty line as empty command
                parts = ['', '']
            params['#command'] = cmd = parts[0] + parts[1].strip()
            #
            self.need_ack = need_ack
            # search the handler for given command
            commander = None
            handler = None
            # search in all commanders
            for c in self.commander:
                handler = self.commander[c].command_handler.get(cmd)
                if handler:
                    commander = self.commander[c]
                    break
            if commander:
                # give the commander the chance to manipulate params
                params = commander.process_command(params)
            else:
                # search local handlers, backups to self.cmd_default
                handler = self.command_handler.get(cmd, self.cmd_default)
            # invoke handler
            try:
                handler(params)
            except error as e:
                self.respond_error(str(e))
                self.printer.event_send("commander:command_error")
                if not need_ack:
                    raise
            except:
                msg = 'Internal error on command:"%s"' % (cmd,)
                logging.exception(msg)
                self.printer.call_shutdown(msg)
                self.respond_error(msg)
                if not need_ack:
                    raise
            # signal ack
            self.ack()
    def _process_data(self, eventtime):
        # Read input, separate by newline, and add to pending_commands
        try:
            data = os.read(self.fd, 4096)
        except os.error:
            logging.exception("Read g-code")
            return
        self.input_log.append((eventtime, data))
        self.bytes_read += len(data)
        lines = data.split('\n')
        lines[0] = self.partial_input + lines[0]
        self.partial_input = lines.pop()
        pending_commands = self.pending_commands
        pending_commands.extend(lines)
        # Special handling for debug file input EOF
        if not data and self.is_fileinput:
            if not self.is_processing_data:
                self.hal.get_reactor().unregister_fd(self.fd_handle)
                self.fd_handle = None
                self.request_restart('exit')
            pending_commands.append("")
        # Handle case where multiple commands pending
        if self.is_processing_data or len(pending_commands) > 1:
            if len(pending_commands) < 20:
                # Check for M112 out-of-order
                for line in lines:
                    if self.m112_r.match(line) is not None:
                        self.cmd_M112({})
            if self.is_processing_data:
                if len(pending_commands) >= 20:
                    # Stop reading input
                    self.hal.get_reactor().unregister_fd(self.fd_handle)
                    self.fd_handle = None
                return
        # Process commands
        self.is_processing_data = True
        while pending_commands:
            self.pending_commands = []
            with self.mutex:
                self._process_commands(pending_commands)
            pending_commands = self.pending_commands
        self.is_processing_data = False
        if self.fd_handle is None:
            self.fd_handle = self.hal.get_reactor().register_fd(self.fd, self._process_data)
    # response handling
    def ack(self, msg=None):
        if not self.need_ack or self.is_fileinput:
            return
        try:
            if msg:
                os.write(self.fd, "ok %s\n" % (msg,))
            else:
                os.write(self.fd, "ok\n")
        except os.error:
            logging.exception("Write g-code ack")
        self.need_ack = False
    def respond(self, msg):
        if self.is_fileinput:
            return
        try:
            os.write(self.fd, msg+"\n")
        except os.error:
            logging.exception("Write g-code response")
    def respond_info(self, msg, log=True):
        if log:
            logging.info(msg)
        if 'console' in self.start_args:
            print msg+"\n"
        lines = [l.strip() for l in msg.strip().split('\n')]
        self.respond("// " + "\n// ".join(lines))
    def respond_error(self, msg):
        logging.warning(msg)
        if 'console' in self.start_args:
            print msg+"\n"
        lines = msg.strip().split('\n')
        if len(lines) > 1:
            self.respond_info("\n".join(lines), log=False)
        self.respond('!! %s' % (lines[0].strip(),))
        if self.is_fileinput:
            self.printer.shutdown('error')
    def _respond_state(self, state):
        self.respond_info("Klipper state: %s" % (state,), log=False)
    #
    def cleanup(self):
        if 'console' in self.start_args:
            self.console.cleanup()
    #
    # printer commands
    def cmd_default(self, params):
        if not self.is_printer_ready:
            self.respond_error(self.printer.get_status())
            return
        cmd = params.get('#command')
        if not cmd:
            logging.debug(params['#original'])
            return
        if cmd.startswith("M116 "):
            # Handle M116 gcode with numeric and special characters
            handler = self.gcode_handlers.get("M116", None)
            if handler is not None:
                handler(params)
                return
        elif cmd in ['M139', 'M104'] and not self.get_float('S', params, 0.):
            # Don't warn about requests to turn off heaters when not present
            return
        elif cmd == 'M106' or (cmd == 'M106' and (
                not self.get_float('S', params, 0.) or self.is_fileinput)):
            # Don't warn about requests to turn off fan when fan not present
            return
        self.respond_info('Unknown command:"%s"' % (cmd,))
    def _cmd__HELP(self, params):
        'Help.'
        cmdhelp = []
        if not self.is_printer_ready:
            cmdhelp.append("Printer is not ready - not all commands available.")
        cmdhelp.append("Available extended commands:")
        for cmd in sorted(self.gcode_handlers):
            if cmd in self.help:
                cmdhelp.append("%-10s: %s" % (cmd, self.help[cmd]))
        self.respond_info("\n".join(cmdhelp), log=False)
    def _cmd__RESPOND(self, params):
        'Send a message to the host.'
        respond_type = self.gcode.get_str('TYPE', params, None)
        prefix = self.default_prefix
        if(respond_type != None):
            respond_type = respond_type.lower()
            if(respond_type in respond_types):
                prefix = respond_types[respond_type]
            else:
                raise self.gcode.error("RESPOND TYPE '%s' is invalid. Must be one of 'echo', 'command', or 'error'" % (respond_type,))
        prefix = self.gcode.get_str('PREFIX', params, prefix)
        msg = self.gcode.get_str('MSG', params, '')
        self.gcode.respond("%s %s" %(prefix, msg))
    def _cmd__RESTART(self, params):
        'Reload config file and restart host software.'
        self.request_restart('restart')
    def _cmd__RESTART_FIRMWARE(self, params):
        'Restart firmware, host, and reload config.'
        self.request_restart('restart_mcu')
    def _cmd__SHOW_PART(self, params):
        'Shows information about a printer part.'
        self.hal.get_commander().respond_info(self.node().show(plus="attrs"), log=False)
    def _cmd__SHOW_PART_FULL(self, params):
        'Shows information about a printer part. Full details.'
        self.hal.get_commander().respond_info(self.node().show(plus="module,object,attrs,details"), log=False)
    def _cmd__SHOW_COMPOSITE(self, params):
        'Shows information about one tree branch.'
        nodename = "???"
        self.hal.get_commander().respond_info(self.node().show(plus="attrs,deep"), log=False)
    def _cmd__SHOW_COMPOSITE_FULL(self, params):
        'Shows information about one tree branch. Full details.'
        nodename = "???"
        self.hal.get_commander().respond_info(self.node().show(plus="module,object,attrs,details,deep"), log=False)
    def _cmd__SHOW_STATUS(self, params):
        'Report the printer status.'
        if self.is_printer_ready:
            self._respond_state("Ready")
            return
        msg = self.printer.get_status()
        msg = msg.rstrip() + "\nKlipper state: Not ready"
        self.respond_error(msg)
    #self.register_command("TOOLHEAD_ENABLE", self.cmd_TOOLHEAD_ENABLE, desc = self.cmd_TOOLHEAD_ENABLE_help)

# gcode child commander, to use in conjunction with toolheads
class Gcode(Object):
    #self.metaconf["resolution"] = {"t":"float", "default":1., "above":0.}
    def __init__(self, hal, node):
        Object.__init__(self, hal, node)
        # G-Code coordinate manipulation
        self.absolute_coord = self.absolute_extrude = True
        self.base_position = [0.0, 0.0, 0.0, 0.0]
        self.last_position = [0.0, 0.0, 0.0, 0.0]
        self.homing_position = [0.0, 0.0, 0.0, 0.0]
        self.speed = 25.
        self.speed_factor = 1. / 60.
        self.extrude_factor = 1.
        # G-Code state
        self.saved_states = {}
        self.move_transform = self.move_with_transform = None
        self.position_with_transform = (lambda: [0., 0., 0., 0.])
        self.need_ack = False
        self.toolhead = None
        self.heaters = None
        self.axis2pos = {'X': 0, 'Y': 1, 'Z': 2, 'E': 3}
        self.ready = True
    def register(self):
        self.register_commands(self, None, self)
        # events
        self.hal.get_printer().event_register_handler("extruder:activate_extruder", self._handle_activate_extruder)
    # event handlers
    def _dump_debug(self):
        out = []
        out.append("Dumping gcode input %d blocks" % (len(self.input_log),))
        for eventtime, data in self.input_log:
            out.append("Read %f: %s" % (eventtime, repr(data)))
        out.append(
            "gcode state: absolute_coord=%s absolute_extrude=%s"
            " base_position=%s last_position=%s homing_position=%s"
            " speed_factor=%s extrude_factor=%s speed=%s" % (
                self.absolute_coord, self.absolute_extrude,
                self.base_position, self.last_position, self.homing_position,
                self.speed_factor, self.extrude_factor, self.speed))
        return str("\n".join(out))
    def _handle_activate_extruder(self):
        self.reset_last_position()
        self.extrude_factor = 1.
        self.base_position[3] = self.last_position[3]
    # process command's params
    def process_command(self, params):
        logging.warning("TOOLHEAD '%s': TODO process Gcode command params:", self.name)
        logging.warning("       %s", params)
        return params
    # ???
    def stats(self, eventtime):
        return False, "gcodein=%d" % (self.bytes_read,)
    def set_move_transform(self, transform, force=False):
        if self.move_transform is not None and not force:
            raise error("G-Code move transform already specified")
        old_transform = self.move_transform
        if old_transform is None:
            old_transform = self.toolhead
        self.move_transform = transform
        self.move_with_transform = transform.move
        self.position_with_transform = transform.get_position
        return old_transform
    def reset_last_position(self):
        self.last_position = self.position_with_transform()
    # temperature wrappers
    def get_temp(self, eventtime):
        # Tn:XXX /YYY B:XXX /YYY
        out = []
        if self.heaters is not None:
            for gcode_id, sensor in sorted(self.heaters.get_gcode_sensors()):
                cur, target = sensor.get_temp(eventtime)
                out.append("%s:%.1f /%.1f" % (gcode_id, cur, target))
        if not out:
            return "T:0"
        return " ".join(out)
    def wait_for_temperature(self, heater):
        # Helper to wait on heater.check_busy() and report M105 temperatures
        if self.is_fileinput:
            return
        eventtime = self.hal.get_reactor().monotonic()
        while self.is_printer_ready and heater.check_busy(eventtime):
            print_time = self.toolhead.get_last_move_time()
            self.respond(self.get_temp(eventtime))
            eventtime = self.hal.get_reactor().pause(eventtime + 1.)
    # status management
    def _action_emergency_stop(self, msg="action_emergency_stop"):
        self.printer.call_shutdown("Shutdown due to %s" % (msg,))
        return ""
    def _action_respond_info(self, msg):
        self.respond_info(msg)
        return ""
    def _action_respond_error(self, msg):
        self.respond_error(msg)
        return ""
    def _get_gcode_position(self):
        p = [lp - bp for lp, bp in zip(self.last_position, self.base_position)]
        p[3] /= self.extrude_factor
        return p
    def _get_gcode_speed(self):
        return self.speed / self.speed_factor
    def _get_gcode_speed_override(self):
        return self.speed_factor * 60.
    def get_status(self, eventtime):
        move_position = self._get_gcode_position()
        busy = self.is_processing_data
        return {
            'speed_factor': self._get_gcode_speed_override(),
            'speed': self._get_gcode_speed(),
            'extrude_factor': self.extrude_factor,
            'abs_extrude': self.absolute_extrude,
            'busy': busy,
            'move_xpos': move_position[0],
            'move_ypos': move_position[1],
            'move_zpos': move_position[2],
            'move_epos': move_position[3],
            'last_xpos': self.last_position[0],
            'last_ypos': self.last_position[1],
            'last_zpos': self.last_position[2],
            'last_epos': self.last_position[3],
            'base_xpos': self.base_position[0],
            'base_ypos': self.base_position[1],
            'base_zpos': self.base_position[2],
            'base_epos': self.base_position[3],
            'homing_xpos': self.homing_position[0],
            'homing_ypos': self.homing_position[1],
            'homing_zpos': self.homing_position[2],
            'gcode_position': homing.Coord(*move_position),
            'action_respond_info': self._action_respond_info,
            'action_respond_error': self._action_respond_error,
            'action_emergency_stop': self._action_emergency_stop,
        }
    # (G) codes
    _cmd__G1_aliases = ['G0'] # G0 Rapid move
    def _cmd__G1(self, params):
        'Linear move'
        try:
            for axis in 'XYZ':
                if axis in params:
                    v = float(params[axis])
                    pos = self.axis2pos[axis]
                    if not self.absolute_coord:
                        # value relative to position of last move
                        self.last_position[pos] += v
                    else:
                        # value relative to base coordinate position
                        self.last_position[pos] = v + self.base_position[pos]
            if 'E' in params:
                v = float(params['E']) * self.extrude_factor
                if not self.absolute_coord or not self.absolute_extrude:
                    # value relative to position of last move
                    self.last_position[3] += v
                else:
                    # value relative to base coordinate position
                    self.last_position[3] = v + self.base_position[3]
            if 'F' in params:
                gcode_speed = float(params['F'])
                if gcode_speed <= 0.:
                    raise error("Invalid speed in '%s'" % (params['#original'],))
                self.speed = gcode_speed * self.speed_factor
        except ValueError as e:
            raise error("Unable to parse move '%s'" % (params['#original'],))
        self.move_with_transform(self.last_position, self.speed)
    # function planArc() originates from marlin plan_arc() at https://github.com/MarlinFirmware/Marlin
    # Copyright (C) 2011 Camiel Gubbels / Erik van der Zalm
    #
    # Adds support fro ARC commands via G2/G3
    # - Coordinates created by this are converted into G1 commands.
    # - Uses the plan_arc function from marlin which does steps in mm rather then in degrees.
    # - IJ version only
    #
    #   The arc is approximated by generating many small linear segments.
    #   The length of each segment is configured in MM_PER_ARC_SEGMENT
    #   Arcs smaller then this value, will be a Line only
    # TODO
    def planArc(self, currentPos, targetPos=[0.,0.,0.,0.], offset=[0.,0.], clockwise=False):
        # todo: sometimes produces full circles
        coords = []
        MM_PER_ARC_SEGMENT = self.mm_per_arc_segment
        #
        X_AXIS = 0
        Y_AXIS = 1
        Z_AXIS = 2
        # Radius vector from center to current location
        r_P = offset[0]*-1
        r_Q = offset[1]*-1
        #
        radius = math.hypot(r_P, r_Q)
        center_P = currentPos[X_AXIS] - r_P
        center_Q = currentPos[Y_AXIS] - r_Q
        rt_X = targetPos[X_AXIS] - center_P
        rt_Y = targetPos[Y_AXIS] - center_Q
        linear_travel = targetPos[Z_AXIS] - currentPos[Z_AXIS]
        #
        angular_travel = math.atan2(r_P * rt_Y - r_Q * rt_X,
            r_P * rt_X + r_Q * rt_Y)
        if (angular_travel < 0): angular_travel+= math.radians(360)
        if (clockwise): angular_travel-= math.radians(360)
        # Make a circle if the angular rotation is 0
        # and the target is current position
        if (angular_travel == 0
            and currentPos[X_AXIS] == targetPos[X_AXIS]
            and currentPos[Y_AXIS] == targetPos[Y_AXIS]):
            angular_travel = math.radians(360)
        #
        flat_mm = radius * angular_travel
        mm_of_travel = linear_travel
        if(mm_of_travel == linear_travel):
            mm_of_travel = math.hypot(flat_mm, linear_travel)
        else:
            mm_of_travel = math.abs(flat_mm)
        #
        if (mm_of_travel < 0.001):
            return coords
        #
        segments = int(math.floor(mm_of_travel / (MM_PER_ARC_SEGMENT)))
        if(segments<1):
            segments=1
        #
        raw = [0.,0.,0.,0.]
        theta_per_segment = float(angular_travel / segments)
        linear_per_segment = float(linear_travel / segments)
        # Initialize the linear axis
        raw[Z_AXIS] = currentPos[Z_AXIS];
        #
        for i in range(1,segments+1):
            cos_Ti = math.cos(i * theta_per_segment)
            sin_Ti = math.sin(i * theta_per_segment)
            r_P = -offset[0] * cos_Ti + offset[1] * sin_Ti
            r_Q = -offset[0] * sin_Ti - offset[1] * cos_Ti
            #
            raw[X_AXIS] = center_P + r_P
            raw[Y_AXIS] = center_Q + r_Q
            raw[Z_AXIS] += linear_per_segment
            #
            coords.append([raw[X_AXIS],  raw[Y_AXIS], raw[Z_AXIS] ])
        return coords
    _cmd__G2_aliases = ['G3'] # G3 "Clockwise rotaion move"
    def _cmd__G2(self, params):
        'Counterclockwise rotation move'
        # set vars
        currentPos =  self.get_status(None)['gcode_position']
        #
        asX = params.get("X", None)
        asY = params.get("Y", None)
        asZ = params.get("Z", None)
        asR = float(params.get("R", 0.))    #radius
        asI = float(params.get("I", 0.))
        asJ = float(params.get("J", 0.))
        asE = float(params.get("E", 0.))
        asF = float(params.get("F", -1))
        # health checks of code
        if (asX is None or asY is None):
            raise error("g2/g3: Coords missing")
        elif asR == 0 and asI == 0 and asJ==0:
            raise error("g2/g3: neither R nor I and J given")
        elif asR > 0 and (asI !=0 or asJ!=0):
            raise error("g2/g3: R, I and J were given. Invalid")
        else:   # execute conversion
            coords = []
            clockwise = params['#command'].lower().startswith("g2")
            asY = float(asY)
            asX = float(asX)
            # TODO: check if R is needed
            # use radius
            # if asR > 0:
                # not sure if neccessary since R barely seems to be used
            # use IJK
            if asI != 0 or asJ!=0:
                coords = self.planArc(currentPos, [asX,asY,0.,0.], [asI, asJ], clockwise)
            # converting coords into G1 codes (lazy aproch)
            if len(coords)>0:
                # build dict and call cmd_G1
                for coord in coords:
                    g1_params = {'X': coord[0], 'Y': coord[1]}
                    if asZ!=None:
                        g1_params['Z']= float(asZ)
                    if asE>0:
                        g1_params['E']= float(asE)/len(coords)
                    if asF>0:
                        g1_params['F']= asF
                    self.cmd_G1(g1_params)
            else:
                self.respond_info("could not tranlate from '" + params['#original'] + "'")
    def _cmd__G4(self, params):
        'Dwell'
        delay = self.get_float('P', params, 0., minval=0.) / 1000.
        self.toolhead.dwell(delay)
    def _cmd__G20(self, params):
        ''
        self.respond_error('Machine does not support G20 (inches) command')    
    def _cmd__G28(self, params):
        'Move to origin (home)'
        axes = []
        for axis in 'XYZ':
            if axis in params:
                axes.append(self.axis2pos[axis])
        if not axes:
            axes = [0, 1, 2]
        homing_state = homing.Homing(self.printer)
        if self.is_fileinput:
            homing_state.set_no_verify_retract()
        homing_state.home_axes(axes)
        for axis in homing_state.get_axes():
            self.base_position[axis] = self.homing_position[axis]
        self.reset_last_position()
    def _cmd__G90(self, params):
        'Set to absolute positioning'
        self.absolute_coord = True
    def _cmd__G91(self, params):
        'Set to relative positioning'
        self.absolute_coord = False
    def _cmd__G92(self, params):
        ''
        offsets = { p: self.get_float(a, params)
                    for a, p in self.axis2pos.items() if a in params }
        for p, offset in offsets.items():
            if p == 3:
                offset *= self.extrude_factor
            self.base_position[p] = self.last_position[p] - offset
        if not offsets:
            self.base_position = list(self.last_position)
    # (M)iscellaneous commands
    _cmd__M18_aliases = ['M84'] # M84 "Disable idle hold"
    def _cmd__M18(self, params):
        'Disable all stepper motors'
        # Turn off motors
        # TODO params
        self.hal.get_controller().cmd_STEPPER_GROUP_SWITCH(params)
    def _cmd__M82(self, params):
        'Set extruder to absolute mode'
        self.absolute_extrude = True
    def _cmd__M83(self, params):
        'Set extruder to relative mode'
        self.absolute_extrude = False
    def _cmd__M104_ready_only(self, params, wait=False):
        'Set extrude temperature'
        gcode = self.printer.lookup_object('base_gcode')
        temp = gcode.get_float('S', params, 0.)
        if 'T' in params:
            index = gcode.get_int('T', params, minval=0)
            section = 'extruder'
            if index:
                section = 'extruder%d' % (index,)
            extruder = self.printer.lookup_object(section, None)
            if extruder is None:
                if temp <= 0.:
                    return
                raise gcode.error("Extruder not configured")
        else:
            extruder = self.printer.lookup_object('toolhead').get_extruder()
        heater = extruder.get_heater()
        heater.set_temp(temp)
        if wait and temp:
            gcode.wait_for_temperature(heater)
    def _cmd__M105_ready_only(self, params):
        'Get extruder temperature'
        msg = self.get_temp(self.hal.get_reactor().monotonic())
        if self.need_ack:
            self.ack(msg)
        else:
            self.respond(msg)
    def _cmd__M109_ready_only(self, params):
        'Set Extruder Temperature and Wait'
        self.cmd_M104(params, wait=True)
    def _cmd__M112_ready_only(self, params):
        'Full (Emergency) stop'
        self.printer.call_shutdown("Shutdown due to M112 command")
    def _cmd__M114_ready_only(self, params):
        'Get current position'
        p = self._get_gcode_position()
        self.respond("X:%.3f Y:%.3f Z:%.3f E:%.3f" % tuple(p))
    def _cmd__M115_ready_only(self, params):
        'Get firmware version and capabilities'
        software_version = self.printer.get_args().get('software_version')
        kw = {"FIRMWARE_NAME": "Klipper", "FIRMWARE_VERSION": software_version}
        self.ack(" ".join(["%s:%s" % (k, v) for k, v in kw.items()]))
    def _cmd__M118_ready_only(self, params):
        'Send a message to the host'
        if '#original' in params:
            msg = params['#original']
            if not msg.startswith('M118'):
                # Parse out additional info if M118 recd during a print
                start = msg.find('M118')
                end = msg.rfind('*')
                msg = msg[start:end]
            if len(msg) > 5:
                msg = msg[5:]
            else:
                msg = ''
            self.gcode.respond("%s %s" %(self.default_prefix, msg))
    def _cmd__M119_ready_only(self, params):
        'Get endstop status'
        self.hal.get_controller().cmd_SHOW_ENDSTOPS(params)
    def _cmd__M204(self, params):
        'Set default acceleration'
        gcode = self.hal.get_gcode()
        if 'S' in params:
            # Use S for accel
            accel = gcode.get_float('S', params, above=0.)
        elif 'P' in params and 'T' in params:
            # Use minimum of P and T for accel
            accel = min(gcode.get_float('P', params, above=0.), gcode.get_float('T', params, above=0.))
        else:
            gcode.respond_info('Invalid M204 command "%s"' % (params['#original'],))
            return
        toolhead.max_accel = min(accel, self.config_max_accel)
        toolhead._calc_junction_deviation()
    def _cmd__M220(self, params):
        'Set speed factor override percentage'
        value = self.get_float('S', params, 100., above=0.) / (60. * 100.)
        self.speed = self._get_gcode_speed() * value
        self.speed_factor = value
    def _cmd__M221(self, params):
        'Set extrude factor override percentage'
        new_extrude_factor = self.get_float('S', params, 100., above=0.) / 100.
        last_e_pos = self.last_position[3]
        e_value = (last_e_pos - self.base_position[3]) / self.extrude_factor
        self.base_position[3] = last_e_pos - e_value * new_extrude_factor
        self.extrude_factor = new_extrude_factor
    def _cmd__M400(self, params):
        'Wait for current moves to finish'
        self.toolhead.wait_moves()
    def _cmd__GCODE_SET_OFFSET(self, params):
        'Set a virtual offset to g-code positions'
        move_delta = [0., 0., 0., 0.]
        for axis, pos in self.axis2pos.items():
            if axis in params:
                offset = self.get_float(axis, params)
            elif axis + '_ADJUST' in params:
                offset = self.homing_position[pos]
                offset += self.get_float(axis + '_ADJUST', params)
            else:
                continue
            delta = offset - self.homing_position[pos]
            move_delta[pos] = delta
            self.base_position[pos] += delta
            self.homing_position[pos] = offset
        # Move the toolhead the given offset if requested
        if self.get_int('MOVE', params, 0):
            speed = self.get_float('MOVE_SPEED', params, self.speed, above=0.)
            for pos, delta in enumerate(move_delta):
                self.last_position[pos] += delta
            self.move_with_transform(self.last_position, speed)
    def _cmd__GCODE_SAVE_STATE(self, params):
        'Save G-Code coordinate state'
        state_name = self.get_str('NAME', params, 'default')
        self.saved_states[state_name] = {
            'absolute_coord': self.absolute_coord,
            'absolute_extrude': self.absolute_extrude,
            'base_position': list(self.base_position),
            'last_position': list(self.last_position),
            'homing_position': list(self.homing_position),
            'speed': self.speed, 'speed_factor': self.speed_factor,
            'extrude_factor': self.extrude_factor,
        }
    def _cmd__GCODE_RESTORE_STATE(self, params):
        'Restore a previously saved G-Code state'
        state_name = self.get_str('NAME', params, 'default')
        state = self.saved_states.get(state_name)
        if state is None:
            raise error("Unknown g-code state: %s" % (state_name,))
        # Restore state
        self.absolute_coord = state['absolute_coord']
        self.absolute_extrude = state['absolute_extrude']
        self.base_position = list(state['base_position'])
        self.homing_position = list(state['homing_position'])
        self.speed = state['speed']
        self.speed_factor = state['speed_factor']
        self.extrude_factor = state['extrude_factor']
        # Restore the relative E position
        e_diff = self.last_position[3] - state['last_position'][3]
        self.base_position[3] += e_diff
        # Move the toolhead back if requested
        if self.get_int('MOVE', params, 0):
            speed = self.get_float('MOVE_SPEED', params, self.speed, above=0.)
            self.last_position[:3] = state['last_position'][:3]
            self.move_with_transform(self.last_position, speed)

def load_node_object(hal, node):
    if node.name == "commander":
        node.object = Dispatch(hal, node)
    else:
        node.object = Gcode(hal, node)
        hal.get_commander().register_commander("gcode "+node.id(), node.object)
    return node.object

