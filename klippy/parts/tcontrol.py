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

#
# Tcontrol
#

ATTRS = ("type", "min", "max", "control")

class Dummy(composite.Object):
    def __init__(self, hal, node):
        composite.Object.__init__(self, hal, node)
        logging.warning("(%s) tcontrol.Dummy", self.name)
    def init():
        if self.ready:
            return
        # TODO 
        self.hal.get_temperature().tc_register(self.node())
        self.ready = True
    def register(self):
        pass

KELVIN_TO_CELSIUS = -273.15
ALUMINIUM_OPERATING = 400.00
MAX_HEAT_TIME = 5.0
PID_PARAM_BASE = 255.
OBJ = {"pin": None, "gov": None, "min": None, "target": None, "max": None, "current": None, "smoothed": None, "last": None}
class Object(composite.Object):
    def __init__(self, hal, node):
        composite.Object.__init__(self, hal, node)
        self.metaconf["control"] = {"t":"choice", "choices":{"watermark": "watermark", "pid": "pid"}}
        self.metaconf["smooth_time"] = {"t":"float", "default":2., "above":0.}
        self.metaconf["min"] = {"t":"float", "default":0., "minval":KELVIN_TO_CELSIUS}
        self.metaconf["max"] = {"t":"float", "default":250., "maxval":ALUMINIUM_OPERATING, "above":"self._min"}
        self.metaconf["temp_ambient"] = {"t":"float", "default":25., "above":4., "maxval":100.}
        self.metaconf["pwm_cycle_time"] = {"t":"float", "default":-1.100, "above":0.}
    def init(self):
        if self.ready:
            return
        # capabilities
        self.capas = {"temperature":False, "humidity":False, "pressure":False, "heat":False, "cool":False}
        self.min_temp = KELVIN_TO_CELSIUS
        self.max_temp = ALUMINIUM_OPERATING
        # sensors-actuators-gov
        self.thermometer = {}
        self.hygrometer = {}
        self.barometer = {}
        self.heater = {}
        self.cooler = {}
        self.gov = self.govoff = self.hal.get_temperature().govoff
        self.govon = self.hal.get_temperature().govon
        # timing
        self.lock = threading.Lock()
        self.inv_smooth_time = 1. / self._smooth_time
        self.last_time = 0.
        # pwm caching
        self.pwm_delay = 0.
        self.next_pwm_time = 0.
        self.last_pwm_value = 0.
        # register all sensors, actuators off
        for t in self.children_bytype("sensor", "thermometer"):
            self._register_thermometer(t)
        for h in self.children_bytype("sensor", "hygrometer"):
            self._register_hygrometer(h)
        for b in self.children_bytype("sensor", "barometer"):
            self._register_barometer(b)
        for h in self.children_bygroup("heater"):
            self._register_heater(h)
        for c in self.children_bygroup("cooler"):
            self._register_cooler(c)
        # mangle sensor-heater-cooler relations and setup safe governors:
        #   - first thermometer actuate heaters/coolers
        #   - if no thermomether, heaters/coolers stay off
        #   - more complex relations must be established in other ways
        if len(self.thermometer) > 0:
            if len(self.heater) == 0 and len(self.cooler) == 0:
                #logging.debug("Pure sensor, no temperature adjust (%s)", self.name)
                pass
            elif len(self.heater) > 0 and len(self.cooler) == 0 and not self.capas["humidity"] and not self.capas["pressure"]:
                #logging.debug("Pure heater (%s)", self.name)
                # get maximum allowable power among all heaters
                maxpower = 1.
                for h in self.heater.values():
                    if h["pin"].max_power < maxpower:
                        maxpower = h["pin"].max_power
                # create a common gov for all heaters
                gov = self._mkgov(maxpower)
                # set gov
                for h in self.heater:
                    self.heater[h]["gov"] = gov
                # first thermometer in command
                self.thermometer[next(iter(self.thermometer))]["gov"] = gov
            elif (len(self.heater) == 0) and (len(self.cooler) > 0) and not self.capas["humidity"] and not self.capas["pressure"]:
                #logging.debug("Pure cooler (%s)", self.name)
                # get maximum allowable power among all coolers
                maxpower = 1.
                for c in self.cooler.values():
                    if c["pin"]._power_max < maxpower:
                        maxpower = c["pin"].pin._power_max
                # create a common gov for all coolers
                gov = self._mkgov(maxpower)
                for c in self.cooler:
                    self.cooler[c]["gov"] = gov
                # first thermometer in command
                self.thermometer[next(iter(self.thermometer))]["gov"] = gov
            elif len(self.thermometer) == len(self.heater) and len(self.heater) == len(self.cooler):
                #logging.debug("Thermometer (%d), heater (%d), cooler (%d), (%s)", len(self.thermometer), len(self.heater), len(self.cooler), self.name)
                # get maximum allowable power among all heaters
                maxpower = 1.
                # TODO FIX POWER_MAX!!!!!!
                #for h in self.heater.values():
                #    if h["pin"].power_max < maxpower:
                #        maxpower = h["pin"].power_max
                # get maximum allowable power among all coolers
                #for c in self.cooler.values():
                #    if c["pin"].power_max < maxpower:
                #        maxpower = c["pin"].power_max
                # create a common gov for all heaters&coolers
                gov = self._mkgov(maxpower)
                for h in self.heater:
                    self.heater[h]["gov"] = gov
                for c in self.cooler:
                    self.cooler[c]["gov"] = gov
                # first thermometer in command
                self.thermometer[next(iter(self.thermometer))]["gov"] = gov
            else:
                raise error("Unknown sensors(%d)-actuators(%d) combo." % (len(self.thermometer)+len(self.hygrometer)+len(self.barometer), len(self.heater)+len(self.cooler)))
        elif len(self.thermometer) == 0:
            #logging.debug("No Thermometer, misc sensors/heaters/coolers, always off (%s)." % self.name)
            for h in self.heater:
                self.heater[c]["gov"] = self.govoff
            for c in self.cooler:
                self.cooler[c]["gov"] = self.govoff
        else :
            raise error("Unknown sensors(%d)-actuators(%d) combo." % (len(self.thermometer)+len(self.hygrometer)+len(self.barometer), len(self.heater)+len(self.cooler)))
        #
        self.hal.get_temperature().tc_register(self.node())
        self.ready = True
    def register(self):
        #gcode = self.hal.get_my_gcode(tc)
        #gcode.register_mux_command("SET_TEMPERATURE", "TCONTROL", self.name, self.cmd_SET_TEMPERATURE, desc=self.cmd_SET_TEMPERATURE_help)
        pass
    # helper to setup governors
    def _mkgov(self, max_power):
        # TODO check the self._power_max value!!! 
        self._power_max = max_power
        gov = self._control
        if gov == "watermark":
            return governor.BangBang(self._delta_max, self._power_max)
        else:
            #if "sensor ambient" in self.thermometer:
            #    startvalue =  self.conf_get_float("temp_ambient", default=self.thermometer["sensor ambient"]["current"], above=4., maxval=100.)
            #else:
            startvalue = self._temp_ambient
            return governor.PID(self._pid_kp / PID_PARAM_BASE, self._pid_ki / PID_PARAM_BASE, self._pid_kd / PID_PARAM_BASE, self._power_max, self._smooth_time, self._pid_integral_max, startvalue)
    # register objects
    def _register_thermometer(self, node):
        # set defaults
        self.thermometer[node.name] = OBJ.copy()
        self.thermometer[node.name]["pin"] = node.object
        self.thermometer[node.name]["gov"] = self.govoff
        self.thermometer[node.name]["min"] = self._min
        self.thermometer[node.name]["target"] = 0.
        self.thermometer[node.name]["max"] = self._max
        self.thermometer[node.name]["current"] = 0.
        self.thermometer[node.name]["smoothed"] = 0.
        # setup sensor
        node.object.setup_minmax(self.thermometer[node.name]["min"],  self.thermometer[node.name]["max"])
        node.object.setup_cb(self._temperature_callback)
        self.set_pwm_delay(self.thermometer[node.name]["pin"].get_report_time_delta())
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.object._temp_max)
        self.capas["temperature"] = True
    def _register_hygrometer(self, node):
        # set defaults
        self.hygrometer[node.name] = OBJ.copy()
        self.hygrometer[node.name]["pin"] = node.object
        self.hygrometer[node.name]["gov"] = self.govoff
        self.hygrometer[node.name]["min"] = node.conf_get_float("hygro_min", minval=0)
        self.hygrometer[node.name]["target"] = 0.
        self.hygrometer[node.name]["max"] = node.conf_get_float("hygro_max", maxval=100, above=self.hygrometer[node.name]["min"])
        self.hygrometer[node.name]["current"] = 0.
        self.hygrometer[node.name]["smoothed"] = 0.
        # setup sensor
        # TODO
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.object._temp_max)
        self.capas["humidity"] = True
    def _register_barometer(self, node):
        # set defaults
        self.barometer[node.name] = OBJ.copy()
        self.barometer[node.name]["pin"] = node.object
        self.barometer[node.name]["gov"] = self.govoff
        self.barometer[node.name]["min"] = node.conf_get_float("baro_min", minval=0)
        self.barometer[node.name]["target"] = 0.
        self.barometer[node.name]["max"] = node.conf_get_float("baro_max", maxval=50000, above=self.barometer[node.name]["min"]) # TODO mbar, pa, ... ?
        self.barometer[node.name]["current"] = 0.
        self.barometer[node.name]["smoothed"] = 0.
        # setup sensor
        # TODO
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.object._temp_max)
        self.capas["pressure"] = True
    def _register_heater(self, node):
        if isinstance(node.object.pin, controller.MCU_pin_out_pwm):
            pwm_cycle_time = self._pwm_cycle_time
            if self._pwm_cycle_time > self.pwm_delay:
                self._pwm_cycle_time = self.pwm_delay
            node.object.pin.setup_cycle_time(pwm_cycle_time)
        node.object.pin[node.object._pin].setup_max_duration(MAX_HEAT_TIME)
        # set defaults
        self.heater[node.name] = OBJ.copy()
        self.heater[node.name]["pin"] = node.object
        self.heater[node.name]["gov"] = self.govoff
        self.heater[node.name]["min"] = node.object._min
        self.heater[node.name]["target"] = 0.
        self.heater[node.name]["max"] = node.object._max
        self.heater[node.name]["current"] = 0.
        self.heater[node.name]["smoothed"] = 0.
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.object._temp_max)
        self.capas["heat"] = True
    def _register_cooler(self, node):
        # set defaults
        self.cooler[node.name] = OBJ.copy()
        self.cooler[node.name]["pin"] = node.object
        self.cooler[node.name]["gov"] = self.govoff
        self.cooler[node.name]["min"] = node.object._min
        self.cooler[node.name]["target"] = 0.
        self.cooler[node.name]["max"] = node.object._max
        self.cooler[node.name]["current"] = 0.
        self.cooler[node.name]["smoothed"] = 0.
        # adapt max temp (in case this part can't withstand higher temperatures)
        self.alter_max_temp(node.object._temp_max)
        self.capas["cool"] = True
    # get objects
    def get_thermometer(name):
        return self.thermometer[name]
    def get_hygrometer(name):
        return self.hygrometer[name]
    def get_barometer(name):
        return self.barometer[name]
    def get_heater(name):
        return self.heater[name]
    def get_cooler(name):
        return self.cooler[name]
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
                sensor = self.thermometer[next(iter(self.thermometer))]
            return _get_value(eventtime, sensor)
        else:
            raise error("Requested temperature sensor reading but '%s' doesn't have any temperature sensor!!!", self.node.name)
    def get_hygro(self, eventtime, sensor = None):
        if self.caps["humidity"]:
            if not sensor:
                sensor = self.thermometer[next(iter(self.hygrometer))]
            return _get_value(eventtime, sensor)
        else:
            raise error("Requested humidity sensor reading but '%s' doesn't have any humidity sensor!!!", self.node.name)
    def get_pressure(self, eventtime, sensor = None):
        if self.caps["pressure"]:
            if not sensor:
                sensor = self.thermometer[next(iter(self.barometer))]
            return _get_value(eventtime, sensor)
        else:
            raise error("Requested pressure sensor reading but '%s' doesn't have any pressure sensor!!!", self.node.name)
    # set heaters pwm output value
    def set_heaters(self, pwm_time, value, sensorname):
        for h in self.heater.value():
            h.pin.set_pwm(pwm_time, value)
    # set coolers pwm output value
    def set_coolers(self, pwm_time, hvalue, sensorname):
        # get options
        maxpower = self.thermometer[sensorname]["gov"].max_power
        for c in self.cooler.value():
            # compute
            if c.mode == "on":
                cvalue = maxpower
            elif c.mode == "equal":
                cvalue = hvalue
            elif c.mode == "inverted":
                cvalue = 1.0-hvalue
            elif c.mode == "moderated":
                if hvalue > (0.7*maxpower):
                    cvalue = 0.
                elif hvalue < (0.2*maxpower):
                    cvalue = maxpower
                else:
                    cvalue = 1.0-hvalue
            else:
                cvalue = 0.
            # apply
            logging.debug("%s coolers pwm value: %s", self.node.name, cvalue)
            c.pin.set_pwm(pwm_time, cvalue)
    # set both pwm output value
    def set_output(self, pwm_time, value, sensorname):
        self.set_heaters(pwm_time, value, sensorname)
        self.set_coolers(pwm_time, value, sensorname)
    # adjust temp by modifying pwm output
    def _adj_temp(self, read_time, value, sensorname):
        #logging.debug("%s governor pwm value: %s", self.node.name, value)
        sensor = self.thermometer[sensorname]
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
        logging.debug("%s: pwm=%.3f@%.3f (from %.3f@%.3f [%.3f])", self.node.name, value, pwm_time, sensor["current"], self.last_time, sensor["target"])
        # output
        self.set_output(pwm_time, value, sensorname)
    # 
    def _temperature_callback(self, read_time, temp, sensorname):
        if sensorname in self.thermometer:
            sensor = self.thermometer[sensorname]
        else:
            raise error("Can't read temperature: unknown sensor '%s'" % sensorname)
        if sensorname == next(iter(self.thermometer)):
            # first thermometer keeps the clock and trigger governor(s)
            with self.lock:
                time_diff = read_time - self.last_time
                sensor["current"] = temp
                sensor["last"] = self.last_time = read_time
                # heaters&coolers, adjust temperature
                sensor["gov"].value_update(read_time, sensorname, sensor, self._adj_temp)
                #
                temp_diff = temp - sensor["smoothed"]
                adj_time = min(time_diff * self.inv_smooth_time, 1.)
                sensor["smoothed"] += temp_diff * adj_time
        else:
            # other thermometers store read time and temperature only
            with self.lock:
                sensor["current"] = temp
                sensor["last"] = read_time
        # TODO check they are updated
        #logging.debug("%s: current=%s time=%s", sensorname, sensor["current"], sensor["last"])
    def _humidity_callback(self, read_time, hum, sensorname):
        if sensorname in self.hygrometer:
            sensor = self.hygrometer[sensorname]
        else:
            raise error("Can't read humidity: unknown sensor '%s'" % sensorname)
        with self.lock:
            sensor["current"] = hum
            sensor["last"] = read_time
    def _pressure_callback(self, read_time, press, sensorname):
        if sensorname in self.barometer:
            sensor = self.barometer[sensorname]
        else:
            raise error("Can't read pressure: unknown sensor '%s'" % sensorname)
        with self.lock:
            sensor["current"] = press
            sensor["last"] = read_time
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
    # set min to avoid dew
    def avoid_dew(self):
        self.alter_min_temp(self.calc_dew_point())
    # 
    def get_max_power(self):
        return self.max_power
    def get_pwm_delay(self):
        return self.pwm_delay
    def set_pwm_delay(self, pwm_delay):
        self.pwm_delay = min(self.pwm_delay, pwm_delay)
    def get_smooth_time(self):
        return self._smooth_time
    def set_target_temp(self, degrees, sensor = None):
        if not sensor:
            sensor = self.thermometer[next(iter(self.thermometer))]
        if degrees and (degrees < self.min_temp or degrees > self.max_temp):
            raise self.printer.command_error("Requested temperature (%.1f) out of range (%.1f:%.1f)" % (degrees, self.min_temp, self.max_temp))
        with self.lock:
            sensor["target"] = degrees
    def set_off_heaters(self, degrees):
        # TODO
        logging.warning("TODO set_off_heaters")
    def set_off_coolers(self, degrees):
        # TODO
        logging.warning("TODO set_off_coolers")
    def check_busy(self, eventtime, sensor = None):
        if not sensor:
            sensor = self.thermometer[next(iter(self.thermometer))]
        with self.lock:
            return self.control.check_busy(eventtime, sensor["smoothed"], sensor["target"])
    def set_control(self, control, sensor = None):
        if not sensor:
            sensor = self.thermometer[next(iter(self.thermometer))]
        with self.lock:
            old_control = sensor["gov"]
            sensor["gov"] = control
            sensor["target"] = 0.
        return old_control
    def alter_target(self, target, sensor = None):
        if not sensor:
            sensor = self.thermometer[next(iter(self.thermometer))]
        if target:
            target = max(self.min_temp, min(self.max_temp, target))
        sensor["target"] = target
    def alter_min_temp(self, min_temp):
        self.min_temp = max(self.min_temp,min_temp)
    def alter_max_temp(self, max_temp):
        self.max_temp = min(self.max_temp,max_temp)
    def stats(self, eventtime, sensor = None):
        if not sensor:
            sensor = self.thermometer[next(iter(self.thermometer))]
        with self.lock:
            target_temp = sensor["target"]
            last_temp = sensor["current"]
            last_pwm_value = self.last_pwm_value
        is_active = target_temp or last_temp > 50.
        return is_active, '%s: target=%.0f temp=%.1f pwm=%.3f' % (self.node.name, target_temp, last_temp, last_pwm_value)
    def get_status(self, eventtime, sensor = None):
        if not sensor:
            sensor = self.thermometer[next(iter(self.thermometer))]
        with self.lock:
            target_temp = sensor["target"]
            smoothed_temp = sensor["smoothed"]
        return {'temperature': smoothed_temp, 'target': target_temp}

def load_node_object(hal, node):
    if node.attrs_check():
        node.object = Object(hal, node)
        if node.attr("control") == "watermark":
            node.object.metaconf["delta_max"] = {"t":"float", "default":2.0, "above":0.}
        if node.attr("control") == "pid":
            node.object.metaconf["pid_kp"] = {"t":"float"}
            node.object.metaconf["pid_ki"] = {"t":"float"}
            node.object.metaconf["pid_kd"] = {"t":"float"}
            # TODO FIX _POWER_MAX!!!
            node.object.metaconf["pid_integral_max"] = {"t":"float", "default":1., "minval":0.}
            #node.object.metaconf["pid_integral_max"] = {"t":"float", "default":self._power_max, "minval":0.}
    else:
        node.object = Dummy(hal,node)
    return node.object

