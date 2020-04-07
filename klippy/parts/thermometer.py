# Obtain temperature using linear interpolation of ADC values
#
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, bisect, math
from messaging import msg
from messaging import Kerr as error
import sensor

KELVIN_TO_CELSIUS = -273.15

######################################################################
# Analogue probes
######################################################################

AD595 = [
    (0., .0027), (10., .101), (20., .200), (25., .250), (30., .300),
    (40., .401), (50., .503), (60., .605), (80., .810), (100., 1.015),
    (120., 1.219), (140., 1.420), (160., 1.620), (180., 1.817), (200., 2.015),
    (220., 2.213), (240., 2.413), (260., 2.614), (280., 2.817), (300., 3.022),
    (320., 3.227), (340., 3.434), (360., 3.641), (380., 3.849), (400., 4.057),
    (420., 4.266), (440., 4.476), (460., 4.686), (480., 4.896)
]


AD8494 = [
    (-180, -0.714), (-160, -0.658), (-140, -0.594), (-120, -0.523),
    (-100, -0.446), (-80, -0.365), (-60, -0.278), (-40, -0.188),
    (-20, -0.095), (0, 0.002), (20, 0.1), (25, 0.125), (40, 0.201),
    (60, 0.303), (80, 0.406), (100, 0.511), (120, 0.617), (140, 0.723),
    (160, 0.829), (180, 0.937), (200, 1.044), (220, 1.151), (240, 1.259),
    (260, 1.366), (280, 1.473), (300, 1.58), (320, 1.687), (340, 1.794),
    (360, 1.901), (380, 2.008), (400, 2.114), (420, 2.221), (440, 2.328),
    (460, 2.435), (480, 2.542), (500, 2.65), (520, 2.759), (540, 2.868),
    (560, 2.979), (580, 3.09), (600, 3.203), (620, 3.316), (640, 3.431),
    (660, 3.548), (680, 3.666), (700, 3.786), (720, 3.906), (740, 4.029),
    (760, 4.152), (780, 4.276), (800, 4.401), (820, 4.526), (840, 4.65),
    (860, 4.774), (880, 4.897), (900, 5.018), (920, 5.138), (940, 5.257),
    (960, 5.374), (980, 5.49), (1000, 5.606), (1020, 5.72), (1040, 5.833),
    (1060, 5.946), (1080, 6.058), (1100, 6.17), (1120, 6.282), (1140, 6.394),
    (1160, 6.505), (1180, 6.616), (1200, 6.727)
]

AD8495 = [
    (-260, -0.786), (-240, -0.774), (-220, -0.751), (-200, -0.719),
    (-180, -0.677), (-160, -0.627), (-140, -0.569), (-120, -0.504),
    (-100, -0.432), (-80, -0.355), (-60, -0.272), (-40, -0.184), (-20, -0.093),
    (0, 0.003), (20, 0.1), (25, 0.125), (40, 0.2), (60, 0.301), (80, 0.402),
    (100, 0.504), (120, 0.605), (140, 0.705), (160, 0.803), (180, 0.901),
    (200, 0.999), (220, 1.097), (240, 1.196), (260, 1.295), (280, 1.396),
    (300, 1.497), (320, 1.599), (340, 1.701), (360, 1.803), (380, 1.906),
    (400, 2.01), (420, 2.113), (440, 2.217), (460, 2.321), (480, 2.425),
    (500, 2.529), (520, 2.634), (540, 2.738), (560, 2.843), (580, 2.947),
    (600, 3.051), (620, 3.155), (640, 3.259), (660, 3.362), (680, 3.465),
    (700, 3.568), (720, 3.67), (740, 3.772), (760, 3.874), (780, 3.975),
    (800, 4.076), (820, 4.176), (840, 4.275), (860, 4.374), (880, 4.473),
    (900, 4.571), (920, 4.669), (940, 4.766), (960, 4.863), (980, 4.959),
    (1000, 5.055), (1020, 5.15), (1040, 5.245), (1060, 5.339), (1080, 5.432),
    (1100, 5.525), (1120, 5.617), (1140, 5.709), (1160, 5.8), (1180, 5.891),
    (1200, 5.98), (1220, 6.069), (1240, 6.158), (1260, 6.245), (1280, 6.332),
    (1300, 6.418), (1320, 6.503), (1340, 6.587), (1360, 6.671), (1380, 6.754)
]

AD8496 = [
    (-180, -0.642), (-160, -0.59), (-140, -0.53), (-120, -0.464),
    (-100, -0.392), (-80, -0.315), (-60, -0.235), (-40, -0.15), (-20, -0.063),
    (0, 0.027), (20, 0.119), (25, 0.142), (40, 0.213), (60, 0.308),
    (80, 0.405), (100, 0.503), (120, 0.601), (140, 0.701), (160, 0.8),
    (180, 0.9), (200, 1.001), (220, 1.101), (240, 1.201), (260, 1.302),
    (280, 1.402), (300, 1.502), (320, 1.602), (340, 1.702), (360, 1.801),
    (380, 1.901), (400, 2.001), (420, 2.1), (440, 2.2), (460, 2.3),
    (480, 2.401), (500, 2.502), (520, 2.603), (540, 2.705), (560, 2.808),
    (580, 2.912), (600, 3.017), (620, 3.124), (640, 3.231), (660, 3.34),
    (680, 3.451), (700, 3.562), (720, 3.675), (740, 3.789), (760, 3.904),
    (780, 4.02), (800, 4.137), (820, 4.254), (840, 4.37), (860, 4.486),
    (880, 4.6), (900, 4.714), (920, 4.826), (940, 4.937), (960, 5.047),
    (980, 5.155), (1000, 5.263), (1020, 5.369), (1040, 5.475), (1060, 5.581),
    (1080, 5.686), (1100, 5.79), (1120, 5.895), (1140, 5.999), (1160, 6.103),
    (1180, 6.207), (1200, 6.311)
]

AD8497 = [
    (-260, -0.785), (-240, -0.773), (-220, -0.751), (-200, -0.718),
    (-180, -0.676), (-160, -0.626), (-140, -0.568), (-120, -0.503),
    (-100, -0.432), (-80, -0.354), (-60, -0.271), (-40, -0.184),
    (-20, -0.092), (0, 0.003), (20, 0.101), (25, 0.126), (40, 0.2),
    (60, 0.301), (80, 0.403), (100, 0.505), (120, 0.605), (140, 0.705),
    (160, 0.804), (180, 0.902), (200, 0.999), (220, 1.097), (240, 1.196),
    (260, 1.296), (280, 1.396), (300, 1.498), (320, 1.599), (340, 1.701),
    (360, 1.804), (380, 1.907), (400, 2.01), (420, 2.114), (440, 2.218),
    (460, 2.322), (480, 2.426), (500, 2.53), (520, 2.634), (540, 2.739),
    (560, 2.843), (580, 2.948), (600, 3.052), (620, 3.156), (640, 3.259),
    (660, 3.363), (680, 3.466), (700, 3.569), (720, 3.671), (740, 3.773),
    (760, 3.874), (780, 3.976), (800, 4.076), (820, 4.176), (840, 4.276),
    (860, 4.375), (880, 4.474), (900, 4.572), (920, 4.67), (940, 4.767),
    (960, 4.863), (980, 4.96), (1000, 5.055), (1020, 5.151), (1040, 5.245),
    (1060, 5.339), (1080, 5.433), (1100, 5.526), (1120, 5.618), (1140, 5.71),
    (1160, 5.801), (1180, 5.891), (1200, 5.981), (1220, 6.07), (1240, 6.158),
    (1260, 6.246), (1280, 6.332), (1300, 6.418), (1320, 6.503), (1340, 6.588),
    (1360, 6.671), (1380, 6.754)
]

PT100 = [
    (0, 0.00), (1, 1.11), (10, 1.15), (20, 1.20), (30, 1.24), (40, 1.28),
    (50, 1.32), (60, 1.36), (70, 1.40), (80, 1.44), (90, 1.48), (100, 1.52),
    (110, 1.56), (120, 1.61), (130, 1.65), (140, 1.68), (150, 1.72),
    (160, 1.76), (170, 1.80), (180, 1.84), (190, 1.88), (200, 1.92),
    (210, 1.96), (220, 2.00), (230, 2.04), (240, 2.07), (250, 2.11),
    (260, 2.15), (270, 2.18), (280, 2.22), (290, 2.26), (300, 2.29),
    (310, 2.33), (320, 2.37), (330, 2.41), (340, 2.44), (350, 2.48),
    (360, 2.51), (370, 2.55), (380, 2.58), (390, 2.62), (400, 2.66),
    (500, 3.00), (600, 3.33), (700, 3.63), (800, 3.93), (900, 4.21),
    (1000, 4.48), (1100, 4.73)
]

PT1000 = [
    (0., 1000.), (100., 1385.1), (200., 1758.6), (300., 2120.5),
    (400., 2470.9), (500., 2809.8),
]

# Code to perform linear interpolation
class LinearInterpolate:
    def __init__(self, samples):
        self.keys = []
        self.slopes = []
        last_key = last_value = None
        for key, value in sorted(samples):
            if last_key is None:
                last_key = key
                last_value = value
                continue
            if key <= last_key:
                raise ValueError("duplicate value")
            gain = (value - last_value) / (key - last_key)
            offset = last_value - last_key * gain
            if self.slopes and self.slopes[-1] == (gain, offset):
                continue
            last_value = value
            last_key = key
            self.keys.append(key)
            self.slopes.append((gain, offset))
        if not self.keys:
            raise ValueError("need at least two samples")
        self.keys.append(9999999999999.)
        self.slopes.append(self.slopes[-1])
    def interpolate(self, key):
        pos = bisect.bisect(self.keys, key)
        gain, offset = self.slopes[pos]
        return key * gain + offset
    def reverse_interpolate(self, value):
        values = [key * gain + offset for key, (gain, offset) in zip(
            self.keys, self.slopes)]
        if values[0] < values[-2]:
            valid = [i for i in range(len(values)) if values[i] >= value]
        else:
            valid = [i for i in range(len(values)) if values[i] <= value]
        gain, offset = self.slopes[min(valid + [len(values) - 1])]
        return (value - offset) / gain

# Linear voltage calibrated from temperature measurements
class LinearVoltage:
    def __init__(self, name, voltage, offset, params):
        #logging.debug("                 LINEAR VOLTAGE %s %s %s %s", name, voltage, offset, params)
        samples = []
        for temp, volt in params:
            adc = (volt - offset) / voltage
            if adc < 0. or adc > 1.:
                logging.warn("Ignoring adc sample %.3f/%.3f in heater %s", temp, volt, name)
                continue
            samples.append((adc, temp))
        try:
            li = LinearInterpolate(samples)
        except ValueError as e:
            raise config.error("thermometer_adc %s in heater %s" % (str(e), name))
        self.calc_temp = li.interpolate
        self.calc_adc = li.reverse_interpolate

# Linear resistance calibrated from temperature measurements
class LinearResistance:
    def __init__(self, name, pullup, samples):
        #logging.debug("                 LINEAR RESISTANCE %s %s %s", name, pullup, samples)
        try:
            self.li = LinearInterpolate([(r, t) for t, r in samples])
        except ValueError as e:
            raise config.error("thermometer_adc %s in heater %s" % (str(e), name))
    def calc_temp(self, adc):
        # Calculate temperature from adc
        adc = max(.00001, min(.99999, adc))
        r = self.pullup * adc / (1.0 - adc)
        return self.li.interpolate(r)
    def calc_adc(self, temp):
        # Calculate adc reading from a temperature
        r = self.li.reverse_interpolate(temp)
        return r / (self.pullup + r)

# Non linear approximation (Steinhart-Hart)
class NonLinearResistance:
    def __init__(self, name, pullup, inline_resistor, params):
        #logging.debug("                 NON LINEAR RESISTANCE %s %s %s %s", name, pullup, inline_resistor, params)
        self.pullup = pullup
        self.inline_resistor = inline_resistor
        self.c1 = self.c2 = self.c3 = 0.
        self.name = name
        # setup coefficients
        if 'beta' in params:
            self.setup_coefficients_beta(params['t1'], params['r1'], params['beta'])
        else:
            self.setup_coefficients(params['t1'], params['r1'], params['t2'], params['r2'], params['t3'], params['r3'])
    def setup_coefficients(self, t1, r1, t2, r2, t3, r3):
        # Calculate Steinhart-Hart coefficents from temp measurements.
        # Arrange samples as 3 linear equations and solve for c1, c2, and c3.
        inv_t1 = 1. / (t1 - KELVIN_TO_CELSIUS)
        inv_t2 = 1. / (t2 - KELVIN_TO_CELSIUS)
        inv_t3 = 1. / (t3 - KELVIN_TO_CELSIUS)
        ln_r1 = math.log(r1)
        ln_r2 = math.log(r2)
        ln_r3 = math.log(r3)
        ln3_r1, ln3_r2, ln3_r3 = ln_r1**3, ln_r2**3, ln_r3**3

        inv_t12, inv_t13 = inv_t1 - inv_t2, inv_t1 - inv_t3
        ln_r12, ln_r13 = ln_r1 - ln_r2, ln_r1 - ln_r3
        ln3_r12, ln3_r13 = ln3_r1 - ln3_r2, ln3_r1 - ln3_r3

        self.c3 = ((inv_t12 - inv_t13 * ln_r12 / ln_r13) / (ln3_r12 - ln3_r13 * ln_r12 / ln_r13))
        if self.c3 <= 0.:
            beta = ln_r13 / inv_t13
            logging.warn("Using thermistor beta %.3f in heater %s", beta, self.name)
            self.setup_coefficients_beta(t1, r1, beta)
            return
        self.c2 = (inv_t12 - self.c3 * ln3_r12) / ln_r12
        self.c1 = inv_t1 - self.c2 * ln_r1 - self.c3 * ln3_r1
    def setup_coefficients_beta(self, t1, r1, beta):
        # Calculate equivalent Steinhart-Hart coefficents from beta
        inv_t1 = 1. / (t1 - KELVIN_TO_CELSIUS)
        ln_r1 = math.log(r1)
        self.c3 = 0.
        self.c2 = 1. / beta
        self.c1 = inv_t1 - self.c2 * ln_r1
    def calc_temp(self, adc):
        # Calculate temperature from adc
        adc = max(.00001, min(.99999, adc))
        r = self.pullup * adc / (1.0 - adc)
        ln_r = math.log(r - self.inline_resistor)
        inv_t = self.c1 + self.c2 * ln_r + self.c3 * ln_r**3
        return 1.0/inv_t + KELVIN_TO_CELSIUS
    def calc_adc(self, temp):
        # Calculate adc reading from a temperature
        if temp <= KELVIN_TO_CELSIUS:
            return 1.
        inv_t = 1. / (temp - KELVIN_TO_CELSIUS)
        if self.c3:
            # Solve for ln_r using Cardano's formula
            y = (self.c1 - inv_t) / (2. * self.c3)
            x = math.sqrt((self.c2 / (3. * self.c3))**3 + y**2)
            ln_r = math.pow(x - y, 1./3.) - math.pow(x + y, 1./3.)
        else:
            ln_r = (inv_t - self.c1) / self.c2
        r = math.exp(ln_r) + self.inline_resistor
        return r / (self.pullup + r)

######################################################################
# Sensors := {thermistor, adc, i2c, spi}
######################################################################

thermistor = {
    "EPCOS 100K B57560G104F": { 't1': 25., 'r1': 100000., 't2': 150., 'r2': 1641.9, 't3': 250., 'r3': 226.15 },
    "ATC Semitec 104GT-2": { 't1': 20., 'r1': 126800., 't2': 150., 'r2': 1360., 't3': 300., 'r3': 80.65 },
    "NTC 100K beta 3950": { 't1': 25., 'r1': 100000., 'beta': 3950. },
    "Honeywell 100K 135-104LAG-J01": { 't1': 25., 'r1': 100000., 'beta': 3974.},
    "NTC 100K MGB18-104F39050L32": { 't1': 25., 'r1': 100000., 'beta': 4100. },
}
adc = {
    "AD595": AD595,
    "AD8494": AD8494,
    "AD8495": AD8495,
    "AD8496": AD8496,
    "AD8497": AD8497,
    "PT100": PT100,
    "INA826": PT100,
    "PT1000": PT1000
}
i2c = {
    "BME280": None,
}
spi = {
    "MAX6675": None,
    "MAX31855": None,
    "MAX31856": None,
    "MAX31865": None,
}

class ADC:
    def __init__(self, params):
        self.probe = None
        # non linear approximation (Steinhart-Hart)
        if "inline" in params:
            self.probe = NonLinearResistance(params["name"], params["pullup"], params["inline"], params["params"])
        # linear approximation (interpolation)
        else:
            # standard, resistance
            if params["model"] == "PT1000":
                self.probe = LinearResistance(params["name"], params["pullup"], params["params"])
            # standard, voltage
            elif params["model"] in adc:
                self.probe = LinearVoltage(params["name"], params["voltage"], params["offset"], params["params"])
            # custom, voltage
            elif "voltage" in params:
                self.probe = LinearVoltage(params["name"], params["voltage"], params["offset"], params["params"])
            # custom, resistance
            elif "pullup" in params:
                self.probe = LinearResistance(params["name"], params["pullup"], params["params"])
            else:
                # doesn't exist TODO an error message
                raise

# TODO
class I2C(sensor.Object):
    def __init__(self, params):
        logging.warning("TODO i2c thermometer")
        self.probe = None

# TODO
class SPI(sensor.Object):
    def __init__(self, params):
        logging.warning("TODO spi thermometer")
        self.probe = None

######################################################################
# Thermometer
######################################################################

ATTRS = ("type", "model")
SAMPLE_TIME = 0.001
SAMPLE_COUNT = 8
REPORT_TIME = 0.300
RANGE_CHECK_COUNT = 4

# TODO
class Dummy(sensor.Object):
    def __init__(self, hal, node):
        sensor.Object(hal,node)
        logging.warning("thermometer.Dummy:__init__():%s", self.node.name)
    def configure(self):
        logging.warning("thermometer.Dummy:configure():%s", self.node.name)
        self.sensor = None
    def setup_cb(self, temperature_callback):
        self.temperature_callback = temperature_callback
    def get_report_time_delta(self):
        return REPORT_TIME
    def cb(self, read_time, read_value):
        # TODO make a fake temp
        #temp = 
        #self.temperature_callback(read_time + SAMPLE_COUNT * SAMPLE_TIME, temp)
        pass
    def setup_minmax(self, min_temp, max_temp):
        # TODO make a fake adc_range
        #adc_range = 
        #self.pin.setup_minmax(SAMPLE_TIME, SAMPLE_COUNT, minval=min(adc_range), maxval=max(adc_range), range_check_count=RANGE_CHECK_COUNT)
        pass

# TODO attrs checks for each model of sensor
# TODO test custom sensors
class Object(sensor.Object):
    def configure(self):
        if self.ready:
            return
        # setup thermometer probe
        params = {}
        params["name"] = self.node.get_id()
        params["model"] = self.node.attrs["model"]
        # thermistor sensor
        if self.node.attrs["model"] in thermistor:
            params["pullup"] = self.node.attr_get_float("pullup", default=4700., above=0.)
            params["inline"] = self.node.attr_get_float("inline", default=0., minval=0.)
            params["params"] = thermistor[self.node.attrs["model"]]
            self.sensor = ADC(params)
        # adc sensor
        elif self.node.attrs["model"] in adc:
            if "pullup" in self.node.attrs:
                params["pullup"] = self.node.attr_get_float("pullup", above=0., default=4700.)
            else: 
                params["voltage"] = self.node.attr_get_float("voltage", above=0., default=5.)
                params["offset"] = self.node.attr_get_float("offset", default=0.0)
            params["params"] = adc[self.node.attrs["model"]]
            self.sensor = ADC(params)
        # i2c digital sensor
        elif self.node.attrs["model"] in i2c:
            self.sensor = I2C(self.node)
        # spi digital sensor
        elif self.node.attrs["model"] in spi:
            self.sensor = SPI(self.node)
        # same, but custom calibration
        elif self.node.attrs["model"].startswith("custom "):
            name = node.attrs["model"].split(" ")
            if name[1] == "thermistor":
                params["pullup"] = self.node.attr_get_float("pullup", 4700., above=0.)
                params["inline"] = self.node.attr_get_float("inline", 0., minval=0.)
                # get samples
                t1 = self.node.attr_get_float("t1", minval=KELVIN_TO_CELSIUS)
                r1 = self.node.attr_get_float("r1", minval=0.)
                if "beta" in self.node.attrs:
                    beta = node.attr_get_float("beta", None, above=0.)
                    if beta is not None:
                        self.params = {'t1': t1, 'r1': r1, 'beta': beta}
                        return
                t2 = node.attr_get_float("t2", minval=KELVIN_TO_CELSIUS)
                r2 = node.attr_get_float("r2", minval=0.)
                t3 = node.attr_get_float("t3", minval=KELVIN_TO_CELSIUS)
                r3 = node.attr_get_float("r3", minval=0.)
                (t1, r1), (t2, r2), (t3, r3) = sorted([(t1, r1), (t2, r2), (t3, r3)])
                params["params"] = {'t1': t1, 'r1': r1, 't2': t2, 'r2': r2, 't3': t3, 'r3': r3}
                self.sensor = ADC(params)
            elif name[1] == "adc":
                self.key = ""
                if "pullup" in self.node.attrs:
                    self.key = "r"
                    params["pullup"] = self.node.attr_get_float('pullup', 4700., above=0.)
                else: 
                    self.key = "v"
                    params["voltage"] = self.node.attr_get_float('voltage', 5., above=0.)
                    params["offset"] = self.node.attr_get_float('offset', 0.0)
                # get samples
                params["params"] = []
                for i in range(1, 1000):
                    t = self.node.attr_get_float("t%d" % (i,), None)
                    if t is None:
                        break
                    v = self.node.attr_get_float(self.key+"%d" % (i,))
                    params["params"].append((t, v))
                self.sensor = ADC(params)
            elif name[1] == "i2c":
                self.sensor = I2C(params)
            elif name[1] == "spi":
                self.sensor = SPI(params)
        # register thermometer
        self.pin = self.hal.get_controller().pin_setup("adc", self.node.attr_get("pin"))
        self.pin.setup_callback(REPORT_TIME, self.cb)
        self.ready = True
    def setup_minmax(self, min_temp, max_temp):
        adc_range = [self.sensor.probe.calc_adc(t) for t in [min_temp, max_temp]]
        self.pin.setup_minmax(SAMPLE_TIME, SAMPLE_COUNT, minval=min(adc_range), maxval=max(adc_range), range_check_count=RANGE_CHECK_COUNT)
    def setup_cb(self, temperature_callback):
        self.temperature_callback = temperature_callback
    def get_report_time_delta(self):
        return REPORT_TIME
    def cb(self, read_time, read_value):
        temp = self.sensor.probe.calc_temp(read_value)
        self.temperature_callback(read_time + SAMPLE_COUNT * SAMPLE_TIME, temp, self.node.name)

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

