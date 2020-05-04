# Generic Filament Sensor Module
#
# Copyright (C) 2019  Eric Callahan <arksine.code@gmail.com>
# Copyright (C) 2019  Mustafa YILDIZ <mydiz@hotmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging

class RunoutHelper:
    def __init__(self, config):
        self.name = config.get_name().split()[-1]
        self.printer = config.get_printer()
        self.hal.get_reactor().= self.printer.get_reactor()
        self.gcode = self.printer.lookup('gcode')
        # Read config
        self.runout_pause = config.getboolean('pause_on_runout', True)
        if self.runout_pause:
            self.printer.try_load_module(config, 'pause_resume')
        self.runout_gcode = self.insert_gcode = None
        gcode_macro = self.printer.try_load_module(config, 'gcode_macro')
        if self.runout_pause or config.get('runout_gcode', None) is not None:
            self.runout_gcode = gcode_macro.load_template(
                config, 'runout_gcode', '')
        if config.get('insert_gcode', None) is not None:
            self.insert_gcode = gcode_macro.load_template(
                config, 'insert_gcode')
        self.pause_delay = config.getfloat('pause_delay', .5, above=.0)
        self.event_delay = config.getfloat('event_delay', 3., above=0.)
        # Internal state
        self.min_event_systime = self.hal.get_reactor().NEVER
        self.filament_present = False
        self.sensor_enabled = True
        # Register commands and event handlers
        self.printer.event_register_handler("klippy:ready", self._handle_ready)
        self.gcode.register_mux_command(
            "QUERY_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_QUERY_FILAMENT_SENSOR,
            desc=self.cmd_QUERY_FILAMENT_SENSOR_help)
        self.gcode.register_mux_command(
            "SET_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_SET_FILAMENT_SENSOR,
            desc=self.cmd_SET_FILAMENT_SENSOR_help)
    def _handle_ready(self):
        self.min_event_systime = self.hal.get_reactor().monotonic() + 2.
    def _runout_event_handler(self, eventtime):
        # Pausing from inside an event requires that the pause portion
        # of pause_resume execute immediately.
        pause_prefix = ""
        if self.runout_pause:
            pause_resume = self.printer.lookup('pause_resume')
            pause_resume.send_pause_command()
            pause_prefix = "PAUSE\n"
            self.printer.get_reactor().pause(eventtime + self.pause_delay)
        self._exec_gcode(pause_prefix, self.runout_gcode)
    def _insert_event_handler(self, eventtime):
        self._exec_gcode("", self.insert_gcode)
    def _exec_gcode(self, prefix, template):
        try:
            self.gcode.run_script(prefix + template.render() + "\nM400")
        except Exception:
            logger.exception("Script running error")
        self.min_event_systime = self.hal.get_reactor().monotonic() + self.event_delay
    def note_filament_present(self, is_filament_present):
        if is_filament_present == self.filament_present:
            return
        self.filament_present = is_filament_present
        eventtime = self.hal.get_reactor().monotonic()
        if eventtime < self.min_event_systime or not self.sensor_enabled:
            # do not process during the initialization time, duplicates,
            # during the event delay time, while an event is running, or
            # when the sensor is disabled
            return
        # Determine "printing" status
        idle_timeout = self.printer.lookup("idle_timeout")
        is_printing = idle_timeout.get_status(eventtime)["state"] == "Printing"
        # Perform filament action associated with status change (if any)
        if is_filament_present:
            if not is_printing and self.insert_gcode is not None:
                # insert detected
                self.min_event_systime = self.hal.get_reactor().NEVER
                logger.info(
                    "Filament Sensor %s: insert event detected, Time %.2f" %
                    (self.name, eventtime))
                self.hal.get_reactor().register_callback(self._insert_event_handler)
        elif is_printing and self.runout_gcode is not None:
            # runout detected
            self.min_event_systime = self.hal.get_reactor().NEVER
            logger.info(
                "Filament Sensor %s: runout event detected, Time %.2f" %
                (self.name, eventtime))
            self.hal.get_reactor().register_callback(self._runout_event_handler)
    def get_status(self, eventtime):
        return {"filament_detected": bool(self.filament_present)}
    cmd_QUERY_FILAMENT_SENSOR_help = "Query the status of the Filament Sensor"
    def cmd_QUERY_FILAMENT_SENSOR(self, params):
        if self.filament_present:
            msg = "Filament Sensor %s: filament detected" % (self.name)
        else:
            msg = "Filament Sensor %s: filament not detected" % (self.name)
        self.gcode.respond_info(msg)
    cmd_SET_FILAMENT_SENSOR_help = "Sets the filament sensor on/off"
    def cmd_SET_FILAMENT_SENSOR(self, params):
        self.sensor_enabled = self.gcode.get_int("ENABLE", params, 1)

class SwitchSensor:
    def __init__(self, config):
        printer = config.get_printer()
        buttons = printer.try_load_module(config, 'buttons')
        switch_pin = config.get('switch_pin')
        buttons.register_buttons([switch_pin], self._button_handler)
        self.runout_helper = RunoutHelper(config)
        self.get_status = self.runout_helper.get_status
    def _button_handler(self, eventtime, state):
        self.runout_helper.note_filament_present(state)

def load_config_prefix(config):
    return SwitchSensor(config)

#
# Support for filament width sensor
#
ADC_REPORT_TIME = 0.500
ADC_SAMPLE_TIME = 0.001
ADC_SAMPLE_COUNT = 5
class HallFilamentWidthSensor:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.hal.get_reactor().= self.printer.get_reactor()
        self.pin1 = config.get('adc1')
        self.pin2 = config.get('adc2')
        self.dia1=config.getfloat('Cal_dia1', 1.5)
        self.dia2=config.getfloat('Cal_dia2', 2.0)
        self.rawdia1=config.getint('Raw_dia1', 9500)
        self.rawdia2=config.getint('Raw_dia2', 10500)
        self.MEASUREMENT_INTERVAL_MM=config.getint('measurement_interval',10)
        self.nominal_filament_dia = config.getfloat(
            'default_nominal_filament_diameter', above=1)
        self.measurement_delay = config.getfloat('measurement_delay', above=0.)
        self.measurement_max_difference = config.getfloat('max_difference', 0.2)
        self.max_diameter = (self.nominal_filament_dia
                             + self.measurement_max_difference)
        self.min_diameter = (self.nominal_filament_dia
                             - self.measurement_max_difference)
        self.diameter =self.nominal_filament_dia
        self.is_active =config.getboolean('enable', False)
        self.runout_dia=config.getfloat('min_diameter', 1.0)
        # filament array [position, filamentWidth]
        self.filament_array = []
        self.lastFilamentWidthReading = 0
        # printers
        self.toolhead = self.ppins = self.mcu_adc = None
        self.printer.event_register_handler("klippy:ready", self.handle_ready)
        # Start adc
        self.ppins = self.printer.lookup('pins')
        self.mcu_adc = self.ppins.setup_pin('adc', self.pin1)
        self.mcu_adc.setup_minmax(ADC_SAMPLE_TIME, ADC_SAMPLE_COUNT)
        self.mcu_adc.setup_adc_callback(ADC_REPORT_TIME, self.adc_callback)
        self.mcu_adc2 = self.ppins.setup_pin('adc', self.pin2)
        self.mcu_adc2.setup_minmax(ADC_SAMPLE_TIME, ADC_SAMPLE_COUNT)
        self.mcu_adc2.setup_adc_callback(ADC_REPORT_TIME, self.adc2_callback)
        # extrude factor updating
        self.extrude_factor_update_timer = self.hal.get_reactor().register_timer(
            self.extrude_factor_update_event)
        # Register commands
        self.gcode = self.printer.lookup('gcode')
        self.gcode.register_command('QUERY_FILAMENT_WIDTH', self.cmd_M407)
        self.gcode.register_command('RESET_FILAMENT_WIDTH_SENSOR',
                                    self.cmd_ClearFilamentArray)
        self.gcode.register_command('DISABLE_FILAMENT_WIDTH_SENSOR',
                                    self.cmd_M406)
        self.gcode.register_command('ENABLE_FILAMENT_WIDTH_SENSOR',
                                    self.cmd_M405)
        self.gcode.register_command('QUERY_RAW_FILAMENT_WIDTH',
                                    self.cmd_Get_Raw_Values)
        self.runout_helper = filament_switch_sensor.RunoutHelper(config)
    # Initialization
    def handle_ready(self):
        # Load printers
        self.toolhead = self.printer.lookup('toolhead')

        # Start extrude factor update timer
        self.hal.get_reactor().update_timer(self.extrude_factor_update_timer,
                                  self.hal.get_reactor().NOW)

    def adc_callback(self, read_time, read_value):
        # read sensor value
        self.lastFilamentWidthReading = round(read_value * 10000)

    def adc2_callback(self, read_time, read_value):
        # read sensor value
        self.lastFilamentWidthReading2 = round(read_value * 10000)
        # calculate diameter
        self.diameter = round((self.dia2 - self.dia1)/
            (self.rawdia2-self.rawdia1)*
          ((self.lastFilamentWidthReading+self.lastFilamentWidthReading2)
           -self.rawdia1)+self.dia1,2)

    def update_filament_array(self, last_epos):
        # Fill array
        if len(self.filament_array) > 0:
            # Get last reading position in array & calculate next
            # reading position
          next_reading_position = (self.filament_array[-1][0] +
          self.MEASUREMENT_INTERVAL_MM)
          if next_reading_position <= (last_epos + self.measurement_delay):
            self.filament_array.append([last_epos + self.measurement_delay,
                                            self.diameter])
        else:
            # add first item to array
            self.filament_array.append([self.measurement_delay + last_epos,
                                        self.diameter])

    def extrude_factor_update_event(self, eventtime):
        # Update extrude factor
        pos = self.toolhead.get_position()
        last_epos = pos[3]
        # Update filament array for lastFilamentWidthReading
        self.update_filament_array(last_epos)
        # Check runout
        self.runout_helper.note_filament_present(
            self.diameter > self.runout_dia)
        # Does filament exists
        if self.lastFilamentWidthReading > 0.5:
            if len(self.filament_array) > 0:
                # Get first position in filament array
                pending_position = self.filament_array[0][0]
                if pending_position <= last_epos:
                    # Get first item in filament_array queue
                    item = self.filament_array.pop(0)
                    filament_width = item[1]
                    if ((filament_width <= self.max_diameter)
                        and (filament_width >= self.min_diameter)):
                        percentage = round(self.nominal_filament_dia**2
                                           / filament_width**2 * 100)
                        self.gcode.run_script("M221 S" + str(percentage))
                    else:
                        self.gcode.run_script("M221 S100")
        else:
            self.gcode.run_script("M221 S100")
            self.filament_array = []
        return eventtime + 1

    def cmd_M407(self, params):
        response = ""
        if self.lastFilamentWidthReading > 0:
            response += ("Filament dia (measured mm): "
                         + str(self.diameter))
        else:
            response += "Filament NOT present"
        self.gcode.respond(response)

    def cmd_ClearFilamentArray(self, params):
        self.filament_array = []
        self.gcode.respond("Filament width measurements cleared!")
        # Set extrude multiplier to 100%
        self.gcode.run_script_from_command("M221 S100")

    def cmd_M405(self, params):
        response = "Filament width sensor Turned On"
        if self.is_active:
            response = "Filament width sensor is already On"
        else:
            self.is_active = True
            # Start extrude factor update timer
            self.hal.get_reactor().update_timer(self.extrude_factor_update_timer,
                                      self.hal.get_reactor().NOW)
        self.gcode.respond(response)

    def cmd_M406(self, params):
        response = "Filament width sensor Turned Off"
        if not self.is_active:
            response = "Filament width sensor is already Off"
        else:
            self.is_active = False
            # Stop extrude factor update timer
            self.hal.get_reactor().update_timer(self.extrude_factor_update_timer,
                                      self.hal.get_reactor().NEVER)
            # Clear filament array
            self.filament_array = []
            # Set extrude multiplier to 100%
            self.gcode.run_script_from_command("M221 S100")
        self.gcode.respond(response)

    def cmd_Get_Raw_Values(self, params):
        response = "ADC1="
        response +=  (" "+str(self.lastFilamentWidthReading))
        response +=  (" ADC2="+str(self.lastFilamentWidthReading2))
        response +=  (" RAW="+
                      str(self.lastFilamentWidthReading
                      +self.lastFilamentWidthReading2))
        self.gcode.respond(response)
    def get_status(self, eventtime):
        return {'Diameter': self.diameter,
                'Raw':(self.lastFilamentWidthReading+
                 self.lastFilamentWidthReading2),
                'is_active':self.is_active}

def load_config(config):
    return HallFilamentWidthSensor(config)

#
# Support for filament width sensor
#
ADC_REPORT_TIME = 0.500
ADC_SAMPLE_TIME = 0.001
ADC_SAMPLE_COUNT = 8
MEASUREMENT_INTERVAL_MM = 10
class FilamentWidthSensor:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.hal.get_reactor().= self.printer.get_reactor()
        self.pin = config.get('pin')
        self.nominal_filament_dia = config.getfloat(
            'default_nominal_filament_diameter', above=1.0)
        self.measurement_delay = config.getfloat('measurement_delay', above=0.)
        self.measurement_max_difference = config.getfloat('max_difference',
                                                          above=0.)
        self.max_diameter = (self.nominal_filament_dia
                             + self.measurement_max_difference)
        self.min_diameter = (self.nominal_filament_dia
                             - self.measurement_max_difference)
        self.is_active = True
        # filament array [position, filamentWidth]
        self.filament_array = []
        self.lastFilamentWidthReading = 0
        # printers
        self.toolhead = self.ppins = self.mcu_adc = None
        self.printer.event_register_handler("klippy:ready", self.handle_ready)
        # Start adc
        self.ppins = self.printer.lookup('pins')
        self.mcu_adc = self.ppins.setup_pin('adc', self.pin)
        self.mcu_adc.setup_minmax(ADC_SAMPLE_TIME, ADC_SAMPLE_COUNT)
        self.mcu_adc.setup_adc_callback(ADC_REPORT_TIME, self.adc_callback)
        # extrude factor updating
        self.extrude_factor_update_timer = self.hal.get_reactor().register_timer(
            self.extrude_factor_update_event)
        # Register commands
        self.gcode = self.printer.lookup('gcode')
        self.gcode.register_command('QUERY_FILAMENT_WIDTH', self.cmd_M407)
        self.gcode.register_command('RESET_FILAMENT_WIDTH_SENSOR', self.cmd_ClearFilamentArray)
        self.gcode.register_command('DISABLE_FILAMENT_WIDTH_SENSOR', self.cmd_M406)
        self.gcode.register_command('ENABLE_FILAMENT_WIDTH_SENSOR', self.cmd_M405)
    # Initialization
    def handle_ready(self):
        # Load printers
        self.toolhead = self.printer.lookup('toolhead')

        # Start extrude factor update timer
        self.hal.get_reactor().update_timer(self.extrude_factor_update_timer, self.hal.get_reactor().NOW)
    def adc_callback(self, read_time, read_value):
        # read sensor value
        self.lastFilamentWidthReading = round(read_value * 5, 2)
    def update_filament_array(self, last_epos):
        # Fill array
        if len(self.filament_array) > 0:
            # Get last reading position in array & calculate next
            # reading position
            next_reading_position = (self.filament_array[-1][0] + MEASUREMENT_INTERVAL_MM)
            if next_reading_position <= (last_epos + self.measurement_delay):
                self.filament_array.append([last_epos + self.measurement_delay, self.lastFilamentWidthReading])
        else:
            # add first item to array
            self.filament_array.append([self.measurement_delay + last_epos, self.lastFilamentWidthReading])
    def extrude_factor_update_event(self, eventtime):
        # Update extrude factor
        pos = self.toolhead.get_position()
        last_epos = pos[3]
        # Update filament array for lastFilamentWidthReading
        self.update_filament_array(last_epos)
        # Does filament exists
        if self.lastFilamentWidthReading > 0.5:
            if len(self.filament_array) > 0:
                # Get first position in filament array
                pending_position = self.filament_array[0][0]
                if pending_position <= last_epos:
                    # Get first item in filament_array queue
                    item = self.filament_array.pop(0)
                    filament_width = item[1]
                    if ((filament_width <= self.max_diameter)
                        and (filament_width >= self.min_diameter)):
                        percentage = round(self.nominal_filament_dia**2 / filament_width**2 * 100)
                        self.gcode.run_script("M221 S" + str(percentage))
                    else:
                        self.gcode.run_script("M221 S100")
        else:
            self.gcode.run_script("M221 S100")
            self.filament_array = []
        return eventtime + 1

    def cmd_M407(self, params):
        response = ""
        if self.lastFilamentWidthReading > 0:
            response += ("Filament dia (measured mm): " + str(self.lastFilamentWidthReading))
        else:
            response += "Filament NOT present"
        self.gcode.respond(response)

    def cmd_ClearFilamentArray(self, params):
        self.filament_array = []
        self.gcode.respond("Filament width measurements cleared!")
        # Set extrude multiplier to 100%
        self.gcode.run_script_from_command("M221 S100")

    def cmd_M405(self, params):
        response = "Filament width sensor Turned On"
        if self.is_active:
            response = "Filament width sensor is already On"
        else:
            self.is_active = True
            # Start extrude factor update timer
            self.hal.get_reactor().update_timer(self.extrude_factor_update_timer, self.hal.get_reactor().NOW)
        self.gcode.respond(response)

    def cmd_M406(self, params):
        response = "Filament width sensor Turned Off"
        if not self.is_active:
            response = "Filament width sensor is already Off"
        else:
            self.is_active = False
            # Stop extrude factor update timer
            self.hal.get_reactor().update_timer(self.extrude_factor_update_timer, self.hal.get_reactor().NEVER)
            # Clear filament array
            self.filament_array = []
            # Set extrude multiplier to 100%
            self.gcode.run_script_from_command("M221 S100")
        self.gcode.respond(response)

