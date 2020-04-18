#!/usr/bin/env python2
#
# Main code to exec host side printer firmware
# - parse opts
# - setup input/output
# - setup logs
# - main loop
#
# Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import optparse, logging, time, sys, threading
import util, printer, queuelogger

def arg_dictionary(option, opt_str, value, parser):
    key, fname = "dictionary", value
    if '=' in value:
        mcu_name, fname = value.split('=', 1)
        key = "dictionary_" + mcu_name
    if parser.values.dictionary is None:
        parser.values.dictionary = {}
    parser.values.dictionary[key] = fname

def main():
    # parse command line options
    usage = "%prog [options]"
    opts = optparse.OptionParser(usage)
    # config_file
    opts.add_option("-c", "--config-file", dest="config_file",
                    default='printer.cfg',
                    help="configuration file name (default is printer.cfg)")
    # input_tty
    opts.add_option("-i", "--input-tty", dest="input_tty",
                    default='/tmp/printer',
                    help="input tty name (default is /tmp/printer)")
    # log_file
    opts.add_option("-l", "--log-file", dest="log_file",
                    default='klippy.log',
                    help="log file name (default is klippy.log)")
    # verbose
    opts.add_option("-v", "--verbose", action="store_true", dest="verbose",
                    help="enable debug messages")
    # dictionary
    opts.add_option("-d", "--dictionary", dest="dictionary", type="string",
                    action="callback", callback=arg_dictionary,
                    help="file to read for mcu protocol dictionary")
    # input_debug
    opts.add_option("-I", "--input-debug", dest="input_debug",
                    help="read commands from file instead of tty port")
    # output_debug
    opts.add_option("-O", "--output-debug", dest="output_debug",
                    help="write output to file instead of serial port")
    # log_stderr
    opts.add_option("-L", "--log-stderr", action="store_true", dest="log_stderr",
                    help="write log to stderr instead of log file")
    # console
    opts.add_option("-C", "--console", action="store_true", dest="console",
                    help="spawn a printer interactive console, implies '-l'")
    options, args = opts.parse_args()
    # make start_args
    start_args = {'config_file': options.config_file, 'start_reason': 'startup'}
    # init logging
    input_fd = bglogger = None
    debuglevel = logging.INFO
    if options.verbose:
        debuglevel = logging.DEBUG
    # setup input
    if options.input_debug:
        start_args['input_debug'] = options.input_debug
        input_debug = open(options.input_debug, 'rb')
        input_fd = input_debug.fileno()
    else:
        input_fd = util.create_pty(options.input_tty)
    # setup output
    if options.output_debug:
        start_args['output_debug'] = options.output_debug
        start_args.update(options.dictionary)
    # setup logging
    if options.log_stderr:
        logging.basicConfig(level=debuglevel)
    else:
        bglogger = queuelogger.setup_bg_logging(options.log_file, debuglevel)
    # setup console
    if options.console:
        start_args['console'] = threading.Lock()
    # start
    logging.info("* Starting Klippy...")
    start_args['software_version'] = util.get_git_version()
    if bglogger is not None:
        versions = "\n".join([
            "Args: %s" % (sys.argv,),
            "Git version: %s" % (repr(start_args['software_version']),),
            "CPU: %s" % (util.get_cpu_info(),),
            "Python: %s" % (repr(sys.version),)])
        logging.info(versions)
    elif not options.output_debug:
        logging.warning("No log file specified! Severe timing issues may result!")
    # start printer.Main() class,
    if bglogger is not None:
        bglogger.clear_rollover_info()
        bglogger.set_rollover_info('versions', versions)
    # - init hardware manager (ie: hw abstraction layer), 
    # - init reactor (ie: fds and timers microthreading),
    # - set klippy._connect as first reactor's task to run
    ecodes = ['exit', 'error', 'restart', 'reconf']
    klippy = printer.Main(input_fd, bglogger, start_args, ecodes)
    # open, read, parse, validate cfg file, build printer tree
    need_config = klippy.setup()
    # printer loop
    while 1:
        # config reload: new hal, new reactor, new tree, new ... printer
        if need_config:
            need_config = klippy.setup()
        # reactor go! 
        exit_reason = klippy.run()
        # evaluate exit reason (result)
        if exit_reason in ['exit', 'error']:
            # exit from klippy
            if exit_reason == 'exit':
                logging.info("* Klippy clean exit.")
            elif exit_reason == 'error':
                logging.info("* Klippy exited with error.")
            break
        elif exit_reason == 'restart':
            # restart without changing configuration
            logging.info("Klippy restarting using the same conf.")
        elif exit_reason == 'reconf':
            # reload configuration and restart
            need_config = True
            logging.info("Klippy restarting using a fresh conf.")
        else:
            # unknown result
            logging.warning("Unknown exit code (%s). Given reason: '%s'", exit_code, exit_reason)
            break
        #
        start_args['start_reason'] = klippy.cleanup(exit_reason)
        time.sleep(1.)
        # log rollover
        if bglogger is not None:
            bglogger.clear_rollover_info()
            bglogger.set_rollover_info('versions', versions)
    #
    # close logger thread
    if bglogger is not None:
        bglogger.stop()
    # return exit_code to os shell
    sys.exit(ecodes.index(exit_reason))

if __name__ == '__main__':
    main()

