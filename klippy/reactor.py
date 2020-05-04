# Timers and callbacks
#
# Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, sys, time, multiprocessing, concurrent.futures, random
from text import msg
from error import KError as error
import process, tree, chelper
logger = logging.getLogger(__name__)

_NOW = 0.
_NEVER = 9999999999999999.

#
# Multiprocessing version (ie: cpu cores > 3)
#

class ProcessTimer:
    def __init__(self, ident, waketime, callback = None):
        self.id = ident
        self.waketime = waketime
        self.callback = callback

class ProcessCompletion:
    "A concurrent.futures.Future wrapped with helper methods."
    def __init__(self, future = None, subcompletions = None):
        self.future = future
        if subcompletions:
            self.subs = [c.future for c in subcompletions]
        else:
            self.subs = None
        self.result = None
    def isdone(self):
        "Return True if we have a result."
        if self.result:
            return True
        else:
            if self.future:
                return self.future.done()
            else:
                return False
    def result(self, timeout = None):
        "Try to get a result."
        if not isdone():
            if self.subs:
                done, not_done = concurrent.futures.wait(self.subs, timeout, FIRST_COMPLETED)
                if len(done) == len(self.subs):
                    self.result = done
                    return self.result
            else:
                done, not_done = concurrent.futures.wait([self.future], timeout, ALL_COMPLETED)
                if len(done) > 0:
                    self.result = done[0]
                    return self.result
        return None
    def wait(self, timeout = None):
        "Wait for a result."
        if self.subs:
            self.result, not_done = concurrent.futures.wait(self.subs, timeout, ALL_COMPLETED)
        else:
            self.result = self.future.result(timeout)
        return self.result

class ProcessCallback:
    "4-modes callback: manual invoke, scheduled invoke, async (ie: run now, get result later), async-multi (ie: wait for multiple completions to complete before setting the result)."
    def __init__(self, callback, timer = None, asyn = False, subcompletions = None):
        self.callback = callback
        #
        self.timer = timer
        if timer:
            self.timer.callback = self.invoke
        #
        if asyn:
            if subcompletions:
                self.completion = ProcessCompletion(None, subcompletions)
            else:
                self.completion = ProcessCompletion(None)
    def invoke(self, eventtime):
        "Invoke callback on timer trigger."
        self.callback(eventtime)
        return _NEVER
    def wait(self, timeout = None):
        "Wait for result of an async callback."
        return self.completion.wait(timeout)
    def result(self):
        "Return the current result."
        return self.completion.result
            
class Process(process.Base, tree.Part):
    "Multiprocessing reactor."
    NEVER = _NEVER
    def __init__(self, name, starttime = _NEVER, verbose = False):
        process.Base.__init__(self, name)
        tree.Part.__init__(self, name)
        # scheduled timers (note: copied on fork/spawn, local copy have callbacks)
        self._timers = []
        # start scheduler
        process.worker_start(self, (self._subpipe,starttime,verbose))
        # async workers (note: not in the timers context)
        self._async = concurrent.futures.ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()-3)
        if verbose:
            timer = self.timer(None, self.monotonic(), self._print_overhead)
            self.timer_add(timer)
        self.ready = True
    def __getstate__(self):
        "Removes unpickle-ables."
        # TODO
        state = self.__dict__.copy()
        del state['monotonic']
        del state['_timers']
        del state['_pipe']
        del state['_async']
        return state
    def __setstate__(self, state):
        "Set back unpickle-ables."
        # TODO
        self.__dict__.update(state)
        self.monotonic = chelper.get_ffi()[1].get_monotonic
        self._timers = []
        self._pipe, subpipe = multiprocessing.Pipe()
        process.worker_start(self, (subpipe,_NEVER))
        self._async = concurrent.futures.ProcessPoolExecutor(max_workers=multiprocessing.cpu_count())
    def _show_details(self, indent = 0):
        "Return formatted details about reactor node."
        txt = "\t"*(indent+1) + "--------------------- (timers)\n"
        for t in sorted(self._timers):
            txt = txt + '\t' * (indent+1) + "- " + str(t.id).ljust(20, " ") + str(t.waketime).ljust(20, " ") + str(t.callback).ljust(20, " ") + "\n"
        return txt
    def _print_overhead(self, eventtime):
        "Print reactor overhead for debugging purposes."
        oh = (self.monotonic()-eventtime)
        logger.debug("--- reactor: timers %d, overhead %1.3fms ---", len(self._timers), oh*1000)
        # the more overhead, the more debug messages
        return eventtime+((1/oh)/1000)
    def _check_timers(self, eventtime):
        "Trigger expired timers and set next wakeup time."
        if eventtime < self._next_timer:
            return min(1., max(.001, self._next_timer - eventtime))
        self._next_timer = _NEVER
        for t in self._timers:
            waketime = t.waketime
            if eventtime >= waketime:
                t.waketime = waketime = _NEVER
                self._subpipe.send({'todo':t.id, 'eventtime':eventtime})
            # update next wakeup time
            self._next_timer = min(self._next_timer, waketime)
        if eventtime >= self._next_timer:
            return 0.
        return min(1., max(.001, self._next_timer - self.monotonic()))
    def _dispatch(self, eventtime, obj):
        "Dispatch an incoming command accordingly."
        if 'showth' in obj:
            self._subpipe.send({'showth':self._showth(), 'eventtime':eventtime})
        elif 'timer' in obj:
            self._timers.append(obj['timer'])
            self._next_timer = min(self._next_timer, obj['timer'].waketime)
        elif 'pause' in obj:
            delay = obj['pause'] - self.monotonic()
            if delay > 0.:
                time.sleep(delay)
        elif 'update' in obj:
            self._timers[obj['update']].waketime = obj['waketime']
            self._next_timer = min(self._next_timer, obj['waketime'])
        elif 'remove' in obj:
            self._timers.pop(obj['remove'])
        else:
            raise error("Unknown message: %s", obj)
    def _runner(self, *args):
        "Process runner. Reactor Scheduler."
        self._subpipe = args[0]
        self.message = {}
        self._next_timer = args[1]
        while self._running.is_set():
            # emit timestamp
            eventtime = self.monotonic()
            # check timers
            timeout = self._check_timers(eventtime)
            # poll pipe for new messages
            if self._subpipe.poll(timeout):
                self._dispatch(eventtime, self._subpipe.recv())
    # reactor
    def pause(self, waketime):
        self.send({'pause':waketime})
        delay = waketime - self.monotonic()
        if delay > 0.:
            time.sleep(delay)
    #
    # timers
    def timer(self, ident = None, waketime = None, callback = None):
        "Create a new event timer."
        if not ident:
            ident = len(self._timers)
        if not waketime:
            waketime = _NEVER
        return ProcessTimer(ident, waketime, callback)
    def timer_add(self, timer):
        "Schedule an event."
        # remove callback (to make it pickle-able)
        cb = timer.callback
        timer.callback = None
        # send new timer to reactor process
        self.send({'timer':timer})
        # set callback and register
        timer.callback = cb
        self._timers.append(timer)
        return timer
    def timer_register(self, func):
        return self.timer_add(self.timer(None, None, func))
    def timer_update(self, timer_handler, waketime):
        "Update event waketime."
        self.send({'update':timer_handler.id, 'waketime':waketime})
        timer_handler.waketime = waketime
    def timer_cancel(self, timer_handler):
        "Cancel an event."
        self.send({'remove':timer_handler.id})
        self._timers.pop(timer_handler.id)
    # callbacks
    def callback(self, callback, waketime = _NOW):
        "Schedule a callback event."
        timer = ProcessTimer(len(self._timers), waketime)
        cb = ProcessCallback(callback, timer)
        self.timer_add(timer)
        return cb
    def callback_async(self, callback):
        "Run an async callback."
        cb = ProcessCallback(callback, None, True)
        cb.completion.future = self._async.submit(cb.callback, self.monotonic(), None)
        cb.completion.future.add_done_callback(cb.completion.wait)
        return cb.completion
    def callback_multi(self, completions, callback = None):
        "Return a completion that completes when all completions in the given list complete."
        cb = ProcessCallback(None, None, True, completions)
        cb.completion.future = self._async.submit(cb.completion.wait, None, None)
        # if callback exist, call on completion
        if callback:
            cb.completion.future.add_done_callback(callback)
        return cb.completion
        
#
# Co-routine (greenlet) version (ie: cpu cores < 3)
#

# NOTE: need to test multiprocessing on single core cpu first.
# If older single-core boards (ex: Rpi 0-2) die for too many context switches, 
# paste here pristine old reactor and adapt it to have the same class fingerprint.

# single process, fallback in case poll method isn't available
class GreenSelect:
    # TODO
    pass

# single process, single thread reactor
class GreenPoll(GreenSelect):
    # TODO
    pass

def make(name, single, verbose):
    # Use multiprocessing if cpu cores > 3 and not forced to single process
    if multiprocessing.cpu_count() > 3 and not single:
        return Process(name, _NEVER, verbose)
    else:
        # Use the poll based reactor if it is available
        try:
            select.poll
            Reactor = GreenPoll
        except:
            Reactor = GreenSelect
        return Reactor()

