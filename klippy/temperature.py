# Printer heat controller, sensors and heaters lookup
#
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from messaging import msg
from messaging import Kerr as error


'''
logging.info(temperature.sensor_factories)
INFO:root:{'NTC 100K beta 3950': <function <lambda> at 0x70751013a150>, 'Honeywell 100K 135-104LAG-J01': <function <lambda> at 0x70751011ac50>, 'NTC 100K MGB18-104F39050L32': <function <lambda> at 0x70750feb6a50>, 'PT100 INA826': <function <lambda> at 0x70750feb6dd0>, 'ATC Semitec 104GT-2': <function <lambda> at 0x70751011ae50>, 'MAX31855': <class extras.spi_temperature.MAX31855 at 0x70750fec4360>, 'MAX31856': <class extras.spi_temperature.MAX31856 at 0x70750fec42f0>, 'AD8496': <function <lambda> at 0x70750feb6cd0>, 'AD8497': <function <lambda> at 0x70750feb6d50>, 'AD8494': <function <lambda> at 0x70750feb6bd0>, 'AD8495': <function <lambda> at 0x70750feb6c50>, 'MAX31865': <class extras.spi_temperature.MAX31865 at 0x70750fec4440>, 'EPCOS 100K B57560G104F': <function <lambda> at 0x70750feb6ad0>, 'PT1000': <function <lambda> at 0x70750feb6e50>, 'AD595': <function <lambda> at 0x70750feb6b50>, 'BME280': <class extras.bme280.BME280 at 0x70750fec4590>, 'MAX6675': <class extras.spi_temperature.MAX6675 at 0x70750fec43d0>}

logging.info(temperature.heaters)
INFO:root:{'heater_bed': <heater.Heater instance at 0x70750fecb230>, 'extruder': <heater.Heater instance at 0x70750f8afd70>}

logging.info(temperature.gcode_id_to_sensor)
INFO:root:{'B': <heater.Heater instance at 0x70750fecb230>, 'T0': <heater.Heater instance at 0x70750f8afd70>}

logging.info(temperature.available_heaters)
INFO:root:['heater_bed', 'extruder']

logging.info(temperature.available_sensors)
INFO:root:['heater_bed', 'extruder']
'''


class Object:
    def __init__(self, hal, hnode):
        self.hal = hal
        self.node = hnode
    def init(self):
        self.tcontroller = {}
        self.gcodeid = {}
    def register(self):
        self.hal.get_printer().register_event_handler("controller:request_restart", self._off_all_controls)
        self.hal.get_commander().register_command("TEMPERATURE_HEATERS_OFF", self.cmd_TEMPERATURE_HEATERS_OFF, desc=self.cmd_TEMPERATURE_HEATERS_OFF_help)
        self.hal.get_commander().register_command("TEMPERATURE_COOLERS_OFF", self.cmd_TEMPERATURE_COOLERS_OFF, desc=self.cmd_TEMPERATURE_COOLERS_OFF_help)
        self.hal.get_commander().register_command("TEMPERATURE_CONTROL_OFF", self.cmd_TEMPERATURE_CONTROL_OFF, desc=self.cmd_TEMPERATURE_CONTROL_OFF_help)
    # setup temperature controller
    def tc_setup(self):
        sensor_type = hal.get(node, "type")
        if sensor_type not in self.sensor_factories:
            raise self.printer.config_error("Unknown temperature sensor '%s'" % (sensor_type,))
        return self.sensor_factories[sensor_type](hal, node)
    # register temperature controller to the given commander
    def tc_register(self, psensor, gcode_id=None):
        if gcode_id is None:
            gcode_id = hal.get(node, "gcode_id", None)
            if gcode_id is None:
                return
        if gcode_id in self.gcode_id_to_sensor:
            raise self.printer.config_error("G-Code sensor id %s already registered" % (gcode_id,))
        self.gcode_id_to_sensor[gcode_id] = psensor
        self.available_sensors.append(node.name)
        #self.gcode.register_mux_command("SET_TEMPERATURE", "TCONTROL", self.name, self.cmd_SET_TEMPERATURE, desc=self.cmd_SET_TEMPERATURE_help)
    def get_tc(self, name):
        return self.tcontroller[name]
    def get_tc_all(self):
        return self.tcontroller
    def get_gcode(self):
        return self.gcode_id_to_sensor.items()
    # commands handlers
    def _off_all_heaters(self, print_time=0.):
        for heater in self.heaters.values():
            heater.set_temp(0.)
    def _off_all_coolers(self, print_time=0.):
        for heater in self.heaters.values():
            heater.set_temp(0.)
    def _off_all_controls(self, print_time=0.):
        self.off_all_heaters()
        self.off_all_coolers()
    cmd_TEMPERATURE_HEATERS_OFF_help = "Turn off all heaters"
    def cmd_TEMPERATURE_HEATERS_OFF(self, params):
        self._off_all_heaters()
    cmd_TEMPERATURE_COOLERS_OFF_help = "Turn off all coolers"
    def cmd_TEMPERATURE_COOLERS_OFF(self, params):
        self._off_all_coolers()
    cmd_TEMPERATURE_CONTROL_OFF_help = "Turn off all controls (heaters and coolers included)"
    def cmd_TEMPERATURE_CONTROL_OFF(self, params):
        self._off_all_controls()
    def get_status(self, eventtime):
        return {'available_heaters': self.available_heaters, 'available_sensors': self.available_sensors}
    cmd_SET_TEMPERATURE_help = "Sets the temperature for the given controller"
    def cmd_SET_TEMPERATURE(self, params):
        temp = self.gcode.get_float('TARGET', params, 0.)
        self.set_temp(temp)

def load_node_object(hal, node):
    node.object = Object(hal, node)
    node.object.init()

