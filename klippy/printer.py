# Printer Master: 
# - setup,
# - events loop,
# - setup restart/reload/save/restore/standby/exit
# 
# Copyright (C) 2016-2018 Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, time, threading, multiprocessing
from text import msg
from error import KError as error
import tree, chelper, process, hal
logger = logging.getLogger(__name__)

# - init hardware manager (ie: hw abstraction layer), 
# - manage processes and threads
class Master(tree.Root):
    def __init__(self, name, args, exit_codes):
        super().__init__(name, hal = None)
        # system timer
        self.monotonic = chelper.get_ffi()[1].get_monotonic
        #
        self.args = args
        self.ecodes = exit_codes
        # message receiver (from all subprocesses)
        self._receive = multiprocessing.Queue(-1)
        # status&events
        self.status = 'startup'
        self.event_handlers = {}
        self.exit_reason = None
        # start init
        systime = time.time()
        monotime = self.monotonic()
        logger.info("* Init printer at %s (systime %.1f, monotime %.1f)", time.asctime(time.localtime(systime)), systime, monotime)
        # add reactor child
        self.child_add(process.workers["reactor"])
        # init hal and set as child
        self.hal = hal.Manager(self)
        self.child_add(self.hal)
    def _show_details(self, indent = 0):
        "Return formatted details about printer node."
        txt = "\t"*(indent+1) + "--------------------- (events)\n"
        for e in sorted(self.event_handlers):
            methparts = str(self.event_handlers[e]).split(".",1)[1].split("instance", 1)[0].split(" ")
            meth = methparts[2] + "." + methparts[0]
            txt = txt + str('\t' * (indent+1) + "- " + str(e).ljust(30, " ") + meth[1:] + "\n")
        return txt
    def _register(self):
        "Register local commands."
        self.hal.get_commander().register_commands(self)
    #
    # setup methods
    def _read_config(self):
        "Open and read config file. Return parser."
        cparser = tree.Config(self.hal)
        cparser.read()
        return cparser
    def _connect(self, eventtime):
        "Reactor task: identify mcu and complete controller init."
        #logger.debug(self.hal.master.show(plus="attrs,details,deep")+self.hal.master.spare.show(plus="deep"))
        # exec mcu identify handlers
        self.event_send("klippy:mcu_identify")
        self._set_status('controlled')
        #
        # if command line options requested the printer console,
        # a lock is placed in order to give the console
        # a chance to investigate the mcu before the printer connects.
        # Console user must issue the "continue" command to resume
        # normal operations.
        if self.args.console:
            self.args.console.acquire()
        #
        # exec connect handlers
        self.event_send("klippy:connect")
        self._set_status('connected')
        # exec ready handlers
        self.event_send("klippy:ready")
        self._set_status('ready')
    #
    # process cfg file, build printer tree, enqueue _connect()
    def setup(self):
        "Read config file, start msg receive threads, build printer tree."
        self.cparser = self._read_config()
        # spawn threads to receive sub-processes's messages
        self.thread = []
        for p in process.workers:
            th = threading.Thread(name=p, target=self._receive_msg, args=(p,))
            th.start()
            self.thread.append(th)
        # collect processes and threads description for later use
        process.workers_collect()
        # turn config into a printer tree
        builder = tree.Builder(self.hal, self.cparser)
        systime = time.time()

        logger.info("* Init complete at %s (%.1f %.1f)", time.asctime(time.localtime(systime)), time.time(), self.hal.get_reactor().monotonic())
        # enqueue self._connect in reactor's task queue
        self.hal.get_reactor().callback(self._connect)
        return False
    #
    #
    def _receive_msg(self, *args):
        "Receive messages from sub-process and enqueue in receiver queue."
        # process messages incoming from sub-processes pipes
        while process.running.is_set():
            # wait for new messages
            if process.workers[args[0]].poll(None):
                obj = process.workers[args[0]].recv()
                if 'showth' in obj:
                    self._receive.put(obj)
                else:
                    # envelope
                    msg = {args[0]:obj}
                    # enqueue in main queue
                    self._receive.put(msg)
    #
    def _set_status(self, message):
        "Set printer status."
        logger.warning("TODO _set_status()")
    def run(self):
        ""
        # printer loop (check messages and execute)
        try:
            self.terminate = False
            # process sub-processes messages
            while process.running.is_set() and not self.terminate:
                # block to wait for new messages
                obj = self._receive.get()
                if 'showth' in obj:
                    process._worker_collect(obj['showth'])
                elif 'terminate' in obj:
                    self.terminate = True
                elif 'log' in obj:
                    # TODO
                    obj = obj['log']
                    if 'asasdads' in obj:
                        pass
                    else:
                        logger.warning("UNKNOWN MSG %s", obj)
                elif 'fd' in obj:
                    # TODO
                    obj = obj['fd']
                    if 'asdasdds' in obj:
                        pass
                    else:
                        logger.warning("UNKNOWN MSG %s", obj)
                elif 'reactor' in obj:
                    obj = obj['reactor']
                    if 'todo' in obj:
                        # exec timer callback and return the new waketime to reactor
                        tid = obj['todo']
                        eventtime = obj['eventtime']
                        waketime = self.hal.get_reactor()._timers[tid].callback(eventtime)
                        self.hal.get_reactor().send({'update':tid,'eventtime':eventtime,'waketime':waketime})
                    else:
                        logger.warning("UNKNOWN MSG %s", obj)
                elif 'console' in obj:
                    # TODO
                    obj = obj['console']
                    if 'asdasdsd' in obj:
                        pass
                    else:
                        logger.warning("UNKNOWN MSG %s", obj)
                else:
                    logger.warning("UNKNOWN MSG %s", obj)
            self.hal.get_reactor().stop()
        except:
            logger.exception("Unhandled exception during run.")
            return "error"
        # restart flags
        try:
            #self.event_send("klippy:disconnect")
            pass
        except:
            logger.exception("Unhandled exception on event klippy:disconnect.")
            return "error"
        return self.run_result
    #
    # events management
    def event_register_handler(self, event, callback):
        self.event_handlers.setdefault(event, []).append(callback)
    def event_send(self, event, *params):
        result = []
        try:
            for cb in self.event_handlers.get(event, []):
                result.append(cb(*params))
        except error as e:
            logger.exception("Klippy Error: %s", e.msg())
            self._set_status(e.status())
            return []
        except Exception as e:
            logger.exception("Unhandled exception: %s" % str(e))
            self._set_status('offline')
            return []
        return result
    # any part can call this method to shut down the printer
    # when the method is called, printer.Main spread the shutdown message
    # to other parts with registered event handler
    def call_shutdown(self, message):
        # single shutdown guard
        if self.is_shutdown:
            return
        self.is_shutdown = True
        #
        self._set_status("%s %s" % (message, msg("shutdown")))
        for cb in self.event_handlers.get("klippy:shutdown", []):
            try:
                cb()
            except error as e:
                logger.exception("Klippy Error: %s", e.msg())
                self._set_status(e.status())
                return
            except Exception as e:
                logger.exception("Unhandled exception during shutdown: %s" % str(e))
    # same of call_shutdown(), but called from another thread
    def call_shutdown_async(self, message):
        self.hal.get_reactor().register_async_callback((lambda e: self.call_shutdown(message)))
    #
    # misc helpers
    def get_args(self):
        return self.args
    def get_status(self):
        return self.status_message
    #
    def set_rollover_info(self, name, info, log=True):
        if log:
            logger.info(info)
        if self.bglogger is not None:
            self.bglogger.set_rollover_info(name, info)
    # close the running printer
    def shutdown(self, reason):
        logger.info("SHUTDOWN (%s)", reason)
        if reason == 'exit':
            pass
        elif reason == 'error':
            pass
        elif reason == 'restart':
            pass
        elif reason == 'restart_mcu':
            pass
        elif reason == 'reconf':
            pass
        else:
            raise error("Unknown shutdown reason (%s)." % reason)
        if self.run_result is None:
            self.run_result = reason
        # terminate reactor loop
        self.hal.get_reactor().end()
    #
    def stop(self, run_result = 'restart'):
        ""
        self.run_result = run_result
        for th in self.thread:
            th.join()
        time.sleep(1)
        self.terminate = True
    # called from __main__ loop
    def cleanup(self, reason):
        logger.info("CLEANUP (%s)", reason)
        if reason == 'exit':
            pass
        elif reason == 'error':
            pass
        elif reason == 'restart':
            # TODO: in order to avoid reconfiguring, reactor must be revisited
            #       to allow for resetting it without the need to re-register everything.
            #self.n.children["reactor"] = reactor.Reactor(self.hal, self.hal.node("reactor")) 
            pass
        elif reason == 'reload':
            self.tree = None
            self.hal.get_reactor().cleanup()
            self.hal.cleanup()
            self.hal = None
            self.status_message = msg("startup")
            self.is_shutdown = False
            self.run_result = None
            self.event_handlers = {}
        else:
            raise error("Unknown exit reason (%s).", reason)
        return reason
    #
    # commands
    def _cmd__SHOW(self, params):
        "Shows the printer's topology."
        self.hal.get_commander().respond_info(self.tree.show(), log=False)
    def _cmd__SHOW_FULL(self, params):
        "Shows the printer's tree. Full details."
        self.hal.get_commander().respond_info(self.tree.printer.show(plus="attrs,details,deep")+self.tree.spare.show(plus="deep"), log=False)

