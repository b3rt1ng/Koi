from __future__ import annotations

import sys
import termios
import threading
import tty
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional
import socket

from koi.utils.ui import _gr, _p, _r, _y, _bl


OsType = Literal["linux", "windows_cmd", "windows_ps"] | None


@dataclass
class Session:
    id: int
    conn: socket.socket
    addr: tuple
    connected_at: datetime = field(default_factory=datetime.now)
    alive: bool = True
    upgraded: bool = False
    os_type: OsType = field(default=None)
    encoding: str = field(default="utf-8")
    eol: str = field(default="\n")
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _uptime(self) -> str:
        secs = int((datetime.now() - self.connected_at).total_seconds())
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def os_label(self) -> str:
        return {
            "linux":       _y("linux"),
            "windows_cmd": _bl("cmd"),
            "windows_ps":  _bl("powershell"),
        }.get(self.os_type or "", _gr("?"))

    def status_dot(self) -> str:
        if not self.alive:
            return _gr("○")
        return _p("◆") if self.upgraded else _r("●")

    def send(self, data: bytes) -> bool:
        try:
            with self._lock:
                self.conn.sendall(data)
            return True
        except OSError:
            self.alive = False
            return False

    def close(self) -> None:
        self.alive = False
        for fn in (lambda: self.conn.shutdown(socket.SHUT_RDWR), self.conn.close):
            try:
                fn()
            except OSError:
                pass


class RawTerminal:
    def __init__(self):
        self._old = None
        self._fd = sys.stdin.fileno()

    def __enter__(self):
        self._old = termios.tcgetattr(self._fd)
        tty.setraw(self._fd)
        return self

    def __exit__(self, *_):
        if self._old:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)