from __future__ import annotations

import select
import time
import uuid
import logging
import re
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from koi.session import Session

from koi.utils.config import TIMEOUTS

logger = logging.getLogger("koi.detect")

_TIMEOUT = TIMEOUTS["session_detect"]
_SELECT_TIMEOUT = 0.1


def _recv_for(
    session: "Session",
    duration: float,
    stop_when: Optional[Callable[[str], bool]] = None,
) -> str:
    """Read from the socket for at most `duration` seconds.

    If `stop_when` is given, it is called with the decoded buffer after each
    chunk; returning True stops reading early. This lets detection return as
    soon as the OS can be decided instead of always waiting the full timeout.
    """
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
                if stop_when is not None and stop_when(buf.decode("utf-8", errors="replace")):
                    break
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

    response = _recv_for(
        session, _TIMEOUT,
        stop_when=lambda text: _classify(text, expected) is not None,
    )
    logger.debug(f"[detect] session #{session.id} raw response: {response!r}")

    _apply(session, response, expected)


def _classify(response: str, expected: str) -> "str | None":
    """Return the detected os_type from a probe response, or None if undecided.

    Shared by the early-exit predicate and `_apply` so both always agree on the
    verdict (Linux takes precedence, then PowerShell, then cmd).
    """
    if expected in response:
        return "linux"

    r = response.lower()

    ps_hints = [
        "is not recognized as the name of a cmdlet",
        "windows powershell",
        "powershell",
    ]
    if re.search(r'\bps\s+[a-z]:\\', r) or any(hint in r for hint in ps_hints):
        return "windows_ps"

    cmd_hints = [
        "is not recognized as an internal or external command",
        "microsoft windows",
        "c:\\",
        "c:/",
    ]
    if any(hint in r for hint in cmd_hints):
        return "windows_cmd"

    return None


def _apply(session: "Session", response: str, expected: str) -> None:
    os_type = _classify(response, expected)
    if os_type is None:
        _fallback(session)
        return

    session.os_type = os_type
    if os_type == "linux":
        session.encoding = "utf-8"
        session.eol = "\n"
    else:
        session.encoding = "cp1252"
        session.eol = "\r\n"
    logger.debug(f"[detect] session #{session.id}, {os_type}")


def _fallback(session: "Session") -> None:
    """Second attempt: send `uname` and check for a recognizable response."""
    if not session.alive:
        return
    try:
        session.conn.sendall(b"uname\r\n")
    except OSError:
        return

    _FALLBACK_TOKENS = ("linux", "darwin", "freebsd", "openbsd", "netbsd",
                        "windows", "microsoft", "c:\\")
    response = _recv_for(
        session, _TIMEOUT,
        stop_when=lambda text: any(x in text.lower() for x in _FALLBACK_TOKENS),
    )
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
        logger.debug(f"[detect] session #{session.id}, detection failed, os_type stays None")