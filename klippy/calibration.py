# Helper script for manual z height probing
#
# Copyright (C) 2017-2020  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2019  Rui Caridade <rui.mcbc@gmail.com>
# Copyright (C) 2018-2019 Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, bisect, math, mathutil, json, collections
import pins, homing

class Manual:
    def __init__(self, config):
        self.printer = config.get_printer()
        # Register commands
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('MANUAL_PROBE', self.cmd_MANUAL_PROBE, desc=self.cmd_MANUAL_PROBE_help)
        self.z_position_endstop = None
        if config.has_section('stepper_z'):
            zconfig = config.getsection('stepper_z')
            if zconfig.get_prefix_options('position_endstop'):
                self.z_position_endstop = zconfig.getfloat('position_endstop')
                self.gcode.register_command('Z_ENDSTOP_CALIBRATE', self.cmd_Z_ENDSTOP_CALIBRATE, desc=self.cmd_Z_ENDSTOP_CALIBRATE_help)
    def manual_probe_finalize(self, kin_pos):
        if kin_pos is not None:
            self.gcode.respond_info("Z position is %.3f" % (kin_pos[2],))
    cmd_MANUAL_PROBE_help = "Start manual probe helper script"
    def cmd_MANUAL_PROBE(self, params):
        ManualProbeHelper(self.printer, params, self.manual_probe_finalize)
    def z_endstop_finalize(self, kin_pos):
        if kin_pos is None:
            return
        z_pos = self.z_position_endstop - kin_pos[2]
        self.gcode.respond_info(
            "stepper_z: position_endstop: %.3f\n"
            "The SAVE_CONFIG command will update the printer config file\n"
            "with the above and restart the printer." % (z_pos,))
        configfile = self.printer.lookup_object('configfile')
        configfile.set('stepper_z', 'position_endstop', "%.3f" % (z_pos,))
    cmd_Z_ENDSTOP_CALIBRATE_help = "Calibrate a Z endstop"
    def cmd_Z_ENDSTOP_CALIBRATE(self, params):
        ManualProbeHelper(self.printer, params, self.z_endstop_finalize)

# Verify that a manual probe isn't already in progress
def verify_no_manual_probe(printer):
    gcode = printer.lookup_object('gcode')
    try:
        gcode.register_command('ACCEPT', 'dummy')
    except printer.config_error as e:
        raise gcode.error(
            "Already in a manual Z probe. Use ABORT to abort it.")
    gcode.register_command('ACCEPT', None)

Z_BOB_MINIMUM = 0.500
BISECT_MAX = 0.200

# Helper script to determine a Z height
class ManualProbeHelper:
    def __init__(self, printer, params, finalize_callback):
        self.printer = printer
        self.finalize_callback = finalize_callback
        self.gcode = self.printer.lookup_object('gcode')
        self.toolhead = self.printer.lookup_object('toolhead')
        self.speed = self.gcode.get_float("SPEED", params, 5.)
        self.past_positions = []
        self.last_toolhead_pos = self.last_kinematics_pos = None
        # Register commands
        verify_no_manual_probe(printer)
        self.gcode.register_command('ACCEPT', self.cmd_ACCEPT,
                                    desc=self.cmd_ACCEPT_help)
        self.gcode.register_command('NEXT', self.cmd_ACCEPT)
        self.gcode.register_command('ABORT', self.cmd_ABORT,
                                    desc=self.cmd_ABORT_help)
        self.gcode.register_command('TESTZ', self.cmd_TESTZ,
                                    desc=self.cmd_TESTZ_help)
        self.gcode.respond_info(
            "Starting manual Z probe. Use TESTZ to adjust position.\n"
            "Finish with ACCEPT or ABORT command.")
        self.start_position = self.toolhead.get_position()
        self.report_z_status()
    def get_kinematics_pos(self):
        toolhead_pos = self.toolhead.get_position()
        if toolhead_pos == self.last_toolhead_pos:
            return self.last_kinematics_pos
        self.toolhead.flush_step_generation()
        kin = self.toolhead.get_kinematics()
        for s in kin.get_steppers():
            s.set_tag_position(s.get_commanded_position())
        kin_pos = kin.calc_tag_position()
        self.last_toolhead_pos = toolhead_pos
        self.last_kinematics_pos = kin_pos
        return kin_pos
    def move_z(self, z_pos):
        curpos = self.toolhead.get_position()
        try:
            if curpos[2] - z_pos < Z_BOB_MINIMUM:
                curpos[2] = z_pos + Z_BOB_MINIMUM
                self.toolhead.move(curpos, self.speed)
            curpos[2] = z_pos
            self.toolhead.move(curpos, self.speed)
        except homing.CommandError as e:
            self.finalize(False)
            raise
    def report_z_status(self, warn_no_change=False, prev_pos=None):
        # Get position
        kin_pos = self.get_kinematics_pos()
        z_pos = kin_pos[2]
        if warn_no_change and z_pos == prev_pos:
            self.gcode.respond_info(
                "WARNING: No change in position (reached stepper resolution)")
        # Find recent positions that were tested
        pp = self.past_positions
        next_pos = bisect.bisect_left(pp, z_pos)
        prev_pos = next_pos - 1
        if next_pos < len(pp) and pp[next_pos] == z_pos:
            next_pos += 1
        prev_str = next_str = "??????"
        if prev_pos >= 0:
            prev_str = "%.3f" % (pp[prev_pos],)
        if next_pos < len(pp):
            next_str = "%.3f" % (pp[next_pos],)
        # Find recent positions
        self.gcode.respond_info("Z position: %s --> %.3f <-- %s" % (
            prev_str, z_pos, next_str))
    cmd_ACCEPT_help = "Accept the current Z position"
    def cmd_ACCEPT(self, params):
        pos = self.toolhead.get_position()
        start_pos = self.start_position
        if pos[:2] != start_pos[:2] or pos[2] >= start_pos[2]:
            self.gcode.respond_info(
                "Manual probe failed! Use TESTZ commands to position the\n"
                "nozzle prior to running ACCEPT.")
            self.finalize(False)
            return
        self.finalize(True)
    cmd_ABORT_help = "Abort manual Z probing tool"
    def cmd_ABORT(self, params):
        self.finalize(False)
    cmd_TESTZ_help = "Move to new Z height"
    def cmd_TESTZ(self, params):
        # Store current position for later reference
        kin_pos = self.get_kinematics_pos()
        z_pos = kin_pos[2]
        pp = self.past_positions
        insert_pos = bisect.bisect_left(pp, z_pos)
        if insert_pos >= len(pp) or pp[insert_pos] != z_pos:
            pp.insert(insert_pos, z_pos)
        # Determine next position to move to
        req = self.gcode.get_str("Z", params)
        if req in ('+', '++'):
            check_z = 9999999999999.9
            if insert_pos < len(self.past_positions) - 1:
                check_z = self.past_positions[insert_pos + 1]
            if req == '+':
                check_z = (check_z + z_pos) / 2.
            next_z_pos = min(check_z, z_pos + BISECT_MAX)
        elif req in ('-', '--'):
            check_z = -9999999999999.9
            if insert_pos > 0:
                check_z = self.past_positions[insert_pos - 1]
            if req == '-':
                check_z = (check_z + z_pos) / 2.
            next_z_pos = max(check_z, z_pos - BISECT_MAX)
        else:
            next_z_pos = z_pos + self.gcode.get_float("Z", params)
        # Move to given position and report it
        self.move_z(next_z_pos)
        self.report_z_status(next_z_pos != z_pos, z_pos)
    def finalize(self, success):
        self.gcode.register_command('ACCEPT', None)
        self.gcode.register_command('NEXT', None)
        self.gcode.register_command('ABORT', None)
        self.gcode.register_command('TESTZ', None)
        kin_pos = None
        if success:
            kin_pos = self.get_kinematics_pos()
        self.finalize_callback(kin_pos)

def load_config(config):
    return ManualProbe(config)

#
# Z-Probe support
#

HINT_TIMEOUT = """
Make sure to home the printer before probing. If the probe
did not move far enough to trigger, then consider reducing
the Z axis minimum position so the probe can travel further
(the Z minimum position can be negative).
"""

class Probe:
    def __init__(self, config, mcu_probe):
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.mcu_probe = mcu_probe
        self.speed = config.getfloat('speed', 5.0, above=0.)
        self.lift_speed = config.getfloat('lift_speed', self.speed, above=0.)
        self.x_offset = config.getfloat('x_offset', 0.)
        self.y_offset = config.getfloat('y_offset', 0.)
        self.z_offset = config.getfloat('z_offset')
        self.probe_calibrate_z = 0.
        self.multi_probe_pending = False
        # Infer Z position to move to during a probe
        if config.has_section('stepper_z'):
            zconfig = config.getsection('stepper_z')
            self.z_position = zconfig.getfloat('position_min', 0.)
        else:
            pconfig = config.getsection('printer')
            self.z_position = pconfig.getfloat('minimum_z_position', 0.)
        # Multi-sample support (for improved accuracy)
        self.sample_count = config.getint('samples', 1, minval=1)
        self.sample_retract_dist = config.getfloat('sample_retract_dist', 2.,
                                                   above=0.)
        atypes = {'median': 'median', 'average': 'average'}
        self.samples_result = config.getchoice('samples_result', atypes,
                                               'average')
        self.samples_tolerance = config.getfloat('samples_tolerance', 0.100,
                                                 minval=0.)
        self.samples_retries = config.getint('samples_tolerance_retries', 0,
                                             minval=0)
        # Register z_virtual_endstop pin
        self.printer.lookup_object('pins').register_chip('probe', self)
        # Register homing event handlers
        self.printer.event_register_handler("homing:homing_move_begin",
                                            self._handle_homing_move_begin)
        self.printer.event_register_handler("homing:homing_move_end",
                                            self._handle_homing_move_end)
        self.printer.event_register_handler("homing:home_rails_begin",
                                            self._handle_home_rails_begin)
        self.printer.event_register_handler("homing:home_rails_end",
                                            self._handle_home_rails_end)
        self.printer.event_register_handler("gcode:command_error",
                                            self._handle_command_error)
        # Register PROBE/QUERY_PROBE commands
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('PROBE', self.cmd_PROBE,
                                    desc=self.cmd_PROBE_help)
        self.gcode.register_command('QUERY_PROBE', self.cmd_QUERY_PROBE,
                                    desc=self.cmd_QUERY_PROBE_help)
        self.gcode.register_command('PROBE_CALIBRATE', self.cmd_PROBE_CALIBRATE,
                                    desc=self.cmd_PROBE_CALIBRATE_help)
        self.gcode.register_command('PROBE_ACCURACY', self.cmd_PROBE_ACCURACY,
                                    desc=self.cmd_PROBE_ACCURACY_help)
    def _handle_homing_move_begin(self, endstops):
        if self.mcu_probe in endstops:
            self.mcu_probe.probe_prepare()
    def _handle_homing_move_end(self, endstops):
        if self.mcu_probe in endstops:
            self.mcu_probe.probe_finalize()
    def _handle_home_rails_begin(self, rails):
        endstops = [es for rail in rails for es, name in rail.get_endstops()]
        if self.mcu_probe in endstops:
            self.multi_probe_begin()
    def _handle_home_rails_end(self, rails):
        endstops = [es for rail in rails for es, name in rail.get_endstops()]
        if self.mcu_probe in endstops:
            self.multi_probe_end()
    def _handle_command_error(self):
        try:
            self.multi_probe_end()
        except:
            logging.exception("Multi-probe end")
    def multi_probe_begin(self):
        self.mcu_probe.multi_probe_begin()
        self.multi_probe_pending = True
    def multi_probe_end(self):
        if self.multi_probe_pending:
            self.multi_probe_pending = False
            self.mcu_probe.multi_probe_end()
    def setup_pin(self, pin_type, pin_params):
        if pin_type != 'endstop' or pin_params['pin'] != 'z_virtual_endstop':
            raise pins.error("Probe virtual endstop only useful as endstop pin")
        if pin_params['invert'] or pin_params['pullup']:
            raise pins.error("Can not pullup/invert probe virtual endstop")
        return self.mcu_probe
    def get_lift_speed(self, params=None):
        if params is not None:
            return self.gcode.get_float("LIFT_SPEED", params,
                                        self.lift_speed, above=0.)
        return self.lift_speed
    def get_offsets(self):
        return self.x_offset, self.y_offset, self.z_offset
    def _probe(self, speed):
        toolhead = self.printer.lookup_object('toolhead')
        homing_state = homing.Homing(self.printer)
        pos = toolhead.get_position()
        pos[2] = self.z_position
        endstops = [(self.mcu_probe, "probe")]
        verify = self.printer.get_args().get('debugoutput') is None
        try:
            homing_state.homing_move(pos, endstops, speed,
                                     probe_pos=True, verify_movement=verify)
        except homing.CommandError as e:
            reason = str(e)
            if "Timeout during endstop homing" in reason:
                reason += HINT_TIMEOUT
            raise homing.CommandError(reason)
        pos = toolhead.get_position()
        self.gcode.respond_info("probe at %.3f,%.3f is z=%.6f" % (
            pos[0], pos[1], pos[2]))
        self.gcode.reset_last_position()
        return pos[:3]
    def _move(self, coord, speed):
        toolhead = self.printer.lookup_object('toolhead')
        curpos = toolhead.get_position()
        for i in range(len(coord)):
            if coord[i] is not None:
                curpos[i] = coord[i]
        toolhead.move(curpos, speed)
        self.gcode.reset_last_position()
    def _calc_mean(self, positions):
        count = float(len(positions))
        return [sum([pos[i] for pos in positions]) / count
                for i in range(3)]
    def _calc_median(self, positions):
        z_sorted = sorted(positions, key=(lambda p: p[2]))
        middle = len(positions) // 2
        if (len(positions) & 1) == 1:
            # odd number of samples
            return z_sorted[middle]
        # even number of samples
        return self._calc_mean(z_sorted[middle-1:middle+1])
    def run_probe(self, params={}):
        speed = self.gcode.get_float(
            "PROBE_SPEED", params, self.speed, above=0.)
        lift_speed = self.get_lift_speed(params)
        sample_count = self.gcode.get_int(
            "SAMPLES", params, self.sample_count, minval=1)
        sample_retract_dist = self.gcode.get_float(
            "SAMPLE_RETRACT_DIST", params, self.sample_retract_dist, above=0.)
        samples_tolerance = self.gcode.get_float(
            "SAMPLES_TOLERANCE", params, self.samples_tolerance, minval=0.)
        samples_retries = self.gcode.get_int(
            "SAMPLES_TOLERANCE_RETRIES", params, self.samples_retries, minval=0)
        samples_result = self.gcode.get_str(
            "SAMPLES_RESULT", params, self.samples_result)
        must_notify_multi_probe = not self.multi_probe_pending
        if must_notify_multi_probe:
            self.multi_probe_begin()
        retries = 0
        positions = []
        while len(positions) < sample_count:
            # Probe position
            pos = self._probe(speed)
            positions.append(pos)
            # Check samples tolerance
            z_positions = [p[2] for p in positions]
            if max(z_positions) - min(z_positions) > samples_tolerance:
                if retries >= samples_retries:
                    raise homing.CommandError(
                        "Probe samples exceed samples_tolerance")
                self.gcode.respond_info(
                    "Probe samples exceed tolerance. Retrying...")
                retries += 1
                positions = []
            # Retract
            if len(positions) < sample_count:
                liftpos = [None, None, pos[2] + sample_retract_dist]
                self._move(liftpos, lift_speed)
        if must_notify_multi_probe:
            self.multi_probe_end()
        # Calculate and return result
        if samples_result == 'median':
            return self._calc_median(positions)
        return self._calc_mean(positions)
    cmd_PROBE_help = "Probe Z-height at current XY position"
    def cmd_PROBE(self, params):
        pos = self.run_probe(params)
        self.gcode.respond_info("Result is z=%.6f" % (pos[2],))
    cmd_QUERY_PROBE_help = "Return the status of the z-probe"
    def cmd_QUERY_PROBE(self, params):
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        res = self.mcu_probe.query_endstop(print_time)
        self.gcode.respond_info(
            "probe: %s" % (["open", "TRIGGERED"][not not res],))
    cmd_PROBE_ACCURACY_help = "Probe Z-height accuracy at current XY position"
    def cmd_PROBE_ACCURACY(self, params):
        speed = self.gcode.get_float("PROBE_SPEED", params,
                                     self.speed, above=0.)
        lift_speed = self.get_lift_speed(params)
        sample_count = self.gcode.get_int("SAMPLES", params, 10, minval=1)
        sample_retract_dist = self.gcode.get_float(
            "SAMPLE_RETRACT_DIST", params, self.sample_retract_dist, above=0.)
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        self.gcode.respond_info("PROBE_ACCURACY at X:%.3f Y:%.3f Z:%.3f"
                                " (samples=%d retract=%.3f"
                                " speed=%.1f lift_speed=%.1f)\n"
                                % (pos[0], pos[1], pos[2],
                                   sample_count, sample_retract_dist,
                                   speed, lift_speed))
        # Probe bed sample_count times
        self.multi_probe_begin()
        positions = []
        while len(positions) < sample_count:
            # Probe position
            pos = self._probe(speed)
            positions.append(pos)
            # Retract
            liftpos = [None, None, pos[2] + sample_retract_dist]
            self._move(liftpos, lift_speed)
        self.multi_probe_end()
        # Calculate maximum, minimum and average values
        max_value = max([p[2] for p in positions])
        min_value = min([p[2] for p in positions])
        range_value = max_value - min_value
        avg_value = self._calc_mean(positions)[2]
        median = self._calc_median(positions)[2]
        # calculate the standard deviation
        deviation_sum = 0
        for i in range(len(positions)):
            deviation_sum += pow(positions[i][2] - avg_value, 2.)
        sigma = (deviation_sum / len(positions)) ** 0.5
        # Show information
        self.gcode.respond_info(
            "probe accuracy results: maximum %.6f, minimum %.6f, range %.6f, "
            "average %.6f, median %.6f, standard deviation %.6f" % (
            max_value, min_value, range_value, avg_value, median, sigma))
    def probe_calibrate_finalize(self, kin_pos):
        if kin_pos is None:
            return
        z_offset = self.probe_calibrate_z - kin_pos[2]
        self.gcode.respond_info(
            "%s: z_offset: %.3f\n"
            "The SAVE_CONFIG command will update the printer config file\n"
            "with the above and restart the printer." % (self.name, z_offset))
        configfile = self.printer.lookup_object('configfile')
        configfile.set(self.name, 'z_offset', "%.3f" % (z_offset,))
    cmd_PROBE_CALIBRATE_help = "Calibrate the probe's z_offset"
    def cmd_PROBE_CALIBRATE(self, params):
        manual_probe.verify_no_manual_probe(self.printer)
        # Perform initial probe
        lift_speed = self.get_lift_speed(params)
        curpos = self.run_probe(params)
        # Move away from the bed
        self.probe_calibrate_z = curpos[2]
        curpos[2] += 5.
        self._move(curpos, lift_speed)
        # Move the nozzle over the probe point
        curpos[0] += self.x_offset
        curpos[1] += self.y_offset
        self._move(curpos, self.speed)
        # Start manual probe
        manual_probe.ManualProbeHelper(self.printer, params,
                                       self.probe_calibrate_finalize)

# Endstop wrapper that enables probe specific features
class ProbeEndstopWrapper:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.position_endstop = config.getfloat('z_offset')
        gcode_macro = self.printer.try_load_module(config, 'gcode_macro')
        self.activate_gcode = gcode_macro.load_template(
            config, 'activate_gcode', '')
        self.deactivate_gcode = gcode_macro.load_template(
            config, 'deactivate_gcode', '')
        # Create an "endstop" object to handle the probe pin
        ppins = self.printer.lookup_object('pins')
        pin = config.get('pin')
        pin_params = ppins.lookup_pin(pin, can_invert=True, can_pullup=True)
        mcu = pin_params['chip']
        mcu.register_config_callback(self._build_config)
        self.mcu_endstop = mcu.setup_pin('endstop', pin_params)
        # Wrappers
        self.get_mcu = self.mcu_endstop.get_mcu
        self.add_stepper = self.mcu_endstop.add_stepper
        self.get_steppers = self.mcu_endstop.get_steppers
        self.home_start = self.mcu_endstop.home_start
        self.home_wait = self.mcu_endstop.home_wait
        self.query_endstop = self.mcu_endstop.query_endstop
    def _build_config(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis('z'):
                self.add_stepper(stepper)
    def multi_probe_begin(self):
        pass
    def multi_probe_end(self):
        pass
    def probe_prepare(self):
        toolhead = self.printer.lookup_object('toolhead')
        start_pos = toolhead.get_position()
        self.activate_gcode.run_gcode_from_command()
        if toolhead.get_position()[:3] != start_pos[:3]:
            raise homing.CommandError(
                "Toolhead moved during probe activate_gcode script")
    def probe_finalize(self):
        toolhead = self.printer.lookup_object('toolhead')
        start_pos = toolhead.get_position()
        self.deactivate_gcode.run_gcode_from_command()
        if toolhead.get_position()[:3] != start_pos[:3]:
            raise homing.CommandError(
                "Toolhead moved during probe deactivate_gcode script")
    def get_position_endstop(self):
        return self.position_endstop

# Helper code that can probe a series of points and report the
# position at each point.
class ProbePointsHelper:
    def __init__(self, config, finalize_callback, default_points=None):
        self.printer = config.get_printer()
        self.finalize_callback = finalize_callback
        self.probe_points = default_points
        self.name = config.get_name()
        self.gcode = self.printer.lookup_object('gcode')
        # Read config settings
        if default_points is None or config.get('points', None) is not None:
            points = config.get('points').split('\n')
            try:
                points = [line.split(',', 1) for line in points if line.strip()]
                self.probe_points = [(float(p[0].strip()), float(p[1].strip()))
                                     for p in points]
            except:
                raise config.error("Unable to parse probe points in %s" % (
                    self.name))
        self.horizontal_move_z = config.getfloat('horizontal_move_z', 5.)
        self.speed = config.getfloat('speed', 50., above=0.)
        self.use_offsets = False
        # Internal probing state
        self.lift_speed = self.speed
        self.probe_offsets = (0., 0., 0.)
        self.results = []
    def minimum_points(self,n):
        if len(self.probe_points) < n:
            raise self.printer.config_error(
                "Need at least %d probe points for %s" % (n, self.name))
    def use_xy_offsets(self, use_offsets):
        self.use_offsets = use_offsets
    def get_lift_speed(self):
        return self.lift_speed
    def _move_next(self):
        toolhead = self.printer.lookup_object('toolhead')
        # Lift toolhead
        speed = self.lift_speed
        if not self.results:
            # Use full speed to first probe position
            speed = self.speed
        curpos = toolhead.get_position()
        curpos[2] = self.horizontal_move_z
        toolhead.move(curpos, speed)
        # Check if done probing
        if len(self.results) >= len(self.probe_points):
            self.gcode.reset_last_position()
            toolhead.get_last_move_time()
            res = self.finalize_callback(self.probe_offsets, self.results)
            if res != "retry":
                return True
            self.results = []
        # Move to next XY probe point
        curpos[:2] = self.probe_points[len(self.results)]
        if self.use_offsets:
            curpos[0] -= self.probe_offsets[0]
            curpos[1] -= self.probe_offsets[1]
        toolhead.move(curpos, self.speed)
        self.gcode.reset_last_position()
        return False
    def start_probe(self, params):
        manual_probe.verify_no_manual_probe(self.printer)
        # Lookup objects
        probe = self.printer.lookup_object('probe', None)
        method = self.gcode.get_str('METHOD', params, 'automatic').lower()
        self.results = []
        if probe is None or method != 'automatic':
            # Manual probe
            self.lift_speed = self.speed
            self.probe_offsets = (0., 0., 0.)
            self._manual_probe_start()
            return
        # Perform automatic probing
        self.lift_speed = probe.get_lift_speed(params)
        self.probe_offsets = probe.get_offsets()
        if self.horizontal_move_z < self.probe_offsets[2]:
            raise self.gcode.error("horizontal_move_z can't be less than"
                                   " probe's z_offset")
        probe.multi_probe_begin()
        while 1:
            done = self._move_next()
            if done:
                break
            pos = probe.run_probe(params)
            self.results.append(pos)
        probe.multi_probe_end()
    def _manual_probe_start(self):
        done = self._move_next()
        if not done:
            manual_probe.ManualProbeHelper(self.printer, {},
                                           self._manual_probe_finalize)
    def _manual_probe_finalize(self, kin_pos):
        if kin_pos is None:
            return
        self.results.append(kin_pos)
        self._manual_probe_start()

def load_config(config):
    return PrinterProbe(config, ProbeEndstopWrapper(config))

#
# Helper script to adjust bed screws
#

def parse_coord(config, param):
    pair = config.get(param).strip().split(',', 1)
    try:
        return (float(pair[0]), float(pair[1]))
    except:
        raise config.error("%s:%s needs to be an x,y coordinate" % (
            config.get_name(), param))

class BedScrews:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.state = None
        self.current_screw = 0
        self.adjust_again = False
        # Read config
        screws = []
        fine_adjust = []
        for i in range(99):
            prefix = "screw%d" % (i + 1,)
            if config.get(prefix, None) is None:
                break
            screw_coord = parse_coord(config, prefix)
            screw_name = "screw at %.3f,%.3f" % screw_coord
            screw_name = config.get(prefix + "_name", screw_name)
            screws.append((screw_coord, screw_name))
            if config.get(prefix + "_fine_adjust", None) is not None:
                fine_coord = parse_coord(config, prefix + "_fine_adjust")
                fine_adjust.append((fine_coord, screw_name))
        if len(screws) < 3:
            raise config.error("bed_screws: Must have at least three screws")
        self.states = {'adjust': screws, 'fine': fine_adjust}
        self.speed = config.getfloat('speed', 50., above=0.)
        self.lift_speed = config.getfloat('probe_speed', 5., above=0.)
        self.horizontal_move_z = config.getfloat('horizontal_move_z', 5.)
        self.probe_z = config.getfloat('probe_height', 0.)
        # Register command
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command("BED_SCREWS_ADJUST",
                                    self.cmd_BED_SCREWS_ADJUST,
                                    desc=self.cmd_BED_SCREWS_ADJUST_help)
    def move(self, coord, speed):
        toolhead = self.printer.lookup_object('toolhead')
        curpos = toolhead.get_position()
        for i in range(len(coord)):
            if coord[i] is not None:
                curpos[i] = coord[i]
        toolhead.move(curpos, speed)
        self.gcode.reset_last_position()
    def move_to_screw(self, state, screw):
        # Move up, over, and then down
        self.move((None, None, self.horizontal_move_z), self.lift_speed)
        coord, name = self.states[state][screw]
        self.move((coord[0], coord[1], self.horizontal_move_z), self.speed)
        self.move((coord[0], coord[1], self.probe_z), self.lift_speed)
        # Update state
        self.state = state
        self.current_screw = screw
        # Register commands
        self.gcode.respond_info(
            "Adjust %s. Then run ACCEPT, ADJUSTED, or ABORT\n"
            "Use ADJUSTED if a significant screw adjustment is made" % (name,))
        self.gcode.register_command('ACCEPT', self.cmd_ACCEPT,
                                    desc=self.cmd_ACCEPT_help)
        self.gcode.register_command('ADJUSTED', self.cmd_ADJUSTED,
                                    desc=self.cmd_ADJUSTED_help)
        self.gcode.register_command('ABORT', self.cmd_ABORT,
                                    desc=self.cmd_ABORT_help)
    def unregister_commands(self):
        self.gcode.register_command('ACCEPT', None)
        self.gcode.register_command('ADJUSTED', None)
        self.gcode.register_command('ABORT', None)
    cmd_BED_SCREWS_ADJUST_help = "Tool to help adjust bed leveling screws"
    def cmd_BED_SCREWS_ADJUST(self, params):
        if self.state is not None:
            raise self.gcode.error(
                "Already in bed_screws helper; use ABORT to exit")
        self.adjust_again = False
        self.move((None, None, self.horizontal_move_z), self.speed)
        self.move_to_screw('adjust', 0)
    cmd_ACCEPT_help = "Accept bed screw position"
    def cmd_ACCEPT(self, params):
        self.unregister_commands()
        if self.current_screw + 1 < len(self.states[self.state]):
            # Continue with next screw
            self.move_to_screw(self.state, self.current_screw + 1)
            return
        if self.adjust_again:
            # Retry coarse adjustments
            self.adjust_again = False
            self.move_to_screw('adjust', 0)
            return
        if self.state == 'adjust' and self.states['fine']:
            # Perform fine screw adjustments
            self.move_to_screw('fine', 0)
            return
        # Done
        self.state = None
        self.move((None, None, self.horizontal_move_z), self.lift_speed)
        self.gcode.respond_info("Bed screws tool completed successfully")
    cmd_ADJUSTED_help = "Accept bed screw position after notable adjustment"
    def cmd_ADJUSTED(self, params):
        self.unregister_commands()
        self.adjust_again = True
        self.cmd_ACCEPT(params)
    cmd_ABORT_help = "Abort bed screws tool"
    def cmd_ABORT(self, params):
        self.unregister_commands()
        self.state = None

def load_config(config):
    return BedScrews(config)

#
# Helper script to adjust bed screws tilt using Z probe
#

def parse_coord(config, param):
    pair = config.get(param).strip().split(',', 1)
    try:
        return (float(pair[0]), float(pair[1]))
    except:
        raise config.error("%s:%s needs to be an x,y coordinate" % (
            config.get_name(), param))

class ScrewsTiltAdjust:
    def __init__(self, config):
        self.config = config
        self.printer = config.get_printer()
        self.screws = []
        # Read config
        for i in range(99):
            prefix = "screw%d" % (i + 1,)
            if config.get(prefix, None) is None:
                break
            screw_coord = parse_coord(config, prefix)
            screw_name = "screw at %.3f,%.3f" % screw_coord
            screw_name = config.get(prefix + "_name", screw_name)
            self.screws.append((screw_coord, screw_name))
        if len(self.screws) < 3:
            raise config.error("screws_tilt_adjust: Must have "
                               "at least three screws")
        self.threads = {'CW-M3': 0, 'CCW-M3': 1, 'CW-M4': 2, 'CCW-M4': 3,
                        'CW-M5': 4, 'CCW-M5': 5}
        self.thread = config.getchoice('screw_thread', self.threads,
                                       default='CW-M3')
        # Initialize ProbePointsHelper
        points = [coord for coord, name in self.screws]
        self.probe_helper = probe.ProbePointsHelper(self.config,
                                                    self.probe_finalize,
                                                    default_points=points)
        self.probe_helper.minimum_points(3)
        # Register command
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command("SCREWS_TILT_CALCULATE",
                                    self.cmd_SCREWS_TILT_CALCULATE,
                                    desc=self.cmd_SCREWS_TILT_CALCULATE_help)
    cmd_SCREWS_TILT_CALCULATE_help = "Tool to help adjust bed leveling " \
                                     "screws by calculating the number " \
                                     "of turns to level it."

    def cmd_SCREWS_TILT_CALCULATE(self, params):
        self.probe_helper.start_probe(params)

    def probe_finalize(self, offsets, positions):
        # Factors used for CW-M3, CCW-M3, CW-M4, CCW-M4, CW-M5 and CCW-M5
        threads_factor = {0: 0.5, 1: 0.5, 2: 0.7, 3: 0.7, 4: 0.8, 5: 0.8}
        # Process the read Z values and
        for i, screw in enumerate(self.screws):
            if i == 0:
                # First screw is the base position used for comparison
                z_base = positions[i][2]
                coord_base, name_base = screw
                # Show the results
                self.gcode.respond_info("%s (Base): X %.1f, Y %.1f, Z %.5f" %
                                        (name_base, coord_base[0],
                                         coord_base[1], z_base))
            else:
                # Calculate how knob must me adjusted for other positions
                z = positions[i][2]
                coord, name = screw
                diff = z_base - z
                if abs(diff) < 0.001:
                    adjust = 0
                else:
                    adjust = diff / threads_factor.get(self.thread, 0.5)
                if (self.thread & 1) == 1:
                    sign = "CW" if adjust < 0 else "CCW"
                else:
                    sign = "CCW" if adjust < 0 else "CW"
                full_turns = math.trunc(adjust)
                decimal_part = adjust - full_turns
                minutes = round(decimal_part * 60, 0)
                # Show the results
                self.gcode.respond_info("%s : X %.1f, Y %.1f, Z %.5f : "
                                        "Adjust -> %s %02d:%02d" %
                                        (name, coord[0], coord[1], z, sign,
                                         abs(full_turns), abs(minutes)))

def load_config(config):
    return ScrewsTiltAdjust(config)

#
# Bed tilt compensation
#

class BedTilt:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.event_register_handler("klippy:connect",
                                            self.handle_connect)
        self.x_adjust = config.getfloat('x_adjust', 0.)
        self.y_adjust = config.getfloat('y_adjust', 0.)
        self.z_adjust = config.getfloat('z_adjust', 0.)
        if config.get('points', None) is not None:
            BedTiltCalibrate(config, self)
        self.toolhead = None
        # Register move transform with g-code class
        gcode = self.printer.lookup_object('gcode')
        gcode.set_move_transform(self)
    def handle_connect(self):
        self.toolhead = self.printer.lookup_object('toolhead')
    def get_position(self):
        x, y, z, e = self.toolhead.get_position()
        return [x, y, z - x*self.x_adjust - y*self.y_adjust - self.z_adjust, e]
    def move(self, newpos, speed):
        x, y, z, e = newpos
        self.toolhead.move([x, y, z + x*self.x_adjust + y*self.y_adjust
                            + self.z_adjust, e], speed)
    def update_adjust(self, x_adjust, y_adjust, z_adjust):
        self.x_adjust = x_adjust
        self.y_adjust = y_adjust
        self.z_adjust = z_adjust
        configfile = self.printer.lookup_object('configfile')
        configfile.set('bed_tilt', 'x_adjust', "%.6f" % (x_adjust,))
        configfile.set('bed_tilt', 'y_adjust', "%.6f" % (y_adjust,))
        configfile.set('bed_tilt', 'z_adjust', "%.6f" % (z_adjust,))

# Helper script to calibrate the bed tilt
class BedTiltCalibrate:
    def __init__(self, config, bedtilt):
        self.printer = config.get_printer()
        self.bedtilt = bedtilt
        self.probe_helper = probe.ProbePointsHelper(config, self.probe_finalize)
        self.probe_helper.minimum_points(3)
        # Register BED_TILT_CALIBRATE command
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command(
            'BED_TILT_CALIBRATE', self.cmd_BED_TILT_CALIBRATE,
            desc=self.cmd_BED_TILT_CALIBRATE_help)
    cmd_BED_TILT_CALIBRATE_help = "Bed tilt calibration script"
    def cmd_BED_TILT_CALIBRATE(self, params):
        self.probe_helper.start_probe(params)
    def probe_finalize(self, offsets, positions):
        # Setup for coordinate descent analysis
        z_offset = offsets[2]
        logging.info("Calculating bed_tilt with: %s", positions)
        params = { 'x_adjust': self.bedtilt.x_adjust,
                   'y_adjust': self.bedtilt.y_adjust,
                   'z_adjust': z_offset }
        logging.info("Initial bed_tilt parameters: %s", params)
        # Perform coordinate descent
        def adjusted_height(pos, params):
            x, y, z = pos
            return (z - x*params['x_adjust'] - y*params['y_adjust']
                    - params['z_adjust'])
        def errorfunc(params):
            total_error = 0.
            for pos in positions:
                total_error += adjusted_height(pos, params)**2
            return total_error
        new_params = mathutil.coordinate_descent(
            params.keys(), params, errorfunc)
        # Update current bed_tilt calculations
        x_adjust = new_params['x_adjust']
        y_adjust = new_params['y_adjust']
        z_adjust = (new_params['z_adjust'] - z_offset
                    - x_adjust * offsets[0] - y_adjust * offsets[1])
        self.bedtilt.update_adjust(x_adjust, y_adjust, z_adjust)
        self.gcode.reset_last_position()
        # Log and report results
        logging.info("Calculated bed_tilt parameters: %s", new_params)
        for pos in positions:
            logging.info("orig: %s new: %s", adjusted_height(pos, params),
                         adjusted_height(pos, new_params))
        msg = "x_adjust: %.6f y_adjust: %.6f z_adjust: %.6f" % (
            x_adjust, y_adjust, z_adjust)
        self.printer.set_rollover_info("bed_tilt", "bed_tilt: %s" % (msg,))
        self.gcode.respond_info(
            "%s\nThe above parameters have been applied to the current\n"
            "session. The SAVE_CONFIG command will update the printer\n"
            "config file and restart the printer." % (msg,))

def load_config(config):
    return BedTilt(config)

#
# Mechanical bed tilt calibration with multiple Z steppers
#

class ZAdjustHelper:
    def __init__(self, config, z_count):
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.z_count = z_count
        self.z_steppers = []
        self.printer.event_register_handler("klippy:connect",
                                            self.handle_connect)
    def handle_connect(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        z_steppers = [s for s in kin.get_steppers() if s.is_active_axis('z')]
        if len(z_steppers) != self.z_count:
            raise self.printer.config_error(
                "%s z_positions needs exactly %d items" % (
                    self.name, len(z_steppers)))
        if len(z_steppers) < 2:
            raise self.printer.config_error(
                "%s requires multiple z steppers" % (self.name,))
        self.z_steppers = z_steppers
    def adjust_steppers(self, adjustments, speed):
        toolhead = self.printer.lookup_object('toolhead')
        gcode = self.printer.lookup_object('gcode')
        curpos = toolhead.get_position()
        # Report on movements
        stepstrs = ["%s = %.6f" % (s.get_name(), a)
                    for s, a in zip(self.z_steppers, adjustments)]
        msg = "Making the following Z adjustments:\n%s" % ("\n".join(stepstrs),)
        gcode.respond_info(msg)
        # Disable Z stepper movements
        toolhead.flush_step_generation()
        for s in self.z_steppers:
            s.set_trapq(None)
        # Move each z stepper (sorted from lowest to highest) until they match
        positions = [(-a, s) for a, s in zip(adjustments, self.z_steppers)]
        positions.sort()
        first_stepper_offset, first_stepper = positions[0]
        z_low = curpos[2] - first_stepper_offset
        for i in range(len(positions)-1):
            stepper_offset, stepper = positions[i]
            next_stepper_offset, next_stepper = positions[i+1]
            toolhead.flush_step_generation()
            stepper.set_trapq(toolhead.get_trapq())
            curpos[2] = z_low + next_stepper_offset
            try:
                toolhead.move(curpos, speed)
                toolhead.set_position(curpos)
            except:
                logging.exception("ZAdjustHelper adjust_steppers")
                toolhead.flush_step_generation()
                for s in self.z_steppers:
                    s.set_trapq(toolhead.get_trapq())
                raise
        # Z should now be level - do final cleanup
        last_stepper_offset, last_stepper = positions[-1]
        toolhead.flush_step_generation()
        last_stepper.set_trapq(toolhead.get_trapq())
        curpos[2] += first_stepper_offset
        toolhead.set_position(curpos)
        gcode.reset_last_position()

class RetryHelper:
    def __init__(self, config, error_msg_extra = ""):
        self.gcode = config.get_printer().lookup_object('gcode')
        self.default_max_retries = config.getint("retries", 0, minval=0)
        self.default_retry_tolerance = \
            config.getfloat("retry_tolerance", 0., above=0.)
        self.value_label = "Probed points range"
        self.error_msg_extra = error_msg_extra
    def start(self, params):
        self.max_retries = self.gcode.get_int('RETRIES', params,
            default=self.default_max_retries, minval=0, maxval=30)
        self.retry_tolerance = self.gcode.get_float('RETRY_TOLERANCE', params,
            default=self.default_retry_tolerance, minval=0, maxval=1.0)
        self.current_retry = 0
        self.previous = None
        self.increasing = 0
    def check_increase(self,error):
        if self.previous and error > self.previous + 0.0000001:
            self.increasing += 1
        elif self.increasing > 0:
            self.increasing -= 1
        self.previous = error
        return self.increasing > 1
    def check_retry(self,z_positions):
        if self.max_retries == 0:
            return
        error = max(z_positions) - min(z_positions)
        if self.check_increase(error):
            self.gcode.respond_error(
                "Retries aborting: %s is increasing. %s" % (
                    self.value_label, self.error_msg_extra))
            return
        self.gcode.respond_info(
            "Retries: %d/%d %s: %0.6f tolerance: %0.6f" % (
                self.current_retry, self.max_retries, self.value_label,
                error, self.retry_tolerance))
        if error <= self.retry_tolerance:
            return "done"
        self.current_retry += 1
        if self.current_retry > self.max_retries:
            self.gcode.respond_error("Too many retries")
            return
        return "retry"

class ZTilt:
    def __init__(self, config):
        self.printer = config.get_printer()
        z_positions = config.get('z_positions').split('\n')
        try:
            z_positions = [line.split(',', 1)
                           for line in z_positions if line.strip()]
            self.z_positions = [(float(zp[0].strip()), float(zp[1].strip()))
                                for zp in z_positions]
        except:
            raise config.error("Unable to parse z_positions in %s" % (
                config.get_name()))
        self.retry_helper = RetryHelper(config)
        self.probe_helper = probe.ProbePointsHelper(config, self.probe_finalize)
        self.probe_helper.minimum_points(2)
        self.z_helper = ZAdjustHelper(config, len(self.z_positions))
        # Register Z_TILT_ADJUST command
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('Z_TILT_ADJUST', self.cmd_Z_TILT_ADJUST,
                                    desc=self.cmd_Z_TILT_ADJUST_help)
    cmd_Z_TILT_ADJUST_help = "Adjust the Z tilt"
    def cmd_Z_TILT_ADJUST(self, params):
        self.retry_helper.start(params)
        self.probe_helper.start_probe(params)
    def probe_finalize(self, offsets, positions):
        # Setup for coordinate descent analysis
        z_offset = offsets[2]
        logging.info("Calculating bed tilt with: %s", positions)
        params = { 'x_adjust': 0., 'y_adjust': 0., 'z_adjust': z_offset }
        # Perform coordinate descent
        def adjusted_height(pos, params):
            x, y, z = pos
            return (z - x*params['x_adjust'] - y*params['y_adjust']
                    - params['z_adjust'])
        def errorfunc(params):
            total_error = 0.
            for pos in positions:
                total_error += adjusted_height(pos, params)**2
            return total_error
        new_params = mathutil.coordinate_descent(
            params.keys(), params, errorfunc)
        # Apply results
        speed = self.probe_helper.get_lift_speed()
        logging.info("Calculated bed tilt parameters: %s", new_params)
        x_adjust = new_params['x_adjust']
        y_adjust = new_params['y_adjust']
        z_adjust = (new_params['z_adjust'] - z_offset
                    - x_adjust * offsets[0] - y_adjust * offsets[1])
        adjustments = [x*x_adjust + y*y_adjust + z_adjust
                       for x, y in self.z_positions]
        self.z_helper.adjust_steppers(adjustments, speed)
        return self.retry_helper.check_retry([p[2] for p in positions])

def load_config(config):
    return ZTilt(config)

#
# Mesh Bed Leveling
#

PROFILE_VERSION = 1
PROFILE_OPTIONS = {
    'min_x': float, 'max_x': float, 'min_y': float, 'max_y': float,
    'x_count': int, 'y_count': int, 'mesh_x_pps': int, 'mesh_y_pps': int,
    'algo': str, 'tension': float
}

class BedMeshError(Exception):
    pass

# PEP 485 isclose()
def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

# Constrain value between min and max
def constrain(val, min_val, max_val):
    return min(max_val, max(min_val, val))

# Linear interpolation between two values
def lerp(t, v0, v1):
    return (1. - t) * v0 + t * v1

# retreive commma separated pair from config
def parse_pair(config, param, check=True, cast=float,
               minval=None, maxval=None):
    val = config.get(*param).strip().split(',', 1)
    pair = tuple(cast(p.strip()) for p in val)
    if check and len(pair) != 2:
        raise config.error(
            "bed_mesh: malformed '%s' value: %s"
            % (param[0], config.get(*param)))
    elif len(pair) == 1:
        pair = (pair[0], pair[0])
    if minval is not None:
        if pair[0] < minval or pair[1] < minval:
            raise config.error(
                "Option '%s' in section bed_mesh must have a minimum of %s"
                % (param[0], str(minval)))
    if maxval is not None:
        if pair[0] > maxval or pair[1] > maxval:
            raise config.error(
                "Option '%s' in section bed_mesh must have a maximum of %s"
                % (param[0], str(maxval)))
    return pair

class BedMesh:
    FADE_DISABLE = 0x7FFFFFFF
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.event_register_handler("klippy:ready",
                                            self.handle_ready)
        self.last_position = [0., 0., 0., 0.]
        self.bmc = BedMeshCalibrate(config, self)
        self.z_mesh = None
        self.toolhead = None
        self.horizontal_move_z = config.getfloat('horizontal_move_z', 5.)
        self.fade_start = config.getfloat('fade_start', 1.)
        self.fade_end = config.getfloat('fade_end', 0.)
        self.fade_dist = self.fade_end - self.fade_start
        if self.fade_dist <= 0.:
            self.fade_start = self.fade_end = self.FADE_DISABLE
        self.log_fade_complete = False
        self.base_fade_target = config.getfloat('fade_target', None)
        self.fade_target = 0.
        self.gcode = self.printer.lookup_object('gcode')
        self.splitter = MoveSplitter(config, self.gcode)
        self.gcode.register_command(
            'BED_MESH_OUTPUT', self.cmd_BED_MESH_OUTPUT,
            desc=self.cmd_BED_MESH_OUTPUT_help)
        self.gcode.register_command(
            'BED_MESH_MAP', self.cmd_BED_MESH_MAP,
            desc=self.cmd_BED_MESH_MAP_help)
        self.gcode.register_command(
            'BED_MESH_CLEAR', self.cmd_BED_MESH_CLEAR,
            desc=self.cmd_BED_MESH_CLEAR_help)
        self.gcode.set_move_transform(self)
    def handle_ready(self):
        self.toolhead = self.printer.lookup_object('toolhead')
        self.bmc.handle_ready()
    def set_mesh(self, mesh):
        if mesh is not None and self.fade_end != self.FADE_DISABLE:
            self.log_fade_complete = True
            if self.base_fade_target is None:
                self.fade_target = mesh.avg_z
            else:
                self.fade_target = self.base_fade_target
                min_z, max_z = mesh.get_z_range()
                if (not min_z <= self.fade_target <= max_z and
                        self.fade_target != 0.):
                    # fade target is non-zero, out of mesh range
                    err_target = self.fade_target
                    self.z_mesh = None
                    self.fade_target = 0.
                    raise self.gcode.error(
                        "bed_mesh: ERROR, fade_target lies outside of mesh z "
                        "range\nmin: %.4f, max: %.4f, fade_target: %.4f"
                        % (min_z, max_z, err_target))
            if self.fade_target:
                mesh.offset_mesh(self.fade_target)
            min_z, max_z = mesh.get_z_range()
            if self.fade_dist <= max(abs(min_z), abs(max_z)):
                self.z_mesh = None
                self.fade_target = 0.
                raise self.gcode.error(
                    "bed_mesh:  Mesh extends outside of the fade range, "
                    "please see the fade_start and fade_end options in"
                    "example-extras.cfg. fade distance: %.2f mesh min: %.4f"
                    "mesh max: %.4f" % (self.fade_dist, min_z, max_z))
        else:
            self.fade_target = 0.
        self.z_mesh = mesh
        self.splitter.initialize(mesh)
        # cache the current position before a transform takes place
        self.gcode.reset_last_position()
    def get_z_factor(self, z_pos):
        if z_pos >= self.fade_end:
            return 0.
        elif z_pos >= self.fade_start:
            return (self.fade_end - z_pos) / self.fade_dist
        else:
            return 1.
    def get_position(self):
        # Return last, non-transformed position
        if self.z_mesh is None:
            # No mesh calibrated, so send toolhead position
            self.last_position[:] = self.toolhead.get_position()
            self.last_position[2] -= self.fade_target
        else:
            # return current position minus the current z-adjustment
            x, y, z, e = self.toolhead.get_position()
            z_adj = self.z_mesh.calc_z(x, y)
            factor = 1.
            max_adj = z_adj + self.fade_target
            if min(z, (z - max_adj)) >= self.fade_end:
                # Fade out is complete, no factor
                factor = 0.
            elif max(z, (z - max_adj)) >= self.fade_start:
                # Likely in the process of fading out adjustment.
                # Because we don't yet know the gcode z position, use
                # algebra to calculate the factor from the toolhead pos
                factor = ((self.fade_end + self.fade_target - z) /
                          (self.fade_dist - z_adj))
                factor = constrain(factor, 0., 1.)
            final_z_adj = factor * z_adj + self.fade_target
            self.last_position[:] = [x, y, z - final_z_adj, e]
        return list(self.last_position)
    def move(self, newpos, speed):
        factor = self.get_z_factor(newpos[2])
        if self.z_mesh is None or not factor:
            # No mesh calibrated, or mesh leveling phased out.
            x, y, z, e = newpos
            if self.log_fade_complete:
                self.log_fade_complete = False
                logging.info(
                    "bed_mesh fade complete: Current Z: %.4f fade_target: %.4f "
                    % (z, self.fade_target))
            self.toolhead.move([x, y, z + self.fade_target, e], speed)
        else:
            self.splitter.build_move(self.last_position, newpos, factor)
            while not self.splitter.traverse_complete:
                split_move = self.splitter.split()
                if split_move:
                    self.toolhead.move(split_move, speed)
                else:
                    raise self.gcode.error(
                        "Mesh Leveling: Error splitting move ")
        self.last_position[:] = newpos
    cmd_BED_MESH_OUTPUT_help = "Retrieve interpolated grid of probed z-points"
    def cmd_BED_MESH_OUTPUT(self, params):
        if self.gcode.get_int('PGP', params, 0):
            # Print Generated Points instead of mesh
            self.bmc.print_generated_points(self.gcode.respond_info)
        elif self.z_mesh is None:
            self.gcode.respond_info("Bed has not been probed")
        else:
            self.bmc.print_probed_positions(self.gcode.respond_info)
            self.z_mesh.print_mesh(self.gcode.respond, self.horizontal_move_z)
    cmd_BED_MESH_MAP_help = "Serialize mesh and output to terminal"
    def cmd_BED_MESH_MAP(self, params):
        if self.z_mesh is not None:
            params = self.z_mesh.mesh_params
            outdict = {
                'mesh_min': (params['min_x'], params['min_y']),
                'mesh_max': (params['max_x'], params['max_y']),
                'z_positions': self.bmc.probed_matrix}
            self.gcode.respond(
                "mesh_map_output " + json.dumps(outdict))
        else:
            self.gcode.respond_info("Bed has not been probed")
    cmd_BED_MESH_CLEAR_help = "Clear the Mesh so no z-adjusment is made"
    def cmd_BED_MESH_CLEAR(self, params):
        self.set_mesh(None)


class BedMeshCalibrate:
    ALGOS = ['lagrange', 'bicubic']
    def __init__(self, config, bedmesh):
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.radius = self.origin = None
        self.relative_reference_index = config.getint(
            'relative_reference_index', None)
        self.bedmesh = bedmesh
        self.probed_matrix = None
        self.mesh_params = collections.OrderedDict()
        self.points = self._generate_points(config)
        self._init_mesh_params(config, self.points)
        self.probe_helper = probe.ProbePointsHelper(
            config, self.probe_finalize, self.points)
        self.probe_helper.minimum_points(3)
        self.probe_helper.use_xy_offsets(True)
        # setup persistent storage
        self.profiles = {}
        self.incompatible_profiles = []
        self._load_storage(config)
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command(
            'BED_MESH_CALIBRATE', self.cmd_BED_MESH_CALIBRATE,
            desc=self.cmd_BED_MESH_CALIBRATE_help)
        self.gcode.register_command(
            'BED_MESH_PROFILE', self.cmd_BED_MESH_PROFILE,
            desc=self.cmd_BED_MESH_PROFILE_help)
    def handle_ready(self):
        self.print_generated_points(logging.info)
        self._check_incompatible_profiles()
        if "default" in self.profiles:
            self.load_profile("default")
    def _generate_points(self, config):
        self.radius = config.getfloat('mesh_radius', None, above=0.)
        if self.radius is not None:
            self.origin = parse_pair(config, ('mesh_origin', "0, 0"))
            x_cnt = y_cnt = config.getint('round_probe_count', 5, minval=3)
            # round beds must have an odd number of points along each axis
            if not x_cnt & 1:
                raise config.error(
                    "bed_mesh: probe_count must be odd for round beds")
            # radius may have precision to .1mm
            self.radius = math.floor(self.radius * 10) / 10
            min_x = min_y = -self.radius
            max_x = max_y = self.radius
        else:
            # rectangular
            x_cnt, y_cnt = parse_pair(
                config, ('probe_count', '3'), check=False, cast=int, minval=3)
            min_x, min_y = parse_pair(config, ('mesh_min',))
            max_x, max_y = parse_pair(config, ('mesh_max',))
            if max_x <= min_x or max_y <= min_y:
                raise config.error('bed_mesh: invalid min/max points')

        self.mesh_params['x_count'] = x_cnt
        self.mesh_params['y_count'] = y_cnt
        x_dist = (max_x - min_x) / (x_cnt - 1)
        y_dist = (max_y - min_y) / (y_cnt - 1)
        # floor distances down to next hundredth
        x_dist = math.floor(x_dist * 100) / 100
        y_dist = math.floor(y_dist * 100) / 100
        if x_dist <= 1. or y_dist <= 1.:
            raise config.error("bed_mesh: min/max points too close together")

        if self.radius is not None:
            # round bed, min/max needs to be recalculated
            y_dist = x_dist
            new_r = (x_cnt / 2) * x_dist
            min_x = min_y = -new_r
            max_x = max_y = new_r
        else:
            # rectangular bed, only re-calc max_x
            max_x = min_x + x_dist * (x_cnt - 1)
        pos_y = min_y
        points = []
        for i in range(y_cnt):
            for j in range(x_cnt):
                if not i % 2:
                    # move in positive directon
                    pos_x = min_x + j * x_dist
                else:
                    # move in negative direction
                    pos_x = max_x - j * x_dist
                if self.radius is None:
                    # rectangular bed, append
                    points.append((pos_x, pos_y))
                else:
                    # round bed, check distance from origin
                    dist_from_origin = math.sqrt(pos_x*pos_x + pos_y*pos_y)
                    if dist_from_origin <= self.radius:
                        points.append(
                            (self.origin[0] + pos_x, self.origin[1] + pos_y))
            pos_y += y_dist
        return points
    def print_generated_points(self, print_func):
        x_offset = y_offset = 0.
        probe = self.printer.lookup_object('probe', None)
        if probe is not None:
            x_offset, y_offset = probe.get_offsets()[:2]
        print_func("bed_mesh: generated points\nIndex"
                   " |  Tool Adjusted  |   Probe")
        for i, (x, y) in enumerate(self.points):
            adj_pt = "(%.1f, %.1f)" % (x - x_offset, y - y_offset)
            mesh_pt = "(%.1f, %.1f)" % (x, y)
            print_func(
                "  %-4d| %-16s| %s" % (i, adj_pt, mesh_pt))
        if self.relative_reference_index is not None:
            rri = self.relative_reference_index
            print_func(
                "bed_mesh: relative_reference_index %d is (%.2f, %.2f)"
                % (rri, self.points[rri][0], self.points[rri][1]))
    def _init_mesh_params(self, config, points):
        pps = parse_pair(config, ('mesh_pps', '2'), check=False,
                         cast=int, minval=0)
        params = self.mesh_params
        params['mesh_x_pps'] = pps[0]
        params['mesh_y_pps'] = pps[1]
        params['algo'] = config.get('algorithm', 'lagrange').strip().lower()
        if params['algo'] not in self.ALGOS:
            raise config.error(
                "bed_mesh: Unknown algorithm <%s>"
                % (self.mesh_params['algo']))
        # Check the algorithm against the current configuration
        max_probe_cnt = max(params['x_count'], params['y_count'])
        min_probe_cnt = min(params['x_count'], params['y_count'])
        if max(pps[0], pps[1]) == 0:
            # Interpolation disabled
            self.mesh_params['algo'] = 'direct'
        elif params['algo'] == 'lagrange' and max_probe_cnt > 6:
            # Lagrange interpolation tends to oscillate when using more
            # than 6 samples
            raise config.error(
                "bed_mesh: cannot exceed a probe_count of 6 when using "
                "langrange interpolation. Configured Probe Count: %d, %d" %
                (self.mesh_params['x_count'], self.mesh_params['y_count']))
        elif params['algo'] == 'bicubic' and min_probe_cnt < 4:
            if max_probe_cnt > 6:
                raise config.error(
                    "bed_mesh: invalid probe_count option when using bicubic "
                    "interpolation.  Combination of 3 points on one axis with "
                    "more than 6 on another is not permitted. "
                    "Configured Probe Count: %d, %d" %
                    (self.mesh_params['x_count'], self.mesh_params['y_count']))
            else:
                logging.info(
                    "bed_mesh: bicubic interpolation with a probe_count of "
                    "less than 4 points detected.  Forcing lagrange "
                    "interpolation. Configured Probe Count: %d, %d" %
                    (self.mesh_params['x_count'], self.mesh_params['y_count']))
                params['algo'] = 'lagrange'
        params['tension'] = config.getfloat(
            'bicubic_tension', .2, minval=0., maxval=2.)
    def _check_incompatible_profiles(self):
        if self.incompatible_profiles:
            configfile = self.printer.lookup_object('configfile')
            for profile in self.incompatible_profiles:
                configfile.remove_section('bed_mesh ' + profile)
            self.gcode.respond_info(
                "The following incompatible profiles have been detected\n"
                "and are scheduled for removal:\n%s\n"
                "The SAVE_CONFIG command will update the printer config\n"
                "file and restart the printer" %
                (('\n').join(self.incompatible_profiles)))
    def _load_storage(self, config):
        stored_profs = config.get_prefix_sections(self.name)
        # Remove primary bed_mesh section, as it is not a stored profile
        stored_profs = [s for s in stored_profs
                        if s.get_name() != self.name]
        for profile in stored_profs:
            name = profile.get_name().split(' ', 1)[1]
            version = profile.getint('version', 0)
            if version != PROFILE_VERSION:
                logging.info(
                    "bed_mesh: Profile [%s] not compatible with this version\n"
                    "of bed_mesh.  Profile Version: %d Current Version: %d "
                    % (name, version, PROFILE_VERSION))
                self.incompatible_profiles.append(name)
                continue
            self.profiles[name] = {}
            z_values = profile.get('points').split('\n')
            self.profiles[name]['points'] = \
                [[float(pt.strip()) for pt in line.split(',')]
                    for line in z_values if line.strip()]
            self.profiles[name]['mesh_params'] = params = \
                collections.OrderedDict()
            for key, t in PROFILE_OPTIONS.iteritems():
                if t is int:
                    params[key] = profile.getint(key)
                elif t is float:
                    params[key] = profile.getfloat(key)
                elif t is str:
                    params[key] = profile.get(key)
    def save_profile(self, prof_name):
        if self.probed_matrix is None:
            self.gcode.respond_info(
                "Unable to save to profile [%s], the bed has not been probed"
                % (prof_name))
            return
        configfile = self.printer.lookup_object('configfile')
        cfg_name = self.name + " " + prof_name
        # set params
        z_values = ""
        for line in self.probed_matrix:
            z_values += "\n  "
            for p in line:
                z_values += "%.6f, " % p
            z_values = z_values[:-2]
        configfile.set(cfg_name, 'version', PROFILE_VERSION)
        configfile.set(cfg_name, 'points', z_values)
        for key, value in self.mesh_params.iteritems():
            configfile.set(cfg_name, key, value)
        # save copy in local storage
        self.profiles[prof_name] = profile = {}
        profile['points'] = list(self.probed_matrix)
        profile['mesh_params'] = collections.OrderedDict(self.mesh_params)
        self.gcode.respond_info(
            "Bed Mesh state has been saved to profile [%s]\n"
            "for the current session.  The SAVE_CONFIG command will\n"
            "update the printer config file and restart the printer."
            % (prof_name))
    def load_profile(self, prof_name):
        profile = self.profiles.get(prof_name, None)
        if profile is None:
            raise self.gcode.error(
                "bed_mesh: Unknown profile [%s]" % prof_name)
        self.probed_matrix = profile['points']
        zmesh = ZMesh(profile['mesh_params'])
        try:
            zmesh.build_mesh(self.probed_matrix)
        except BedMeshError as e:
            raise self.gcode.error(e.message)
        self.bedmesh.set_mesh(zmesh)
    def remove_profile(self, prof_name):
        if prof_name in self.profiles:
            configfile = self.printer.lookup_object('configfile')
            configfile.remove_section('bed_mesh ' + prof_name)
            del self.profiles[prof_name]
            self.gcode.respond_info(
                "Profile [%s] removed from storage for this session.\n"
                "The SAVE_CONFIG command will update the printer\n"
                "configuration and restart the printer" % (prof_name))
        else:
            self.gcode.respond_info(
                "No profile named [%s] to remove" % (prof_name))
    cmd_BED_MESH_PROFILE_help = "Bed Mesh Persistent Storage management"
    def cmd_BED_MESH_PROFILE(self, params):
        options = collections.OrderedDict({
            'LOAD': self.load_profile,
            'SAVE': self.save_profile,
            'REMOVE': self.remove_profile
        })
        for key in options:
            name = self.gcode.get_str(key, params, None)
            if name is not None:
                if name == "default" and key == 'SAVE':
                    self.gcode.respond_info(
                        "Profile 'default' is reserved, please chose"
                        " another profile name.")
                else:
                    options[key](name)
                return
        self.gcode.respond_info(
            "Invalid syntax '%s'" % (params['#original']))
    cmd_BED_MESH_CALIBRATE_help = "Perform Mesh Bed Leveling"
    def cmd_BED_MESH_CALIBRATE(self, params):
        self.build_map = False
        self.bedmesh.set_mesh(None)
        self.probe_helper.start_probe(params)
    def print_probed_positions(self, print_func):
        if self.probed_matrix is not None:
            msg = "Mesh Leveling Probed Z positions:\n"
            for line in self.probed_matrix:
                for x in line:
                    msg += " %f" % x
                msg += "\n"
            print_func(msg)
        else:
            print_func("bed_mesh: bed has not been probed")
    def probe_finalize(self, offsets, positions):
        x_offset, y_offset, z_offset = offsets
        params = self.mesh_params
        params['min_x'] = min(positions, key=lambda p: p[0])[0] + x_offset
        params['max_x'] = max(positions, key=lambda p: p[0])[0] + x_offset
        params['min_y'] = min(positions, key=lambda p: p[1])[1] + y_offset
        params['max_y'] = max(positions, key=lambda p: p[1])[1] + y_offset
        x_cnt = params['x_count']
        y_cnt = params['y_count']

        if self.relative_reference_index is not None:
            # zero out probe z offset and
            # set offset relative to reference index
            z_offset = positions[self.relative_reference_index][2]

        self.probed_matrix = []
        row = []
        prev_pos = positions[0]
        for pos in positions:
            if not isclose(pos[1], prev_pos[1], abs_tol=.1):
                # y has changed, append row and start new
                self.probed_matrix.append(row)
                row = []
            if pos[0] > prev_pos[0]:
                # probed in the positive direction
                row.append(pos[2] - z_offset)
            else:
                # probed in the negative direction
                row.insert(0, pos[2] - z_offset)
            prev_pos = pos
        # append last row
        self.probed_matrix.append(row)

        # make sure the y-axis is the correct length
        if len(self.probed_matrix) != y_cnt:
            raise self.gcode.error(
                ("bed_mesh: Invalid y-axis table length\n"
                 "Probed table length: %d Probed Table:\n%s") %
                (len(self.probed_matrix), str(self.probed_matrix)))

        if self.radius is not None:
            # round bed, extrapolate probed values to create a square mesh
            for row in self.probed_matrix:
                row_size = len(row)
                if not row_size & 1:
                    # an even number of points in a row shouldn't be possible
                    msg = "bed_mesh: incorrect number of points sampled on X\n"
                    msg += "Probed Table:\n"
                    msg += str(self.probed_matrix)
                    raise self.gcode.error(msg)
                buf_cnt = (x_cnt - row_size) / 2
                if buf_cnt == 0:
                    continue
                left_buffer = [row[0]] * buf_cnt
                right_buffer = [row[row_size-1]] * buf_cnt
                row[0:0] = left_buffer
                row.extend(right_buffer)

        #  make sure that the x-axis is the correct length
        for row in self.probed_matrix:
            if len(row) != x_cnt:
                raise self.gcode.error(
                    ("bed_mesh: invalid x-axis table length\n"
                        "Probed table length: %d Probed Table:\n%s") %
                    (len(self.probed_matrix), str(self.probed_matrix)))

        mesh = ZMesh(params)
        try:
            mesh.build_mesh(self.probed_matrix)
        except BedMeshError as e:
            raise self.gcode.error(e.message)
        self.bedmesh.set_mesh(mesh)
        self.gcode.respond_info("Mesh Bed Leveling Complete")
        self.save_profile("default")


class MoveSplitter:
    def __init__(self, config, gcode):
        self.split_delta_z = config.getfloat(
            'split_delta_z', .025, minval=0.01)
        self.move_check_distance = config.getfloat(
            'move_check_distance', 5., minval=3.)
        self.z_mesh = None
        self.gcode = gcode
    def initialize(self, mesh):
        self.z_mesh = mesh
    def build_move(self, prev_pos, next_pos, factor):
        self.prev_pos = tuple(prev_pos)
        self.next_pos = tuple(next_pos)
        self.current_pos = list(prev_pos)
        self.z_factor = factor
        self.z_offset = self._calc_z_offset(prev_pos)
        self.traverse_complete = False
        self.distance_checked = 0.
        axes_d = [self.next_pos[i] - self.prev_pos[i] for i in range(4)]
        self.total_move_length = math.sqrt(sum([d*d for d in axes_d[:3]]))
        self.axis_move = [not isclose(d, 0., abs_tol=1e-10) for d in axes_d]
    def _calc_z_offset(self, pos):
        z = self.z_mesh.calc_z(pos[0], pos[1])
        return self.z_factor * z + self.z_mesh.mesh_offset
    def _set_next_move(self, distance_from_prev):
        t = distance_from_prev / self.total_move_length
        if t > 1. or t < 0.:
            raise self.gcode.error(
                "bed_mesh: Slice distance is negative "
                "or greater than entire move length")
        for i in range(4):
            if self.axis_move[i]:
                self.current_pos[i] = lerp(
                    t, self.prev_pos[i], self.next_pos[i])
    def split(self):
        if not self.traverse_complete:
            if self.axis_move[0] or self.axis_move[1]:
                # X and/or Y axis move, traverse if necessary
                while self.distance_checked + self.move_check_distance \
                        < self.total_move_length:
                    self.distance_checked += self.move_check_distance
                    self._set_next_move(self.distance_checked)
                    next_z = self._calc_z_offset(self.current_pos)
                    if abs(next_z - self.z_offset) >= self.split_delta_z:
                        self.z_offset = next_z
                        return self.current_pos[0], self.current_pos[1], \
                            self.current_pos[2] + self.z_offset, \
                            self.current_pos[3]
            # end of move reached
            self.current_pos[:] = self.next_pos
            self.z_offset = self._calc_z_offset(self.current_pos)
            # Its okay to add Z-Offset to the final move, since it will not be
            # used again.
            self.current_pos[2] += self.z_offset
            self.traverse_complete = True
            return self.current_pos
        else:
            # Traverse complete
            return None


class ZMesh:
    def __init__(self, params):
        self.mesh_matrix = None
        self.mesh_params = params
        self.avg_z = 0.
        self.mesh_offset = 0.
        logging.debug('bed_mesh: probe/mesh parameters:')
        for key, value in self.mesh_params.iteritems():
            logging.debug("%s :  %s" % (key, value))
        self.mesh_x_min = params['min_x']
        self.mesh_x_max = params['max_x']
        self.mesh_y_min = params['min_y']
        self.mesh_y_max = params['max_y']
        logging.debug(
            "bed_mesh: Mesh Min: (%.2f,%.2f) Mesh Max: (%.2f,%.2f)"
            % (self.mesh_x_min, self.mesh_y_min,
               self.mesh_x_max, self.mesh_y_max))
        # Set the interpolation algorithm
        interpolation_algos = {
            'lagrange': self._sample_lagrange,
            'bicubic': self._sample_bicubic,
            'direct': self._sample_direct
        }
        self._sample = interpolation_algos.get(params['algo'])
        # Number of points to interpolate per segment
        mesh_x_pps = params['mesh_x_pps']
        mesh_y_pps = params['mesh_y_pps']
        px_cnt = params['x_count']
        py_cnt = params['y_count']
        self.mesh_x_count = (px_cnt - 1) * mesh_x_pps + px_cnt
        self.mesh_y_count = (py_cnt - 1) * mesh_y_pps + py_cnt
        self.x_mult = mesh_x_pps + 1
        self.y_mult = mesh_y_pps + 1
        logging.debug("bed_mesh: Mesh grid size - X:%d, Y:%d"
                      % (self.mesh_x_count, self.mesh_y_count))
        self.mesh_x_dist = (self.mesh_x_max - self.mesh_x_min) / \
                           (self.mesh_x_count - 1)
        self.mesh_y_dist = (self.mesh_y_max - self.mesh_y_min) / \
                           (self.mesh_y_count - 1)
    def print_mesh(self, print_func, move_z=None):
        if self.mesh_matrix is not None:
            msg = "Mesh X,Y: %d,%d\n" % (self.mesh_x_count, self.mesh_y_count)
            if move_z is not None:
                msg += "Search Height: %d\n" % (move_z)
            msg += "Mesh Average: %.2f\n" % (self.avg_z)
            rng = self.get_z_range()
            msg += "Mesh Range: min=%.4f max=%.4f\n" % (rng[0], rng[1])
            msg += "Interpolation Algorithm: %s\n" \
                   % (self.mesh_params['algo'])
            msg += "Measured points:\n"
            for y_line in range(self.mesh_y_count - 1, -1, -1):
                for z in self.mesh_matrix[y_line]:
                    msg += "  %f" % (z + self.mesh_offset)
                msg += "\n"
            print_func(msg)
        else:
            print_func("bed_mesh: Z Mesh not generated")
    def build_mesh(self, z_matrix):
        self._sample(z_matrix)
        self.avg_z = (sum([sum(x) for x in self.mesh_matrix]) /
                      sum([len(x) for x in self.mesh_matrix]))
        # Round average to the nearest 100th.  This
        # should produce an offset that is divisible by common
        # z step distances
        self.avg_z = round(self.avg_z, 2)
        self.print_mesh(logging.debug)
    def offset_mesh(self, offset):
        if self.mesh_matrix:
            self.mesh_offset = offset
            for y_line in self.mesh_matrix:
                for idx, z in enumerate(y_line):
                    y_line[idx] = z - self.mesh_offset
    def get_x_coordinate(self, index):
        return self.mesh_x_min + self.mesh_x_dist * index
    def get_y_coordinate(self, index):
        return self.mesh_y_min + self.mesh_y_dist * index
    def calc_z(self, x, y):
        if self.mesh_matrix is not None:
            tbl = self.mesh_matrix
            tx, xidx = self._get_linear_index(x, 0)
            ty, yidx = self._get_linear_index(y, 1)
            z0 = lerp(tx, tbl[yidx][xidx], tbl[yidx][xidx+1])
            z1 = lerp(tx, tbl[yidx+1][xidx], tbl[yidx+1][xidx+1])
            return lerp(ty, z0, z1)
        else:
            # No mesh table generated, no z-adjustment
            return 0.
    def get_z_range(self):
        if self.mesh_matrix is not None:
            mesh_min = min([min(x) for x in self.mesh_matrix])
            mesh_max = max([max(x) for x in self.mesh_matrix])
            return mesh_min, mesh_max
        else:
            return 0., 0.
    def _get_linear_index(self, coord, axis):
        if axis == 0:
            # X-axis
            mesh_min = self.mesh_x_min
            mesh_cnt = self.mesh_x_count
            mesh_dist = self.mesh_x_dist
            cfunc = self.get_x_coordinate
        else:
            # Y-axis
            mesh_min = self.mesh_y_min
            mesh_cnt = self.mesh_y_count
            mesh_dist = self.mesh_y_dist
            cfunc = self.get_y_coordinate
        t = 0.
        idx = int(math.floor((coord - mesh_min) / mesh_dist))
        idx = constrain(idx, 0, mesh_cnt - 2)
        t = (coord - cfunc(idx)) / mesh_dist
        return constrain(t, 0., 1.), idx
    def _sample_direct(self, z_matrix):
        self.mesh_matrix = z_matrix
    def _sample_lagrange(self, z_matrix):
        x_mult = self.x_mult
        y_mult = self.y_mult
        self.mesh_matrix = \
            [[0. if ((i % x_mult) or (j % y_mult))
             else z_matrix[j/y_mult][i/x_mult]
             for i in range(self.mesh_x_count)]
             for j in range(self.mesh_y_count)]
        xpts, ypts = self._get_lagrange_coords()
        # Interpolate X coordinates
        for i in range(self.mesh_y_count):
            # only interpolate X-rows that have probed coordinates
            if i % y_mult != 0:
                continue
            for j in range(self.mesh_x_count):
                if j % x_mult == 0:
                    continue
                x = self.get_x_coordinate(j)
                self.mesh_matrix[i][j] = self._calc_lagrange(xpts, x, i, 0)
        # Interpolate Y coordinates
        for i in range(self.mesh_x_count):
            for j in range(self.mesh_y_count):
                if j % y_mult == 0:
                    continue
                y = self.get_y_coordinate(j)
                self.mesh_matrix[j][i] = self._calc_lagrange(ypts, y, i, 1)
    def _get_lagrange_coords(self):
        xpts = []
        ypts = []
        for i in range(self.mesh_params['x_count']):
            xpts.append(self.get_x_coordinate(i * self.x_mult))
        for j in range(self.mesh_params['y_count']):
            ypts.append(self.get_y_coordinate(j * self.y_mult))
        return xpts, ypts
    def _calc_lagrange(self, lpts, c, vec, axis=0):
        pt_cnt = len(lpts)
        total = 0.
        for i in range(pt_cnt):
            n = 1.
            d = 1.
            for j in range(pt_cnt):
                if j == i:
                    continue
                n *= (c - lpts[j])
                d *= (lpts[i] - lpts[j])
            if axis == 0:
                # Calc X-Axis
                z = self.mesh_matrix[vec][i*self.x_mult]
            else:
                # Calc Y-Axis
                z = self.mesh_matrix[i*self.y_mult][vec]
            total += z * n / d
        return total
    def _sample_bicubic(self, z_matrix):
        # should work for any number of probe points above 3x3
        x_mult = self.x_mult
        y_mult = self.y_mult
        c = self.mesh_params['tension']
        self.mesh_matrix = \
            [[0. if ((i % x_mult) or (j % y_mult))
             else z_matrix[j/y_mult][i/x_mult]
             for i in range(self.mesh_x_count)]
             for j in range(self.mesh_y_count)]
        # Interpolate X values
        for y in range(self.mesh_y_count):
            if y % y_mult != 0:
                continue
            for x in range(self.mesh_x_count):
                if x % x_mult == 0:
                    continue
                pts = self._get_x_ctl_pts(x, y)
                self.mesh_matrix[y][x] = self._cardinal_spline(pts, c)
        # Interpolate Y values
        for x in range(self.mesh_x_count):
            for y in range(self.mesh_y_count):
                if y % y_mult == 0:
                    continue
                pts = self._get_y_ctl_pts(x, y)
                self.mesh_matrix[y][x] = self._cardinal_spline(pts, c)
    def _get_x_ctl_pts(self, x, y):
        # Fetch control points and t for a X value in the mesh
        x_mult = self.x_mult
        x_row = self.mesh_matrix[y]
        last_pt = self.mesh_x_count - 1 - x_mult
        if x < x_mult:
            p0 = p1 = x_row[0]
            p2 = x_row[x_mult]
            p3 = x_row[2*x_mult]
            t = x / float(x_mult)
        elif x > last_pt:
            p0 = x_row[last_pt - x_mult]
            p1 = x_row[last_pt]
            p2 = p3 = x_row[last_pt + x_mult]
            t = (x - last_pt) / float(x_mult)
        else:
            found = False
            for i in range(x_mult, last_pt, x_mult):
                if x > i and x < (i + x_mult):
                    p0 = x_row[i - x_mult]
                    p1 = x_row[i]
                    p2 = x_row[i + x_mult]
                    p3 = x_row[i + 2*x_mult]
                    t = (x - i) / float(x_mult)
                    found = True
                    break
            if not found:
                raise BedMeshError(
                    "bed_mesh: Error finding x control points")
        return p0, p1, p2, p3, t
    def _get_y_ctl_pts(self, x, y):
        # Fetch control points and t for a Y value in the mesh
        y_mult = self.y_mult
        last_pt = self.mesh_y_count - 1 - y_mult
        y_col = self.mesh_matrix
        if y < y_mult:
            p0 = p1 = y_col[0][x]
            p2 = y_col[y_mult][x]
            p3 = y_col[2*y_mult][x]
            t = y / float(y_mult)
        elif y > last_pt:
            p0 = y_col[last_pt - y_mult][x]
            p1 = y_col[last_pt][x]
            p2 = p3 = y_col[last_pt + y_mult][x]
            t = (y - last_pt) / float(y_mult)
        else:
            found = False
            for i in range(y_mult, last_pt, y_mult):
                if y > i and y < (i + y_mult):
                    p0 = y_col[i - y_mult][x]
                    p1 = y_col[i][x]
                    p2 = y_col[i + y_mult][x]
                    p3 = y_col[i + 2*y_mult][x]
                    t = (y - i) / float(y_mult)
                    found = True
                    break
            if not found:
                raise BedMeshError(
                    "bed_mesh: Error finding y control points")
        return p0, p1, p2, p3, t
    def _cardinal_spline(self, p, tension):
        t = p[4]
        t2 = t*t
        t3 = t2*t
        m1 = tension * (p[2] - p[0])
        m2 = tension * (p[3] - p[1])
        a = p[1] * (2*t3 - 3*t2 + 1)
        b = p[2] * (-2*t3 + 3*t2)
        c = m1 * (t3 - 2*t2 + t)
        d = m2 * (t3 - t2)
        return a + b + c + d


def load_config(config):
    return BedMesh(config)

#
# Helper script to adjust parameters based on Z level
#

CANCEL_Z_DELTA=2.0

class TuningTower:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.normal_transform = None
        self.last_position = [0., 0., 0., 0.]
        self.last_z = self.start = self.factor = self.band = 0.
        self.command_fmt = ""
        # Register command
        gcode = self.printer.lookup_object("gcode")
        gcode.register_command("TUNING_TOWER", self.cmd_TUNING_TOWER,
                               desc=self.cmd_TUNING_TOWER_help)
    cmd_TUNING_TOWER_help = "Tool to adjust a parameter at each Z height"
    def cmd_TUNING_TOWER(self, params):
        if self.normal_transform is not None:
            self.end_test()
        # Get parameters
        gcode = self.printer.lookup_object("gcode")
        command = gcode.get_str('COMMAND', params)
        parameter = gcode.get_str('PARAMETER', params)
        self.start = gcode.get_float('START', params, 0.)
        self.factor = gcode.get_float('FACTOR', params)
        self.band = gcode.get_float('BAND', params, 0., minval=0.)
        # Enable test mode
        if gcode.is_traditional_gcode(command):
            self.command_fmt = "%s %s%%.9f" % (command, parameter)
        else:
            self.command_fmt = "%s %s=%%.9f" % (command, parameter)
        self.normal_transform = gcode.set_move_transform(self, force=True)
        self.last_z = -99999999.9
        gcode.reset_last_position()
        self.get_position()
        gcode.respond_info("Starting tuning test (start=%.6f factor=%.6f)"
                           % (self.start, self.factor))
    def get_position(self):
        pos = self.normal_transform.get_position()
        self.last_position = list(pos)
        return pos
    def calc_value(self, z):
        if self.band:
            z = (math.floor(z / self.band) + .5) * self.band
        return self.start + z * self.factor
    def move(self, newpos, speed):
        normal_transform = self.normal_transform
        if (newpos[3] > self.last_position[3] and newpos[2] != self.last_z
            and newpos[:3] != self.last_position[:3]):
            # Extrusion move at new z height
            z = newpos[2]
            if z < self.last_z - CANCEL_Z_DELTA:
                # Extrude at a lower z height - probably start of new print
                self.end_test()
            else:
                # Process update
                oldval = self.calc_value(self.last_z)
                newval = self.calc_value(z)
                self.last_z = z
                if newval != oldval:
                    gcode = self.printer.lookup_object("gcode")
                    gcode.run_script_from_command(self.command_fmt % (newval,))
        # Forward move to actual handler
        self.last_position[:] = newpos
        normal_transform.move(newpos, speed)
    def end_test(self):
        gcode = self.printer.lookup_object("gcode")
        gcode.respond_info("Ending tuning test mode")
        gcode.set_move_transform(self.normal_transform, force=True)
        self.normal_transform = None

def load_config(config):
    return TuningTower(config)

#
# Printer Skew Correction
#
# This implementation is a port of Marlin's skew correction as
# implemented in planner.h, Copyright (C) Marlin Firmware
#
# https://github.com/MarlinFirmware/Marlin/tree/1.1.x/Marlin

def calc_skew_factor(ac, bd, ad):
    side = math.sqrt(2*ac*ac + 2*bd*bd - 4*ad*ad) / 2.
    return math.tan(math.pi/2 - math.acos(
        (ac*ac - side*side - ad*ad) / (2*side*ad)))

class PrinterSkew:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.gcode = self.printer.lookup_object('gcode')
        self.toolhead = None
        self.xy_factor = 0.
        self.xz_factor = 0.
        self.yz_factor = 0.
        self.skew_profiles = {}
        self._load_storage(config)
        self.printer.event_register_handler("klippy:ready",
                                            self._handle_ready)
        self.next_transform = None
        self.gcode.register_command(
            'GET_CURRENT_SKEW', self.cmd_GET_CURRENT_SKEW,
            desc=self.cmd_GET_CURRENT_SKEW_help)
        self.gcode.register_command(
            'CALC_MEASURED_SKEW', self.cmd_CALC_MEASURED_SKEW,
            desc=self.cmd_CALC_MEASURED_SKEW_help)
        self.gcode.register_command(
            'SET_SKEW', self.cmd_SET_SKEW,
            desc=self.cmd_SET_SKEW_help)
        self.gcode.register_command(
            'SKEW_PROFILE', self.cmd_SKEW_PROFILE,
            desc=self.cmd_SKEW_PROFILE_help)
    def _handle_ready(self):
        self.next_transform = self.gcode.set_move_transform(self, force=True)
    def _load_storage(self, config):
        stored_profs = config.get_prefix_sections(self.name)
        # Remove primary skew_correction section, as it is not a stored profile
        stored_profs = [s for s in stored_profs
                        if s.get_name() != self.name]
        for profile in stored_profs:
            name = profile.get_name().split(' ', 1)[1]
            self.skew_profiles[name] = {
                'xy_skew': profile.getfloat("xy_skew"),
                'xz_skew': profile.getfloat("xz_skew"),
                'yz_skew': profile.getfloat("yz_skew"),
            }
    def calc_skew(self, pos):
        skewed_x = pos[0] - pos[1] * self.xy_factor \
            - pos[2] * (self.xz_factor - (self.xy_factor * self.yz_factor))
        skewed_y = pos[1] - pos[2] * self.yz_factor
        return [skewed_x, skewed_y, pos[2], pos[3]]
    def calc_unskew(self, pos):
        skewed_x = pos[0] + pos[1] * self.xy_factor \
            + pos[2] * self.xz_factor
        skewed_y = pos[1] + pos[2] * self.yz_factor
        return [skewed_x, skewed_y, pos[2], pos[3]]
    def get_position(self):
        return self.calc_unskew(self.next_transform.get_position())
    def move(self, newpos, speed):
        corrected_pos = self.calc_skew(newpos)
        self.next_transform.move(corrected_pos, speed)
    cmd_GET_CURRENT_SKEW_help = "Report current printer skew"
    def cmd_GET_CURRENT_SKEW(self, params):
        out = "Current Printer Skew:"
        planes = ["XY", "XZ", "YZ"]
        factors = [self.xy_factor, self.xz_factor, self.yz_factor]
        for plane, fac in zip(planes, factors):
            out += '\n' + plane
            out += " Skew: %.6f radians, %.2f degrees" % (
                fac, math.degrees(fac))
        self.gcode.respond_info(out)
    cmd_CALC_MEASURED_SKEW_help = "Calculate skew from measured print"
    def cmd_CALC_MEASURED_SKEW(self, params):
        ac = self.gcode.get_float("AC", params, above=0.)
        bd = self.gcode.get_float("BD", params, above=0.)
        ad = self.gcode.get_float("AD", params, above=0.)
        factor = calc_skew_factor(ac, bd, ad)
        self.gcode.respond_info(
            "Calculated Skew: %.6f radians, %.2f degrees" %
            (factor, math.degrees(factor)))
    cmd_SET_SKEW_help = "Set skew based on lengths of measured object"
    def cmd_SET_SKEW(self, params):
        if self.gcode.get_int("CLEAR", params, 0):
            self.xy_factor = 0.
            self.xz_factor = 0.
            self.yz_factor = 0.
            return
        planes = ["XY", "XZ", "YZ"]
        for plane in planes:
            lengths = self.gcode.get_str(plane, params, None)
            if lengths is not None:
                try:
                    lengths = lengths.strip().split(",", 2)
                    lengths = [float(l.strip()) for l in lengths]
                    if len(lengths) != 3:
                        raise Exception
                except Exception:
                    raise self.gcode.error(
                        "skew_correction: improperly formatted entry for "
                        "plane [%s]\n%s" % (plane, params['#original']))
                factor = plane.lower() + '_factor'
                setattr(self, factor, calc_skew_factor(*lengths))
    cmd_SKEW_PROFILE_help = "Profile management for skew_correction"
    def cmd_SKEW_PROFILE(self, params):
        if 'LOAD' in params:
            name = self.gcode.get_str('LOAD', params)
            if name not in self.skew_profiles:
                self.gcode.respond_info(
                    "skew_correction:  Load failed, unknown profile [%s]" %
                    (name))
                return
            self.xy_factor = self.skew_profiles[name]['xy_skew']
            self.xz_factor = self.skew_profiles[name]['xz_skew']
            self.yz_factor = self.skew_profiles[name]['yz_skew']
        elif 'SAVE' in params:
            name = self.gcode.get_str('SAVE', params)
            configfile = self.printer.lookup_object('configfile')
            cfg_name = self.name + " " + name
            configfile.set(cfg_name, 'xy_skew', self.xy_factor)
            configfile.set(cfg_name, 'xz_skew', self.xz_factor)
            configfile.set(cfg_name, 'yz_skew', self.yz_factor)
            # Copy to local storage
            self.skew_profiles[name] = {
                'xy_skew': self.xy_factor,
                'xz_skew': self.xz_factor,
                'yz_skew': self.yz_factor
            }
            self.gcode.respond_info(
                "Skew Correction state has been saved to profile [%s]\n"
                "for the current session.  The SAVE_CONFIG command will\n"
                "update the printer config file and restart the printer."
                % (name))
        elif 'REMOVE' in params:
            name = self.gcode.get_str('REMOVE', params)
            if name in self.skew_profiles:
                configfile = self.printer.lookup_object('configfile')
                configfile.remove_section('skew_correction ' + name)
                del self.skew_profiles[name]
                self.gcode.respond_info(
                    "Profile [%s] removed from storage for this session.\n"
                    "The SAVE_CONFIG command will update the printer\n"
                    "configuration and restart the printer" % (name))
            else:
                self.gcode.respond_info(
                    "skew_correction: No profile named [%s] to remove" %
                    (name))


def load_config(config):
    return PrinterSkew(config)
