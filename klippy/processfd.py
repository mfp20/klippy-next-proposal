# Filesystem facility
#
# Copyright (C) 2020  Anichang <anichang@protonmail.ch>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging, multiprocessing, threading, select
from text import msg
from error import KError as error
import util, process, chelper, serialhdl
logger = logging.getLogger(__name__)

class Handler:
    def __init__(self, fd = None):
        self.fd = fd
    def fileno(self):
        return self.fd

class HandlerTty(Handler):
    pass

class HandlerTtyVirtual(Handler):
    pass

class HandlerTtyChelper(Handler):
    def __init__(self, serialport, baud, rts = True):
        super().__init__()
        # Serial port
        self.serialport = serialport
        self.baud = baud
        self.rts = rts
        self.ser = None
        # C interface
        self.ffi_main, self.ffi_lib = chelper.get_ffi()
        self.serialqueue = None
        self.default_cmd_queue = self.alloc_command_queue()
        self.stats_buf = self.ffi_main.new('char[4096]')
        # Threading
        self.lock = threading.Lock()
        self.background_thread = None
    def _bg_thread(self):
        response = self.ffi_main.new('struct pull_queue_message *')
        while 1:
            self.ffi_lib.serialqueue_pull(self.serialqueue, response)
            count = response.len
            # ...
    def connect(self):
        # Initial connection
        logger.debug("- Starting serial connect to '%s' at '%s' baud.", self.serialport, self.baud)
        start_time = self.hal.get_reactor().monotonic()
        while 1:
            connect_time = self.hal.get_reactor().monotonic()
            if connect_time > start_time + 150.:
                raise error("Unable to connect")
            try:
                self.ser = serial.Serial(self.serialport, self.baud, timeout=0, exclusive=True)
            except (OSError, IOError, serial.SerialException) as e:
                logger.warn("Unable to open port: %s", e)
                self.hal.get_reactor().pause(connect_time + 5.)
                continue
            self.fd = self.ser.fileno()
            stk500v2_leave(self.ser, self.hal.get_reactor())
            self.serialqueue = self.ffi_lib.serialqueue_alloc(self.fd, 0)
            self.background_thread = threading.Thread(name='polling:mcu at '+self.serialport, target=self._bg_thread)
            self.background_thread.start()
    #
    def alloc_command_queue(self):
        return self.ffi_main.gc(self.ffi_lib.serialqueue_alloc_commandqueue(), self.ffi_lib.serialqueue_free_commandqueue)
    def get_default_command_queue(self):
        return self.default_cmd_queue
    def raw_send(self, cmd, minclock, reqclock, cmd_queue):
        self.ffi_lib.serialqueue_send(self.serialqueue, cmd_queue, cmd, len(cmd), minclock, reqclock, 0)
    def stats(self, eventtime):
        if self.serialqueue is None:
            return ""
        self.ffi_lib.serialqueue_get_stats(self.serialqueue, self.stats_buf, len(self.stats_buf))
        return self.ffi_main.string(self.stats_buf)
    def dump_debug(self):
        out = []
        out.append("Dumping serial stats: %s" % (self.stats(self.hal.get_reactor().monotonic()),))
        sdata = self.ffi_main.new('struct pull_queue_message[1024]')
        rdata = self.ffi_main.new('struct pull_queue_message[1024]')
        scount = self.ffi_lib.serialqueue_extract_old(self.serialqueue, 1, sdata, len(sdata))
        rcount = self.ffi_lib.serialqueue_extract_old(self.serialqueue, 0, rdata, len(rdata))
        out.append("Dumping send queue %d messages" % (scount,))
        for i in range(scount):
            msg = sdata[i]
            cmds = self.msgparser.dump(msg.msg[0:msg.len])
            out.append("Sent %d %f %f %d: %s" % (
                i, msg.receive_time, msg.sent_time, msg.len, ', '.join(cmds)))
        out.append("Dumping receive queue %d messages" % (rcount,))
        for i in range(rcount):
            msg = rdata[i]
            cmds = self.msgparser.dump(msg.msg[0:msg.len])
            out.append("Receive: %d %f %f %d: %s" % (i, msg.receive_time, msg.sent_time, msg.len, ', '.join(cmds)))
        return '\n'.join(out)
    #
    def disconnect(self):
        if self.serialqueue is not None:
            self.ffi_lib.serialqueue_exit(self.serialqueue)
            if self.background_thread is not None:
                self.background_thread.join()
            self.ffi_lib.serialqueue_free(self.serialqueue)
            self.background_thread = self.serialqueue = None
        if self.ser is not None:
            self.ser.close()
            self.ser = None
    def __del__(self):
        self.disconnect()

class FdProcess(process.Base):
    "File descriptors worker process."
    def __init__(self, name):
        super().__init__(name)
        # start
        process.worker_start(self, (self._subpipe,))
        # list of opened file descriptors
        self.fd = []
    def _poll_fds(self):
        # poll
        while self._running.is_set():
            res = self._poll.poll(1)
            for fd, event in res:
                obj = None
                if event == select.POLLIN:
                    obj = {'read': fd}
                elif event == select.POLLPRI:
                    obj = {'read': fd}
                elif event == select.POLLOUT:
                    pass
                elif event == select.POLLERR:
                    pass
                elif event == select.POLLHUP:
                    obj = {'read': fd}
                elif event == select.POLLRDHUP:
                    obj = {'read': fd}
                elif event == select.POLLNVAL:
                    pass
                if obj:
                    self.message_lock.acquire()
                    self.message[len(self.message)] = obj
                    self.message_lock.release()
    def _dispatch(self, eventtime, obj):
        "Dispatch an incoming message accordingly."
        if 'showth' in obj:
            self._subpipe.send({'showth':self._showth(), 'eventtime':eventtime})
            return True
        elif 'open' in obj:
            if obj['open']['tty'] == True:
                # create virtual tty
                fd = HandlerTtyVirtual(util.create_pty(obj['open']['filename']))
            elif obj['open']['tty']:
                tty = obj['open']['tty']
                if 'chelper' in tty:
                    #fd = 
                    pass
                else:
                    # open hw tty
                    fd = serial.Serial(obj['open']['filename'], obj['open']['tty']['baud'], obj['open']['tty']['timeout'], obj['open']['tty']['exclusive']).fileno()
            else:
                # open file
                fd = open(obj['open']['filename'], obj['open']['mode']).fileno()
            if obj['open']['poll']:
                self._poll.register(fd, select.POLLIN | select.POLLHUP)
            self.fd[fd] = obj['open']
            self._subpipe.send({'open':fd, 'eventtime':eventtime})
            return True
        elif 'info' in obj:
            fd = obj['info']
            self._subpipe.send({'info':self.fd[fd], 'eventtime':eventtime})
            return True
        elif 'seek' in obj:
            fd = obj['seek']
            fd.seek(obj['pos'])
            return True
        elif 'truncate' in obj:
            fd = obj['truncate']
            fd.truncate()
            return True
        elif 'read' in obj:
            fd = obj['read']
            if 'size' in obj:
                chunksize = obj['size']
            else:
                chunksize = self.fd[fd]['chunksize']
            data = fd.read(chunksize)
            self._subpipe.send({'eventtime':eventtime, 'fd':fd, 'data':data})
            return True
        elif 'write' in obj:
            fd = obj['write']
            fd.write(obj['data'])
            return True
        elif 'close' in obj:
            fd = obj['close']
            if 'poll' in self.fd[fd]:
                self._poll.unregister(fd)
            fd.close()
            self.fd.pop(fd)
            return True
        else:
            self.message_lock.acquire()
            self.message[len(self.message)] = obj
            self.message_lock.release()
            return False
    def _runner(self, *args):
        "FD process runner."
        self._subpipe = args[0]
        self.fd = {}
        self._poll = select.poll()
        self.message = {}
        self.message_lock = multiprocessing.Lock()
        # polling thread
        self._polling_th = threading.Thread(name="polling:common", target=self._poll_fds)
        self._polling_th.start()
        while self._running.is_set():
            eventtime = self.monotonic()
            # TODO adjust timeout according to I/O traffic
            timeout = 0.001
            # dispatch tasks in command queue
            mqueue = sorted(self.message.keys())
            for k in mqueue:
                if self._dispatch(eventtime, self.message[k]):
                    self.message_lock.acquire()
                    self.message.pop(k)
                    self.message_lock.release()
                elif k < eventtime-10.:
                    logger.warning("BUG: weird old message removed: %s", str(self.message[k]))
                    self.message_lock.acquire()
                    self.message.pop(k)
                    self.message_lock.release()
            elapsed = self.monotonic()-eventtime
            if elapsed > timeout:
                continue
            sparetime = timeout-elapsed
            if sparetime > 0:
                timeout = sparetime
            else:
                timeout = 0
            # check the up-connection for new requests
            if self._subpipe.poll(timeout):
                obj = self._subpipe.recv()
                self.message_lock.acquire()
                self.message[len(self.message)] = obj
                self.message_lock.release()
        for fd in self.fd.keys():
            fd.close()
    def open(self, filename, mode = "rb", chunksize = 4096, tty = False, poll = False):
        "Add a file to be accessed."
        opts = {'filename':filename, 'mode':mode, 'chunksize':chunksize, 'tty':tty, 'poll':poll}
        self._pipe.send({'open':opts})
        if self._pipe.poll(5):
            self.fd.append(self._pipe.recv())
            return self.fd[-1]
        return None
    def info(self, fd):
        "Return info about the given file descriptor."
        ic = {'info': fd}
        self._pipe.send(ic)
        if self._pipe.poll(5):
            return self._pipe.recv()
        return None
    def ident(self, filename):
        "Return (fd,info) of the given filename."
        for fd in self.fd:
            info = self.info(fd)
            if info['filename'] == filename:
                return fd, info
        return None
    def seek(self, fd, pos):
        "Seek position of the given file descriptor."
        sc = {'seek': fd, 'pos': pos}
        self._pipe.send(sc)
    def truncate(self, fd):
        "Truncate file at the current file descriptor position."
        tc = {'truncate': fd}
        self._pipe.send(tc)
    def read(self, fd, size = None):
        "Read sized data from given file descriptor."
        rc = {'read':fd}
        if size:
            rc['size'] = size
        self._pipe.send(rc)
        if self._pipe.poll(5):
            return self._pipe.recv()
        return None
    def write(self, fd, data):
        "Write data to the given file descriptor."
        wc = {'write':fd, 'data':data}
        self._pipe.send(wc)
        if self._pipe.poll(5):
            return self._pipe.recv()
        return None
    def close(self, fd):
        "Close the given file descriptor."
        self._pipe.send({'close':fd})

