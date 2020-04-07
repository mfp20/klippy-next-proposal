# Governors for value controllers
#
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

class AlwaysOff:
    def __init__(self):
        pass
    def value_update(self, readtime, sname, sensor, adj):
        if adj:
            adj(readtime, 0., sname)
    def check_busy(self, eventtime, smoothed, target):
        return False

class AlwaysOn:
    def __init__(self):
        pass
    def value_update(self, readtime, sname, sensor, adj):
        if adj:
            adj(readtime, 1., sname)
    def check_busy(self, eventtime, smoothed, target):
        return True

class BangBang:
    def __init__(self, delta,  maxpower):
        self.delta = delta
        self.bang = maxpower
        self.acting = False
    def value_update(self, readtime, sname, sensor, adj):
        value = sensor["current"]
        target = sensor["target"]
        # evaluate
        if self.acting and value >= target+self.delta:
            self.acting = False
        elif not self.acting and value <= target-self.delta:
            self.acting = True
        # output
        if self.acting:
            if adj:
                adj(readtime, self.bang, sname)
        else:
            if adj:
                adj(readtime, 0., sname)
    def check_busy(self, eventtime, smoothed, target):
        return smoothed < target-self.delta

PID_SETTLE_DELTA = 1.
PID_SETTLE_SLOPE = .1
class PID:
    def __init__(self, kp, ki, kd, maxpower, smoothtime, imax, startvalue):
        self.Kp = kp
        self.Ki = ki
        self.Kd = kd
        self.max = maxpower
        self.min_deriv_time = smoothtime
        self.value_integ_max = imax / self.Ki
        self.prev_value = startvalue
        self.prev_value_time = 0.
        self.prev_value_deriv = 0.
        self.prev_value_integ = 0.
    def value_update(self, readtime, sname, sensor, adj):
        value = sensor["current"]
        target = sensor["target"]
        time_diff = readtime - self.prev_value_time
        # Calculate change of value
        value_diff = value - self.prev_value
        if time_diff >= self.min_deriv_time:
            value_deriv = value_diff / time_diff
        else:
            value_deriv = (self.prev_value_deriv * (self.min_deriv_time-time_diff) + value_diff) / self.min_deriv_time
        # Calculate accumulated value "error"
        value_err = target - value
        value_integ = self.prev_value_integ + value_err * time_diff
        value_integ = max(0., min(self.value_integ_max, value_integ))
        # Calculate output
        co = self.Kp*value_err + self.Ki*value_integ - self.Kd*value_deriv
        #logging.debug("pid: %f@%.3f -> diff=%f deriv=%f err=%f integ=%f co=%d",
        #    value, readtime, value_diff, value_deriv, value_err, value_integ, co)
        bounded_co = max(0., min(self.max, co))
        # output
        if adj:
            adj(readtime, bounded_co, sname)
        # Store state for next measurement
        self.prev_value = value
        self.prev_value_time = readtime
        self.prev_value_deriv = value_deriv
        if co == bounded_co:
            self.prev_value_integ = value_integ
    def check_busy(self, eventtime, smoothed, target):
        value_diff = target - smoothed
        return (abs(value_diff) > PID_SETTLE_DELTA or abs(self.prev_value_deriv) > PID_SETTLE_SLOPE)

