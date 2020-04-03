# Read, parse, dispatch and execute commands
#
# Gcode info at:
# - https://reprap.org/wiki/G-code
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, re, collections, os
from messaging import msg
from messaging import Kerr as error

class sentinel:
    pass

class Object:
    object_command = ["UNKNOWN", "IGNORE", "ECHO"]
    def __init__(self, hal, node):
        self.hal = hal
        self.node = node
        self.reactor = self.hal.get_reactor()
        self.mutex = self.reactor.mutex()
        # Command handling
        self.command_handler = {}
        self.command_help = {}
        self.ready_only = []
    def register(self):
        for cmd in self.object_command:
            func = getattr(self, 'cmd_' + cmd)
            wnr = getattr(self, 'cmd_' + cmd + '_ready_only', False)
            desc = getattr(self, 'cmd_' + cmd + '_help', None)
            self.register_command(cmd, func, wnr, desc)
            for a in getattr(self, 'cmd_' + cmd + '_aliases', []):
                self.register_command(a, func, wnr)
    # (un)register command
    def register_command(self, cmd, func, ready_only=False, desc=None):
        # removes and returns
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
        # add command handler
        self.command_handler[cmd] = func
        if ready_only:
            self.ready_only.append(cmd)
        if desc is not None:
            self.command_help[cmd] = desc
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

# Parse and handle commands

class Dispatch(Object):
    RETRY_TIME = 0.100
    printer_command = ['RESTART', 'RESTART_FIRMWARE', 'SHOW_STATUS', 'HELP']
    args_r = re.compile('([A-Z_]+|[A-Z*/])')
    m112_r = re.compile('^(?:[nN][0-9]+)?\s*[mM]112(?:\s|$)')
    def __init__(self, hal, node):
        Object.__init__(self, hal, node)
        self.printer = self.hal.tree.printer.object
        self.fd = self.printer.input_fd
        # Input handling
        self.is_processing_data = False
        self.is_fileinput = not not self.printer.get_start_args().get("debuginput")
        self.fd_handle = None
        if not self.is_fileinput:
            self.fd_handle = self.reactor.register_fd(self.fd, self._process_data)
        self.partial_input = ""
        self.pending_commands = []
        self.bytes_read = 0
        self.input_log = collections.deque([], 50)
        # command handling
        self.is_printer_ready = False
        # External commanders
        self.commander = {}
    def register(self):
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.printer.register_event_handler("klippy:shutdown", self.handle_shutdown)
        self.printer.register_event_handler("klippy:disconnect", self.handle_disconnect)
        Object.register(self)
        for cmd in self.printer_command:
            func = getattr(self, 'cmd_' + cmd)
            wnr = getattr(self, 'cmd_' + cmd + '_ready_only', False)
            desc = getattr(self, 'cmd_' + cmd + '_help', None)
            self.register_command(cmd, func, wnr, desc)
            for a in getattr(self, 'cmd_' + cmd + '_aliases', []):
                self.register_command(a, func, wnr)
    # event handlers
    def handle_shutdown(self):
        if not self.is_printer_ready:
            return
        self.is_printer_ready = False
        self._dump_debug()
        if self.is_fileinput:
            self.printer.request_exit('error_exit')
        self._respond_state("Shutdown")
    def handle_disconnect(self):
        self._respond_state("Disconnect")
    def handle_ready(self):
        self.is_printer_ready = True
        if self.is_fileinput and self.fd_handle is None:
            self.fd_handle = self.reactor.register_fd(self.fd, self._process_data)
        self._respond_state("Ready")
    # (un)register a child commander
    def register_commander(self, name, commander):
        if commander == None:
            self.commander.pop(name)
        commander.respond = self.respond
        commander.respond_info = self.respond_info
        commander.respond_error = self.respond_error
        self.commander[name] = commander
    # Parse input into commands
    def _process_commands(self, commands, need_ack=True):
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
                handler = self.command_handler.get(cmd, self.cmd_UNKNOWN)
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
    # Response handling
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
    # PRINTER COMMANDS
    def request_restart(self, result):
        if self.is_printer_ready:
            print_time = self.toolhead.get_last_move_time()
            self.printer.send_event("commander:request_restart", print_time)
            self.toolhead.dwell(0.500)
            self.toolhead.wait_moves()
        self.printer.request_exit(result)
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

# GCODE

class Gcode(Object):
    my_command = [
            'G1', 'G4', 'G28', 'G20', 'G90', 'G91', 'G92', 
            'M82', 'M83', 'M114', 'M220', 'M221', 'M105', 'M112', 'M115', 'M400', 
            'GCODE_SET_OFFSET', 'GCODE_SAVE_STATE', 'GCODE_RESTORE_STATE', 'GET_POSITION'
        ]
    def register(self):
        for cmd in self.my_command:
            func = getattr(self, 'cmd_' + cmd)
            wnr = getattr(self, 'cmd_' + cmd + '_ready_only', True)
            desc = getattr(self, 'cmd_' + cmd + '_help', None)
            self.register_command(cmd, func, wnr, desc)
            for a in getattr(self, 'cmd_' + cmd + '_aliases', []):
                self.register_command(a, func, wnr)
        self.hal.get_commander().register_commander(self.node.name, self)
    def process_command(self, params):
        logging.warning("TODO process Gcode command params:")
        logging.warning("       %s", params)
    # G0 Rapid move
    cmd_G1_help = "Linear move"
    cmd_G1_aliases = ['G0']
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
        msg = self._get_temp(self.reactor.monotonic())
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

