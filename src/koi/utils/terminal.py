from __future__ import annotations

import os
import select
import sys
import termios
import tty

HIDE       = "\033[?25l"
SHOW       = "\033[?25h"
ALT_ON     = "\033[?1049h"
ALT_OFF    = "\033[?1049l"
CLEAR      = "\033[2J\033[H"
BPASTE_ON  = "\033[?2004h"
BPASTE_OFF = "\033[?2004l"


def getch() -> bytes:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1)
        if ch == b'\x1b':
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                nxt = os.read(fd, 1)
                if nxt == b'[':
                    param = bytearray()
                    while True:
                        b = os.read(fd, 1)
                        if not b:
                            break
                        param.extend(b)
                        if 0x40 <= b[0] <= 0x7E:
                            break
                        if len(param) > 16:
                            break
                    seq = b'[' + bytes(param)
                    if seq == b'[200~':
                        paste = bytearray()
                        while len(paste) < 500_000:
                            b = os.read(fd, 1)
                            if not b:
                                break
                            paste.extend(b)
                            if paste.endswith(b'\x1b[201~'):
                                return b'\x1b[200~' + bytes(paste[:-6])
                        return b'\x1b[200~' + bytes(paste)
                    return b'\x1b' + seq
                return b'\x1b' + nxt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
