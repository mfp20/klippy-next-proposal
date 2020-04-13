# Cooler support file.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import part


# TODO
class Dummy(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self,hal,node)
        logging.warning("(%s) cooler.Dummy", self.name)
    def configure(self):
        if self.ready:
            return
        logging.warning("(%s) cooler.configure: TODO dummy MCU_digital_out and MCU_pwm", self.get_name())
        self.ready = True

class Object(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self,hal,node)
        self.metaconf["type"] = {"t":"str"}
        self.metaconf["pin"] = {"t":"str"}
        self.metaconf["power_max"] = {"t":"float", "default":1., "above":0., "maxval":1.}
        self.metaconf["mode"] = {"t":"choice", "default":"moderated", "choices":{"on": "on", "equal": "equal", "invert": "invert", "moderated": "moderated"}}
        # pwm min and max
        self.metaconf["min"] = {"t":"float", "default":0., "minval":0.}
        self.metaconf["max"] = {"t":"float", "default":1., "maxval":1., "above":"self._min"}
        # min operating temperature #TODO move in a better location, so that EVERY part have one of those
        self.metaconf["temp_min"] = {"t":"float", "default":-273.0}
        # max operating temperature
        self.metaconf["temp_max"] = {"t":"float", "default":400.0}
    def configure(self):
        if self.ready:
            return
        tcnode = self.node().parent(self.hal.tree.printer, self.name)
        gov = tcnode.object._control
        if gov == "watermark" and self._power_max == 1.:
            self.pin[self._pin] = self.hal.get_controller().pin_setup("out_digital", self._pin)
        else:
            self.pin[self._pin] = self.hal.get_controller().pin_setup("out_pwm", self._pin)
        #
        self.hal.get_controller().register_part(self.node())
        #
        self.ready = True

ATTRS = ("type", "pin",)
def load_node_object(hal, node):
    if node.attrs_check():
        node.object = Object(hal, node)
    else:
        node.object = Dummy(hal,node)
    return node.object

# Support fans that are enabled when temperature exceeds a set threshold
#
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

KELVIN_TO_CELSIUS = -273.15
MAX_FAN_TIME = 5.0
AMBIENT_TEMP = 25.
PID_PARAM_BASE = 255.

class TemperatureFan:
    def __init__(self, config):
        self.name = config.get_name().split()[1]
        self.printer = config.get_printer()
        self.fan = fan.PrinterFan(config, default_shutdown_speed=1.)
        self.gcode = self.printer.lookup_object('gcode')
        self.min_temp = config.getfloat('min_temp', minval=KELVIN_TO_CELSIUS)
        self.max_temp = config.getfloat('max_temp', above=self.min_temp)
        self.sensor = self.printer.lookup_object('heater').setup_sensor(config)
        self.sensor.setup_minmax(self.min_temp, self.max_temp)
        self.sensor.setup_callback(self.temperature_callback)
        self.printer.lookup_object('heater').register_sensor(config, self)
        self.speed_delay = self.sensor.get_report_time_delta()
        self.max_speed = config.getfloat('max_speed', 1., above=0., maxval=1.)
        self.min_speed = config.getfloat('min_speed', 0.3, minval=0., maxval=1.)
        self.last_temp = 0.
        self.last_temp_time = 0.
        self.target_temp_conf = config.getfloat(
            'target_temp', 40. if self.max_temp > 40. else self.max_temp,
            minval=self.min_temp, maxval=self.max_temp)
        self.target_temp = self.target_temp_conf
        algos = {'watermark': ControlBangBang, 'pid': ControlPID}
        algo = config.getchoice('control', algos)
        self.control = algo(self, config)
        self.next_speed_time = 0.
        self.last_speed_value = 0.
        self.gcode.register_mux_command(
            "SET_TEMPERATURE_FAN_TARGET", "TEMPERATURE_FAN", self.name,
            self.cmd_SET_TEMPERATURE_FAN_TARGET_TEMP,
            desc=self.cmd_SET_TEMPERATURE_FAN_TARGET_TEMP_help)

    def set_speed(self, read_time, value):
        if value <= 0.:
            value = 0.
        elif value < self.min_speed:
            value = self.min_speed
        if self.target_temp <= 0.:
            value = 0.
        if ((read_time < self.next_speed_time or not self.last_speed_value)
                and abs(value - self.last_speed_value) < 0.05):
            # No significant change in value - can suppress update
            return
        speed_time = read_time + self.speed_delay
        self.next_speed_time = speed_time + 0.75 * MAX_FAN_TIME
        self.last_speed_value = value
        self.fan.set_speed(speed_time, value)
    def temperature_callback(self, read_time, temp):
        self.last_temp = temp
        self.control.temperature_callback(read_time, temp)
    def get_temp(self, eventtime):
        return self.last_temp, self.target_temp
    def get_min_speed(self):
        return self.min_speed
    def get_max_speed(self):
        return self.max_speed
    def get_status(self, eventtime):
        status = self.fan.get_status(eventtime)
        status["temperature"] = self.last_temp
        status["target"] = self.target_temp
        return status
    cmd_SET_TEMPERATURE_FAN_TARGET_TEMP_help = "Sets a temperature fan target"
    def cmd_SET_TEMPERATURE_FAN_TARGET_TEMP(self, params):
        temp = self.gcode.get_float('TARGET', params, self.target_temp_conf)
        self.set_temp(temp)
    def set_temp(self, degrees):
        if degrees and (degrees < self.min_temp or degrees > self.max_temp):
            raise self.gcode.error(
                "Requested temperature (%.1f) out of range (%.1f:%.1f)"
                % (degrees, self.min_temp, self.max_temp))
        self.target_temp = degrees

# Printer cooling fan
#
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

FAN_MIN_TIME = 0.100

class PrinterFan:
    def __init__(self, config, default_shutdown_speed=0.):
        self.last_fan_value = 0.
        self.last_fan_time = 0.
        self.printer = config.get_printer()
        self.printer.register_event_handler("gcode:request_restart", self.handle_request_restart)
        self.max_power = config.getfloat('max_power', 1., above=0., maxval=1.)
        self.kick_start_time = config.getfloat('kick_start_time', 0.1, minval=0.)
        self.off_below = config.getfloat('off_below', default=0., minval=0., maxval=1.)
        ppins = self.printer.lookup_object('pins')
        self.mcu_fan = ppins.setup_pin('pwm', config.get('pin'))
        self.mcu_fan.setup_max_duration(0.)
        cycle_time = config.getfloat('cycle_time', 0.010, above=0.)
        hardware_pwm = config.getboolean('hardware_pwm', False)
        self.mcu_fan.setup_cycle_time(cycle_time, hardware_pwm)
        shutdown_speed = config.getfloat('shutdown_speed', default_shutdown_speed, minval=0., maxval=1.)
        self.mcu_fan.setup_start_value(0., max(0., min(self.max_power, shutdown_speed)))
        # Register commands
        if config.get_name() == 'fan':
            gcode = self.printer.lookup_object('gcode')
            gcode.register_command("M106", self.cmd_M106)
            gcode.register_command("M107", self.cmd_M107)
    def handle_request_restart(self, print_time):
        self.set_speed(print_time, 0.)
    def set_speed(self, print_time, value):
        if value < self.off_below:
            value = 0.
        value = max(0., min(self.max_power, value * self.max_power))
        if value == self.last_fan_value:
            return
        print_time = max(self.last_fan_time + FAN_MIN_TIME, print_time)
        if (value and value < self.max_power and self.kick_start_time
            and (not self.last_fan_value or value - self.last_fan_value > .5)):
            # Run fan at full speed for specified kick_start_time
            self.mcu_fan.set_pwm(print_time, self.max_power)
            print_time += self.kick_start_time
        self.mcu_fan.set_pwm(print_time, value)
        self.last_fan_time = print_time
        self.last_fan_value = value
    def get_status(self, eventtime):
        return {'speed': self.last_fan_value}
    def _delayed_set_speed(self, value):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.register_lookahead_callback((lambda pt:self.set_speed(pt, value)))
    def cmd_M106(self, params):
        # Set fan speed
        gcode = self.printer.lookup_object('gcode')
        value = gcode.get_float('S', params, 255., minval=0.) / 255.
        self._delayed_set_speed(value)
    def cmd_M107(self, params):
        # Turn fan off
        self._delayed_set_speed(0.)

def load_config(config):
    return PrinterFan(config)

# Support a fan for cooling the MCU whenever a stepper or heater is on
#
# Copyright (C) 2019  Nils Friedchen <nils.friedchen@googlemail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

PIN_MIN_TIME = 0.100

class ControllerFan:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.stepper_names = []
        self.stepper_enable = self.printer.try_load_module(config, 'stepper_enable')
        self.heaters = []
        self.fan = fan.PrinterFan(config)
        self.mcu = self.fan.mcu_fan.get_mcu()
        self.max_power = config.getfloat(
            'max_power', default=1.,
            minval=0., maxval=1.)
        self.idle_speed = config.getfloat(
            'idle_speed', default=self.max_power,
            minval=0., maxval=self.max_power)
        self.idle_timeout = config.getint("idle_timeout", default=30, minval=0)
        self.heater_name = config.get("heater", "extruder")
        self.last_on = self.idle_timeout
    def handle_ready(self):
        pheater = self.printer.lookup_object('heater')
        self.heaters = [pheater.lookup_heater(n.strip())
                        for n in self.heater_name.split(',')]
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        self.stepper_names = [s.get_name() for s in kin.get_steppers()]
        reactor = self.printer.get_reactor()
        reactor.register_timer(self.callback, reactor.NOW)
    def callback(self, eventtime):
        power = 0.
        active = False
        for name in self.stepper_names:
            active |= self.stepper_enable.lookup_enable(name).is_motor_enabled()
        for heater in self.heaters:
            _, target_temp = heater.get_temp(eventtime)
            if target_temp:
                active = True
        if active:
            self.last_on = 0
            power = self.max_power
        elif self.last_on < self.idle_timeout:
            power = self.idle_speed
            self.last_on += 1
        print_time = self.mcu.estimated_print_time(eventtime) + PIN_MIN_TIME
        self.fan.set_speed(print_time, power)
        return eventtime + 1.

def load_config_prefix(config):
    return ControllerFan(config)

# Support fans that are enabled when a heater is on
#
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

PIN_MIN_TIME = 0.100

class PrinterHeaterFan:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.heater_name = config.get("heater", "extruder")
        self.heater_temp = config.getfloat("heater_temp", 50.0)
        self.heaters = []
        self.fan = fan.PrinterFan(config, default_shutdown_speed=1.)
        self.mcu = self.fan.mcu_fan.get_mcu()
        self.fan_speed = config.getfloat("fan_speed", 1., minval=0., maxval=1.)
    def handle_ready(self):
        pheater = self.printer.lookup_object('heater')
        self.heaters = [pheater.lookup_heater(n.strip())
                        for n in self.heater_name.split(',')]
        reactor = self.printer.get_reactor()
        reactor.register_timer(self.callback, reactor.NOW)
    def get_status(self, eventtime):
        return self.fan.get_status(eventtime)
    def callback(self, eventtime):
        power = 0.
        for heater in self.heaters:
            current_temp, target_temp = heater.get_temp(eventtime)
            if target_temp or current_temp > self.heater_temp:
                power = self.fan_speed
        print_time = self.mcu.estimated_print_time(eventtime) + PIN_MIN_TIME
        self.fan.set_speed(print_time, power)
        return eventtime + 1.

def load_config_prefix(config):
    return PrinterHeaterFan(config)
