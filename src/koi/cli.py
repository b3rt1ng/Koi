from __future__ import annotations

import readline
from typing import TYPE_CHECKING

from koi.modules.loader import load_modules, get_module
from koi.utils.payloads import _get_interfaces
from koi.utils.ui import (
    print_report_box, notify,
    _b, _p, _y,
)

if TYPE_CHECKING:
    pass

COMMANDS = [
    "ls", "go", "upgrade", "kill", "help", "exit",
    "quit", "interact", "payload", "run", "modules", "reload",
]

readline.set_history_length(200)
readline.parse_and_bind("tab: complete")


def completer(text: str, state: int):
    line = readline.get_line_buffer()
    parts = line.strip().split()

    if len(parts) == 0 or (len(parts) == 1 and not line.endswith(" ")):
        options = [cmd for cmd in COMMANDS if cmd.startswith(text)]

    elif parts[0] in ("payload", "p") and (
        len(parts) == 1 or (len(parts) == 2 and not line.endswith(" "))
    ):
        interfaces = list(_get_interfaces().keys())
        options = [iface for iface in interfaces if iface.startswith(text)]

    elif parts[0] == "run" and (
        len(parts) == 1 or (len(parts) == 2 and not line.endswith(" "))
    ):
        modules = load_modules()
        options = [name for name in modules if name.startswith(text)]

    else:
        options = []

    return options[state] + " " if state < len(options) else None


readline.set_completer(completer)


def print_help() -> None:
    data = {
        "Commands": {
            f"{_p('ls')}": "List all active sessions",
            f"{_p('go')} {_b('<id>')}": "Enter a session interactively",
            f"{_p('upgrade')} {_b('<id>')}": "Upgrade session to a full PTY",
            f"{_p('kill')} {_b('<id>')}": "Terminate and remove a session",
            f"{_p('payload')} {_b('[iface]')}": "Show reverse shell payloads",
            f"{_p('modules')}": "List available modules",
            f"{_p('reload')}": "Reload modules from disk (useful during development)",
            f"{_p('run')} {_b('<module>')} {_b('<id>')} {_b('[args…]')}": "Run a module against a session",
            f"{_p('help')}": "Show this message",
            f"{_p('exit')}": "Shut down the listener",
        },
        "Session Signals": {
            f"{_y('Ctrl+Z')}": "Background → return to listener shell",
            f"{_y('Ctrl+C')}": "Send SIGINT to remote (keeps session alive)",
        },
    }
    print_report_box("help", data)