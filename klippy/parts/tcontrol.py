# Temperature Control (Tcontrol) composite part.
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, threading, copy, math
from messaging import msg
from messaging import Kerr as error
import composite, controller, governor

ATTRS = ("type", "min", "max", "control")

class Dummy(composite.Object):
    def __init__(self, hal, node):
        logging.warning("tcontrol.Dummy:__init__():%s", node.name)
        composite.Object(hal, node)
    def init():
        if self.ready:
            return
        self.ready = True
    def register(self):
        pass

KELVIN_TO_CELSIUS = -273.15
ALUMINIUM_OPERATING = 400.00
MAX_HEAT_TIME = 5.0
PID_PARAM_BASE = 255.
OBJ = {"pin": None, "gov": None, "min": None, "target": None, "max": None, "current": None, "smoothed": None, "last": None}
class Object(composite.Object):
    def init(self):
        if self.ready:
            return
        # capabilities
        self.capas = {"temperature":False, "humidity":False, "pressure":False, "heat":False, "cool":False}
        self.min_temp = KELVIN_TO_CELSIUS
        self.max_temp = ALUMINIUM_OPERATING
        # sensors-actuators
        self.thermometer = {}
        self.hygrometer = {}
        self.barometer = {}
        self.heater = {}
        self.cooler = {}
        # timing
        self.lock = threading.Lock()
        self.smooth_time = self.node.attr_get_float("smooth_time", default=2., above=0.)
        self.inv_smooth_time = 1. / self.smooth_time
        self.last_time = 0.
        # pwm caching
        self.pwm_delay = 0.
        self.next_pwm_time = 0.
        self.last_pwm_value = 0.
        # register all sensors
        for t in self.children_bytype("sensor", "thermometer"):
            self.register_thermometer(t)
        for h in self.children_bytype("sensor", "hygrometer"):
            self.register_hygrometer(h)
        for b in self.children_bytype("sensor", "barometer"):
            self.register_barometer(b)
        for h in self.children_bygroup("heater"):
            self.register_heater(h)
        for c in self.children_bygroup("cooler"):
            self.register_cooler(c)
        self.ready = True
    def register(self):
        #self.gcode.register_mux_command("SET_TEMPERATURE", "TCONTROL", self.node.name, self.cmd_SET_TEMPERATURE, desc=self.cmd_SET_TEMPERATURE_help)
        pass
    # helper to setup governors
    def _mkgov(self, node):
        max_power = node.attr_get_float("max", default=1., above=0., maxval=1.)
        gov = self.node.attr_get_choice("control", {"watermark": "watermark", "pid": "pid"})
        if gov == "watermark":
            max_delta = self.node.attr_get_float("delta_max", default=2.0, above=0.)
            return governor.BangBang(max_delta, max_power)
        else:
            kp = self.node.attr_get_float("pid_kp") / PID_PARAM_BASE
            ki = self.node.attr_get_float("pid_ki") / PID_PARAM_BASE
            kd = self.node.attr_get_float("pid_kd") / PID_PARAM_BASE
            imax = self.node.attr_get_float("pid_integral_max", default=max_power, minval=0.)
            if "sensor ambient" in self.thermometer:
                startvalue =  self.node.attr_get_float("temp_ambient", default=self.thermometer["sensor ambient"]["current"], above=4., maxval=100.)
            else:
                startvalue = self.node.attr_get_float("temp_ambient", default=25., above=4., maxval=100.)
            return governor.PID(kp, ki, kd, max_power, self.smooth_time, imax, startvalue)
    def register_thermometer(self, node):
        # set defaults
        self.thermometer[node.name] = OBJ.copy()
        self.thermometer[node.name]["pin"] = node.object
        self.thermometer[node.name]["gov"] = None
        self.thermometer[node.name]["min"] = self.node.attr_get_float("min", default=KELVIN_TO_CELSIUS, minval=KELVIN_TO_CELSIUS)
        self.thermometer[node.name]["target"] = 0.
        self.thermometer[node.name]["max"] = self.node.attr_get_float("max", default=ALUMINIUM_OPERATING, maxval=ALUMINIUM_OPERATING, above=self.thermometer[node.name]["min"])
        self.thermometer[node.name]["current"] = 0.
        self.thermometer[node.name]["smoothed"] = 0.
        # setup sensor
        node.object.setup_minmax(self.thermometer[node.name]["min"],  self.thermometer[node.name]["max"])
        node.object.setup_cb(self.temperature_callback)
        self.set_pwm_delay(self.thermometer[node.name]["pin"].get_report_time_delta())
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.attr_get_float("max", default=ALUMINIUM_OPERATING, above=self.thermometer[node.name]["min"]))
        self.capas["temperature"] = True
    def register_hygrometer(self, node):
        # set defaults
        self.hygrometer[node.name] = OBJ.copy()
        self.hygrometer[node.name]["pin"] = node.object
        self.hygrometer[node.name]["gov"] = None
        self.hygrometer[node.name]["min"] = self.node.attr_get_float("hygro_min", minval=0)
        self.hygrometer[node.name]["target"] = 0.
        self.hygrometer[node.name]["max"] = self.node.attr_get_float("hygro_max", maxval=100, above=self.hygrometer[node.name]["min"])
        self.hygrometer[node.name]["current"] = 0.
        self.hygrometer[node.name]["smoothed"] = 0.
        #
        # TODO
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.attr_get_float("temp_max", default=ALUMINIUM_OPERATING, above=self.hygrometer[node.name]["min"]))
        self.capas["humidity"] = True
    def register_barometer(self, node):
        # set defaults
        self.barometer[node.name] = OBJ.copy()
        self.barometer[node.name]["pin"] = node.object
        self.barometer[node.name]["gov"] = None
        self.barometer[node.name]["min"] = node.attr_get_float("baro_min", minval=0)
        self.barometer[node.name]["target"] = 0.
        self.barometer[node.name]["max"] = node.attr_get_float("baro_max", maxval=50000, above=self.barometer[node.name]["min"]) # TODO mbar, pa, ... ?
        self.barometer[node.name]["current"] = 0.
        self.barometer[node.name]["smoothed"] = 0.
        #
        # TODO
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.attr_get_float("temp_max", default=ALUMINIUM_OPERATING, above=self.barometer[node.name]["min"]))
        self.capas["pressure"] = True
    def register_heater(self, node):
        if isinstance(node.object.pin, controller.MCU_pwm):
            pwm_cycle_time = self.node.attr_get_float("pwm_cycle_time", default=-1.100, above=0., maxval=self.pwm_delay)
            node.object.pin.setup_cycle_time(pwm_cycle_time)
        node.object.pin.setup_max_duration(MAX_HEAT_TIME)
        # set defaults
        self.heater[node.name] = OBJ.copy()
        self.heater[node.name]["pin"] = node.object
        self.heater[node.name]["gov"] = self._mkgov(node)
        self.heater[node.name]["min"] = node.attr_get_float("min", default=0., minval=0.)
        self.heater[node.name]["target"] = 0.
        self.heater[node.name]["max"] = node.attr_get_float("max", default=1., maxval=1.0, above=self.heater[node.name]["min"])
        self.heater[node.name]["current"] = 0.
        self.heater[node.name]["smoothed"] = 0.
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.attr_get_float("temp_max", default=ALUMINIUM_OPERATING, above=self.heater[node.name]["min"]))
        self.capas["heat"] = True
    def register_cooler(self, node):
        # set defaults
        self.cooler[node.name] = OBJ.copy()
        self.cooler[node.name]["pin"] = node.object
        self.cooler[node.name]["gov"] = self._mkgov(node)
        self.cooler[node.name]["min"] = node.attr_get_float("min", default=0., minval=0.)
        self.cooler[node.name]["target"] = 0.
        self.cooler[node.name]["max"] = node.attr_get_float("max", default=1., maxval=1.0, above=self.cooler[node.name]["min"])
        self.cooler[node.name]["current"] = 0.
        self.cooler[node.name]["smoothed"] = 0.
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.attr_get_float("temp_max", default=ALUMINIUM_OPERATING, above=self.cooler[node.name]["min"]))
        self.capas["cool"] = True
    # sensors values
    def _get_value(self, eventtime, sensor):
            print_time = sensor["pin"].get_mcu().estimated_print_time(eventtime) - 5.
            with self.lock:
                if self.last_time < print_time:
                    return 0., sensor["target"]
                return sensor["smoothed"], sensor["target"]
    def _get_avg(self, sensors, value):
        summed = 0
        for s in sensors:
            summed = summed + sensors[s][value]
        return summed/len(sensors)
    def get_temp(self, eventtime, sensor = None):
        if self.caps["temperature"]:
            if not sensor:
                sensor = next(iter(self.thermometer))
            return _get_value(eventtime, sensor)
        else:
            raise error("Requested temperature sensor reading but '%s' doesn't have any temperature sensor!!!", self.node.name)
    def get_hygro(self, eventtime, sensor = None):
        if self.caps["humidity"]:
            if not sensor:
                sensor = next(iter(self.hygrometer))
            return _get_value(eventtime, sensor)
        else:
            raise error("Requested humidity sensor reading but '%s' doesn't have any humidity sensor!!!", self.node.name)
    def get_pressure(self, eventtime, sensor = None):
        if self.caps["pressure"]:
            if not sensor:
                sensor = next(iter(self.barometer))
            return _get_value(eventtime, sensor)
        else:
            raise error("Requested pressure sensor reading but '%s' doesn't have any pressure sensor!!!", self.node.name)
    # calc dew point
    def calc_dew_point(self):
        # celsius
        temp = next(iter(self.thermometer))["smoothed"]
        # relative humidity
        hygro = next(iter(self.hygrometer))["smoothed"]
        if temp and hygro:
            if hygro > 50:
                # simple formula accurate for humidity > 50%
                # Lawrence, Mark G., 2005: The relationship between relative humidity and the dewpoint temperature in moist air: A simple conversion and applications. Bull. Amer. Meteor. Soc., 86, 225-233
                return (temp-((100-hygro)/5))
            else:
                # http://en.wikipedia.org/wiki/Dew_point
                a = 17.271;
                b = 237.7;
                temp2 = (a * temp) / (b + temp) + math.log(hygro*0.01);
                return ((b * temp2) / (a - temp2))
        else:
            raise error("Requested the dew temperature but '%s' doesn't have the needed sensors!!!", self.node.name)
    # set heaters pwm output value
    def set_heaters(self, pwm_time, value):
        for h in self.heater:
            h.pin.set_pwm(pwm_time, value)
    # set coolers pwm output value
    def set_coolers(self, pwm_time, value):
        for c in self.cooler:
            c.pin.set_pwm(pwm_time, value)
    # set both pwm output value (coolers are inverse of heaters)
    def set_output(self, pwm_time, value):
        self.set_heaters(self, pwm_time, value)
        self.set_coolers(self, pwm_time, 1/value)
    # adjust temp by modifying pwm output
    def adj_temp(self, read_time, value, sensor = None):
        if not sensor:
            sensor = next(iter(self.thermometer))
        # off
        if sensor["target"] <= 0.:
            value = 0.
        # no significant change in value - can suppress update
        if ((read_time < self.next_pwm_time or not self.last_pwm_value) and abs(value - self.last_pwm_value) < 0.05):
            return
        # time calculation
        pwm_time = read_time + self.pwm_delay
        self.next_pwm_time = pwm_time + 0.75 * MAX_HEAT_TIME
        self.last_pwm_value = value
        # value calculation
        # TODO, check value limited := [0.0,1.0], in order to invert it easy
        logging.debug("%s: pwm=%.3f@%.3f (from %.3f@%.3f [%.3f])", self.node.name, value, pwm_time, sensor["last"], self.last_time, sensor["target"])
        # output
        self.set_output(pwm_time, value)
    #
    def temperature_callback(self, read_time, temp, sensor = None):
        if not sensor:
            sensor = next(iter(self.thermometer))
            logging.info(sensor)
        with self.lock:
            time_diff = read_time - self.last_time
            sensor["last"] = sensor["current"]
            self.last_time = read_time
            sensor["gov"].value_update(read_time, sensor["current"], sensor["target"], adj_temp)
            temp_diff = sensor["current"] - sensor["smoothed"]
            adj_time = min(time_diff * self.inv_smooth_time, 1.)
            sensor["smoothed"] += temp_diff * adj_time
        #logging.debug("temp: %.3f %f = %f", read_time, temp)
    #
    def avoid_dew(self):
        self.alter_min_temp(self.calc_dew_point())
        pass
    def get_max_power(self):
        return self.max_power
    def get_pwm_delay(self):
        return self.pwm_delay
    def set_pwm_delay(self, pwm_delay):
        self.pwm_delay = min(self.pwm_delay, pwm_delay)
    def get_smooth_time(self):
        return self.smooth_time
    def set_temp(self, degrees, sensor = None):
        if not sensor:
            sensor = next(iter(self.thermometer))
        if degrees and (degrees < self.min_temp or degrees > self.max_temp):
            raise self.printer.command_error("Requested temperature (%.1f) out of range (%.1f:%.1f)" % (degrees, self.min_temp, self.max_temp))
        with self.lock:
            sensor["target"] = degrees
    def check_busy(self, eventtime, sensor = None):
        if not sensor:
            sensor = next(iter(self.thermometer))
        with self.lock:
            return self.control.check_busy(eventtime, sensor["smoothed"], sensor["target"])
    def set_control(self, control, sensor = None):
        if not sensor:
            sensor = next(iter(self.thermometer))
        with self.lock:
            old_control = sensor["gov"]
            sensor["gov"] = control
            sensor["target"] = 0.
        return old_control
    def alter_target(self, target, sensor = None):
        if not sensor:
            sensor = next(iter(self.thermometer))
        if target:
            target = max(self.min_temp, min(self.max_temp, target))
        sensor["target"] = target
    def alter_min_temp(self, min_temp):
        self.min_temp = max(self.min_temp,min_temp)
    def alter_max_temp(self, max_temp):
        self.max_temp = min(self.max_temp,max_temp)
    def stats(self, eventtime, sensor = None):
        if not sensor:
            sensor = next(iter(self.thermometer))
        with self.lock:
            target_temp = sensor["target"]
            last_temp = sensor["last"]
            last_pwm_value = self.last_pwm_value
        is_active = target_temp or last_temp > 50.
        return is_active, '%s: target=%.0f temp=%.1f pwm=%.3f' % (self.node.name, target_temp, last_temp, last_pwm_value)
    def get_status(self, eventtime, sensor = None):
        if not sensor:
            sensor = next(iter(self.thermometer))
        with self.lock:
            target_temp = sensor["target"]
            smoothed_temp = sensor["smoothed"]
        return {'temperature': smoothed_temp, 'target': target_temp}

def load_node_object(hal, node):
    config_ok = True
    for a in node.module.ATTRS:
        if a not in node.attrs:
            config_ok = False
            break
    if config_ok:
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal, node)

