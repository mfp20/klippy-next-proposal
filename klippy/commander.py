# Read, parse, dispatch and execute commands
#
# Gcode info at:
# - https://reprap.org/wiki/G-code
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2018  Alec Plumb <alec@etherwalker.com>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, re, collections, os
from messaging import msg
from messaging import Kerr as error
import part

class sentinel:
    pass

class Object(part.Object):
    respond_types = { 'echo': 'echo:', 'command': '//', 'error' : '!!'}
    object_command = ["UNKNOWN", "IGNORE", "ECHO"]
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
        self.printer = self.hal.tree.printer.object
        self.reactor = self.hal.get_reactor()
        self.mutex = self.reactor.mutex()
        # input handling
        self.input_log = collections.deque([], 50)
        # command handling
        self.command_handler = {}
        self.command_help = {}
        self.ready_only = []
        self.mux_commands = {}
    def register(self):
        for cmd in self.object_command:
            func = getattr(self, 'cmd_' + cmd)
            wnr = getattr(self, 'cmd_' + cmd + '_ready_only', False)
            desc = getattr(self, 'cmd_' + cmd + '_help', None)
            self.register_command(cmd, func, wnr, desc)
            for a in getattr(self, 'cmd_' + cmd + '_aliases', []):
                self.register_command(a, func, wnr)
    # command and params, parsing and manipulation
    def is_traditional_gcode(self, cmd):
        # A "traditional" g-code command is a letter and followed by a number
        try:
            cmd = cmd.upper().split()[0]
            val = float(cmd[1:])
            return cmd[0].isupper() and cmd[1].isdigit()
        except:
            return False
    def get_extended_params(self, params):
        m = self.extended_r.match(params['#original'])
        if m is None:
            raise self.error("Malformed command '%s'" % (params['#original'],))
        eargs = m.group('args')
        try:
            eparams = [earg.split('=', 1) for earg in shlex.split(eargs)]
            eparams = { k.upper(): v for k, v in eparams }
            eparams.update({k: params[k] for k in params if k.startswith('#')})
            return eparams
        except ValueError as e:
            raise self.error("Malformed command '%s'" % (params['#original'],))
    def get_str(self, name, params, default=sentinel, parser=str, minval=None, maxval=None, above=None, below=None):
        if name not in params:
            if default is self.sentinel:
                raise self.error("Error on '%s': missing %s" % (params['#original'], name))
            return default
        try:
            value = parser(params[name])
        except:
            raise self.error("Error on '%s': unable to parse %s" % (params['#original'], params[name]))
        if minval is not None and value < minval:
            raise self.error("Error on '%s': %s must have minimum of %s" % (params['#original'], name, minval))
        if maxval is not None and value > maxval:
            raise self.error("Error on '%s': %s must have maximum of %s" % (params['#original'], name, maxval))
        if above is not None and value <= above:
            raise self.error("Error on '%s': %s must be above %s" % (params['#original'], name, above))
        if below is not None and value >= below:
            raise self.error("Error on '%s': %s must be below %s" % (params['#original'], name, below))
        return value
    def get_int(self, name, params, default=sentinel, minval=None, maxval=None):
        return self.get_str(name, params, default, parser=int, minval=minval, maxval=maxval)
    def get_float(self, name, params, default=sentinel, minval=None, maxval=None, above=None, below=None):
        return self.get_str(name, params, default, parser=float, minval=minval, maxval=maxval, above=above, below=below)
    # (un)register command
    def register_command(self, cmd, func, ready_only=False, desc=None):
        # if func == None, removes and returns
        if func is None:
            old_cmd = self.command_handler.get(cmd)
            if cmd in self.ready_only:
                self.ready_only.remove(cmd)
            if cmd in self.command_handler:
                self.command_handler.pop(cmd)
            return old_cmd
        # check duplicate
        if cmd in self.command_handler:
            raise error("command %s already registered" % (cmd,))
        # check extended params
        if not self.is_traditional_gcode(cmd):
            origfunc = func
            func = lambda params: origfunc(self._get_extended_params(params))
        # add command handler
        self.command_handler[cmd] = func
        # add read_only flag
        if ready_only:
            self.ready_only.append(cmd)
        # add help (if any)
        if desc is not None:
            self.command_help[cmd] = desc
    # mux commands
    def _cmd_mux(self, params):
        key, values = self.mux_commands[params['#command']]
        if None in values:
            key_param = self.get_str(key, params, None)
        else:
            key_param = self.get_str(key, params)
        if key_param not in values:
            raise self.error("The value '%s' is not valid for %s" % (
                key_param, key))
        values[key_param](params)
    def register_mux_command(self, cmd, key, value, func, desc=None):
        prev = self.mux_commands.get(cmd)
        if prev is None:
            self.register_command(cmd, self._cmd_mux, desc=desc)
            self.mux_commands[cmd] = prev = (key, {})
        prev_key, prev_values = prev
        if prev_key != key:
            raise self.printer.config_error(
                "mux command %s %s %s may have only one key (%s)" % (
                    cmd, key, value, prev_key))
        if value in prev_values:
            raise self.printer.config_error(
                "mux command %s %s %s already registered (%s)" % (
                    cmd, key, value, prev_values))
        prev_values[value] = func
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
    # base commands
    cmd_UNKNOWN_ready_only = False
    cmd_UNKNOWN_help = "Echo an unknown command"
    def cmd_UNKNOWN(self, params):
        self.respond_info(params['#original'], log=False)
    cmd_IGNORE_ready_only = False
    cmd_IGNORE_help = "Just silently accepted"
    def cmd_IGNORE(self, params):
        # Commands that are just silently accepted
        pass
    cmd_ECHO_ready_only = False
    cmd_ECHO_help = "Echo a command"
    def cmd_ECHO(self, params):
        self.respond_info(params['#original'], log=False)

# main commander, commands receiver and dispatcher
class Dispatch(Object):
    RETRY_TIME = 0.100
    printer_command = ['RESTART', 'RESTART_FIRMWARE', 'SHOW_STATUS', 'HELP', 'RESPOND']
    args_r = re.compile('([A-Z_]+|[A-Z*/])')
    m112_r = re.compile('^(?:[nN][0-9]+)?\s*[mM]112(?:\s|$)')
    def __init__(self, hal, node):
        Object.__init__(self, hal, node)
        #
        self.fd = self.printer.input_fd
        # input handling
        self.is_processing_data = False
        self.is_fileinput = not not self.printer.get_start_args().get("debuginput")
        self.fd_handle = None
        if not self.is_fileinput:
            self.fd_handle = self.reactor.register_fd(self.fd, self.process_data)
        self.partial_input = ""
        self.pending_commands = []
        self.bytes_read = 0
        # command handling
        self.is_printer_ready = False
        self.commander = {}
        self.ready = True
    def register(self):
        self.printer.register_event_handler("klippy:ready", self._handle_ready)
        self.printer.register_event_handler("klippy:shutdown", self._handle_shutdown)
        self.printer.register_event_handler("klippy:disconnect", self._handle_disconnect)
        Object.register(self)
        for cmd in self.printer_command:
            func = getattr(self, 'cmd_' + cmd)
            wnr = getattr(self, 'cmd_' + cmd + '_ready_only', False)
            desc = getattr(self, 'cmd_' + cmd + '_help', None)
            self.register_command(cmd, func, wnr, desc)
            for a in getattr(self, 'cmd_' + cmd + '_aliases', []):
                self.register_command(a, func, wnr)
    # event handlers
    def _dump_debug(self):
        out = []
        out.append("- Dumping commander input %d blocks" % (len(self.input_log),))
        for eventtime, data in self.input_log:
            out.append("\tRead %f: %s\n" % (eventtime, repr(data)))
        for c in self.commander:
            out.append(self.commander[c]._dump_debug())
        logging.info("\n".join(out))
    def _handle_ready(self):
        self.is_printer_ready = True
        if self.is_fileinput and self.fd_handle is None:
            self.fd_handle = self.reactor.register_fd(self.fd, self._process_data)
        self._respond_state("Ready")
    def _handle_shutdown(self):
        if not self.is_printer_ready:
            return
        self.is_printer_ready = False
        self._dump_debug()
        if self.is_fileinput:
            self.printer.request_exit('error_exit')
        self._respond_state("Shutdown")
    def _handle_disconnect(self):
        self._respond_state("Disconnect")
    # (un)register a child commander
    def register_commander(self, name, commander):
        if commander == None:
            self.commander.pop(name)
        commander.respond = self.respond
        commander.respond_info = self.respond_info
        commander.respond_error = self.respond_error
        self.commander[name] = commander
    # request restart
    def request_restart(self, result):
        if self.is_printer_ready:
            print_time = self.toolhead.get_last_move_time()
            self.printer.send_event("commander:request_restart", print_time)
            self.toolhead.dwell(0.500)
            self.toolhead.wait_moves()
        self.printer.request_exit(result)
    # Parse input into commands
    def process_commands(self, commands, need_ack=True):
        for line in commands:
            # Ignore comments and leading/trailing spaces
            line = origline = line.strip()
            cpos = line.find(';')
            if cpos >= 0:
                line = line[:cpos]
            # Break command into parts
            parts = self.args_r.split(line.upper())[1:]
            params = { parts[i]: parts[i+1].strip() for i in range(0, len(parts), 2) }
            params['#original'] = origline
            if parts and parts[0] == 'N':
                # Skip line number at start of command
                del parts[:2]
            if not parts:
                # Treat empty line as empty command
                parts = ['', '']
            params['#command'] = cmd = parts[0] + parts[1].strip()
            # Invoke handler for command
            self.need_ack = need_ack
            commander = None
            handler = None
            for c in self.commander:
                handler = self.commander[c].command_handler.get(cmd)
                if handler:
                    commander = self.commander[c]
                    break
            if commander:
                params = commander.process_command(params)
            else:
                handler = self.command_handler.get(cmd, self.cmd_default)
            try:
                handler(params)
            except self.error as e:
                self.respond_error(str(e))
                self.printer.send_event("commander:command_error")
                if not need_ack:
                    raise
            except:
                msg = 'Internal error on command:"%s"' % (cmd,)
                logging.exception(msg)
                self.printer.invoke_shutdown(msg)
                self.respond_error(msg)
                if not need_ack:
                    raise
            self.ack()
    def process_data(self, eventtime):
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
                self.reactor.unregister_fd(self.fd_handle)
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
                    self.reactor.unregister_fd(self.fd_handle)
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
            self.fd_handle = self.reactor.register_fd(self.fd, self._process_data)
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
        lines = [l.strip() for l in msg.strip().split('\n')]
        self.respond("// " + "\n// ".join(lines))
    def respond_error(self, msg):
        logging.warning(msg)
        lines = msg.strip().split('\n')
        if len(lines) > 1:
            self.respond_info("\n".join(lines), log=False)
        self.respond('!! %s' % (lines[0].strip(),))
        if self.is_fileinput:
            self.printer.request_exit('error_exit')
    def _respond_state(self, state):
        self.respond_info("Klipper state: %s" % (state,), log=False)
    # printer commands
    def cmd_default(self, params):
        if not self.is_printer_ready:
            self.respond_error(self.printer.get_state_message())
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
    cmd_RESTART_ready_only = False
    cmd_RESTART_help = "Reload config file and restart host software"
    def cmd_RESTART(self, params):
        self.request_restart('restart')
    cmd_RESTART_FIRMWARE_ready_only = False
    cmd_RESTART_FIRMWARE_help = "Restart firmware, host, and reload config"
    def cmd_RESTART_FIRMWARE(self, params):
        self.request_restart('firmware_restart')
    cmd_SHOW_STATUS_ready_only = False
    cmd_SHOW_STATUS_help = "Report the printer status"
    def cmd_SHOW_STATUS(self, params):
        if self.is_printer_ready:
            self._respond_state("Ready")
            return
        msg = self.printer.get_state_message()
        msg = msg.rstrip() + "\nKlipper state: Not ready"
        self.respond_error(msg)
    cmd_HELP_ready_only = False
    def cmd_HELP(self, params):
        cmdhelp = []
        if not self.is_printer_ready:
            cmdhelp.append("Printer is not ready - not all commands available.")
        cmdhelp.append("Available extended commands:")
        for cmd in sorted(self.gcode_handlers):
            if cmd in self.help:
                cmdhelp.append("%-10s: %s" % (cmd, self.help[cmd]))
        self.respond_info("\n".join(cmdhelp), log=False)
    cmd_RESPOND_help = "Send a message to the host"
    def cmd_RESPOND(self, params):
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

# gcode commander, to use in conjunction with toolheads
class Gcode(Object):
    my_command = [
            'G1', 'G4', 'G28', 'G20', 'G90', 'G91', 'G92', 
            'M82', 'M83', 'M114', 'M220', 'M221', 'M105', 'M112', 'M115', 'M118', 'M400', 
            'GCODE_SET_OFFSET', 'GCODE_SAVE_STATE', 'GCODE_RESTORE_STATE', 'GET_POSITION'
        ]
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
        for cmd in self.my_command:
            func = getattr(self, 'cmd_' + cmd)
            wnr = getattr(self, 'cmd_' + cmd + '_ready_only', True)
            desc = getattr(self, 'cmd_' + cmd + '_help', None)
            self.register_command(cmd, func, wnr, desc)
            for a in getattr(self, 'cmd_' + cmd + '_aliases', []):
                self.register_command(a, func, wnr)
        # events
        self.hal.get_printer().register_event_handler("extruder:activate_extruder", self._handle_activate_extruder)
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
        logging.warning("TODO process Gcode command params:")
        logging.warning("       %s", params)
        return params
    # ???
    def stats(self, eventtime):
        return False, "gcodein=%d" % (self.bytes_read,)
    def set_move_transform(self, transform, force=False):
        if self.move_transform is not None and not force:
            raise self.printer.config_error("G-Code move transform already specified")
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
        eventtime = self.reactor.monotonic()
        while self.is_printer_ready and heater.check_busy(eventtime):
            print_time = self.toolhead.get_last_move_time()
            self.respond(self.get_temp(eventtime))
            eventtime = self.reactor.pause(eventtime + 1.)
    # status management
    def _action_emergency_stop(self, msg="action_emergency_stop"):
        self.printer.invoke_shutdown("Shutdown due to %s" % (msg,))
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
    cmd_G1_help = "Linear move"
    cmd_G1_aliases = ['G0'] # G0 Rapid move
    def cmd_G1(self, params):
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
                    raise self.error("Invalid speed in '%s'" % (
                        params['#original'],))
                self.speed = gcode_speed * self.speed_factor
        except ValueError as e:
            raise self.error("Unable to parse move '%s'" % (
                params['#original'],))
        self.move_with_transform(self.last_position, self.speed)
    cmd_G4_help = "Dwell"
    def cmd_G4(self, params):
        delay = self.get_float('P', params, 0., minval=0.) / 1000.
        self.toolhead.dwell(delay)
    cmd_G20_help = "Set Units to Inches"
    def cmd_G20(self, params):
        self.respond_error('Machine does not support G20 (inches) command')    
    cmd_G28_help = "Move to origin (home)"
    def cmd_G28(self, params):
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
    cmd_G90_help = "Set to absolute positioning"
    def cmd_G90(self, params):
        self.absolute_coord = True
    cmd_G91_help = "Set to relative positioning"
    def cmd_G91(self, params):
        self.absolute_coord = False
    cmd_G92_help = "Set position"
    def cmd_G92(self, params):
        offsets = { p: self.get_float(a, params)
                    for a, p in self.axis2pos.items() if a in params }
        for p, offset in offsets.items():
            if p == 3:
                offset *= self.extrude_factor
            self.base_position[p] = self.last_position[p] - offset
        if not offsets:
            self.base_position = list(self.last_position)
    # (M)iscellaneous commands
    cmd_M82_help = "Set extruder to absolute mode"
    def cmd_M82(self, params):
        self.absolute_extrude = True
    cmd_M83_help = "Set extruder to relative mode"
    def cmd_M83(self, params):
        self.absolute_extrude = False
    cmd_M105_help = "Get extruder temperature"
    cmd_M105_ready_only = True
    def cmd_M105(self, params):
        msg = self.get_temp(self.reactor.monotonic())
        if self.need_ack:
            self.ack(msg)
        else:
            self.respond(msg)
    cmd_M112_help = "Full (Emergency) stop"
    cmd_M112_ready_only = True
    def cmd_M112(self, params):
        self.printer.invoke_shutdown("Shutdown due to M112 command")
    cmd_M114_help = "Get current position"
    cmd_M114_ready_only = True
    def cmd_M114(self, params):
        p = self._get_gcode_position()
        self.respond("X:%.3f Y:%.3f Z:%.3f E:%.3f" % tuple(p))
    cmd_M115_help = "Get firmware version and capabilities"
    cmd_M115_ready_only = True
    def cmd_M115(self, params):
        software_version = self.printer.get_start_args().get('software_version')
        kw = {"FIRMWARE_NAME": "Klipper", "FIRMWARE_VERSION": software_version}
        self.ack(" ".join(["%s:%s" % (k, v) for k, v in kw.items()]))
    cmd_M118_help = "Send a message to the host"
    cmd_M118_ready_only = True
    def cmd_M118(self, params):
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
    cmd_M220_help = "Set speed factor override percentage"
    def cmd_M220(self, params):
        value = self.get_float('S', params, 100., above=0.) / (60. * 100.)
        self.speed = self._get_gcode_speed() * value
        self.speed_factor = value
    cmd_M221_help = "Set extrude factor override percentage"
    def cmd_M221(self, params):
        new_extrude_factor = self.get_float('S', params, 100., above=0.) / 100.
        last_e_pos = self.last_position[3]
        e_value = (last_e_pos - self.base_position[3]) / self.extrude_factor
        self.base_position[3] = last_e_pos - e_value * new_extrude_factor
        self.extrude_factor = new_extrude_factor
    cmd_M400_help = "Wair for current moves to finish"
    def cmd_M400(self, params):
        self.toolhead.wait_moves()
    cmd_GET_POSITION_ready_only = True
    def cmd_GET_POSITION(self, params):
        if self.toolhead is None:
            self.cmd_default(params)
            return
        kin = self.toolhead.get_kinematics()
        steppers = kin.get_steppers()
        mcu_pos = " ".join(["%s:%d" % (s.get_name(), s.get_mcu_position())
                            for s in steppers])
        for s in steppers:
            s.set_tag_position(s.get_commanded_position())
        stepper_pos = " ".join(["%s:%.6f" % (s.get_name(), s.get_tag_position())
                                for s in steppers])
        kin_pos = " ".join(["%s:%.6f" % (a, v)
                            for a, v in zip("XYZ", kin.calc_tag_position())])
        toolhead_pos = " ".join(["%s:%.6f" % (a, v) for a, v in zip(
            "XYZE", self.toolhead.get_position())])
        gcode_pos = " ".join(["%s:%.6f"  % (a, v)
                              for a, v in zip("XYZE", self.last_position)])
        base_pos = " ".join(["%s:%.6f"  % (a, v)
                             for a, v in zip("XYZE", self.base_position)])
        homing_pos = " ".join(["%s:%.6f"  % (a, v)
                               for a, v in zip("XYZ", self.homing_position)])
        self.respond_info("mcu: %s\n"
                          "stepper: %s\n"
                          "kinematic: %s\n"
                          "toolhead: %s\n"
                          "gcode: %s\n"
                          "gcode base: %s\n"
                          "gcode homing: %s"
                          % (mcu_pos, stepper_pos, kin_pos, toolhead_pos,
                             gcode_pos, base_pos, homing_pos))
    cmd_GCODE_SET_OFFSET_help = "Set a virtual offset to g-code positions"
    def cmd_GCODE_SET_OFFSET(self, params):
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
    cmd_GCODE_SAVE_STATE_help = "Save G-Code coordinate state"
    def cmd_GCODE_SAVE_STATE(self, params):
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
    cmd_GCODE_RESTORE_STATE_help = "Restore a previously saved G-Code state"
    def cmd_GCODE_RESTORE_STATE(self, params):
        state_name = self.get_str('NAME', params, 'default')
        state = self.saved_states.get(state_name)
        if state is None:
            raise self.error("Unknown g-code state: %s" % (state_name,))
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
    node.object = Gcode(hal, node)
    hal.get_commander().register_commander("gcode "+node.id(), node.object)

# TODO
# Adds support fro ARC commands via G2/G3
# - Coordinates created by this are converted into G1 commands.
# - Uses the plan_arc function from marlin which does steps in mm rather then in degrees.
# - IJ version only
#
# Copyright (C) 2019  Aleksej Vasiljkovic <achmed21@gmail.com>
#
# function planArc() from https://github.com/MarlinFirmware/Marlin
# Copyright (C) 2011 Camiel Gubbels / Erik van der Zalm
class ArcSupport:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.mm_per_arc_segment = config.getfloat('resolution', 1, above=0.0)

        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command("G2", self.cmd_G2, desc=self.cmd_G2_help)
        self.gcode.register_command("G3", self.cmd_G2, desc=self.cmd_G3_help)

    cmd_G2_help = "Counterclockwise rotation move"
    cmd_G3_help = "Clockwise rotaion move"
    def cmd_G2(self, params):
        # set vars
        currentPos =  self.gcode.get_status(None)['gcode_position']
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
            raise self.gcode.error("g2/g3: Coords missing")

        elif asR == 0 and asI == 0 and asJ==0:
            raise self.gcode.error("g2/g3: neither R nor I and J given")

        elif asR > 0 and (asI !=0 or asJ!=0):
            raise self.gcode.error("g2/g3: R, I and J were given. Invalid")
        else:   # execute conversion
            coords = []
            clockwise = params['#command'].lower().startswith("g2")
            asY = float(asY)
            asX = float(asX)

            # use radius
            # if asR > 0:
                # not sure if neccessary since R barely seems to be used

            # use IJK
            if asI != 0 or asJ!=0:
                coords = self.planArc(currentPos,
                            [asX,asY,0.,0.],
                            [asI, asJ],
                            clockwise)
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

                    self.gcode.cmd_G1(g1_params)
            else:
                self.gcode.respond_info(
                    "could not tranlate from '" + params['#original'] + "'")


    # function planArc() originates from marlin plan_arc()
    # https://github.com/MarlinFirmware/Marlin
    #
    # The arc is approximated by generating many small linear segments.
    # The length of each segment is configured in MM_PER_ARC_SEGMENT
    # Arcs smaller then this value, will be a Line only
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

            raw[X_AXIS] = center_P + r_P
            raw[Y_AXIS] = center_Q + r_Q
            raw[Z_AXIS] += linear_per_segment

            coords.append([raw[X_AXIS],  raw[Y_AXIS], raw[Z_AXIS] ])
        return coords

def load_config(config):
    return ArcSupport(config)
