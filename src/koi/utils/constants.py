"""Values shared by the transport, the REPL and the module API."""

from __future__ import annotations

import re

SOCKET_BUFFER_SIZE = 65536

ANSI_RE = re.compile(
    r"\x1b(?:"
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)"   # OSC, BEL- or ST-terminated
    r"|\[[0-?]*[ -/]*[@-~]"            # CSI
    r"|[ -/]+[0-~]"                    # nF (charset designation, etc.)
    r"|[@-Z\\-_]"                      # other two-byte Fe escapes
    r")"
)
