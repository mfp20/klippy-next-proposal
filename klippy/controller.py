# - Pin name to pin number definitions
# - Interface to Klipper micro-controller code
# - Boards
# - Multiple boards Controller
#
# Copyright (C) 2016-2020  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2019  Florian Heilmann <Florian.Heilmann@gmx.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import re, logging, math, zlib, collections
from messaging import msg
from messaging import Kerr as error
import part, composite, chelper, serialhdl, timing
from parts.sensors.endstop import MCU_endstop

######################################################################
# Pins
######################################################################

Arduino_standard = [
    "PD0", "PD1", "PD2", "PD3", "PD4", "PD5", "PD6", "PD7", "PB0", "PB1",
    "PB2", "PB3", "PB4", "PB5", "PC0", "PC1", "PC2", "PC3", "PC4", "PC5",
]
Arduino_standard_analog = [
    "PC0", "PC1", "PC2", "PC3", "PC4", "PC5", "PE0", "PE1",
]

Arduino_mega = [
    "PE0", "PE1", "PE4", "PE5", "PG5", "PE3", "PH3", "PH4", "PH5", "PH6",
    "PB4", "PB5", "PB6", "PB7", "PJ1", "PJ0", "PH1", "PH0", "PD3", "PD2",
    "PD1", "PD0", "PA0", "PA1", "PA2", "PA3", "PA4", "PA5", "PA6", "PA7",
    "PC7", "PC6", "PC5", "PC4", "PC3", "PC2", "PC1", "PC0", "PD7", "PG2",
    "PG1", "PG0", "PL7", "PL6", "PL5", "PL4", "PL3", "PL2", "PL1", "PL0",
    "PB3", "PB2", "PB1", "PB0", "PF0", "PF1", "PF2", "PF3", "PF4", "PF5",
    "PF6", "PF7", "PK0", "PK1", "PK2", "PK3", "PK4", "PK5", "PK6", "PK7",
]
Arduino_mega_analog = [
    "PF0", "PF1", "PF2", "PF3", "PF4", "PF5",
    "PF6", "PF7", "PK0", "PK1", "PK2", "PK3", "PK4", "PK5", "PK6", "PK7",
]

Sanguino = [
    "PB0", "PB1", "PB2", "PB3", "PB4", "PB5", "PB6", "PB7", "PD0", "PD1",
    "PD2", "PD3", "PD4", "PD5", "PD6", "PD7", "PC0", "PC1", "PC2", "PC3",
    "PC4", "PC5", "PC6", "PC7", "PA0", "PA1", "PA2", "PA3", "PA4", "PA5",
    "PA6", "PA7"
]
Sanguino_analog = [
    "PA0", "PA1", "PA2", "PA3", "PA4", "PA5", "PA6", "PA7"
]

Arduino_Due = [
    "PA8", "PA9", "PB25", "PC28", "PA29", "PC25", "PC24", "PC23", "PC22","PC21",
    "PA28", "PD7", "PD8", "PB27", "PD4", "PD5", "PA13", "PA12", "PA11", "PA10",
    "PB12", "PB13", "PB26", "PA14", "PA15", "PD0", "PD1", "PD2", "PD3", "PD6",
    "PD9", "PA7", "PD10", "PC1", "PC2", "PC3", "PC4", "PC5", "PC6", "PC7",
    "PC8", "PC9", "PA19", "PA20", "PC19", "PC18", "PC17", "PC16", "PC15","PC14",
    "PC13", "PC12", "PB21", "PB14", "PA16", "PA24", "PA23", "PA22", "PA6","PA4",
    "PA3", "PA2", "PB17", "PB18", "PB19", "PB20", "PB15", "PB16", "PA1", "PA0",
    "PA17", "PA18", "PC30", "PA21", "PA25", "PA26", "PA27", "PA28", "PB23"
]
Arduino_Due_analog = [
    "PA16", "PA24", "PA23", "PA22", "PA6", "PA4", "PA3", "PA2", "PB17", "PB18",
    "PB19", "PB20"
]

Adafruit_GrandCentral = [
    "PB25", "PB24", "PC18", "PC19", "PC20",
    "PC21", "PD20", "PD21", "PB18", "PB2",
    "PB22", "PB23", "PB0", "PB1", "PB16",
    "PB17", "PC22", "PC23", "PB12", "PB13",
    "PB20", "PB21", "PD12", "PA15", "PC17",
    "PC16", "PA12", "PA13", "PA14", "PB19",
    "PA23", "PA22", "PA21", "PA20", "PA19",
    "PA18", "PA17", "PA16", "PB15", "PB14",
    "PC13", "PC12", "PC15", "PC14", "PC11",
    "PC10", "PC6", "PC7", "PC4", "PC5",
    "PD11", "PD8", "PD9", "PD10", "PA2",
    "PA5", "PB3", "PC0", "PC1", "PC2",
    "PC3", "PB4", "PB5", "PB6", "PB7",
    "PB8", "PB9", "PA4", "PA6", "PA7"
]
Adafruit_GrandCentral_analog = [
    "PA2", "PA5", "PB3", "PC0", "PC1", "PC2", "PC3", "PB4", "PB5", "PB6", "PB7",
    "PB8", "PB9", "PA4", "PA6", "PA7"
]

Arduino_mcu_mappings = {
    "atmega168": (Arduino_standard, Arduino_standard_analog),
    "atmega328": (Arduino_standard, Arduino_standard_analog),
    "atmega328p": (Arduino_standard, Arduino_standard_analog),
    "atmega644p": (Sanguino, Sanguino_analog),
    "atmega1280": (Arduino_mega, Arduino_mega_analog),
    "atmega2560": (Arduino_mega, Arduino_mega_analog),
    "sam3x8e": (Arduino_Due, Arduino_Due_analog),
    "samd51p20a": (Adafruit_GrandCentral, Adafruit_GrandCentral_analog),
}

Beagleboneblack_mappings = {
    'P8_3': 'gpio1_6', 'P8_4': 'gpio1_7', 'P8_5': 'gpio1_2',
    'P8_6': 'gpio1_3', 'P8_7': 'gpio2_2', 'P8_8': 'gpio2_3',
    'P8_9': 'gpio2_5', 'P8_10': 'gpio2_4', 'P8_11': 'gpio1_13',
    'P8_12': 'gpio1_12', 'P8_13': 'gpio0_23', 'P8_14': 'gpio0_26',
    'P8_15': 'gpio1_15', 'P8_16': 'gpio1_14', 'P8_17': 'gpio0_27',
    'P8_18': 'gpio2_1', 'P8_19': 'gpio0_22', 'P8_20': 'gpio1_31',
    'P8_21': 'gpio1_30', 'P8_22': 'gpio1_5', 'P8_23': 'gpio1_4',
    'P8_24': 'gpio1_1', 'P8_25': 'gpio1_0', 'P8_26': 'gpio1_29',
    'P8_27': 'gpio2_22', 'P8_28': 'gpio2_24', 'P8_29': 'gpio2_23',
    'P8_30': 'gpio2_25', 'P8_31': 'gpio0_10', 'P8_32': 'gpio0_11',
    'P8_33': 'gpio0_9', 'P8_34': 'gpio2_17', 'P8_35': 'gpio0_8',
    'P8_36': 'gpio2_16', 'P8_37': 'gpio2_14', 'P8_38': 'gpio2_15',
    'P8_39': 'gpio2_12', 'P8_40': 'gpio2_13', 'P8_41': 'gpio2_10',
    'P8_42': 'gpio2_11', 'P8_43': 'gpio2_8', 'P8_44': 'gpio2_9',
    'P8_45': 'gpio2_6', 'P8_46': 'gpio2_7', 'P9_11': 'gpio0_30',
    'P9_12': 'gpio1_28', 'P9_13': 'gpio0_31', 'P9_14': 'gpio1_18',
    'P9_15': 'gpio1_16', 'P9_16': 'gpio1_19', 'P9_17': 'gpio0_5',
    'P9_18': 'gpio0_4', 'P9_19': 'gpio0_13', 'P9_20': 'gpio0_12',
    'P9_21': 'gpio0_3', 'P9_22': 'gpio0_2', 'P9_23': 'gpio1_17',
    'P9_24': 'gpio0_15', 'P9_25': 'gpio3_21', 'P9_26': 'gpio0_14',
    'P9_27': 'gpio3_19', 'P9_28': 'gpio3_17', 'P9_29': 'gpio3_15',
    'P9_30': 'gpio3_16', 'P9_31': 'gpio3_14', 'P9_41': 'gpio0_20',
    'P9_42': 'gpio3_20', 'P9_43': 'gpio0_7', 'P9_44': 'gpio3_18',

    'P9_33': 'AIN4', 'P9_35': 'AIN6', 'P9_36': 'AIN5', 'P9_37': 'AIN2',
    'P9_38': 'AIN3', 'P9_39': 'AIN0', 'P9_40': 'AIN1',
}

# manages pins on a single board (mcu)
class Pins:
    def __init__(self, hal, boardnode, validate_aliases=True):
        self.hal = hal
        self._name = boardnode.id()
        self.validate_aliases = validate_aliases
        # all pins
        self.id = list()
        self.alias = list()
        self.function = list()
        self.pull = list()
        self.invert = list()
        # reserved for serial, i2c, spi, ...
        self.reserved = {}
        # pins in config file, activated on connect
        self.active = {}
    def map(self, mcu, mapping):
        if mapping == "arduino":
            # grab raw data
            if mcu not in Arduino_mcu_mappings:
                raise error("Arduino aliases not supported on mcu '%s'" % (mcu,))
            dpins, apins = Arduino_mcu_mappings[mcu]
            for i in range(len(dpins)):
                self.id.append(str(dpins[i]))
                self.alias.append('d' + str(i))
            for i in range(len(apins)):
                self.id.append(str(apins[i]))
                self.alias.append('a%d' % (i,))
            for i in range(len(self.alias)):
                self.function.append(None)
                self.pull.append(0)
                self.invert.append(0)
        elif mapping == "beaglebone":
            if mcu != 'pru':
                raise error("Beaglebone aliases not supported on mcu '%s'" % (mcu,))
            self.id = Beagleboneblack_mappings.values()
            self.alias = beagleboneblack_mappings.keys()
            for i in range(len(self.id)):
                self.function.append(None)
                self.pull.append(None)
                self.invert.append(None)
        else:
            raise error("Unknown pin alias mapping '%s'" % (mapping,))
    # bools
    def isid(self, txt):
        if txt in self.id:
            return True
        return False
    def isalias(self, txt):
        if txt in self.alias:
            return True
        return False
    # conversion
    def id2index(self, name):
        return self.id.index(name)
    def alias2index(self, alias):
        return self.alias.index(alias)
    def function2index(self, function):
        return self.function.index(function)
    def id2alias(self, name):
        return self.alias[self.id.index(name)]
    def id2function(self, name):
        return self.function[self.id.index(name)]
    def alias2id(self, alias):
        return self.id[self.alias.index(alias)]
    def alias2function(self, alias):
        return self.function[self.alias.index(alias)]
    def function2id(self, function):
        return self.id[self.function.index(function)]
    def function2alias(self, function):
        return self.alias[self.function.index(function)]
    # name to alias and back
    def alt(self, txt):
        if self.isid(txt):
            return id2alias(txt)
        if self.isalias(txt): 
            return alias2id(txt)
        return None
    # setters
    def set_id(self, index, name):
        self.id[index] = name
    def set_alias(self, index, alias):
        self.alias[index] = alias
    def set_function(self, index, function):
        self.alias[index] = function
    def set_pull(self, index, pull):
        self.alias[index] = pull
    def set_invert(self, index, invert):
        self.alias[index] = invert
    def set_vector(self, index, vector):
        self.id[index] = vector[0]
        self.alias[index] = vector[1]
        self.function[index] = vector[2]
        self.pull[index] = vector[3]
        self.invert[index] = vector[4]
    def set_vector(self, index, name, alias, function, pull, invert):
        self.set_vector(index, [name, alias, function, pull, invert])
    def set_vector_byname(self, name, vector):
        self.set_vector(self.id.index(name),vector)
    def set_vector_byalias(self, alias, vector):
        self.set_vector(self.alias.index(alias),vector)
    def fill_vector(self, index = None, name = None, alias = None, function = None, pull = None, invert = None):
        # identify
        if index:
            pass
        elif name:
            index = id2index(name)
        elif alias:
            index = alias2index(name)
        else:
            raise error("Unknown pin '%s' (%s), index %s", name, alias, index)
        # fill
        if name:
            self.id[index] = name
        if alias:
            self.alias[index] = alias
        if function:
            self.function[index] = function
        if pull:
            self.pull[index] = pull
        if invert:
            self.invert[index] = invert
    # getters
    def get_vector(self, i):
        return [self.id[i], self.alias[i], self.function[i], self.pull[i], self.invert[i]]
    def get_vector_byname(self, name):
        return self.get_vector(self.id.index(name))
    def get_vector_byalias(self, alias):
        return self.get_vector(self.alias.index(alias))
    def get_matrix(self, index = None):
        if index:
            return self.vector(index)
        else:
            matrix = list()
            for i in range(len(self.id)):
                matrix.append(self.get_vector(i))
            return matrix
    # adcs
    def adc_register(self, name, adc):
        # TODO check
        if self.isname(name):
            self.function[self.id2index(name)] = adc
        elif self.isalias(name):
            self.function[self.alias2index(name)] = adc
        else:
            error("ADC pin name '%s' not found.", name)
    def adc_query(self, name):
        # TODO check
        if self.isname(name):
            value, timestamp = self.id2function(name).get_last_value()        
        elif self.isalias(name):
            value, timestamp = self.alias2function(name).get_last_value()        
        else:
            error("ADC pin name '%s' not found.", name)
        return (name, value, timestamp)

#
# Support for custom board pin aliases
#
# TODO
class PinAliasCustom:
    def __init__(self, config, chip_name):
        ppins = config.get_printer().lookup_object('pins')
        pin_resolver = ppins.get_pin_resolver(chip_name)
        aliases = config.get("aliases").strip()
        if aliases.endswith(','):
            aliases = aliases[:-1]
        parts = [a.split('=', 1) for a in aliases.split(',')]
        for pair in parts:
            if len(pair) != 2:
                raise ppins.error("Unable to parse aliases in %s"
                                  % (config.get_name(),))
            name, value = [s.strip() for s in pair]
            if value.startswith('<') and value.endswith('>'):
                pin_resolver.reserve_pin(name, value)
            else:
                pin_resolver.alias_pin(name, value)

######################################################################
# MCU
######################################################################

#
# Code to configure miscellaneous chips
#
# TODO
PIN_MIN_TIME = 0.100
class MCU_pin_out:
    def __init__(self, config):
        self.printer = config.get_printer()
        ppins = self.printer.lookup_object('pins')
        self.is_pwm = config.getboolean('pwm', False)
        if self.is_pwm:
            self.mcu_pin = ppins.setup_pin('pwm', config.get('pin'))
            cycle_time = config.getfloat('cycle_time', 0.100, above=0.)
            hardware_pwm = config.getboolean('hardware_pwm', False)
            self.mcu_pin.setup_cycle_time(cycle_time, hardware_pwm)
            self.scale = config.getfloat('scale', 1., above=0.)
        else:
            self.mcu_pin = ppins.setup_pin('digital_out', config.get('pin'))
            self.scale = 1.
        self.mcu_pin.setup_max_duration(0.)
        self.last_value_time = 0.
        static_value = config.getfloat('static_value', None, minval=0., maxval=self.scale)
        if static_value is not None:
            self.last_value = static_value / self.scale
            self.mcu_pin.setup_start_value(self.last_value, self.last_value, True)
        else:
            self.last_value = config.getfloat('value', 0., minval=0., maxval=self.scale) / self.scale
            shutdown_value = config.getfloat('shutdown_value', 0., minval=0., maxval=self.scale) / self.scale
            self.mcu_pin.setup_start_value(self.last_value, shutdown_value)
            pin_name = config.get_name().split()[1]
            self.gcode = self.printer.lookup_object('gcode')
            self.gcode.register_mux_command("SET_PIN", "PIN", pin_name, self.cmd_SET_PIN, desc=self.cmd_SET_PIN_help)
    def get_status(self, eventtime):
        return {'value': self.last_value}
    cmd_SET_PIN_help = "Set the value of an output pin"
    def cmd_SET_PIN(self, params):
        value = self.gcode.get_float('VALUE', params, minval=0., maxval=self.scale)
        value /= self.scale
        if value == self.last_value:
            return
        print_time = self.printer.lookup_object('toolhead').get_last_move_time()
        print_time = max(print_time, self.last_value_time + PIN_MIN_TIME)
        if self.is_pwm:
            self.mcu_pin.set_pwm(print_time, value)
        else:
            if value not in [0., 1.]:
                raise self.gcode.error("Invalid pin value")
            self.mcu_pin.set_digital(print_time, value)
        self.last_value = value
        self.last_value_time = print_time

#
# Virtual pin that propagates its changes to multiple output pins
#
# TODO
class MCU_pin_out_virtual:
    def __init__(self, hal, name, pins):
        self.hal = hal
        try:
            hal.get_controller().register_chip("multi_pin", self)
        except error:
            pass
        self.pin_type = None
        self.pin_list = [pin.strip() for pin in config.get("pins").split(',')]
        self.mcu_pins = []
    def setup_pin(self, pin_type, pin_params):
        pin_name = pin_params["pin"]
        pin = self.printer.lookup_object("multi_pin " + pin_name, None)
        if pin is not self:
            if pin is None:
                raise error("multi_pin %s not configured" % (pin_name,))
            return pin.setup_pin(pin_type, pin_params)
        if self.pin_type is not None:
            raise ppins.error("Can't setup multi_pin %s twice" % (pin_name,))
        self.pin_type = pin_type
        invert = ""
        if pin_params["invert"]:
            invert = "!"
        self.mcu_pins = [ppins.setup_pin(pin_type, invert + pin_desc)
                         for pin_desc in self.pin_list]
        return self
    def get_mcu(self):
        return self.mcu_pins[0].get_mcu()
    def setup_max_duration(self, max_duration):
        for mcu_pin in self.mcu_pins:
            mcu_pin.setup_max_duration(max_duration)
    def setup_start_value(self, start_value, shutdown_value):
        for mcu_pin in self.mcu_pins:
            mcu_pin.setup_start_value(start_value, shutdown_value)
    def setup_cycle_time(self, cycle_time, hardware_pwm=False):
        for mcu_pin in self.mcu_pins:
            mcu_pin.setup_cycle_time(cycle_time, hardware_pwm)
    def set_digital(self, print_time, value):
        for mcu_pin in self.mcu_pins:
            mcu_pin.set_digital(print_time, value)
    def set_pwm(self, print_time, value):
        for mcu_pin in self.mcu_pins:
            mcu_pin.set_pwm(print_time, value)

#
# Set the state of a list of digital output pins
#
# TODO
class MCU_pin_out_multi:
    def __init__(self, config):
        printer = config.get_printer()
        ppins = printer.lookup_object('pins')
        pin_list = [pin.strip() for pin in config.get('pins').split(',')]
        for pin_desc in pin_list:
            mcu_pin = ppins.setup_pin('digital_out', pin_desc)
            mcu_pin.setup_start_value(1, 1, True)

#
class MCU_pin_out_digital:
    def __init__(self, mcu, pin_params):
        self._mcu = mcu
        self._oid = None
        self._mcu.register_config_callback(self._build_config)
        self._pin = pin_params['pin']
        self._invert = pin_params['invert']
        self._start_value = self._shutdown_value = self._invert
        self._is_static = False
        self._max_duration = 2.
        self._last_clock = 0
        self._set_cmd = None
    def get_mcu(self):
        return self._mcu
    def setup_max_duration(self, max_duration):
        self._max_duration = max_duration
    def setup_start_value(self, start_value, shutdown_value, is_static=False):
        if is_static and start_value != shutdown_value:
            raise pins.error("Static pin can not have shutdown value")
        self._start_value = (not not start_value) ^ self._invert
        self._shutdown_value = (not not shutdown_value) ^ self._invert
        self._is_static = is_static
    def _build_config(self):
        if self._is_static:
            self._mcu.add_config_cmd("set_digital_out pin=%s value=%d" % (self._pin, self._start_value))
            return
        self._oid = self._mcu.create_oid()
        self._mcu.add_config_cmd("config_digital_out oid=%d pin=%s value=%d default_value=%d max_duration=%d" % (self._oid, self._pin, self._start_value, self._shutdown_value, self._mcu.seconds_to_clock(self._max_duration)))
        cmd_queue = self._mcu.alloc_command_queue()
        self._set_cmd = self._mcu.lookup_command("schedule_digital_out oid=%c clock=%u value=%c", cq=cmd_queue)
    def set_digital(self, print_time, value):
        clock = self._mcu.print_time_to_clock(print_time)
        self._set_cmd.send([self._oid, clock, (not not value) ^ self._invert], minclock=self._last_clock, reqclock=clock)
        self._last_clock = clock
    def set_pwm(self, print_time, value):
        self.set_digital(print_time, value >= 0.5)

# Bus synchronized digital outputs
#   Helper code for a gpio that updates on a cmd_queue
# TODO
class MCU_pin_out_digital_queued:
    def __init__(self, mcu, pin_desc, cmd_queue=None, value=0):
        self.mcu = mcu
        self.oid = mcu.create_oid()
        ppins = hal.get_controller()
        pin_params = ppins.get_pin(pin_desc)
        if pin_params['chip'] is not mcu:
            raise ppins.error("Pin %s must be on mcu %s" % (pin_desc, mcu.get_name()))
        mcu.add_config_cmd("config_digital_out oid=%d pin=%s value=%d default_value=%d max_duration=%d" % (self.oid, pin_params['pin'], value, value, 0))
        mcu.register_config_callback(self.build_config)
        if cmd_queue is None:
            cmd_queue = mcu.alloc_command_queue()
        self.cmd_queue = cmd_queue
        self.update_pin_cmd = None
    def get_oid(self):
        return self.oid
    def get_mcu(self):
        return self.mcu
    def get_command_queue(self):
        return self.cmd_queue
    def build_config(self):
        self.update_pin_cmd = self.mcu.lookup_command("update_digital_out oid=%c value=%c", cq=self.cmd_queue)
    def update_digital_out(self, value, minclock=0, reqclock=0):
        if self.update_pin_cmd is None:
            # Send setup message via mcu initialization
            self.mcu.add_config_cmd("update_digital_out oid=%c value=%c" % (self.oid, not not value))
            return
        self.update_pin_cmd.send([self.oid, not not value], minclock=minclock, reqclock=reqclock)

class MCU_pin_out_pwm:
    def __init__(self, mcu, pin_params):
        self._mcu = mcu
        self._hardware_pwm = False
        self._cycle_time = 0.100
        self._max_duration = 2.
        self._oid = None
        self._mcu.register_config_callback(self._build_config)
        self._pin = pin_params['pin']
        self._invert = pin_params['invert']
        self._start_value = self._shutdown_value = float(self._invert)
        self._is_static = False
        self._last_clock = 0
        self._pwm_max = 0.
        self._set_cmd = None
    def get_mcu(self):
        return self._mcu
    def setup_max_duration(self, max_duration):
        self._max_duration = max_duration
    def setup_cycle_time(self, cycle_time, hardware_pwm=False):
        self._cycle_time = cycle_time
        self._hardware_pwm = hardware_pwm
    def setup_start_value(self, start_value, shutdown_value, is_static=False):
        if is_static and start_value != shutdown_value:
            raise pins.error("Static pin can not have shutdown value")
        if self._invert:
            start_value = 1. - start_value
            shutdown_value = 1. - shutdown_value
        self._start_value = max(0., min(1., start_value))
        self._shutdown_value = max(0., min(1., shutdown_value))
        self._is_static = is_static
    def _build_config(self):
        cmd_queue = self._mcu.alloc_command_queue()
        cycle_ticks = self._mcu.seconds_to_clock(self._cycle_time)
        if self._hardware_pwm:
            self._pwm_max = self._mcu.get_constant_float("PWM_MAX")
            if self._is_static:
                self._mcu.add_config_cmd("set_pwm_out pin=%s cycle_ticks=%d value=%d" % (self._pin, cycle_ticks, self._start_value * self._pwm_max))
                return
            self._oid = self._mcu.create_oid()
            self._mcu.add_config_cmd("config_pwm_out oid=%d pin=%s cycle_ticks=%d value=%d default_value=%d max_duration=%d" % (self._oid, self._pin, cycle_ticks, self._start_value * self._pwm_max, self._shutdown_value * self._pwm_max, self._mcu.seconds_to_clock(self._max_duration)))
            self._set_cmd = self._mcu.lookup_command("schedule_pwm_out oid=%c clock=%u value=%hu", cq=cmd_queue)
        else:
            if self._shutdown_value not in [0., 1.]:
                raise pins.error("shutdown value must be 0.0 or 1.0 on soft pwm")
            self._pwm_max = float(cycle_ticks)
            if self._is_static:
                self._mcu.add_config_cmd("set_digital_out pin=%s value=%d" % (self._pin, self._start_value >= 0.5))
                return
            self._oid = self._mcu.create_oid()
            self._mcu.add_config_cmd("config_soft_pwm_out oid=%d pin=%s cycle_ticks=%d value=%d default_value=%d max_duration=%d" % (self._oid, self._pin, cycle_ticks, self._start_value >= 1.0, self._shutdown_value >= 0.5, self._mcu.seconds_to_clock(self._max_duration)))
            if self._start_value not in [0., 1.]:
                clock = self._mcu.get_query_slot(self._oid)
                svalue = int(self._start_value * self._pwm_max + 0.5)
                self._mcu.add_config_cmd("schedule_soft_pwm_out oid=%d clock=%d on_ticks=%d" % (self._oid, clock, svalue))
            self._set_cmd = self._mcu.lookup_command("schedule_soft_pwm_out oid=%c clock=%u on_ticks=%u", cq=cmd_queue)
    def set_pwm(self, print_time, value):
        clock = self._mcu.print_time_to_clock(print_time)
        if self._invert:
            value = 1. - value
        value = int(max(0., min(1., value)) * self._pwm_max + 0.5)
        self._set_cmd.send([self._oid, clock, value], minclock=self._last_clock, reqclock=clock)
        self._last_clock = clock

class MCU_pin_in_adc:
    def __init__(self, mcu, pin_params):
        self._mcu = mcu
        self._pin = pin_params['pin']
        self._min_sample = self._max_sample = 0.
        self._sample_time = self._report_time = 0.
        self._sample_count = self._range_check_count = 0
        self._report_clock = 0
        self._last_state = (0., 0.)
        self._oid = self._callback = None
        self._mcu.register_config_callback(self._build_config)
        self._inv_max_adc = 0.
    def get_mcu(self):
        return self._mcu
    def setup_minmax(self, sample_time, sample_count, minval=0., maxval=1., range_check_count=0):
        self._sample_time = sample_time
        self._sample_count = sample_count
        self._min_sample = minval
        self._max_sample = maxval
        self._range_check_count = range_check_count
    def setup_callback(self, report_time, callback):
        self._report_time = report_time
        self._callback = callback
    def get_last_value(self):
        return self._last_state
    def _build_config(self):
        if not self._sample_count:
            return
        self._oid = self._mcu.create_oid()
        self._mcu.add_config_cmd("config_analog_in oid=%d pin=%s" % (self._oid, self._pin))
        clock = self._mcu.get_query_slot(self._oid)
        sample_ticks = self._mcu.seconds_to_clock(self._sample_time)
        mcu_adc_max = self._mcu.get_constant_float("ADC_MAX")
        max_adc = self._sample_count * mcu_adc_max
        self._inv_max_adc = 1.0 / max_adc
        self._report_clock = self._mcu.seconds_to_clock(self._report_time)
        min_sample = max(0, min(0xffff, int(self._min_sample * max_adc)))
        max_sample = max(0, min(0xffff, int(math.ceil(self._max_sample * max_adc))))
        self._mcu.add_config_cmd("query_analog_in oid=%d clock=%d sample_ticks=%d sample_count=%d rest_ticks=%d min_value=%d max_value=%d range_check_count=%d" % (self._oid, clock, sample_ticks, self._sample_count, self._report_clock, min_sample, max_sample, self._range_check_count), is_init=True)
        self._mcu.register_response(self._handle_analog_in_state, "analog_in_state", self._oid)
    def _handle_analog_in_state(self, params):
        last_value = params['value'] * self._inv_max_adc
        next_clock = self._mcu.clock32_to_clock64(params['next_clock'])
        last_read_clock = next_clock - self._report_clock
        last_read_time = self._mcu.clock_to_print_time(last_read_clock)
        self._last_state = (last_value, last_read_time)
        if self._callback is not None:
            self._callback(last_read_time, last_value)

# SAMD based boards have six internal serial modules that can be configured individually.
# Some are available for mapping onto specific pins. 
# These interfaces are hardware based and can be I2Cs, UARTs or SPIs types.
# TODO
class MCU_samd_sercom:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[1]
        self.tx_pin = config.get("tx_pin")
        self.rx_pin = config.get("rx_pin", None)
        self.clk_pin = config.get("clk_pin")
        ppins = self.printer.lookup_object("pins")
        tx_pin_params = ppins.lookup_pin(self.tx_pin)
        self.mcu = tx_pin_params['chip']
        self.mcu.add_config_cmd("set_sercom_pin bus=%s sercom_pin_type=tx pin=%s" % (self.name, tx_pin_params['pin']))
        clk_pin_params = ppins.lookup_pin(self.clk_pin)
        if self.mcu is not clk_pin_params['chip']:
           raise ppins.error("%s: SERCOM pins must be on same mcu" % (config.get_name(),))
        self.mcu.add_config_cmd("set_sercom_pin bus=%s sercom_pin_type=clk pin=%s" % (self.name, clk_pin_params['pin']))
        if self.rx_pin:
            rx_pin_params = ppins.lookup_pin(self.rx_pin)
            if self.mcu is not rx_pin_params['chip']:
                raise ppins.error("%s: SERCOM pins must be on same mcu" % (config.get_name(),))
            self.mcu.add_config_cmd("set_sercom_pin bus=%s sercom_pin_type=rx pin=%s" % (self.name, rx_pin_params['pin']))

# Helper code for working with devices connected to an MCU via an I2C bus
class MCU_i2c:
    def __init__(self, mcu, bus, addr, speed):
        self.mcu = mcu
        self.bus = bus
        self.i2c_address = addr
        self.oid = self.mcu.create_oid()
        self.config_fmt = "config_i2c oid=%d i2c_bus=%%s rate=%d address=%d" % (self.oid, speed, addr)
        self.cmd_queue = self.mcu.alloc_command_queue()
        self.mcu.register_config_callback(self.build_config)
        self.i2c_write_cmd = self.i2c_read_cmd = self.i2c_modify_bits_cmd = None
    def get_oid(self):
        return self.oid
    def get_mcu(self):
        return self.mcu
    def get_i2c_address(self):
        return self.i2c_address
    def get_command_queue(self):
        return self.cmd_queue
    def build_config(self):
        bus = resolve_bus_name(self.mcu, "i2c_bus", self.bus)
        self.mcu.add_config_cmd(self.config_fmt % (bus,))
        self.i2c_write_cmd = self.mcu.lookup_command("i2c_write oid=%c data=%*s", cq=self.cmd_queue)
        self.i2c_read_cmd = self.mcu.lookup_query_command("i2c_read oid=%c reg=%*s read_len=%u", "i2c_read_response oid=%c response=%*s", oid=self.oid, cq=self.cmd_queue)
        self.i2c_modify_bits_cmd = self.mcu.lookup_command("i2c_modify_bits oid=%c reg=%*s clear_set_bits=%*s", cq=self.cmd_queue)
    def i2c_write(self, data, minclock=0, reqclock=0):
        if self.i2c_write_cmd is None:
            # Send setup message via mcu initialization
            data_msg = "".join(["%02x" % (x,) for x in data])
            self.mcu.add_config_cmd("i2c_write oid=%d data=%s" % (self.oid, data_msg), is_init=True)
            return
        self.i2c_write_cmd.send([self.oid, data], minclock=minclock, reqclock=reqclock)
    def i2c_read(self, write, read_len):
        return self.i2c_read_cmd.send([self.oid, write, read_len])
    def i2c_modify_bits(self, reg, clear_bits, set_bits, minclock=0, reqclock=0):
        clearset = clear_bits + set_bits
        if self.i2c_modify_bits_cmd is None:
            # Send setup message via mcu initialization
            reg_msg = "".join(["%02x" % (x,) for x in reg])
            clearset_msg = "".join(["%02x" % (x,) for x in clearset])
            self.mcu.add_config_cmd("i2c_modify_bits oid=%d reg=%s clear_set_bits=%s" % (self.oid, reg_msg, clearset_msg), is_init=True)
            return
        self.i2c_modify_bits_cmd.send([self.oid, reg, clearset], minclock=minclock, reqclock=reqclock)

# Helper code for working with devices connected to an MCU via an SPI bus
class MCU_spi:
    def __init__(self, mcu, bus, pin, mode, speed, sw_pins=None):
        self.mcu = mcu
        self.bus = bus
        # Config SPI object (set all CS pins high before spi_set_bus commands)
        self.oid = mcu.create_oid()
        if pin is None:
            mcu.add_config_cmd("config_spi_without_cs oid=%d" % (self.oid,))
        else:
            mcu.add_config_cmd("config_spi oid=%d pin=%s" % (self.oid, pin))
        # Generate SPI bus config message
        if sw_pins is not None:
            self.config_fmt = ("spi_set_software_bus oid=%d miso_pin=%s mosi_pin=%s sclk_pin=%s mode=%d rate=%d" % (self.oid, sw_pins[0], sw_pins[1], sw_pins[2], mode, speed))
        else:
            self.config_fmt = ("spi_set_bus oid=%d spi_bus=%%s mode=%d rate=%d" % (self.oid, mode, speed))
        self.cmd_queue = mcu.alloc_command_queue()
        mcu.register_config_callback(self.build_config)
        self.spi_send_cmd = self.spi_transfer_cmd = None
    def setup_shutdown_msg(self, shutdown_seq):
        shutdown_msg = "".join(["%02x" % (x,) for x in shutdown_seq])
        self.mcu.add_config_cmd("config_spi_shutdown oid=%d spi_oid=%d shutdown_msg=%s" % (self.mcu.create_oid(), self.oid, shutdown_msg))
    def get_oid(self):
        return self.oid
    def get_mcu(self):
        return self.mcu
    def get_command_queue(self):
        return self.cmd_queue
    def build_config(self):
        if '%' in self.config_fmt:
            bus = resolve_bus_name(self.mcu, "spi_bus", self.bus)
            self.config_fmt = self.config_fmt % (bus,)
        self.mcu.add_config_cmd(self.config_fmt)
        self.spi_send_cmd = self.mcu.lookup_command("spi_send oid=%c data=%*s", cq=self.cmd_queue)
        self.spi_transfer_cmd = self.mcu.lookup_query_command("spi_transfer oid=%c data=%*s", "spi_transfer_response oid=%c response=%*s", oid=self.oid, cq=self.cmd_queue)
    def spi_send(self, data, minclock=0, reqclock=0):
        if self.spi_send_cmd is None:
            # Send setup message via mcu initialization
            data_msg = "".join(["%02x" % (x,) for x in data])
            self.mcu.add_config_cmd("spi_send oid=%d data=%s" % (self.oid, data_msg), is_init=True)
            return
        self.spi_send_cmd.send([self.oid, data], minclock=minclock, reqclock=reqclock)
    def spi_transfer(self, data):
        return self.spi_transfer_cmd.send([self.oid, data])

# Class to retry sending of a query command until a given response is received
class RetryAsyncCommand:
    TIMEOUT_TIME = 5.0
    RETRY_TIME = 0.500
    def __init__(self, serial, name, oid=None):
        self.serial = serial
        self.name = name
        self.oid = oid
        self.reactor = serial.get_reactor()
        self.completion = self.reactor.completion()
        self.min_query_time = self.reactor.monotonic()
        self.serial.register_response(self.handle_callback, name, oid)
    def handle_callback(self, params):
        if params['#sent_time'] >= self.min_query_time:
            self.min_query_time = self.reactor.NEVER
            self.reactor.async_complete(self.completion, params)
    def get_response(self, cmd, cmd_queue, minclock=0):
        self.serial.raw_send_wait_ack(cmd, minclock, minclock, cmd_queue)
        first_query_time = query_time = self.reactor.monotonic()
        while 1:
            params = self.completion.wait(query_time + self.RETRY_TIME)
            if params is not None:
                self.serial.register_response(None, self.name, self.oid)
                return params
            query_time = self.reactor.monotonic()
            if query_time > first_query_time + self.TIMEOUT_TIME:
                self.serial.register_response(None, self.name, self.oid)
                raise error("Timeout on wait for '%s' response" % (self.name,))
            self.serial.raw_send(cmd, minclock, minclock, cmd_queue)

# Wrapper around query commands
class CommandQueryWrapper:
    def __init__(self, serial, msgformat, respformat, oid=None,
                 cmd_queue=None, async=False):
        self._serial = serial
        self._cmd = serial.get_msgparser().lookup_command(msgformat)
        serial.get_msgparser().lookup_command(respformat)
        self._response = respformat.split()[0]
        self._oid = oid
        self._xmit_helper = serialhdl.SerialRetryCommand
        if async:
            self._xmit_helper = RetryAsyncCommand
        if cmd_queue is None:
            cmd_queue = serial.get_default_command_queue()
        self._cmd_queue = cmd_queue
    def send(self, data=(), minclock=0):
        cmd = self._cmd.encode(data)
        xh = self._xmit_helper(self._serial, self._response, self._oid)
        try:
            return xh.get_response(cmd, self._cmd_queue, minclock=minclock)
        except serialhdl.error as e:
            raise error(str(e))

# Wrapper around command sending
class CommandWrapper:
    def __init__(self, serial, msgformat, cmd_queue=None):
        self._serial = serial
        self._cmd = serial.get_msgparser().lookup_command(msgformat)
        if cmd_queue is None:
            cmd_queue = serial.get_default_command_queue()
        self._cmd_queue = cmd_queue
    def send(self, data=(), minclock=0, reqclock=0):
        cmd = self._cmd.encode(data)
        self._serial.raw_send(cmd, minclock, reqclock, self._cmd_queue)

class MCU:
    # regex to resolve aliases to pins in commands
    re_pin = re.compile(r'(?P<prefix>[ _]pin=)(?P<name>[^ ]*)')
    def __init__(self, hal, board, name, clocksync):
        self.hal = hal
        self._board = board
        self._name = name
        self._clocksync = clocksync
        #
        self._reactor = self.hal.get_reactor()
        # TODO bug each mcu must register a different handler!!!!
        self.hal.get_printer().register_event_handler("klippy:connect", self._connect)
        self.hal.get_printer().register_event_handler("klippy:mcu_identify", self._mcu_identify)
        self.hal.get_printer().register_event_handler("klippy:shutdown", self._shutdown)
        self.hal.get_printer().register_event_handler("klippy:disconnect", self._disconnect)
        # Serial port
        self._serialport = self._board._serialport
        serial_rts = True
        if self._board._restart_method == "cheetah":
            # Special case: Cheetah boards require RTS to be deasserted, else
            # a reset will trigger the built-in bootloader.
            serial_rts = False
        baud = 0
        if not (self._serialport.startswith("/dev/rpmsg_") or self._serialport.startswith("/tmp/klipper_host_")):
            baud = self._board._baud
        self._serial = serialhdl.SerialReader(self._reactor, self._serialport, baud, serial_rts)
        # Restarts
        self._restart_method = "command"
        if baud:
            self._restart_method = self._board._restart_method
        self._reset_cmd = self._config_reset_cmd = None
        self._emergency_stop_cmd = None
        self._is_shutdown = self._is_timeout = False
        self._shutdown_msg = ""
        # Config building
        self._oid_count = 0
        self._config_callbacks = []
        self._init_cmds = []
        self._config_cmds = []
        self._pin_map = self._board._pin_map
        self._custom = self._board._custom
        self._mcu_freq = 0.
        # Move command queuing
        ffi_main, self._ffi_lib = chelper.get_ffi()
        self._max_stepper_error = self._board._max_stepper_error
        self._stepqueues = []
        self._steppersync = None
        # Stats
        self._stats_sumsq_base = 0.
        self._mcu_tick_avg = 0.
        self._mcu_tick_stddev = 0.
        self._mcu_tick_awake = 0.
    # Serial callbacks
    def _handle_mcu_stats(self, params):
        count = params['count']
        tick_sum = params['sum']
        c = 1.0 / (count * self._mcu_freq)
        self._mcu_tick_avg = tick_sum * c
        tick_sumsq = params['sumsq'] * self._stats_sumsq_base
        diff = count*tick_sumsq - tick_sum**2
        self._mcu_tick_stddev = c * math.sqrt(max(0., diff))
        self._mcu_tick_awake = tick_sum / self._mcu_freq
    def _handle_shutdown(self, params):
        if self._is_shutdown:
            return
        self._is_shutdown = True
        self._shutdown_msg = message = params['static_string_id']
        logging.info("MCU '%s' %s: %s\n%s\n%s", self._name, params['#name'], self._shutdown_msg, self._clocksync.dump_debug(), self._serial.dump_debug())
        prefix = "MCU '%s' shutdown: " % (self._name,)
        if params['#name'] == 'is_shutdown':
            prefix = "Previous MCU '%s' shutdown: " % (self._name,)
        self.hal.get_printer().invoke_async_shutdown(prefix + message + msg(message))
    # Connection phase
    def _check_restart(self, reason):
        start_reason = self.hal.get_printer().get_start_args().get("start_reason")
        if start_reason == 'firmware_restart':
            return
        logging.info("Attempting automated MCU '%s' restart: %s", self._name, reason)
        self.hal.get_printer().request_exit('firmware_restart')
        self._reactor.pause(self._reactor.monotonic() + 2.000)
        raise error("Attempt MCU '%s' restart failed" % (self._name,))
    def _connect_file(self, pace=False):
        # In a debugging mode.  Open debug output file and read data dictionary
        start_args = self.hal.get_printer().get_start_args()
        if self._name == 'mcu':
            out_fname = start_args.get('debugoutput')
            dict_fname = start_args.get('dictionary')
        else:
            out_fname = start_args.get('debugoutput') + "-" + self._name
            dict_fname = start_args.get('dictionary_' + self._name)
        outfile = open(out_fname, 'wb')
        dfile = open(dict_fname, 'rb')
        dict_data = dfile.read()
        dfile.close()
        self._serial.connect_file(outfile, dict_data)
        self._clocksync.connect_file(self._serial, pace)
        # Handle pacing
        if not pace:
            def dummy_estimated_print_time(eventtime):
                return 0.
            self.estimated_print_time = dummy_estimated_print_time
    def _add_custom(self):
        for line in self._custom.split('\n'):
            line = line.strip()
            cpos = line.find('#')
            if cpos >= 0:
                line = line[:cpos].strip()
            if not line:
                continue
            self.add_config_cmd(line)
    # applies pin_fixup to all "pin" occurrences in the given command
    def command_translate(self, cmd):
        def pin_fixup(m):
            name = m.group('name')
            if name in self._board.pin.alias:
                pin_id = self._board.pin.alias2id(name)
                pin_params = self._board.pin.active.pop(name)
                pin_params["pin"] = pin_id
                self._board.pin.active[pin_id] = pin_params
                index = self._board.pin.alias.index(name)
                self._board.pin.invert[index] = pin_params["invert"]
                self._board.pin.pull[index] = pin_params["pullup"]
            else:
                pin_id = name
            if pin_id in self._board.pin.reserved:
                raise error("pin %s is reserved for %s" % (name, self._board.pin.reserved[pin_id]))
            return m.group('prefix') + str(pin_id)
        return self.re_pin.sub(pin_fixup, cmd)
    #
    def _send_config(self, prev_crc):
        # Build config commands
        for cb in self._config_callbacks:
            cb()
        self._add_custom()
        self._config_cmds.insert(0, "allocate_oids count=%d" % (self._oid_count,))
        #
        for i, cmd in enumerate(self._config_cmds):
            self._config_cmds[i] = self.command_translate(cmd)
        for i, cmd in enumerate(self._init_cmds):
            self._init_cmds[i] = self.command_translate(cmd)
        # Calculate config CRC
        config_crc = zlib.crc32('\n'.join(self._config_cmds)) & 0xffffffff
        self.add_config_cmd("finalize_config crc=%d" % (config_crc,))
        # Transmit config messages (if needed)
        if prev_crc is None:
            logging.info("- Sending printer configuration to MCU '%s'.",
                         self._name)
            for c in self._config_cmds:
                self._serial.send(c)
        elif config_crc != prev_crc:
            self._check_restart("CRC mismatch")
            raise error("MCU '%s' CRC does not match config" % (self._name,))
        # Transmit init messages
        for c in self._init_cmds:
            self._serial.send(c)
    def _send_get_config(self):
        get_config_cmd = self.lookup_query_command(
            "get_config",
            "config is_config=%c crc=%u move_count=%hu is_shutdown=%c")
        if self.is_fileoutput():
            return { 'is_config': 0, 'move_count': 500, 'crc': 0 }
        config_params = get_config_cmd.send()
        if self._is_shutdown:
            raise error("MCU '%s' error during config: %s" % (self._name, self._shutdown_msg))
        if config_params['is_shutdown']:
            raise error("Can not update MCU '%s' config as it is shutdown" % (self._name,))
        return config_params
    def _log_info(self):
        msgparser = self._serial.get_msgparser()
        log_info = ["Loaded MCU '%s' %d commands (%s / %s)" % (self._name, len(msgparser.messages_by_id), msgparser.version, msgparser.build_versions),
            "MCU '%s' config: %s" % (self._name, " ".join(["%s=%s" % (k, v) for k, v in self.get_constants().items()]))]
        return "\n".join(log_info)
    def _connect(self):
        config_params = self._send_get_config()
        if not config_params['is_config']:
            if self._restart_method == 'rpi_usb':
                # Only configure mcu after usb power reset
                self._check_restart("full reset before config")
            # Not configured - send config and issue get_config again
            self._send_config(None)
            config_params = self._send_get_config()
            if not config_params['is_config'] and not self.is_fileoutput():
                raise error("Unable to configure MCU '%s'" % (self._name,))
        else:
            start_reason = self.hal.get_printer().get_start_args().get("start_reason")
            if start_reason == 'firmware_restart':
                raise error("Failed automated reset of MCU '%s'" % (self._name,))
            # Already configured - send init commands
            self._send_config(config_params['crc'])
        # Setup steppersync with the move_count returned by get_config
        move_count = config_params['move_count']
        self._steppersync = self._ffi_lib.steppersync_alloc(
            self._serial.serialqueue, self._stepqueues, len(self._stepqueues),
            move_count)
        self._ffi_lib.steppersync_set_time(
            self._steppersync, 0., self._mcu_freq)
        # Log config information
        move_msg = "Configured MCU '%s' (%d moves)" % (self._name, move_count)
        logging.debug(move_msg)
        log_info = self._log_info() + "\n" + move_msg
        self.hal.get_printer().set_rollover_info(self._name, log_info, log=False)
        # board configured
        self.hal.get_printer().send_event("board:"+self._name+":configured")
    def _mcu_identify(self):
        # load MCU
        if self.is_fileoutput():
            self._connect_file()
        else:
            if (self._restart_method == 'rpi_usb'
                and not os.path.exists(self._serialport)):
                # Try toggling usb power
                self._check_restart("enable power")
            try:
                self._serial.connect()
                self._clocksync.connect(self._serial)
            except serialhdl.error as e:
                raise error(str(e))
        logging.info(self._log_info())
        #
        self._mcu_freq = self.get_constant_float('CLOCK_FREQ')
        self._stats_sumsq_base = self.get_constant_float('STATS_SUMSQ_BASE')
        self._emergency_stop_cmd = self.lookup_command("emergency_stop")
        self._reset_cmd = self.try_lookup_command("reset")
        self._config_reset_cmd = self.try_lookup_command("config_reset")
        ext_only = self._reset_cmd is None and self._config_reset_cmd is None
        mbaud = self._serial.get_msgparser().get_constant('SERIAL_BAUD', None)
        if self._restart_method is None and mbaud is None and not ext_only:
            self._restart_method = 'command'
        self.register_response(self._handle_shutdown, 'shutdown')
        self.register_response(self._handle_shutdown, 'is_shutdown')
        self.register_response(self._handle_mcu_stats, 'stats')
        # board identified
        self.hal.get_printer().send_event("board:"+self._name+":identified", self._name)
    # Config creation helpers
    def setup_pin(self, pin_type, pin_params):
        pcs = {'endstop': MCU_endstop, 'digital_out': MCU_pin_out_digital, 'pwm': MCU_pin_out_pwm, 'adc': MCU_pin_in_adc}
        if pin_type not in pcs:
            raise pins.error("pin type %s not supported on mcu" % (pin_type,))
        return pcs[pin_type](self, pin_params)
    def create_oid(self):
        self._oid_count += 1
        return self._oid_count - 1
    def register_config_callback(self, cb):
        self._config_callbacks.append(cb)
    def add_config_cmd(self, cmd, is_init=False):
        if is_init:
            self._init_cmds.append(cmd)
        else:
            self._config_cmds.append(cmd)
    def get_query_slot(self, oid):
        slot = self.seconds_to_clock(oid * .01)
        t = int(self.estimated_print_time(self._reactor.monotonic()) + 1.5)
        return self.print_time_to_clock(t) + slot
    def register_stepqueue(self, stepqueue):
        self._stepqueues.append(stepqueue)
    def seconds_to_clock(self, time):
        return int(time * self._mcu_freq)
    def get_max_stepper_error(self):
        return self._max_stepper_error
    # Wrapper functions
    def get_printer(self):
        return self.hal.get_printer()
    def get_name(self):
        return self._name
    def register_response(self, cb, msg, oid=None):
        self._serial.register_response(cb, msg, oid)
    def alloc_command_queue(self):
        return self._serial.alloc_command_queue()
    def lookup_command(self, msgformat, cq=None):
        return CommandWrapper(self._serial, msgformat, cq)
    def lookup_query_command(self, msgformat, respformat, oid=None, cq=None, async=False):
        return CommandQueryWrapper(self._serial, msgformat, respformat, oid, cq, async)
    def try_lookup_command(self, msgformat):
        try:
            return self.lookup_command(msgformat)
        except self._serial.get_msgparser().error as e:
            return None
    def lookup_command_id(self, msgformat):
        return self._serial.get_msgparser().lookup_command(msgformat).msgid
    def get_enumerations(self):
        return self._serial.get_msgparser().get_enumerations()
    def get_constants(self):
        return self._serial.get_msgparser().get_constants()
    def get_constant_float(self, name):
        return self._serial.get_msgparser().get_constant_float(name)
    def print_time_to_clock(self, print_time):
        return self._clocksync.print_time_to_clock(print_time)
    def clock_to_print_time(self, clock):
        return self._clocksync.clock_to_print_time(clock)
    def estimated_print_time(self, eventtime):
        return self._clocksync.estimated_print_time(eventtime)
    def clock32_to_clock64(self, clock32):
        return self._clocksync.clock32_to_clock64(clock32)
    # Restarts
    def _disconnect(self):
        self._serial.disconnect()
        if self._steppersync is not None:
            self._ffi_lib.steppersync_free(self._steppersync)
            self._steppersync = None
    def _shutdown(self, force=False):
        if (self._emergency_stop_cmd is None
            or (self._is_shutdown and not force)):
            return
        self._emergency_stop_cmd.send()
    def _restart_arduino(self):
        logging.info("Attempting MCU '%s' reset", self._name)
        self._disconnect()
        serialhdl.arduino_reset(self._serialport, self._reactor)
    def _restart_cheetah(self):
        logging.info("Attempting MCU '%s' Cheetah-style reset", self._name)
        self._disconnect()
        serialhdl.cheetah_reset(self._serialport, self._reactor)
    def _restart_via_command(self):
        if ((self._reset_cmd is None and self._config_reset_cmd is None)
            or not self._clocksync.is_active()):
            logging.info("Unable to issue reset command on MCU '%s'", self._name)
            return
        if self._reset_cmd is None:
            # Attempt reset via config_reset command
            logging.info("Attempting MCU '%s' config_reset command", self._name)
            self._is_shutdown = True
            self._shutdown(force=True)
            self._reactor.pause(self._reactor.monotonic() + 0.015)
            self._config_reset_cmd.send()
        else:
            # Attempt reset via reset command
            logging.info("Attempting MCU '%s' reset command", self._name)
            self._reset_cmd.send()
        self._reactor.pause(self._reactor.monotonic() + 0.015)
        self._disconnect()
    def _restart_rpi_usb(self):
        logging.info("Attempting MCU '%s' reset via rpi usb power", self._name)
        self._disconnect()
        chelper.run_hub_ctrl(0)
        self._reactor.pause(self._reactor.monotonic() + 2.)
        chelper.run_hub_ctrl(1)
    def microcontroller_restart(self):
        if self._restart_method == 'rpi_usb':
            self._restart_rpi_usb()
        elif self._restart_method == 'command':
            self._restart_via_command()
        elif self._restart_method == 'cheetah':
            self._restart_cheetah()
        else:
            self._restart_arduino()
    # Misc external commands
    def is_fileoutput(self):
        return self.hal.get_printer().get_start_args().get('debugoutput') is not None
    def is_shutdown(self):
        return self._is_shutdown
    def flush_moves(self, print_time):
        if self._steppersync is None:
            return
        clock = self.print_time_to_clock(print_time)
        if clock < 0:
            return
        ret = self._ffi_lib.steppersync_flush(self._steppersync, clock)
        if ret:
            raise error("Internal error in MCU '%s' stepcompress" % (self._name,))
    def check_active(self, print_time, eventtime):
        if self._steppersync is None:
            return
        offset, freq = self._clocksync.calibrate_clock(print_time, eventtime)
        self._ffi_lib.steppersync_set_time(self._steppersync, offset, freq)
        if (self._clocksync.is_active() or self.is_fileoutput() or self._is_timeout):
            return
        self._is_timeout = True
        logging.info("Timeout with MCU '%s' (eventtime=%f)", self._name, eventtime)
        self.hal.get_printer().invoke_shutdown("Lost communication with MCU '%s'" % (self._name,))
    def stats(self, eventtime):
        msg = "%s: mcu_awake=%.03f mcu_task_avg=%.06f mcu_task_stddev=%.06f" % (self._name, self._mcu_tick_awake, self._mcu_tick_avg, self._mcu_tick_stddev)
        return False, ' '.join([msg, self._serial.stats(eventtime), self._clocksync.stats(eventtime)])
    def __del__(self):
        self._disconnect()

######################################################################
# Board := {mcu, pins, uart, i2c, spi, ...}
######################################################################

# TODO
class Dummy(part.Object):
    def __init__(self, hal, node):
        part.Object.__init__(self,hal,node)
        logging.warning("(%s) controller.Dummy (dummy Board)", self.get_name())
        self.ready = True
    def register(self):
        pass

class Board(part.Object):
    rmethods = [None, "arduino", "cheetah", "command", "rpi_usb"]
    def __init__(self, hal, node):
        part.Object.__init__(self,hal,node)
        self.metaconf["serialport"] = {"t": "str", "default": "/dev/ttyS0"}
        self.metaconf["baud"] = {"t": "int", "default":250000, "minval":2400, "maxval":250000}
        self.metaconf["restart_method"] = {"t": "choice", "choices":self.rmethods, "default":None}
        self.metaconf["pin_map"] = {"t": "str", "default":None}
        self.metaconf["custom"] = {"t": "str", "default":""}
        self.metaconf["max_stepper_error"] = {"t": "float", "minval":0., "default":0.000025}
        #
        self.pin = Pins(self.hal, node)
        self.uart = collections.OrderedDict()
        self.i2c = collections.OrderedDict()
        self.spi = collections.OrderedDict()
    def init_mcu(self):
        if self.hal.mcu_count == 0:
            self.mcu = MCU(self.hal, self, self.id(), self.hal.get_timing())
        else:
            self.mcu = MCU(self.hal, self, self.id(), timing.Secondary(self.hal, self.hal.get_reactor(), self.hal.get_timing()))
        self.hal.mcu_count = self.hal.mcu_count + 1
        self.ready = True
    def register(self):
        self.hal.get_printer().register_event_handler("board:"+self.id()+":identified", self._identified)
        self.hal.get_printer().register_event_handler("board:"+self.id()+":configured", self._configured)
    # events handlers
    def _identified(self, mcuname):
        # init pins
        self.mcu._mcu_type = self.mcu._serial.get_msgparser().get_constant("MCU")
        self.pin.map(self.mcu._mcu_type, self.mcu._pin_map)
        # parse constants
        for cname, value in self.mcu.get_constants().items():
            # ex: RESERVE_PINS_serial
            if cname.startswith("RESERVE_PINS_"):
                for pin in value.split(','):
                    self.pin_reserve(pin, cname[13:])
        # TODO
        # get uart
        # get available i2c
        #enumerations = self.hal.get_node("mcu "+self.id()).object.mcu.get_enumerations()
        #i2c = enumerations.get("i2c_bus", enumerations.get('bus'))
        #for i in i2c:
        #    self.bus_pin_reserve()
        #    self.bus_setup_i2c()
        # get available spi
        #spi = enumerations.get("spi_bus", enumerations.get('bus'))
        #for s in spi:
        #    self.bus_pin_reserve()
        #    self.bus_setup_spi()
    def _configured(self):
        self.hal.get_printer().send_event("controller:ready")
    #
    def pin_parse(self, pin_desc, can_invert=False, can_pullup=False):
        desc = pin_desc.strip()
        pullup = invert = 0
        if can_pullup and (desc.startswith('^') or desc.startswith('~')):
            pullup = 1
            if desc.startswith('~'):
                pullup = -1
            desc = desc[1:].strip()
        if can_invert and desc.startswith('!'):
            invert = 1
            desc = desc[1:].strip()
        if [c for c in '^~!: ' if c in desc]:
            format = ""
            if can_pullup:
                format += "[^~] "
            if can_invert:
                format += "[!] "
            raise error("Invalid pin description '%s'\nFormat is: %s[chip_name:] pin_name" % (pin_desc, format))
        pin_params = {'chip': self.mcu, 'chip_name': self.mcu._name, 'pin': desc, 'invert': invert, 'pullup': pullup}
        return pin_params
    def pin_register(self, pin_desc, can_invert=False, can_pullup=False, share_type=None):
        pin_params = self.pin_parse(pin_desc, can_invert, can_pullup)
        pin = pin_params['pin']
        share_name = pin
        if share_name in self.pin.active:
            share_params = self.pin.active[share_name]
            if share_type is None or share_type != share_params['share_type']:
                raise error("pin %s (%s) used multiple times in config" % (pin,self.pin.alt(pin)))
            if (pin_params['invert'] != share_params['invert'] or pin_params['pullup'] != share_params['pullup']):
                raise error("Shared pin %s must have same polarity" % (pin,))
            return share_params
        pin_params['share_type'] = share_type
        self.pin.active[share_name] = pin_params
        return pin_params
    def pin_setup(self, pin_type, pin_desc):
        can_invert = pin_type in ['endstop', 'digital_out', 'pwm']
        can_pullup = pin_type in ['endstop']
        pin_params = self.pin_register(pin_desc, can_invert, can_pullup)
        return pin_params['chip'].setup_pin(pin_type, pin_params)
    def pin_reserve(self, name, function):
        if name in self.pin.reserved and self.pin.reserved[name] != function:
            raise error("Pin %s reserved for %s - can't reserve for %s" % (name, self.pin.reserved[name], function))
        self.pin.reserved[name] = function
    def pin_reset_sharing(self, pin_params):
        share_name = "%s" % (pin_params['chip_name'], pin_params['pin'])
        del self.pin.active[share_name]
    def bus_pin_reserve(self, bus):
        reserve_pins = self.mcu.get_constants().get('BUS_PINS_%s' % (bus,), None)
        if reserve_pins is not None:
            for pin in reserve_pins.split(','):
                self.pin_reserve(pin, bus)
    def bus_setup_i2c(self, busname = 0, default_speed = 100000, default_addr = None):
        # TODO
        # Load bus parameters
        bus = self.conf_get("i2c_bus", default=busname)
        speed = self.conf_get_int("i2c_speed", default=default_speed, minval=100000)
        if default_addr is None:
            addr = self.conf_get_int("i2c_address", minval=0, maxval=127)
        else:
            addr = self.conf_get_int("i2c_address", default=default_addr, minval=0, maxval=127)
        # create i2c
        self.i2c[bus] = MCU_i2c(self.mcu, bus, addr, speed)
    def bus_setup_spi(self, mode, busname = 0, pin_option="cs_pin", default_speed=100000):
        # TODO
        cs_pin = self.conf_get(pin_option)
        cs_pin_params = self.hal.get_controller().get_pin(cs_pin)
        pin = cs_pin_params["pin"]
        if pin == "None":
            self.hal.get_controller().reset_pin_sharing(cs_pin_params)
            pin = None
        # Load bus parameters
        mcu = cs_pin_params["chip"]
        speed = self.conf_get_int("spi_speed", default=default_speed, minval=100000, maxval=4000000)
        if self.conf_get("spi_software_sclk_pin", None) is not None:
            sw_pin_names = ["spi_software_%s_pin" % (name,) for name in ["miso", "mosi", "sclk"]]
            sw_pin_params = [self.hal.get_controller().get_pin(self.hal.attr_get(name), share_type=name) for name in sw_pin_names]
            for pin_params in sw_pin_params:
                if pin_params["chip"] != mcu:
                    raise error("%s: spi pins must be on same mcu" % (self.get_name(),))
            sw_pins = tuple([pin_params["pin"] for pin_params in sw_pin_params])
            bus = None
        else:
            bus = self.conf_get("spi_bus", default=None)
            sw_pins = None
        # create spi
        self.spi[bus] = MCU_spi(self.mcu, bus, pin, mode, speed, sw_pins)

######################################################################
# Controller: multiboard mapper (was "PrinterPins")
######################################################################

class Object(composite.Object):
    def __init__(self, hal, node):
        composite.Object.__init__(self,hal,node)
        self.board = {}
        self.board_ready = 0
        self.endstop = {}
        self.thermometer = {}
        self.hygrometer = {}
        self.barometer = {}
        self.filament = {}
        self.stepper = {}
        self.heater = {}
        self.cooler = {}
        self.ready = True
    def register(self):
        self.hal.get_printer().register_event_handler("controller:ready", self._ready)
        self.hal.get_commander().register_command('SHOW_PINS_ALL', self.cmd_SHOW_PINS_ALL, desc=self.cmd_SHOW_PINS_ALL_help)
        self.hal.get_commander().register_command('SHOW_PINS_ACTIVE', self.cmd_SHOW_PINS_ACTIVE, desc=self.cmd_SHOW_PINS_ACTIVE_help)
        self.hal.get_commander().register_command("SHOW_ADC_VALUE", self.cmd_SHOW_ADC_VALUE, desc=self.cmd_SHOW_ADC_VALUE_help)
        self.hal.get_commander().register_command("SHOW_ENDSTOPS", self.cmd_SHOW_ENDSTOPS, desc=self.cmd_SHOW_ENDSTOPS_help)
        #gcode.register_command("M119", self.cmd_SHOW_ENDSTOPS)
    # (un)register parts
    def register_part(self, node, remove = False):
        if remove:
            # delete
            for parts in [self.board, self.endstop, self.thermometer, self.hygrometer, self.barometer, self.filament, self.stepper, self.heater, self.cooler]:
                if node.name in parts:
                    parts.pop(node.name)
                    return
            logging.warning("Part '%s' not registered in controller. Can't de-register.", node.name)
        else:
            # register
            if node.name.startswith("mcu "):
                bname = node.id()
                if bname in self.board:
                    raise error("Duplicate mcu name '%s'" % bname)
                self.board[bname] = node.object = Board(self.hal, node)
                node.attrs2obj()
                self.board[bname].init_mcu()
            elif node.name.startswith("sensor "):
                if node.attr("type") == "endstop":
                    self.endstop[node.name] = node.object
                if node.attr("type") == "thermometer":
                    self.thermometer[node.name] = node.object
                if node.attr("type") == "hygrometer":
                    self.hygrometer[node.name] = node.object
                if node.attr("type") == "barometer":
                    self.barometer[node.name] = node.object
                if node.attr("type") == "filament":
                    self.filament[node.name] = node.object
            elif node.name.startswith("stepper "):
                self.stepper[node.name] = node.object
            elif node.name.startswith("heater "):
                self.heater[node.name] = node.object
            elif node.name.startswith("cooler "):
                self.cooler[node.name] = node.object
            else:
                raise error("Unknown group for part '%s'. Can't register in controller.", name)
    # events handlers
    def _ready(self):
        self.board_ready = self.board_ready + 1
        if self.board_ready == self.hal.mcu_count:
            self.hal.ready()
        elif self.board_ready > self.hal.mcu_count:
            raise error("Controller: too many ready MCUs.")
    #
    def list_mcus(self):
        mcus = list()
        for b in self.board:
            mcus.append(self.board[b].mcu)
        return mcus
    def pin_register(self, pin_desc, can_invert=False, can_pullup=False, share_type=None):
        bname = pin_desc.split(":")[0]
        pname = pin_desc.split(":")[1]
        return self.board[bname].pin_register(pname, can_invert, can_pullup, share_type)
    def pin_setup(self, pin_type, pin_desc):
        bname = pin_desc.split(":")[0]
        pname = pin_desc.split(":")[1]
        return self.board[bname].pin_setup(pin_type, pname)
    def pin_matrix(self):
        pins = collections.OrderedDict()
        for b in self.board:
            pins[b] = self.board[b].pin.matrix()
        return pins
    # commands handlers
    cmd_SHOW_PINS_ALL_help = "Shows all pins."
    def cmd_SHOW_PINS_ALL(self):
        self.hal.get_gcode().respond_info(self.pin_matrix(), log=False)
    def pin_matrix_active(self):
        active = collections.OrderedDict()
        for b in self.board:
            active[b] = self.board[b].pin.active
        return active
    cmd_SHOW_PINS_ACTIVE_help = "Shows active pins."
    def cmd_SHOW_PINS_ACTIVE(self):
        self.hal.get_gcode().respond_info(self.pin_matrix_active(), log=False)
    cmd_SHOW_ADC_VALUE_help = "Report the last value of an analog pin"
    def cmd_SHOW_ADC_VALUE(self, params):
        # TODO
        gcode = self.printer.lookup_object('gcode')
        name = gcode.get_str('NAME', params, None)
        mcu = ""
        value = mcu.adc_query(name)
        if not value:
            objs = ['"%s"' % (n,) for n in sorted(self.adc.keys())]
            msg = "Available ADC objects: %s" % (', '.join(objs),)
            gcode.respond_info(msg)
            return
        msg = 'ADC object "%s" has value %.6f (timestamp %.3f)' % value
        pullup = gcode.get_float('PULLUP', params, None, above=0.)
        if pullup is not None:
            v = max(.00001, min(.99999, value))
            r = pullup * v / (1.0 - v)
            msg += "\n resistance %.3f (with %.0f pullup)" % (r, pullup)
        gcode.respond_info(msg)
    cmd_SHOW_ENDSTOPS_help = "Report on the status of each endstop"
    def cmd_SHOW_ENDSTOPS(self, params):
        # TODO
        msg = " "
        for rail in self.hal.children_deep("rail "):
            msg = msg + ["%s:%s\n" % (name, ["open", "TRIGGERED"][not not t]) for name, t in rail.get_endstops_status()]
        #
        self.hal.get_gcode().respond(msg)

ATTRS = ("serialport", "baud", "pin_map", "restart_method")
def load_node_object(hal, node):
    if node.name == "controller":
        node.object = Object(hal, node)
    elif node.name.startswith("mcu "):
        if node.attrs_check():
            hal.get_controller().register_part(node)
        else:
            node.object = Dummy(hal, node)

