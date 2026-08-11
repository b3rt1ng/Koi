"""Values shared by the transport, the REPL and the module API."""

from __future__ import annotations

import re

SOCKET_BUFFER_SIZE = 65536

# Must cover CSI, OSC and two-byte escapes: a pattern assuming every sequence
# ends in 'm' eats the next literal 'm' after a cursor sequence, which breaks
# the display-width maths this feeds.
ANSI_RE = re.compile(
    r"\x1b(?:\][^\x07]*\x07|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])"
)
