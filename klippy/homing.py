# Code for state tracking during homing operations
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2019 Florian Heilmann <Florian.Heilmann@gmx.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, collections

HOMING_START_DELAY = 0.001
ENDSTOP_SAMPLE_TIME = .000015
ENDSTOP_SAMPLE_COUNT = 4

class Homing:
    def __init__(self, hal):
        self.hal = hal
        self.printer = self.hal.get_printer()
        self.toolhead = printer.lookup_object('toolhead')
        self.changed_axes = []
        self.verify_retract = True
    def set_no_verify_retract(self):
        self.verify_retract = False
    def set_axes(self, axes):
        self.changed_axes = axes
    def get_axes(self):
        return self.changed_axes
    def _fill_coord(self, coord):
        # Fill in any None entries in 'coord' with current toolhead position
        thcoord = list(self.toolhead.get_position())
        for i in range(len(coord)):
            if coord[i] is not None:
                thcoord[i] = coord[i]
        return thcoord
    def set_homed_position(self, pos):
        self.toolhead.set_position(self._fill_coord(pos))
    def _calc_endstop_rate(self, mcu_endstop, movepos, speed):
        startpos = self.toolhead.get_position()
        axes_d = [mp - sp for mp, sp in zip(movepos, startpos)]
        move_d = math.sqrt(sum([d*d for d in axes_d[:3]]))
        move_t = move_d / speed
        max_steps = max([(abs(s.calc_position_from_coord(startpos)
                              - s.calc_position_from_coord(movepos))
                          / s.get_step_dist())
                         for s in mcu_endstop.get_steppers()])
        return move_t / max_steps
    def homing_move(self, movepos, endstops, speed,
                    probe_pos=False, verify_movement=False):
        # Notify start of homing/probing move
        self.printer.send_event("homing:homing_move_begin", [es for es, name in endstops])
        # Note start location
        self.toolhead.flush_step_generation()
        kin = self.toolhead.get_kinematics()
        for s in kin.get_steppers():
            s.set_tag_position(s.get_commanded_position())
        start_mcu_pos = [(s, name, s.get_mcu_position())
                         for es, name in endstops for s in es.get_steppers()]
        # Start endstop checking
        print_time = self.toolhead.get_last_move_time()
        endstop_triggers = []
        for mcu_endstop, name in endstops:
            rest_time = self._calc_endstop_rate(mcu_endstop, movepos, speed)
            wait = mcu_endstop.home_start(print_time, ENDSTOP_SAMPLE_TIME, ENDSTOP_SAMPLE_COUNT, rest_time)
            endstop_triggers.append(wait)
        all_endstop_trigger = self.hal.get_reactor().completion_multi(endstop_triggers)
        self.toolhead.dwell(HOMING_START_DELAY)
        # Issue move
        error = None
        try:
            self.toolhead.drip_move(movepos, speed, all_endstop_trigger)
        except CommandError as e:
            error = "Error during homing move: %s" % (str(e),)
        # Wait for endstops to trigger
        move_end_print_time = self.toolhead.get_last_move_time()
        for mcu_endstop, name in endstops:
            did_trigger = mcu_endstop.home_wait(move_end_print_time)
            if not did_trigger and error is None:
                error = "Failed to home %s: Timeout during homing" % (name,)
        # Determine stepper halt positions
        self.toolhead.flush_step_generation()
        end_mcu_pos = [(s, name, spos, s.get_mcu_position())
                       for s, name, spos in start_mcu_pos]
        if probe_pos:
            for s, name, spos, epos in end_mcu_pos:
                md = (epos - spos) * s.get_step_dist()
                s.set_tag_position(s.get_tag_position() + md)
            self.set_homed_position(kin.calc_tag_position())
        else:
            self.toolhead.set_position(movepos)
        # Signal homing/probing move complete
        try:
            self.printer.send_event("homing:homing_move_end", [es for es, name in endstops])
        except CommandError as e:
            if error is None:
                error = str(e)
        if error is not None:
            raise CommandError(error)
        # Check if some movement occurred
        if verify_movement:
            for s, name, spos, epos in end_mcu_pos:
                if spos == epos:
                    if probe_pos:
                        raise EndstopError("Probe triggered prior to movement")
                    raise EndstopError(
                        "Endstop %s still triggered after retract" % (name,))
    def home_rails(self, rails, forcepos, movepos):
        # Notify of upcoming homing operation
        self.printer.send_event("homing:home_rails_begin", rails)
        # Alter kinematics class to think printer is at forcepos
        homing_axes = [axis for axis in range(3) if forcepos[axis] is not None]
        forcepos = self._fill_coord(forcepos)
        movepos = self._fill_coord(movepos)
        self.toolhead.set_position(forcepos, homing_axes=homing_axes)
        # Perform first home
        endstops = [es for rail in rails for es in rail.get_endstops()]
        hi = rails[0].get_homing_info()
        self.homing_move(movepos, endstops, hi.speed)
        # Perform second home
        if hi.retract_dist:
            # Retract
            axes_d = [mp - fp for mp, fp in zip(movepos, forcepos)]
            move_d = math.sqrt(sum([d*d for d in axes_d[:3]]))
            retract_r = min(1., hi.retract_dist / move_d)
            retractpos = [mp - ad * retract_r for mp, ad in zip(movepos, axes_d)]
            self.toolhead.move(retractpos, hi.retract_speed)
            # Home again
            forcepos = [rp - ad * retract_r for rp, ad in zip(retractpos, axes_d)]
            self.toolhead.set_position(forcepos)
            self.homing_move(movepos, endstops, hi.second_homing_speed, verify_movement=self.verify_retract)
        # Signal home operation complete
        self.toolhead.flush_step_generation()
        kin = self.toolhead.get_kinematics()
        for s in kin.get_steppers():
            s.set_tag_position(s.get_commanded_position())
        ret = self.printer.send_event("homing:home_rails_end", rails)
        if any(ret):
            # Apply any homing offsets
            adjustpos = kin.calc_tag_position()
            for axis in homing_axes:
                movepos[axis] = adjustpos[axis]
            self.toolhead.set_position(movepos)
    def home_axes(self, axes):
        self.changed_axes = axes
        try:
            self.toolhead.get_kinematics().home(self)
        except CommandError:
            self.printer.lookup_object('stepper_enable').motor_off()
            raise

class CommandError(Exception):
    pass

class EndstopError(CommandError):
    pass

def EndstopMoveError(pos, msg="Move out of range"):
    return EndstopError("%s: %.3f %.3f %.3f [%.3f]" % (
            msg, pos[0], pos[1], pos[2], pos[3]))

Coord = collections.namedtuple('Coord', ('x', 'y', 'z', 'e'))

#
# Run user defined actions in place of a normal G28 homing command
#
#TODO
class HomingOverride:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.start_pos = [config.getfloat('set_position_' + a, None) for a in 'xyz']
        self.axes = config.get('axes', 'XYZ').upper()
        gcode_macro = self.printer.try_load_module(config, 'gcode_macro')
        self.template = gcode_macro.load_template(config, 'gcode')
        self.in_script = False
        self.gcode = self.printer.lookup_object('gcode')
        self.prev_G28 = self.gcode.register_command("G28", None)
        self.gcode.register_command("G28", self.cmd_G28)
    def cmd_G28(self, params):
        if self.in_script:
            # Was called recursively - invoke the real G28 command
            self.prev_G28(params)
            return

        # if no axis is given as parameter we assume the override
        no_axis = True
        for axis in 'XYZ':
            if axis in params:
                no_axis = False
                break

        if no_axis:
            override = True
        else:
            # check if we home an axsis which needs the override
            override = False
            for axis in self.axes:
                if axis in params:
                    override = True

        if not override:
            self.gcode.cmd_G28(params)
            return

        # Calculate forced position (if configured)
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        homing_axes = []
        for axis, loc in enumerate(self.start_pos):
            if loc is not None:
                pos[axis] = loc
                homing_axes.append(axis)
        toolhead.set_position(pos, homing_axes=homing_axes)
        self.gcode.reset_last_position()
        # Perform homing
        kwparams = { 'printer': self.template.create_status_wrapper() }
        kwparams['params'] = params
        try:
            self.in_script = True
            self.template.run_gcode_from_command(kwparams)
        finally:
            self.in_script = False

#
# Perform Z Homing at specific XY coordinates.
#
# TODO
class HomingSafeZ:
    def __init__(self, config):
        self.printer = config.get_printer()
        try:
            x_pos, y_pos = config.get("home_xy_position", default=",").split(',')
            self.home_x_pos, self.home_y_pos = float(x_pos), float(y_pos)
        except:
            raise config.error("Unable to parse home_xy_position in %s" % (config.get_name()))

        self.z_hop = config.getfloat("z_hop", default=0.0)
        self.z_hop_speed = config.getfloat('z_hop_speed', 15., above=0.)
        self.max_z = config.getsection('stepper_z').getfloat('position_max')
        self.speed = config.getfloat('speed', 50.0, above=0.)
        self.move_to_previous = config.getboolean('move_to_previous', False)
        self.gcode = self.printer.lookup_object('gcode')
        self.prev_G28 = self.gcode.register_command("G28", None)
        self.gcode.register_command("G28", self.cmd_G28)

        if config.has_section("homing_override"):
            raise config.error("homing_override and safe_z_homing cannot be used simultaneously")

    def cmd_G28(self, params):
        toolhead = self.printer.lookup_object('toolhead')

        # Perform Z Hop if necessary
        if self.z_hop != 0.0:
            pos = toolhead.get_position()
            curtime = self.printer.get_reactor().monotonic()
            kin_status = toolhead.get_kinematics().get_status(curtime)
            # Check if Z axis is homed or has a known position
            if 'z' in kin_status['homed_axes']:
                # Check if the zhop would exceed the printer limits
                if pos[2] + self.z_hop > self.max_z:
                    self.gcode.respond_info(
                        "No zhop performed, target Z out of bounds: " +
                        str(pos[2] + self.z_hop)
                    )
                elif pos[2] < self.z_hop:
                    self._perform_z_hop(pos)
            else:
                self._perform_z_hop(pos)
                if hasattr(toolhead.get_kinematics(), "note_z_not_homed"):
                    toolhead.get_kinematics().note_z_not_homed()

        # Determine which axes we need to home
        if not any([axis in params.keys() for axis in ['X', 'Y', 'Z']]):
            need_x, need_y, need_z = [True] * 3
        else:
            need_x, need_y, need_z = tuple(axis in params for axis in ['X', 'Y', 'Z'])

        # Home XY axes if necessary
        new_params = {}
        if need_x:
            new_params['X'] = '0'
        if need_y:
            new_params['Y'] = '0'
        if new_params:
            self.prev_G28(new_params)
        # Home Z axis if necessary
        if need_z:
            # Move to safe XY homing position
            pos = toolhead.get_position()
            prev_x = pos[0]
            prev_y = pos[1]
            pos[0] = self.home_x_pos
            pos[1] = self.home_y_pos
            toolhead.move(pos, self.speed)
            self.gcode.reset_last_position()
            # Home Z
            self.prev_G28({'Z': '0'})
            # Perform Z Hop again for pressure-based probes
            pos = toolhead.get_position()
            if self.z_hop:
                pos[2] = self.z_hop
                toolhead.move(pos, self.z_hop_speed)
            # Move XY back to previous positions
            if self.move_to_previous:
                pos[0] = prev_x
                pos[1] = prev_y
                toolhead.move(pos, self.speed)
            self.gcode.reset_last_position()

    def _perform_z_hop(self, pos):
        toolhead = self.printer.lookup_object('toolhead')
        # Perform the Z-Hop
        toolhead.set_position(pos, homing_axes=[2])
        pos[2] = pos[2] + self.z_hop
        toolhead.move(pos, self.z_hop_speed)
        self.gcode.reset_last_position()

#
# Heater handling on homing moves
#
# TODO
class HomingHeaters:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.printer.register_event_handler("homing:homing_move_begin", self.handle_homing_move_begin)
        self.printer.register_event_handler("homing:homing_move_end", self.handle_homing_move_end)
        self.heaters_to_disable = config.get("heaters", "")
        self.disable_heaters = []
        self.steppers_needing_quiet = config.get("steppers", "")
        self.flaky_steppers = []
        self.pheater = self.printer.lookup_object('heater')
        self.target_save = {}
    def handle_connect(self):
        # heaters to disable
        all_heaters = self.pheater.get_all_heaters()
        self.disable_heaters = [n.strip()
                          for n in self.heaters_to_disable.split(',')]
        if self.disable_heaters == [""]:
            self.disable_heaters = all_heaters
        else:
            if not all(x in all_heaters for x in self.disable_heaters):
                raise self.printer.config_error(
                    "One or more of these heaters are unknown: %s" % (
                        self.disable_heaters))
        # steppers valid?
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        all_steppers = [s.get_name() for s in kin.get_steppers()]
        self.flaky_steppers = [n.strip()
                         for n in self.steppers_needing_quiet.split(',')]
        if self.flaky_steppers == [""]:
            return
        if not all(x in all_steppers for x in self.flaky_steppers):
            raise self.printer.config_error(
                "One or more of these steppers are unknown: %s" % (
                    self.flaky_steppers))
    def check_eligible(self, endstops):
        if self.flaky_steppers == [""]:
            return True
        steppers_being_homed = [s.get_name()
                                for es in endstops
                                for s in es.get_steppers()]
        return any(x in self.flaky_steppers for x in steppers_being_homed)
    def handle_homing_move_begin(self, endstops):
        if not self.check_eligible(endstops):
            return
        for heater_name in self.disable_heaters:
            heater = self.pheater.lookup_heater(heater_name)
            self.target_save[heater_name] = heater.get_temp(0)[1]
            heater.set_temp(0.)
    def handle_homing_move_end(self, endstops):
        if not self.check_eligible(endstops):
            return
        for heater_name in self.disable_heaters:
            heater = self.pheater.lookup_heater(heater_name)
            heater.set_temp(self.target_save[heater_name])

