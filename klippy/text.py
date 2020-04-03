# Klippy text messages.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging

# code to message name
MESSAGE = {
        # 0-99: reserved
        0: "unknown",
        1: "msgname",
        2: "no description",
        3: "single",
        4: "double",
        5: "triple",
        # 100-999: klippy
        100: "ready",
        101: "startup",
        102: "restart",
        103: "shutdown",
        104: "errorproto",
        105: "errormcuconnect",
        106: "noexist1",
        # 1000-1999: gcode
        # 2000-2999: controller
        2000: "Timer too close",
        2001: "No next step",
        2002: "Missed scheduling of next ",
        2003: "ADC out of range",
        2004: "Rescheduled timer in the past",
        2005: "Stepper too far in past",
        2006: "Command request",
        # 3000-3999: power&heat
        # 4000-4999: toolhead&kinematic
        # 5000-5999: composites
        # 6000-6999: parts
        # 10000- : plugins
}

# message name to description
MESSAGE_DESC = {
        "unknown": "Unknown MESSAGE",
        "msgname": "Description",
        "orphaned": "Description",
        "single": "%s",
        "double": "%s %s",
        "triple": "%s %s %s",
        "ready": "Printer is ready",
        "startup": "Printer is not ready\nThe klippy host software is attempting to connect. Please retry in a few moments.",
        "restart": "Once the underlying issue is corrected, use the \"RESTART\" command to reload the config and restart the host software.\nPrinter is halted",
        "shutdown": "Once the underlying issue is corrected, use the \"RESTART_FIRMWARE\" command to reset the firmware, reload the config, and restart the host software.\nPrinter is shutdown",
        "errorproto": "This type of error is frequently caused by running an older version of the firmware on the micro-controller (fix by recompiling and flashing the firmware). Once the underlying issue is corrected, use the \"RESTART\" command to reload the config and restart the host software.\nProtocol error connecting to printer",
        "errormcuconnect": "Once the underlying issue is corrected, use the \"RESTART_FIRMWARE\" command to reset the firmware, reload the config, and restart the host software.\nError configuring printer",
        "noexist1": "%s doesn't exist.",
        "Timer too close": "This is generally indicative of an intermittent communication failure between micro-controller and host.",
        "No next step": "This is generally indicative of an intermittent communication failure between micro-controller and host.",
        "Missed scheduling of next ": "This is generally indicative of an intermittent communication failure between micro-controller and host.",
        "ADC out of range": "This generally occurs when a heater temperature exceeds its configured min_temp or max_temp.",
        "Rescheduled timer in the past": "This generally occurs when the micro-controller has been requested to step at a rate higher than it is capable of obtaining.",
        "Stepper too far in past": "This generally occurs when the micro-controller has been requested to step at a rate higher than it is capable of obtaining.",
        "Command request": "This generally occurs in response to an M112 G-Code command or in response to an internal error in the host software.",
}

# developer maintenance utility: prints out all codes without descriptions
def no_desc_list():
    logging.info("Codes without description: ")
    for c in MESSAGE:
        if MESSAGE[c] not in MESSAGE_DESC:
            logging.info("  * (%s) %s", c, MESSAGE[c])

# developer maintenance utility: prints out all orphaned descriptions
def no_short_list():
    logging.info("Orphaned descriptions: ")
    for k in MESSAGE_DESC.keys():
        if k not in MESSAGE.values():
            logging.info("  * %s - %s", k, MESSAGE_DESC[k])

