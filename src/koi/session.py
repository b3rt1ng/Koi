from __future__ import annotations

import select
import sys
import termios
import threading
import tty
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Literal, Optional
import socket

from koi.utils.ui import muted, accent, alert, cyan


OsType = Literal["linux", "windows_cmd", "windows_ps"] | None


class SessionBusy(RuntimeError):
    """Raised when a session's socket is already owned by another operation."""

    def __init__(self, session_id: int, holder: Optional[str] = None):
        self.session_id = session_id
        self.holder = holder
        detail = f" (held by {holder})" if holder else ""
        super().__init__(f"Session #{session_id} is busy{detail}")

# POLLRDHUP reports the peer's FIN while its last bytes sit unread. Linux-only:
# elsewhere the mask collapses to 0 and _peer_gone() falls back to peeking.
_POLL_HUP = (
    getattr(select, "POLLRDHUP", 0)
    | getattr(select, "POLLHUP", 0)
    | getattr(select, "POLLERR", 0)
) if hasattr(select, "poll") else 0

OS_LABEL_NAMES: dict[str, str] = {
    "linux":       "linux",
    "windows_cmd": "cmd",
    "windows_ps":  "powershell",
}

OS_WIRE: dict[str, tuple[str, str]] = {
    "linux":       ("utf-8",  "\n"),
    "windows_cmd": ("cp1252", "\r\n"),
    "windows_ps":  ("cp1252", "\r\n"),
}


def wire_settings(os_type: Optional[str]) -> tuple[str, str]:
    """The ``(encoding, eol)`` pair for *os_type*, utf-8/LF when unknown."""
    return OS_WIRE.get(os_type or "", ("utf-8", "\n"))


@dataclass
class Session:
    id: int
    conn: socket.socket
    addr: tuple
    connected_at: datetime = field(default_factory=datetime.now)
    alive: bool = True
    upgraded: bool = False
    is_conptyshell: bool = False
    os_type: OsType = field(default=None)
    encoding: str = field(default="utf-8")
    eol: str = field(default="\n")
    log_path: Optional[str] = field(default=None)
    tag: Optional[str] = field(default=None)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _io_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _io_holder: Optional[str] = field(default=None, repr=False)
    _logger: object = field(default=None, repr=False)  # SessionLogger | None

    def attach_logger(self, logger) -> None:
        self._logger = logger

    def set_os_type(self, os_type: OsType) -> None:
        """Set os_type with the encoding and eol it implies; never set it alone."""
        self.os_type = os_type
        self.encoding, self.eol = wire_settings(os_type)

    @contextmanager
    def io(self, holder: str = "?", timeout: Optional[float] = None) -> Iterator["Session"]:
        """Take exclusive ownership of this session's socket.

        Anything reading ``self.conn`` must hold this or concurrent readers
        steal each other's bytes and lose command sentinels. Reentrant per
        thread. ``timeout=None`` blocks; otherwise raises :class:`SessionBusy`.
        """
        if not self._io_lock.acquire(timeout=-1 if timeout is None else timeout):
            raise SessionBusy(self.id, self._io_holder)
        previous = self._io_holder
        self._io_holder = holder
        try:
            yield self
        finally:
            self._io_holder = previous
            self._io_lock.release()

    @property
    def io_holder(self) -> Optional[str]:
        """Name of the operation currently owning the socket, if any."""
        return self._io_holder

    def _uptime(self) -> str:
        secs = int((datetime.now() - self.connected_at).total_seconds())
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def os_label(self) -> str:
        colors = {"linux": alert, "windows_cmd": cyan, "windows_ps": cyan}
        key = self.os_type or ""
        fn = colors.get(key, muted)
        return fn(OS_LABEL_NAMES.get(key, "?"))

    def status_dot(self) -> str:
        if not self.alive:
            return muted("○")
        return accent("◆") if self.upgraded else alert("●")

    def probe(self) -> bool:
        """Refresh :attr:`alive` from the socket and return it.

        Consumes nothing from the stream. A session owned by another operation
        is skipped: that owner will notice a death first-hand.
        """
        if not self.alive:
            return False
        if not self._io_lock.acquire(timeout=0):
            return True
        try:
            if self._peer_gone():
                self.alive = False
        finally:
            self._io_lock.release()
        return self.alive

    def _peer_gone(self) -> bool:
        """Whether the far end has hung up, unread output notwithstanding."""
        if _POLL_HUP:
            poller = select.poll()
            poller.register(self.conn, _POLL_HUP)
            return bool(poller.poll(0))

        # A readable socket yielding nothing has been closed. Misses a peer that
        # died leaving output unread; that death surfaces on the next write.
        try:
            ready, _, _ = select.select([self.conn], [], [], 0)
            return bool(ready) and self.conn.recv(1, socket.MSG_PEEK) == b""
        except BlockingIOError:
            return False
        except OSError:
            return True

    def send(self, data: bytes) -> bool:
        try:
            with self._lock:
                self.conn.sendall(data)
            if self._logger and data:
                self._logger.log_input(data)
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