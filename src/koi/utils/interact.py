from __future__ import annotations

import os
import queue
import select
import signal
import sys
import threading
import time

from koi.session import Session, RawTerminal

CTRL_Z = b"\x1a"
CTRL_C = b"\x03"


def interact(sess: Session, logger=None) -> str:
    if sess.os_type in ("windows_cmd", "windows_ps") and not sess.upgraded:
        return _interact_windows(sess, logger)
    return _interact_raw(sess, logger)


def _interact_raw(sess: Session, logger=None) -> str:
    stop_event = threading.Event()
    result = ["backgrounded"]

    def _recv():
        while not stop_event.is_set() and sess.alive:
            try:
                r, _, _ = select.select([sess.conn], [], [], 0.1)
                if not r:
                    continue
                data = sess.conn.recv(65536)
                if not data:
                    sess.alive = False
                    result[0] = "disconnected"
                    stop_event.set()
                    return
                if logger:
                    logger.log_output(data)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except OSError:
                sess.alive = False
                result[0] = "disconnected"
                stop_event.set()

    recv_thread = threading.Thread(target=_recv, daemon=True)

    with RawTerminal():
        recv_thread.start()
        try:
            while not stop_event.is_set():
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not r:
                    continue
                key = os.read(sys.stdin.fileno(), 1024)

                if CTRL_Z in key:
                    before = key[: key.index(CTRL_Z)]
                    if before:
                        sess.send(before)
                    result[0] = "backgrounded"
                    stop_event.set()
                    break

                if not sess.send(key):
                    result[0] = "disconnected"
                    stop_event.set()
                    break
        except OSError:
            pass

    stop_event.set()
    recv_thread.join(timeout=1.0)
    return result[0]


def _interact_windows(sess: Session, logger=None) -> str:
    enc = sess.encoding
    stop_event = threading.Event()
    result = ["backgrounded"]

    def _recv():
        buf = b""
        while not stop_event.is_set() and sess.alive:
            try:
                r, _, _ = select.select([sess.conn], [], [], 0.1)
                if not r:
                    continue
                data = sess.conn.recv(65536)
                if not data:
                    sess.alive = False
                    result[0] = "disconnected"
                    stop_event.set()
                    return
                buf += data
                if logger:
                    logger.log_output(data)
                text = buf.decode(enc, errors="replace")
                sys.stdout.write(text)
                sys.stdout.flush()
                buf = b""
            except OSError:
                sess.alive = False
                result[0] = "disconnected"
                stop_event.set()

    recv_thread = threading.Thread(target=_recv, daemon=True)
    recv_thread.start()

    time.sleep(0.3)

    old_sigtstp = signal.getsignal(signal.SIGTSTP)

    def _handle_sigtstp(signum, frame):
        result[0] = "backgrounded"
        stop_event.set()

    signal.signal(signal.SIGTSTP, _handle_sigtstp)

    input_queue: queue.Queue = queue.Queue()

    def _read_input():
        while not stop_event.is_set():
            try:
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if r:
                    line = sys.stdin.readline()
                    if line:
                        input_queue.put(line.rstrip('\n'))
                    else:
                        input_queue.put(None)
                        return
            except Exception:
                return

    threading.Thread(target=_read_input, daemon=True).start()

    try:
        while not stop_event.is_set() and sess.alive:
            try:
                cmd = input_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if cmd is None:
                break

            if cmd.strip().lower() in ("exit", "quit"):
                sess.send(b"exit\r\n")
                time.sleep(0.2)
                result[0] = "disconnected"
                break

            line = (cmd + "\r\n").encode(enc, errors="replace")
            if not sess.send(line):
                result[0] = "disconnected"
                break

    except Exception:
        pass
    finally:
        signal.signal(signal.SIGTSTP, old_sigtstp)

    stop_event.set()
    recv_thread.join(timeout=1.0)
    return result[0]
