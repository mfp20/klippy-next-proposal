# Klippy text formatting.
# Klippy custom exceptions handler.
# 
# Copyright (C) 2020    Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
# 
# Examples at the end of this file.

import logging, datetime
from text import MESSAGE
from text import MESSAGE_DESC
import text

def msg(msg):
    # simple string
    if isinstance(msg, str):
        # string have a description = print description
        if msg in MESSAGE_DESC:
            string = MESSAGE_DESC[msg]
        # else print string
        else:
            string = msg
    # simple int
    elif isinstance(msg, int):
        # int is a message code = print description
        if msg in MESSAGE:
            string = MESSAGE_DESC[MESSAGE[msg]]
        # else print int
        else:
            string = msg
    # collection
    else:
        # first is the message id, then all parameters
        text = list(msg)
        if isinstance(msg[0], int):
            string = MESSAGE_DESC[MESSAGE[text.pop(0)]]
            string = string % tuple(text)
        else:
            string = MESSAGE_DESC[text.pop(0)]
            string = string % tuple(text)
    return string

# Klippy Error
class Kerr(Exception):
    def __init__(self, *args):
        self.args = [a for a in args]
        if len(self.args) > 1:
            # multiple args and ... 
            if isinstance(self.args[0], int):
                # ... first arg is a message code ...
                if self.args[0] in MESSAGE and MESSAGE[self.args[0]] in MESSAGE_DESC:
                    self.string = "%s %s" % (datetime.datetime.now(), msg(self.args))
                # ... but unfortunatly is an unknown code.
                else:
                    self.string = "%s Unknown error:" % datetime.datetime.now()
                    for a in args:
                        self.string = self.string + " " + str(a) 
            # ...no code given and...
            else:
                # ... I know the message name ...
                if self.args[0] in MESSAGE_DESC:
                    self.string = "%s %s" % (datetime.datetime.now(), msg(self.args))
                else:
                    # ... I don't know anything.
                    self.string = "%s Unknown error:" % datetime.datetime.now()
                    for a in args:
                        self.string = self.string + " " + str(a)
        elif len(self.args) == 1:
            # single arg and ...
            if isinstance(self.args[0], int):
                if self.args[0] in MESSAGE and MESSAGE[self.args[0]] in MESSAGE_DESC:
                    self.string = "%s %s" % (datetime.datetime.now(), msg(self.args))
                else:
                    self.string = "%s Unknown error: %s." % (datetime.datetime.now(), self.args[0])
            else:
                if self.args[0] in MESSAGE_DESC:
                    self.string = "%s %s" % (datetime.datetime.now(), msg(self.args))
                else:
                    self.string = "%s Unknown error: %s." % (datetime.datetime.now(), self.args[0])
        else:
            self.string = "%s Unknown Error." % datetime.datetime.now()
    def info(self):
        logging.info(self.string)
    def warning(self):
        logging.warning(self.string)
    def debug(self):
        logging.debug(self.string)
    def error(self):
        logging.error(self.string)
        raise

'''
# examples
logging.basicConfig(level=logging.NOTSET)
logging.info(msg("Error test."))

try:
    raise kerr(1)
except kerr as e: e.info()

try:
    raise kerr("msgname")
except kerr as e: e.warning()

try:
    raise kerr(3, "data")
except kerr as e: e.info()

try:
    raise kerr("double", 3893898393, "moredata")
except kerr as e: e.warning()

try:
    raise kerr("triple", "sometext", None, kerr(Exception))
except kerr as e: e.warning()

try:
    raise kerr(35)
except kerr as e: e.warning()

try:
    raise kerr(35, "data")
except kerr as e: e.debug()

try:
    raise kerr("asfrasfr")
except kerr as e: e.debug()

try:
    raise kerr("whtwthrwhtr", kerr(Exception))
except kerr as e: e.error()
'''

