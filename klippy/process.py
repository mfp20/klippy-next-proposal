# Process base class
#
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, multiprocessing, threading, collections
from text import msg
from error import KError as error
import chelper
logger = logging.getLogger(__name__)

# used in all child processes to terminate loops and help join()/terminate()
running = multiprocessing.Event()
running.set()

# process tools
workers = collections.OrderedDict()
# describe processes and threads
pt = collections.OrderedDict()
pt_no = 0
pt_txt = ''

def worker_start(ps, args = None, daemon = True):
    "Start the given Klippy's process."
    if not args:
        args = ()
    ps._ps = multiprocessing.Process(name=ps._name, target=ps._runner, args=args, daemon=daemon)
    ps._ps.start()
    workers[ps._name] = ps

def _worker_collect(ps):
    "Compose processes&threads tree in pt_txt var for later use."
    global pt
    global pt_no
    global pt_txt
    pt[ps['p']] = ps['t']
    pt_no = pt_no + 1
    if pt_no == len(workers):
        pt_txt = 'Processes&Threads:\n'
        logger.debug(pt_txt)
        tab = ''
        for name, threads in pt.items():
            line = tab + "* process " + name
            pt_txt = pt_txt + line + '\n'
            logger.debug(line)
            for t in threads:
                line = tab + "\t- thread " + t
                pt_txt = pt_txt + line + '\n'
                logger.debug(line)
            if name == 'main':
                tab = '\t'
        pt = {}
        pt_no = 0
def workers_collect():
    "Collect processes and threads description."
    t = []
    for th in threading.enumerate():
        if th.name != 'MainThread':
            t.append(th.name)
    pt[multiprocessing.current_process().name] = t
    for p in multiprocessing.active_children():
        workers[p.name].showth()

def worker_stop(name, wait=1):
    "Stop the given Klippy's process."
    workers[name]._ps.join(wait)

class Base:
    "Base class for Klippy's processes."
    def __init__(self, name):
        self._name = name
        self._ps = None
        self._running = running
        # IPC
        self._pipe, self._subpipe = multiprocessing.Pipe()
        # system timer
        self.monotonic = chelper.get_ffi()[1].get_monotonic
    def setup(self):
        "To be overloaded by a process child class."
        logger.warning("Process not configured.")
        worker_start(self)
    def _runner(self, *args):
        "To be overloaded by a process child class."
        "Process worker."
        while self._running.is_set():
            logger.warning("Process not configured.")
            sleep(1)
    def poll(self, *args):
        "Poll the local connection end for news incoming from sub-process."
        # if no args, no timeout (or infinite wait)
        if len(args) > 0:
            # timeout can be "None" for infinite wait
            return self._pipe.poll(args[0])
        else:
            # if no timeout is supplied, it doesn't block
            return self._pipe.poll()
    def recv(self):
        "Receive from sub-process."
        return self._pipe.recv()
    def send(self, obj):
        "Send to the sub-process."
        self._pipe.send(obj)
    def _showth(self):
        "Collect local process&threads names."
        pt = {'p':multiprocessing.current_process().name}
        t = []
        for th in threading.enumerate():
            if th.name != 'MainThread':
                t.append(th.name)
        pt['t'] = t
        return pt
    def showth(self):
        "Query local process&threads names."
        self.send({'showth':self.monotonic()})
        return None

