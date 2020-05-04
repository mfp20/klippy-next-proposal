# Endstop sensor support.
# 
# Copyright (C) 2016-2020  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
from text import msg
from error import KError as error
import tree
from parts import sensor
logger = logging.getLogger(__name__)

# Interface to low-level mcu and chelper code
class MCU_endstop:
    RETRY_QUERY = 1.000
    def __init__(self, reactor, pin_params):
        self._pin = pin_params["pin"]
        self._mcu = pin_params["chip"]
        self._pullup = pin_params["pullup"]
        self._invert = pin_params["invert"]
        self._steppers = []
        #
        self._oid = self._home_cmd = self._requery_cmd = self._query_cmd = None
        self._mcu.register_config_callback(self._build_config)
        self._min_query_time = self._last_sent_time = 0.
        self._next_query_print_time = self._end_home_time = 0.
        self._trigger_completion = self._home_completion = None
    def get_mcu(self):
        return self._mcu
    def add_stepper(self, stepper):
        if stepper.get_mcu() is not self._mcu:
            raise error("Endstop and stepper must be on the same mcu.")
        if stepper in self._steppers:
            return
        self._steppers.append(stepper)
    def get_steppers(self):
        return list(self._steppers)
    def _build_config(self):
        self._oid = self._mcu.create_oid()
        self._mcu.add_config_cmd("config_endstop oid=%d pin=%s pull_up=%d stepper_count=%d" % (self._oid, self._pin, self._pullup, len(self._steppers)))
        self._mcu.add_config_cmd("endstop_home oid=%d clock=0 sample_ticks=0 sample_count=0 rest_ticks=0 pin_value=0" % (self._oid,), is_init=True)
        for i, s in enumerate(self._steppers):
            self._mcu.add_config_cmd("endstop_set_stepper oid=%d pos=%d stepper_oid=%d" % (self._oid, i, s.get_oid()), is_init=True)
        cmd_queue = self._mcu.alloc_command_queue()
        self._home_cmd = self._mcu.lookup_command("endstop_home oid=%c clock=%u sample_ticks=%u sample_count=%c rest_ticks=%u pin_value=%c", cq=cmd_queue)
        self._requery_cmd = self._mcu.lookup_command("endstop_query_state oid=%c", cq=cmd_queue)
        self._query_cmd = self._mcu.lookup_query_command("endstop_query_state oid=%c","endstop_state oid=%c homing=%c pin_value=%c", oid=self._oid, cq=cmd_queue)
    def home_start(self, print_time, sample_time, sample_count, rest_time, triggered=True):
        clock = self._mcu.print_time_to_clock(print_time)
        rest_ticks = self._mcu.print_time_to_clock(print_time+rest_time) - clock
        self._next_query_print_time = print_time + self.RETRY_QUERY
        self._min_query_time = self._reactor.monotonic()
        self._last_sent_time = 0.
        self._home_end_time = self._reactor.NEVER
        self._trigger_completion = self._reactor.completion()
        self._mcu.register_response(self._handle_endstop_state, "endstop_state", self._oid)
        self._home_cmd.send([self._oid, clock, self._mcu.seconds_to_clock(sample_time), sample_count, rest_ticks, triggered ^ self._invert], reqclock=clock)
        self._home_completion = self._reactor.register_callback(self._home_retry)
        return self._trigger_completion
    def _handle_endstop_state(self, params):
        logger.debug("endstop_state %s", params)
        if params['#sent_time'] >= self._min_query_time:
            if params['homing']:
                self._last_sent_time = params['#sent_time']
            else:
                self._min_query_time = self._reactor.NEVER
                self._reactor.async_complete(self._trigger_completion, True)
    def _home_retry(self, eventtime):
        if self._mcu.is_fileoutput():
            return True
        while 1:
            did_trigger = self._trigger_completion.wait(eventtime + 0.100)
            if did_trigger is not None:
                # Homing completed successfully
                return True
            # Check for timeout
            last = self._mcu.estimated_print_time(self._last_sent_time)
            if last > self._home_end_time or self._mcu.is_shutdown():
                return False
            # Check for resend
            eventtime = self._reactor.monotonic()
            est_print_time = self._mcu.estimated_print_time(eventtime)
            if est_print_time >= self._next_query_print_time:
                self._next_query_print_time = est_print_time + self.RETRY_QUERY
                self._requery_cmd.send([self._oid])
    def home_wait(self, home_end_time):
        self._home_end_time = home_end_time
        did_trigger = self._home_completion.wait()
        self._mcu.register_response(None, "endstop_state", self._oid)
        self._home_cmd.send([self._oid, 0, 0, 0, 0, 0])
        for s in self._steppers:
            s.note_homing_end(did_trigger=did_trigger)
        if not self._trigger_completion.test():
            self._trigger_completion.complete(False)
        return did_trigger
    def query_endstop(self, print_time):
        clock = self._mcu.print_time_to_clock(print_time)
        if self._mcu.is_fileoutput():
            return 0
        params = self._query_cmd.send([self._oid], minclock=clock)
        return params['pin_value'] ^ self._invert

#
# Endstop
#


# TODO 
class Dummy(sensor.Object):
    def __init__(self, name, hal):
        super().__init__(self, name, hal)
        logger.warning("(%s) endstop.Dummy", self.name())
    def _configure():
        if self.ready:
            return
        self.sensor = None
        self.ready = True

class Sensor(sensor.Object):
    def __init__(self, name, hal):
        super().__init__(name, hal)
        self.metaconf["type"] = {"t":"str", "default":"endstop"}
        self.metaconf["pin"] = {"t":"str"}
    def _configure(self):
        if self.ready:
            return
        # create probe
        self.probe = MCU_endstop(self.hal.get_reactor(), self.hal.get_controller().pin_register(self._pin, can_invert=True, can_pullup=True))
        # register pin
        self.pin[self._pin] = self.probe
        # register part
        self.hal.get_controller().register_part(self)
        #
        self.ready = True
    def read(self):
        self.value = self.probe.query_endstop(self.hal.get_reactor().monotonic())
        return self.value

ATTRS = ("type", "pin")
def load_node(hal, node, cparser = None):
    #if node.attrs_check():
        return Sensor(hal, node)
    #else:
    #    node = Dummy(hal,node)

