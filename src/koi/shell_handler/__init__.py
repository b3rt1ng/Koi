from .core import ShellHandler
from .result import CommandResult, StreamLine
from .session import PersistentSession
from .exceptions import (
    ShellHandlerError,
    CommandTimeout,
    CommandFailed,
    MaxRetriesExceeded,
    SessionClosed,
    SessionTimeout,
)

__all__ = [
    "ShellHandler",
    "CommandResult",
    "StreamLine",
    "PersistentSession",
    "ShellHandlerError",
    "CommandTimeout",
    "CommandFailed",
    "MaxRetriesExceeded",
    "SessionClosed",
    "SessionTimeout",
]

__version__ = "1.0.0"