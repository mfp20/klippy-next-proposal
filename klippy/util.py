# Low level unix utility functions
#
# Copyright (C) 2016  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, signal, pty, os, fcntl, termios, subprocess
from text import msg
from error import KError as error
logger = logging.getLogger(__name__)

# Return the SIGINT interrupt handler back to the OS default
def fix_sigint():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
fix_sigint()

# Set a file-descriptor as non-blocking
def set_nonblock(fd):
    fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)

# Clear HUPCL flag
def clear_hupcl(fd):
    attrs = termios.tcgetattr(fd)
    attrs[2] = attrs[2] & ~termios.HUPCL
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    except termios.error:
        pass

# Support for creating a pseudo-tty for emulating a serial port
def create_pty(ptyname):
    mfd, sfd = pty.openpty()
    try:
        os.unlink(ptyname)
    except os.error:
        pass
    filename = os.ttyname(sfd)
    os.chmod(filename, 0o660)
    os.symlink(filename, ptyname)
    set_nonblock(mfd)
    old = termios.tcgetattr(mfd)
    old[3] = old[3] & ~termios.ECHO
    termios.tcsetattr(mfd, termios.TCSADRAIN, old)
    return mfd

def get_cpu_info():
    try:
        f = open('/proc/cpuinfo', 'r')
        data = f.read()
        f.close()
    except (IOError, OSError):
        logger.exception("Exception on read /proc/cpuinfo: %s", traceback.format_exc())
        return "?"
    lines = [l.split(':', 1) for l in data.split('\n')]
    lines = [(l[0].strip(), l[1].strip()) for l in lines if len(l) == 2]
    core_count = [k for k, v in lines].count("processor")
    model_name = dict(lines).get("model name", "?")
    return "%d core %s" % (core_count, model_name)

def get_version_from_file(klippy_src):
    try:
        with open(os.path.join(klippy_src, '.version')) as h:
            return h.read().rstrip()
    except IOError:
        pass
    return "?"

def get_git_version(from_file=True):
    klippy_src = os.path.dirname(__file__)

    # Obtain version info from "git" program
    gitdir = os.path.join(klippy_src, '..')
    prog = ('git', '-C', gitdir, 'describe', '--always',
            '--tags', '--long', '--dirty')
    try:
        process = subprocess.Popen(prog, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ver, err = process.communicate()
        retcode = process.wait()
        if retcode == 0:
            return ver.strip()
        else:
            logger.warning("Error getting git version:\n%s", err.decode())
    except OSError:
        logger.exception("Exception on run: %s", traceback.format_exc())
    if from_file:
        return get_version_from_file(klippy_src)
    return "?"

# show methods and vars
def show_methods(obj):
    logger.info("OBJ '%s'", obj)
    for m in sorted([method_name for method_name in dir(obj) if callable(getattr(obj, method_name))]):
        logger.info("\tMETHOD: %s", m)
    for a in sorted(vars(obj)):
        logger.info("\tVAR: %s VALUE %s", a, getattr(obj, a))

