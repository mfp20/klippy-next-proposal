# Logging facility
#
# Copyright (C) 2020  Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, os, multiprocessing, time
from logging import handlers

from text import msg
from error import KError as error
import process
logger = logging.getLogger(__name__)

class FilterMeta(logging.Filter):
    "Adds meta information to logger messages."
    def filter(self, record):
        # debug
        if record.levelno <= 10:
            record.meta = record.levelname.ljust(8, " ") + "] ["
        # info
        if record.levelno > 10:
            record.meta = " ".ljust(8, " ") + "] ["
        # warning
        if record.levelno > 20:
            record.meta = record.levelname.ljust(8, " ") + "] ["
        #
        record.meta = record.meta + record.name.ljust(8, " ")
        # error
        if record.levelno > 30:
            pass
        # critical
        if record.levelno > 40:
            pass
        return True

class FilterMetaDevel(logging.Filter):
    "Adds meta debug information. For development purposes."
    def filter(self, record):
        if record.levelno > 50:
            record.meta = "DEVEL:" + record.processName + ":" + record.filename + ":" + str(record.lineno) + ":" + record.funcName
        return True

class FilterMetaDebug(logging.Filter):
    "Adds meta debug information."
    justmax = 30
    def filter(self, record):
        extras = record.processName + ":" + record.filename + ":" + str(record.lineno) + ":" + record.funcName
        self.justmax = max(self.justmax, len(extras))
        record.meta = record.levelname.ljust(8, " ") + "] [" + extras.ljust(self.justmax, " ")
        return True

# to be applied after Meta filters
class FilterMultiline(logging.Filter):
    "Format multiline text messages."
    def filter(self, record):
        lines = str(record.msg).split('\n')
        if len(lines) > 1:
            if hasattr(record,"meta"):
                spaces = len(str(record.created))+len(record.meta)+10
            else:
                spaces = len(str(record.created))+10
            message = lines[0]+"\n"
            for l in lines[1:]:
                message = message + " "*spaces + l + "\n"
            record.msg = message.strip()
        return True

# log listener for central logging of multiprocessing app
# once started, reads from the given queue and writes to console/file
class Writer(process.Base):
    "Background logging process. Reads from queue, writes to console and file accordingly."
    formatter = logging.Formatter("%(asctime)s [%(meta)-8s] %(message)s", "%Y-%m-%d %H:%M:%S")
    def setup(self, log_queue, console_level: str = 'info', file_level: str = 'debug', log_dir: str = None, file_size:  int = 10485760):
        self.log_queue = log_queue
        self.rollover_info = {}
        # init root logger
        logger = logging.getLogger()
        logger.handlers = []
        if console_level:
            ch = logging.StreamHandler()
            ch.setLevel(console_level.upper())
            ch.addFilter(FilterMeta())
            ch.addFilter(FilterMetaDevel())
            if console_level == 'debug':
                ch.addFilter(FilterMetaDebug())
            ch.addFilter(FilterMultiline())
            ch.setFormatter(self.formatter)
            logger.addHandler(ch)
        if file_level and log_dir:
            fh = handlers.RotatingFileHandler(os.path.join(log_dir, f"{self.name}.log"), 'a', file_size, 10)
            fh.setLevel(file_level.upper())
            fh.addFilter(FilterMeta())
            fh.addFilter(FilterMetaDevel())
            if file_level == 'debug':
                fh.addFilter(FilterMetaDebug())
            fh.addFilter(FilterMultiline())
            fh.setFormatter(self.formatter)
            logger.addHandler(fh)
        logger.setLevel(level=logging.DEBUG)
        process.worker_start(self)
    # runner
    def _runner(self, *args):
        while process.running.is_set():
            while not self.log_queue.empty():
                record = self.log_queue.get()
                logger = logging.getLogger(record.name)
                logger.handle(record)
            if self._subpipe.poll():
                obj = self._subpipe.recv()
                if 'showth' in obj:
                    self._subpipe.send({'showth':self._showth(), 'eventtime':0.})
            time.sleep(0.1)
    def rollover_set_info(self, name, info):
        self.rollover_info[name] = info
    def rollover_clear_info(self):
        self.rollover_info.clear()
    def rollover_do(self):
        # TODO
        handlers.RotatingFileHandler.doRollover(self)
        lines = [self.rollover_info[name] for name in sorted(self.rollover_info)]
        lines.append("=============== Log rollover at %s ===============" % (time.asctime(),))
        #self.emit(logger.makeLogRecord({'msg': "\n".join(lines), 'level': logging.INFO}))

