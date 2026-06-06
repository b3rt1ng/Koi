from __future__ import annotations

import readline

from koi.modules.loader import load_modules, get_module
from koi.utils.payloads import get_interfaces
from koi.utils.ui import (
    print_report_box, notify,
    _b, _p, _y,
)

COMMANDS = [
    "ls", "go", "upgrade", "kill", "setshell", "help", "exit",
    "quit", "interact", "payload", "obfuscator", "run", "modules",
    "reload", "start", "stop", "logs",
]

_OS_TYPES = ["linux", "windows_ps", "windows_cmd"]

readline.set_history_length(200)
readline.parse_and_bind("tab: complete")
readline.parse_and_bind(r'"\C-t": "\C-e\C-u_koi_screenable_\n"')


def _match(text: str, candidates: list[str]) -> list[str]:
    """Prefix matches first, then substring matches (case-insensitive)."""
    if not text:
        return list(candidates)
    t = text.lower()
    prefix = [c for c in candidates if c.lower().startswith(t)]
    substr = [c for c in candidates if t in c.lower() and not c.lower().startswith(t)]
    return prefix + substr


def completer(text: str, state: int):
    line = readline.get_line_buffer()
    parts = line.strip().split()

    if len(parts) == 0 or (len(parts) == 1 and not line.endswith(" ")):
        options = _match(text, COMMANDS)

    elif parts[0] in ("payload", "p", "obfuscator", "obs") and (
        len(parts) == 1 or (len(parts) == 2 and not line.endswith(" "))
    ):
        options = _match(text, list(get_interfaces().keys()))

    elif parts[0] == "run" and (
        len(parts) == 1 or (len(parts) == 2 and not line.endswith(" "))
    ):
        options = _match(text, list(load_modules().keys()))

    elif parts[0] == "setshell" and (
        (len(parts) == 2 and line.endswith(" ")) or
        (len(parts) == 3 and not line.endswith(" "))
    ):
        options = _match(text, _OS_TYPES)

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
            f"{_p('obfuscator')} {_b('[iface]')}": "Interactive payload obfuscator",
            f"{_p('modules')}": "List available modules",
            f"{_p('reload')}": "Reload modules from disk (useful during development)",
            f"{_p('run')} {_b('<module>')} {_b('<id>')} {_b('[args...]')}": "Run a module against a session",
            f"{_p('setshell')} {_b('<id>')} {_b('<os_type>')}": "Manually set the OS type of a session",
            f"{_p('stop')}": "Pause the listener, refuse new connections",
            f"{_p('logs')}": "List recorded session logs",
            f"{_p('start')}": "Resume the listener, accept new connections again",
            f"{_p('help')}": "Show this message",
            f"{_p('exit')}": "Shut down the listener",
        },
        "Session Signals": {
            f"{_y('Ctrl+Z')}": "Background, return to listener shell",
            f"{_y('Ctrl+C')}": "Send SIGINT to remote (keeps session alive)",
            f"{_y('Ctrl+T')}": "Toggle screenable mode, masks IPs for screenshots",
        },
    }
    print_report_box("help", data)