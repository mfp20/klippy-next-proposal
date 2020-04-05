# Temperature Control (Tcontrol) composite part.
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from messaging import msg
from messaging import Kerr as error
import composite

attrs = ("type", "control", "min_temp", "max_temp")
KELVIN_TO_CELSIUS = -273.15
MAX_HEAT_TIME = 5.0
AMBIENT_TEMP = 25.
PID_PARAM_BASE = 255.

class Dummy(composite.Object):
    def __init__(self, hal, node):
        logging.warning("tcontrol.Dummy:__init__():%s", node.name)
        composite.Object(hal, node)
    def init(self, sensor = None, heater = None, cooler = None):
        pass
    def register(self):
        pass

class Object(composite.Object):
    def init(self):
        self.thermometer = {}
        self.hygrometer = {}
        self.barometer = {}
        self.heater = {}
        self.cooler = {}
        for t in self.children_bytype("sensor", "thermometer"):
            pass
        for h in self.children_bytype("sensor", "hygrometer"):
            pass
        for b in self.children_bytype("sensor", "barometer"):
            pass
        for h in self.children_bygroup("heater"):
            pass
        for c in self.children_bygroup("cooler"):
            pass
        self.ready = True
    def register(self):
        pass
    def register_sensor(self):
        self.sensor = sensor
        self.min_temp = self.hal.getfloat(self.node, 'min_temp', minval=KELVIN_TO_CELSIUS)
        self.max_temp = self.hal.getfloat(self.node, 'max_temp', above=self.min_temp)
        self.sensor.setup_minmax(self.min_temp, self.max_temp)
        self.sensor.setup_callback(self.temperature_callback)
        self.pwm_delay = self.sensor.get_report_time_delta()
        # Setup temperature checks
        self.min_extrude_temp = self.hal.getfloat(self.node, 'min_extrude_temp', 170., minval=self.min_temp, maxval=self.max_temp)
        is_fileoutput = (self.printer.get_start_args().get('debugoutput') is not None)
        self.can_extrude = self.min_extrude_temp <= 0. or is_fileoutput
        self.max_power = self.hal.getfloat(self.node, 'max_power', 1., above=0., maxval=1.)
        self.smooth_time = self.hal.getfloat(self.node, 'smooth_time', 2., above=0.)
        self.inv_smooth_time = 1. / self.smooth_time
        self.lock = threading.Lock()
        self.last_temp = self.smoothed_temp = self.target_temp = 0.
        self.last_temp_time = 0.
        # pwm caching
        self.next_pwm_time = 0.
        self.last_pwm_value = 0.
    def register_heater(self):
        # governor
        algos = {'watermark': ControlBangBang, 'pid': ControlPID}
        algo = self.hal.getchoice(self.node, 'control', algos)
        self.control = algo(self, config)
        # pin
        heater_pin = self.hal.get(self.node, 'heater_pin')
        ppins = self.hal.get_controller()
        if algo is ControlBangBang and self.max_power == 1.:
            self.mcu_pwm = ppins.setup_pin('digital_out', heater_pin)
        else:
            self.mcu_pwm = ppins.setup_pin('pwm', heater_pin)
            pwm_cycle_time = self.hal.getfloat(self.node, 'pwm_cycle_time', 0.100, above=0., maxval=self.pwm_delay)
            self.mcu_pwm.setup_cycle_time(pwm_cycle_time)
        self.mcu_pwm.setup_max_duration(MAX_HEAT_TIME)
        # Load additional modules
        #self.printer.try_load_module(config, "verify_heater %s" % (self.name,))
        #self.printer.try_load_module(config, "pid_calibrate")
    def register_cooler(self):
        pass
    def set_pwm(self, read_time, value):
        if self.target_temp <= 0.:
            value = 0.
        if ((read_time < self.next_pwm_time or not self.last_pwm_value)
            and abs(value - self.last_pwm_value) < 0.05):
            # No significant change in value - can suppress update
            return
        pwm_time = read_time + self.pwm_delay
        self.next_pwm_time = pwm_time + 0.75 * MAX_HEAT_TIME
        self.last_pwm_value = value
        logging.debug("%s: pwm=%.3f@%.3f (from %.3f@%.3f [%.3f])",
                      self.name, value, pwm_time,
                      self.last_temp, self.last_temp_time, self.target_temp)
        self.mcu_pwm.set_pwm(pwm_time, value)
    def temperature_callback(self, read_time, temp):
        with self.lock:
            time_diff = read_time - self.last_temp_time
            self.last_temp = temp
            self.last_temp_time = read_time
            self.control.temperature_update(read_time, temp, self.target_temp)
            temp_diff = temp - self.smoothed_temp
            adj_time = min(time_diff * self.inv_smooth_time, 1.)
            self.smoothed_temp += temp_diff * adj_time
            self.can_extrude = (self.smoothed_temp >= self.min_extrude_temp)
        #logging.debug("temp: %.3f %f = %f", read_time, temp)
    # External commands
    def get_pwm_delay(self):
        return self.pwm_delay
    def get_max_power(self):
        return self.max_power
    def get_smooth_time(self):
        return self.smooth_time
    def set_temp(self, degrees):
        if degrees and (degrees < self.min_temp or degrees > self.max_temp):
            raise self.printer.command_error(
                "Requested temperature (%.1f) out of range (%.1f:%.1f)"
                % (degrees, self.min_temp, self.max_temp))
        with self.lock:
            self.target_temp = degrees
    def get_temp(self, eventtime):
        print_time = self.mcu_pwm.get_mcu().estimated_print_time(eventtime) - 5.
        with self.lock:
            if self.last_temp_time < print_time:
                return 0., self.target_temp
            return self.smoothed_temp, self.target_temp
    def check_busy(self, eventtime):
        with self.lock:
            return self.control.check_busy(
                eventtime, self.smoothed_temp, self.target_temp)
    def set_control(self, control):
        with self.lock:
            old_control = self.control
            self.control = control
            self.target_temp = 0.
        return old_control
    def alter_target(self, target_temp):
        if target_temp:
            target_temp = max(self.min_temp, min(self.max_temp, target_temp))
        self.target_temp = target_temp
    def stats(self, eventtime):
        with self.lock:
            target_temp = self.target_temp
            last_temp = self.last_temp
            last_pwm_value = self.last_pwm_value
        is_active = target_temp or last_temp > 50.
        return is_active, '%s: target=%.0f temp=%.1f pwm=%.3f' % (
            self.name, target_temp, last_temp, last_pwm_value)
    def get_status(self, eventtime):
        with self.lock:
            target_temp = self.target_temp
            smoothed_temp = self.smoothed_temp
        return {'temperature': smoothed_temp, 'target': target_temp}

def load_node_object(hal, node):
    config_ok = True
    for a in node.module.attrs:
        if a not in node.attrs:
            config_ok = False
            break
    if config_ok:
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal, node)

