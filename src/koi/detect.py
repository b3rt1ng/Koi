from __future__ import annotations

import select
import time
import uuid
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from koi.session import Session

logger = logging.getLogger("koi.detect")

_TIMEOUT = 4.0
_SELECT_TIMEOUT = 0.1


def _recv_for(session: "Session", duration: float) -> str:
    """Read everything available on the socket for `duration` seconds."""
    buf = b""
    deadline = time.monotonic() + duration
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            r, _, _ = select.select([session.conn], [], [], min(remaining, _SELECT_TIMEOUT))
            if r:
                chunk = session.conn.recv(4096)
                if not chunk:
                    session.alive = False
                    break
                buf += chunk
        except OSError:
            session.alive = False
            break
    return buf.decode("utf-8", errors="replace")


def detect_os(session: "Session") -> None:
    """
    Probe the remote shell to determine OS and shell type.

    Sets on the session:
        os_type  : "linux" | "windows_cmd" | "windows_ps"
        encoding : "utf-8" | "cp1252"
        eol      : "\n"    | "\r\n"

    If detection fails, os_type stays None.
    """
    if not session.alive:
        return

    a = uuid.uuid4().hex[:8]
    b = uuid.uuid4().hex[:8]
    expected = a + b
    probe = f" A={a} B={b}; echo $A$B\r\n"

    try:
        session.conn.sendall(probe.encode("utf-8"))
    except OSError:
        session.alive = False
        return

    response = _recv_for(session, _TIMEOUT)
    logger.debug(f"[detect] session #{session.id} raw response: {response!r}")

    _apply(session, response, expected)


def _apply(session: "Session", response: str, expected: str) -> None:
    r = response.lower()

    if expected in response:
        session.os_type = "linux"
        session.encoding = "utf-8"
        session.eol = "\n"
        logger.debug(f"[detect] session #{session.id} → linux")
        return

    ps_hints = [
        "is not recognized as the name of a cmdlet",
        "windows powershell",
        "powershell",
    ]
    ps_prompt = bool(re.search(r'\bps\s+[a-z]:\\', r))
    if ps_prompt or any(hint in r for hint in ps_hints):
        session.os_type = "windows_ps"
        session.encoding = "cp1252"
        session.eol = "\r\n"
        logger.debug(f"[detect] session #{session.id} → windows_ps")
        return

    cmd_hints = [
        "is not recognized as an internal or external command",
        "microsoft windows",
        "c:\\",
        "c:/",
    ]
    if any(hint in r for hint in cmd_hints):
        session.os_type = "windows_cmd"
        session.encoding = "cp1252"
        session.eol = "\r\n"
        logger.debug(f"[detect] session #{session.id} → windows_cmd")
        return

    _fallback(session)


def _fallback(session: "Session") -> None:
    """Second attempt: send `uname` and check for a recognizable response."""
    if not session.alive:
        return
    try:
        session.conn.sendall(b"uname\r\n")
    except OSError:
        return

    response = _recv_for(session, _TIMEOUT)
    r = response.lower()
    logger.debug(f"[detect] session #{session.id} fallback response: {response!r}")

    if any(x in r for x in ("linux", "darwin", "freebsd", "openbsd", "netbsd")):
        session.os_type = "linux"
        session.encoding = "utf-8"
        session.eol = "\n"
    elif any(x in r for x in ("windows", "microsoft", "c:\\")):
        session.os_type = "windows_cmd"
        session.encoding = "cp1252"
        session.eol = "\r\n"
    else:
        logger.debug(f"[detect] session #{session.id} → detection failed, os_type stays None")