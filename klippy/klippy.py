#!/usr/bin/env python2
# Main code for host side printer firmware
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
    usage = "%prog [options] <config file>"
    opts = optparse.OptionParser(usage)
    opts.add_option("-v", action="store_true", dest="verbose",
                    help="enable debug messages")
    opts.add_option("-I", "--input-tty", dest="inputtty",
                    default='/tmp/printer',
                    help="input tty name (default is /tmp/printer)")
    opts.add_option("-i", "--debug-input", dest="debuginput",
                    help="read commands from file instead of from tty port")
    opts.add_option("-o", "--debug-output", dest="debugoutput",
                    help="write output to file instead of to serial port")
    opts.add_option("-l", "--logfile", dest="logfile",
                    help="write log to file instead of stderr")
    opts.add_option("-d", "--dictionary", dest="dictionary", type="string",
                    action="callback", callback=arg_dictionary,
                    help="file to read for mcu protocol dictionary")
    opts.add_option("-c", action="store_true", dest="printerconsole",
                    help="spawn a printer command interactive console, implies '-l klippy.log'")
    options, args = opts.parse_args()
    if len(args) != 1:
        opts.error("Incorrect number of arguments")
    start_args = {'config_file': args[0], 'start_reason': 'startup'}
    # init logging
    input_fd = bglogger = None
    debuglevel = logging.INFO
    if options.verbose:
        debuglevel = logging.DEBUG
    if options.debuginput:
        start_args['debuginput'] = options.debuginput
        debuginput = open(options.debuginput, 'rb')
        input_fd = debuginput.fileno()
    else:
        input_fd = util.create_pty(options.inputtty)
    if options.debugoutput:
        start_args['debugoutput'] = options.debugoutput
        start_args.update(options.dictionary)
    if options.printerconsole:
        bglogger = queuelogger.setup_bg_logging("klippy.log", debuglevel)
        start_args['printerconsole'] = options.printerconsole
        start_args['printerconsole_lock'] = threading.Lock()
    elif options.logfile:
        bglogger = queuelogger.setup_bg_logging(options.logfile, debuglevel)
    else:
        logging.basicConfig(level=debuglevel)
    logging.info("* Starting Klippy...")
    start_args['software_version'] = util.get_git_version()
    if bglogger is not None:
        versions = "\n".join([
            "Args: %s" % (sys.argv,),
            "Git version: %s" % (repr(start_args['software_version']),),
            "CPU: %s" % (util.get_cpu_info(),),
            "Python: %s" % (repr(sys.version),)])
        logging.info(versions)
    elif not options.debugoutput:
        logging.warning("No log file specified! Severe timing issues may result!")
    # start printer.Main() class,
    if bglogger is not None:
        bglogger.clear_rollover_info()
        bglogger.set_rollover_info('versions', versions)
    # - init hardware manager (ie: hw abstraction layer), 
    # - init reactor (ie: fds and timers microthreading),
    # - set klippy._connect as first reactor's task to run
    klippy = printer.Main(input_fd, bglogger, start_args)
    # open, read, parse, validate cfg file, build printer tree
    need_config = klippy.config()
    # printer loop; ends IF printer.Main() returns "exit" or "error_exit"
    while 1:
        # config reload: new hal, new reactor, new tree, new ... printer
        if need_config:
            klippy = printer.Main(input_fd, bglogger, start_args)
            # open, read, parse, validate cfg file, build printer tree
            need_config = klippy.config()
        # reactor go! 
        res = klippy.run()
        # evaluate exit result
        if res in ['exit', 'error_exit']:
            #if options.printerconsole:
                #self.sw._console_th.join()
            # exit from klippy
            if res == 'exit':
                logging.info("* Klippy clean exit.")
            elif res == 'error_exit':
                logging.info("* Klippy exited with error.")
            break
        elif res in ['reload']:
            # reload configuration
            need_config = True
            logging.info("Klippy reloading config and restarting.")
        else:
            # restart without changing configuration
            logging.info("Klippy restarting using the same conf.")
        #
        time.sleep(1.)
        start_args['start_reason'] = res
        # log rollover
        if bglogger is not None:
            bglogger.clear_rollover_info()
            bglogger.set_rollover_info('versions', versions)
    # close logger thread
    if bglogger is not None:
        bglogger.stop()
    # return "res(ult)" to os shell
    sys.exit(res)

if __name__ == '__main__':
    main()

