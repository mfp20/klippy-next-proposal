#!/usr/bin/env python3
#
# main(), host side printer firmware
# - parse opts
# - init log, fd and reactor processes
# - init and run printer.Manager
# - restart/reload/save/restore/standby/exit
#
# Copyright (C) 2016-2019 Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2020 Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, sys, time, argparse, multiprocessing
from text import msg
from error import KError as error
import util, process, processlog, processfd, reactor, printer

# root logger (ie: enqueues all messages to log_queue)
log_queue = multiprocessing.Queue(-1)
root = logging.getLogger()
root.addHandler(logging.handlers.QueueHandler(log_queue))
# local logger, propagates to root logger
logger = logging.getLogger("klippy")

ecodes = ['exit', 'error', 'standby', 'save', 'restore', 'restart', 'reload']
def main():
    "Klippy app main()."
    input_fd = None
    # parse command line options
    parser = argparse.ArgumentParser()
    # verbose
    parser.add_argument("-v", "--verbose", dest="verbose",
                    action='store_true',
                    default=False,
                    help="enable debug messages")
    # config_file
    parser.add_argument("-c", "--config-file", dest="config_file",
                    default='printer.cfg',
                    help="configuration file name (default is printer.cfg)")
    # input_tty
    parser.add_argument("-i", "--input-tty", dest="input_tty",
                    default='/tmp/printer',
                    help="input tty name (default is /tmp/printer)")
    # log_dir
    parser.add_argument("-l", "--log-dir", dest="log_dir",
                    default='log',
                    help="log directory (default is 'log')")
    # dictionary
    parser.add_argument("-d", "--dictionary", dest="dict_file", 
                    default=None,
                    help="file to read for mcu protocol dictionary")
    # input_debug
    parser.add_argument("-I", "--input-debug", dest="input_debug",
                    default=None,
                    help="read commands from file instead of tty port")
    # output_debug
    parser.add_argument("-O", "--output-debug", dest="output_debug",
                    default=None,
                    help="write output to file instead of tty port")
    # log_stderr
    parser.add_argument("-L", "--log-stderr", dest="log_stderr",
                    action='store_true',
                    default=False,
                    help="write log to stderr instead of log file")
    # console
    parser.add_argument("-C", "--console", dest="console",
                    action='store_true',
                    default=False,
                    help="spawn a printer interactive console, implies '-l'")
    # single core -> single process (ie: use old reactor)
    parser.add_argument("-S", "--single", dest="single",
                    action='store_true',
                    default=False,
                    help="force single process, ie: use old greenlet-based reactor")
    args = parser.parse_args()
    args.start_reason = 'startup'
    args.software_version = util.get_git_version()
    # setup log
    console_level = None
    file_level = 'info'
    if args.verbose:
        file_level = 'debug'
    if args.log_stderr:
        console_level = file_level
        file_level = None
    ps_log = processlog.Writer("log")
    ps_log.setup(log_queue, console_level, file_level, args.log_dir)
    # setup host I/O process (files and printer tty)
    ps_fd = processfd.FdProcess("fd")
    if args.dict_file:
        args.dictionary = None
        # TODO read dict_file and fill args.dictionary
        #def arg_dictionary(option, opt_str, value, parser):
        #    key, fname = "dictionary", value
        #    if '=' in value:
        #        mcu_name, fname = value.split('=', 1)
        #        key = "dictionary_" + mcu_name
        #    if args.dictionary is None:
        #        args.dictionary = {}
        #    args.dictionary[key] = fname
    if args.input_debug and args.output_debug:
        args.input_fd = args.output_fd = ps_fd.open(args.input_debug)
    elif args.input_debug:
        args.input_fd = ps_fd.open(args.input_debug)
        args.output_fd = ps_fd.open(args.input_tty, mode="w", tty=True)
    elif args.output_debug:
        args.input_fd = ps_fd.open(args.input_tty, mode="r", tty=True)
        args.output_fd = ps_fd.open(args.input_debug)
    else:
        args.input_fd = args.output_fd = ps_fd.open(args.input_tty, mode="r+", tty=True)
    # setup reactor (timers and callbacks)
    ps_reactor = reactor.make("reactor", args.single, args.verbose)
    # setup console
    if args.console:
        args.console = multiprocessing.Lock()
    # services ready, let's start... 
    logger.info("--------------------")
    logger.info("* Starting Klippy...")
    if ps_log is not None:
        versions = "\n".join([
            "Args: %s" % (sys.argv,),
            "Git version: %s" % (repr(args.software_version),),
            "CPU: %s" % (util.get_cpu_info(),),
            "Python: %s" % (repr(sys.version),)])
        ps_log.rollover_clear_info()
        ps_log.rollover_set_info('versions', versions)
        for l in [line for line in versions.split('\n')]:
            logger.info(l)
    elif not args.output_debug:
        logger.warning("No log file specified! Severe timing issues may result!")
    # start printer.Master() class,
    myprinter = printer.Master("printer", args, ecodes)
    # open, read, parse, validate cfg file, build printer tree
    need_config = myprinter.setup()
    # printer restart/reload/exit loop
    while 1:
        # config reload: new hal, new reactor, new tree, new ... printer
        if need_config:
            need_config = myprinter.setup()
        # reactor go! 
        exit_reason = myprinter.run()
        # evaluate exit reason (result)
        if exit_reason in ['exit', 'error']:
            # exit from klippy
            if exit_reason == 'exit':
                logger.info("* Klippy clean exit.")
            elif exit_reason == 'error':
                logger.info("* Klippy exited with error.")
            break
        elif exit_reason == 'restart':
            # restart without changing configuration
            logger.info("Klippy restarting using the same conf.")
        elif exit_reason == 'reload':
            # reload configuration and restart
            need_config = True
            logger.info("Klippy restarting using a fresh conf.")
        else:
            # unknown result
            logger.warning("Unknown exit code (%s). Given reason: '%s'", exit_code, exit_reason)
            break
        #
        args.start_reason = myprinter.cleanup(exit_reason)
        time.sleep(1.)
        # log rollover
        if ps_log is not None:
            #ps_log.rollover_do()
            pass
    # graceful stop
    for w in reversed(workers.keys()):
        worker_stop(w)
    # open all the loops
    process.running.clear()
    # try again, stronger
    for w in reversed(workers.values()):
        if w.is_alive():
            w.terminate()
            w.join()
            # python > 3.7
            #w.close()
    # return exit_code to os shell
    sys.exit(ecodes.index(exit_reason))

if __name__ == '__main__':
    try:
        # TODO why this gives a RuntimeError???
        # in theory this is the first instruction to be executed
        # but it says the context has been already set
        #multiprocessing.set_start_method('spawn')
        #multiprocessing.set_start_method('forkserver')
        pass
    except RuntimeError:
        print("ERROR")
        pass
    #print(multiprocessing.get_start_method())
    multiprocessing.current_process().name = 'main'
    main()

