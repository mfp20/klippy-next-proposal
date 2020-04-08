# Governors for value controllers
#
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

#
class AlwaysOff:
    def __init__(self):
        pass
    def value_update(self, readtime, sname, sensor, adj):
        if adj:
            adj(readtime, 0., sname)
    def check_busy(self, eventtime, smoothed, target):
        return False

#
class AlwaysOn:
    def __init__(self):
        pass
    def value_update(self, readtime, sname, sensor, adj):
        if adj:
            adj(readtime, 1., sname)
    def check_busy(self, eventtime, smoothed, target):
        return True

# simple On/Off governor
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

# Proportional-Integrative-Derivative governor
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

# PID calibration governor
TUNE_PID_DELTA = 5.0
class AutoTune:
    def __init__(self, heater, target):
        self.heater = heater
        self.heater_max_power = heater.get_max_power()
        self.calibrate_temp = target
        # Heating control
        self.heating = False
        self.peak = 0.
        self.peak_time = 0.
        # Peak recording
        self.peaks = []
        # Sample recording
        self.last_pwm = 0.
        self.pwm_samples = []
        self.temp_samples = []
    # Heater control
    def set_pwm(self, read_time, value):
        if value != self.last_pwm:
            self.pwm_samples.append(
                (read_time + self.heater.get_pwm_delay(), value))
            self.last_pwm = value
        self.heater.set_pwm(read_time, value)
    def value_update(self, read_time, temp, target_temp):
        self.temp_samples.append((read_time, temp))
        # Check if the temperature has crossed the target and
        # enable/disable the heater if so.
        if self.heating and temp >= target_temp:
            self.heating = False
            self.check_peaks()
            self.heater.alter_target(self.calibrate_temp - TUNE_PID_DELTA)
        elif not self.heating and temp <= target_temp:
            self.heating = True
            self.check_peaks()
            self.heater.alter_target(self.calibrate_temp)
        # Check if this temperature is a peak and record it if so
        if self.heating:
            self.set_pwm(read_time, self.heater_max_power)
            if temp < self.peak:
                self.peak = temp
                self.peak_time = read_time
        else:
            self.set_pwm(read_time, 0.)
            if temp > self.peak:
                self.peak = temp
                self.peak_time = read_time
    def check_busy(self, eventtime, smoothed_temp, target_temp):
        if self.heating or len(self.peaks) < 12:
            return True
        return False
    # Analysis
    def check_peaks(self):
        self.peaks.append((self.peak, self.peak_time))
        if self.heating:
            self.peak = 9999999.
        else:
            self.peak = -9999999.
        if len(self.peaks) < 4:
            return
        self.calc_pid(len(self.peaks)-1)
    def calc_pid(self, pos):
        temp_diff = self.peaks[pos][0] - self.peaks[pos-1][0]
        time_diff = self.peaks[pos][1] - self.peaks[pos-2][1]
        # Use Astrom-Hagglund method to estimate Ku and Tu
        amplitude = .5 * abs(temp_diff)
        Ku = 4. * self.heater_max_power / (math.pi * amplitude)
        Tu = time_diff
        # Use Ziegler-Nichols method to generate PID parameters
        Ti = 0.5 * Tu
        Td = 0.125 * Tu
        Kp = 0.6 * Ku * heater.PID_PARAM_BASE
        Ki = Kp / Ti
        Kd = Kp * Td
        logging.info("Autotune: raw=%f/%f Ku=%f Tu=%f  Kp=%f Ki=%f Kd=%f",
                     temp_diff, self.heater_max_power, Ku, Tu, Kp, Ki, Kd)
        return Kp, Ki, Kd
    def calc_final_pid(self):
        cycle_times = [(self.peaks[pos][1] - self.peaks[pos-2][1], pos)
                       for pos in range(4, len(self.peaks))]
        midpoint_pos = sorted(cycle_times)[len(cycle_times)/2][1]
        return self.calc_pid(midpoint_pos)
    # Offline analysis helper
    def write_file(self, filename):
        pwm = ["pwm: %.3f %.3f" % (time, value)
               for time, value in self.pwm_samples]
        out = ["%.3f %.3f" % (time, temp) for time, temp in self.temp_samples]
        f = open(filename, "wb")
        f.write('\n'.join(pwm + out))
        f.close()

