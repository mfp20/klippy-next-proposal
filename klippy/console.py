# command console for klippy
#
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, os, sys, cmd, re, time
from messaging import msg
from messaging import Kerr as error
import msgproto

# commander's shell, base class
class ObjectShell(cmd.Cmd):
    __hiden_methods = ('do_EOF',)
    intro = None
    prompt = None
    def __init__(self, hal, node):
        cmd.Cmd.__init__(self)
        self.hal = hal
        self.node = node
    # disable repetition of last command on empty line
    def emptyline(self):
        pass
    # hide some methods from help and completion
    def get_names(self):
        return [n for n in dir(self.__class__) if n not in self.__hiden_methods]
    # helper to write to console
    def output(self, msg):
        sys.stdout.write("%s\n" % (msg,))
        sys.stdout.flush()
    # exit from console
    def do_exit(self, arg):
        return True
    def help_exit(self):
        self.output("Exit this (sub-)console.")
        self.output("You can also use the Ctrl-D shortcut.")
    do_EOF = do_exit

# main printer console
class DispatchShell(ObjectShell):
    intro = "\n * Klippy command console. Type 'help' or '?' to list currently available commands.\n"
    prompt = "Klippy > "
    can_exit = False
    def __init__(self, hal, node, lock):
        ObjectShell.__init__(self, hal, node)
        self.lock = lock
        # lock klippy startup before connect
        # allow to use a pristine mcu for debugging
        # when ready, issue "continue" command
        # to resume normal startup
        self.lock.acquire()
    # protect from accidental exit
    def onecmd(self, line):
        r = ObjectShell.onecmd(self,line)
        if r:
            if self.can_exit:
                self.cleanup()
                return True
            elif raw_input('\nClose Klippy and return to OS shell? (yes/no):')=='yes':
                self.cleanup()
                self.hal.get_printer().shutdown('exit')
                return True
        return False
    # help README
    def help_README(self):
        help_txt = """
            This is the main Klippy console. Exiting this console closes gracefully the whole Klippy app.
            The console features "tab completion": tapping TAB will complete the current word, double TAB will give you hints.
            Some commands make you enter sub-consoles, each with its own set of commands. Example: "toolhead" and "mcu".
            There is also a subset of OS shell commands (ex: ls, cd, cat), just prepend the OS shell command with "!" or "shell",
            Example: "! ls"
        """
        self.output('README')
        self.output(help_txt)
    # shell commands
    def do_shell(self, arg):
        'Prepend ! or "shell" to issue an OS command. Only a small subset of shell commands are available.'
        available = ['pwd', 'ls', 'cd', 'cat']
        invoke = False
        for c in available:
            if arg.startswith(c):
                invoke = True
                break
        if invoke:
            os.system(arg)
        else:
            self.output("Command '%s' not allowed." % arg)
            self.output("Allowed commands: %s" % str(available))
    # python introspection/reflection tools
    def do_reflector(self, arg):
        'Introspection/Reflection sub-console. Currently a useless stub.'
        sh = ReflectorShell(self.hal, self.node)
        sh.prompt = "Klippy:reflector > "
        sh.cmdloop()
    # enter mcu shell
    def do_mcu(self, arg):
        'MCU sub-console. To exit just type "exit" and you will be back to main Klippy console.'
        node = self.hal.node("mcu "+arg)
        if node != None:
            sh = MCUShell(self.hal, node)
            sh.prompt = "Klippy:mcu "+node.id()+" > "
            sh.cmdloop()
        else:
            self.output("MCU '%s' doesn't exist." % arg)
    def complete_mcu(self, text, line, begidx, endidx):
        return [i for i in self.hal.get_controller().board.keys()]
    def do_continue(self, arg):
        '''Allow the printer to run. This command can be issued once only.
        When Klippy runs with this command console enabled, 
        the printer startup process is blocked right after mcu_identify, 
        before mcu(s) connection. 
        In order to allow the operator to use the mcu sub-console before normal printer connect.
        When this command is issued, the printer resume normal startup process.
        After the printer resumed normal operation, in order to access pristine mcu status
        you will need to restart the printer first.'''
        if self.lock.locked():
            self.lock.release()
    # enter toolhead shell
    def do_toolhead(self, arg):
        'Toolhead sub-console. To exit just type "exit" and you will be back to main Klippy console.'
        node = self.hal.node("gcode "+arg)
        if node != None:
            sh = GcodeShell(self.hal, node)
            sh.prompt = "Klippy:toolhead "+node.id()+" > "
            sh.cmdloop(intro=None)
        else:
            self.output("Toolhead '%s' doesn't exist." % arg)
    def complete_toolhead(self, text, line, begidx, endidx):
        return [i.split(" ")[1] for i in self.node.object.commander if i.split(" ")[1].startswith(text)]
    def do_restart(self, arg):
        'Restart Klippy without config reload.'
        self.can_exit = True
        logging.warning("TODO currently 'restart' isn't supported, backups to 'reload'")
        self.hal.get_printer().shutdown('reconf')
        return True
    def do_reload(self, arg):
        'Reload config and restart Klippy.'
        self.can_exit = True
        self.hal.get_printer().shutdown('reconf')
        return True
    def cleanup(self):
        if self.lock.locked():
            self.lock.release()

class ReflectorShell(ObjectShell):
    def __init__(self, hal, node):
        ObjectShell.__init__(self, hal, node)
        self.name = "Reflector"
        self.intro = "\n * Reflector console. Type 'help' or '?' to list currently available commands.\n"
    # help README
    def help_README(self):
        help_txt = """
            Just a placeholder for a introspection/reflection shell, for klippy development purposes.
        """
        self.output('README')
        self.output(help_txt)

# MCU sub-console
class MCUShell(ObjectShell):
    re_eval = re.compile(r'\{(?P<eval>[^}]*)\}')
    def __init__(self, hal, node):
        ObjectShell.__init__(self, hal, node)
        self.name = node.id()
        self.pins = node.object.pins
        self.mcu = node.object.mcu
        self.intro = "\n * MCU '%s' command console. Type 'help' or '?' to list currently available commands.\n" % self.name
        #
        self.clocksync = self.hal.get_timing()
        self.ser = self.mcu._serial
        self.start_time = self.hal.get_reactor().monotonic()
        self.mcu_freq = 0.
        self.data = ""
        self.eval_globals = {}
        self.connected = False
    #
    # helpers
    def handle_default(self, params):
        tdiff = params['#receive_time'] - self.start_time
        msg = self.ser.get_msgparser().format_params(params)
        self.output("%07.3f: %s" % (tdiff, msg))
    def handle_output(self, params):
        tdiff = params['#receive_time'] - self.start_time
        self.output("%07.3f: %s: %s" % (tdiff, params['#name'], params['#msg']))
    def handle_suppress(self, params):
        pass
    def connect(self):
        # backups the printer's serial default handle, restores on disconnect
        self.handle_default_backup = self.ser.handle_default
        # 
        msgparser = self.ser.get_msgparser()
        self.output("Loaded %d commands (%s / %s)" % (len(msgparser.messages_by_id), msgparser.version, msgparser.build_versions))
        self.output("MCU config: %s" % (" ".join(["%s=%s" % (k, v) for k, v in msgparser.config.items()])))
        self.ser.handle_default = self.handle_default
        self.ser.register_response(self.handle_output, '#output')
        self.mcu_freq = msgparser.get_constant_float('CLOCK_FREQ')
        self.connected = True
        return self.hal.get_reactor().NEVER
    def update_evals(self, eventtime):
        self.eval_globals['freq'] = self.mcu_freq
        self.eval_globals['clock'] = self.clocksync.get_clock(eventtime)
    def translate(self, line, eventtime):
        evalparts = self.re_eval.split(line)
        if len(evalparts) > 1:
            self.update_evals(eventtime)
            try:
                for i in range(1, len(evalparts), 2):
                    e = eval(evalparts[i], dict(self.eval_globals))
                    if type(e) == type(0.):
                        e = int(e)
                    evalparts[i] = str(e)
            except:
                self.output("Unable to evaluate: %s" % (line,))
                return None
            line = ''.join(evalparts)
            self.output("Eval: %s" % (line,))
        try:
            line = self.pins._command_fixup(line).strip()
        except:
            self.output("Unable to map pin: %s" % (line,))
            return None
        return line
    def disconnect(self):
        # cleanup
        self.ser.register_response(None, '#output')
        self.ser.handle_default = self.handle_default_backup
        self.connected = False
    #
    # commands
    def do_help(self, arg):
        'List available commands with "help" or detailed help with "help cmd".'
        # print custom help intro
        help_txt = """
Intro
=====
This is a mcu debugging console for the Klipper micro-controller.
The "connect" command is automatically issued once at first given command
to collect all handles and information. Disconnect is automatic on exit.

In addition to console commands, you can issue mcu commands.
Example: "get_uptime".
All commands also support evaluation by enclosing an expression in { }.
Example: "reset_step_clock oid=4 clock={clock + freq}"
In addition to user defined variables (via the SET command) 
the following builtin variables may be used in expressions:
    clock : The current mcu clock time (as estimated by the host).
    freq  : The mcu clock frequency.
"""
        if arg == "":
            self.output(help_txt)
        # print default help
        ObjectShell.do_help(self,arg)
        if arg != "":
            return
        # list available mcu commands and local variables
        self.update_evals(self.hal.get_reactor().monotonic())
        mp = self.ser.get_msgparser()
        out = "Available mcu commands:"
        out += "\n======================="
        out += "\n".join([""] + sorted([mp.messages_by_id[i].msgformat for i in mp.command_ids]))
        out += "\n\nAvailable local variables:"
        out += "\n=========================="
        lvars = sorted(self.eval_globals.items())
        out += "\n  ".join([""] + ["%s: %s" % (k, v) for k, v in lvars])
        self.output(out)
    def default(self, arg):
        if not self.connected:
            self.connect()
        msg = self.translate(arg.strip(), self.hal.get_reactor().monotonic())
        if msg is None:
            return
        try:
            self.ser.send(msg)
        except msgproto.error as e:
            self.output("Error: %s" % (str(e),))
    def do_connect(self, arg):
        'Issue this command to collect information about the mcu and grab serial handlers.'
        self.connect()
        if self.mcu_freq == 0.:
            self.output("\nCouldn't connect. Retry.")
    def do_disconnect(self, arg):
        'Issue this command to restore handlers and cleanup.'
        self.disconnect()
    def do_set(self, arg):
        'Create a local variable (eg, "set myvar 123.4").'
        parts = arg.split(" ")
        val = parts[1]
        try:
            val = float(val)
        except ValueError:
            pass
        self.eval_globals[parts[0]] = val
    def do_delay(self, arg):
        'Send a command at a clock time (eg, "delay 9999 get_uptime").'
        parts = arg.split(" ")
        if not self.connected:
            self.connect()
        try:
            val = int(parts[0])
        except ValueError as e:
            self.output("Error: %s" % (str(e),))
            return
        try:
            self.ser.send(' '.join(parts[1:]), minclock=val)
        except msgproto.error as e:
            self.output("Error: %s" % (str(e),))
            return
    def do_flood(self, arg):
        'Send a command many times (eg, "flood 22 .01 get_uptime").'
        parts = arg.split(" ")
        if not self.connected:
            self.connect()
        try:
            count = int(parts[0])
            delay = float(parts[1])
        except ValueError as e:
            self.output("Error: %s" % (str(e),))
            return
        msg = ' '.join(parts[2:])
        delay_clock = int(delay * self.mcu_freq)
        msg_clock = int(self.clocksync.get_clock(self.hal.get_reactor().monotonic()) + self.mcu_freq * .200)
        try:
            for i in range(count):
                next_clock = msg_clock + delay_clock
                self.ser.send(msg, minclock=msg_clock, reqclock=next_clock)
                msg_clock = next_clock
        except msgproto.error as e:
            self.output("Error: %s" % (str(e),))
            return
    def do_suppress(self, arg):
        'Suppress a response message (eg, "suppress analog_in_state 4").'
        parts = arg.split(" ")
        if not self.connected:
            self.connect()
        oid = None
        try:
            name = parts[0]
            if len(parts) > 1:
                oid = int(parts[1])
        except ValueError as e:
            self.output("Error: %s" % (str(e),))
            return
        self.ser.register_response(self.handle_suppress, name, oid)
    def do_stats(self, arg):
        'Report serial statistics.'
        parts = arg.split(" ")
        if not self.connected:
            self.connect()
        curtime = self.hal.get_reactor().monotonic()
        self.output(' '.join([self.ser.stats(curtime), self.clocksync.stats(curtime)]))
    def do_exit(self, arg):
        if self.connected:
            self.disconnect()
        return ObjectShell.do_exit(self, arg)

# each toolhead has one of these
class GcodeShell(ObjectShell):
    def __init__(self, hal, node):
        ObjectShell.__init__(self, hal, node)
        self.name = node.id()
        self.intro = "\n* Toolhead '%s' command console. Type 'help' or '?' to list currently available commands.\n" % self.name

