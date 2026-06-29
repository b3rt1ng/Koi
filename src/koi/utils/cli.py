from __future__ import annotations

import readline
from typing import Callable, Optional

from koi.modules.loader import load_modules
from koi.utils.payloads import get_interfaces
from koi.utils.ui import (
    print_report_box,
    bold, accent, alert,
)

COMMANDS = [
    "ls", "go", "upgrade", "kill", "tag", "setshell", "help", "exit",
    "quit", "interact", "payload", "obfuscator", "run", "modules",
    "reload", "start", "stop", "logs",
]

_OS_TYPES = ["linux", "windows_ps", "windows_cmd"]
_SESSION_ARG1_CMDS = {"go", "g", "interact", "upgrade", "u", "kill", "tag"}

_session_provider: Optional[Callable[[], list[str]]] = None


def set_session_provider(fn: Callable[[], list[str]]) -> None:
    global _session_provider
    _session_provider = fn


def _session_refs() -> list[str]:
    return _session_provider() if _session_provider else []


readline.set_history_length(200)
readline.parse_and_bind("tab: complete")
readline.parse_and_bind(r'"\C-t": "\C-e\C-u_koi_screenable_\n"')
readline.parse_and_bind(r'"\C-w": "\C-e\C-u_koi_toggle_\n"')


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

    elif parts[0] == "run" and (
        (len(parts) == 2 and line.endswith(" ")) or
        (len(parts) == 3 and not line.endswith(" "))
    ):
        options = _match(text, _session_refs())

    elif parts[0] in _SESSION_ARG1_CMDS and (
        (len(parts) == 1 and line.endswith(" ")) or
        (len(parts) == 2 and not line.endswith(" "))
    ):
        options = _match(text, _session_refs())

    elif parts[0] in ("setshell", "sh") and (
        (len(parts) == 1 and line.endswith(" ")) or
        (len(parts) == 2 and not line.endswith(" "))
    ):
        options = _match(text, _session_refs())

    elif parts[0] in ("setshell", "sh") and (
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
            f"{accent('ls')}": "List all active sessions",
            f"{accent('go')} {bold('<id|tag>')}": "Enter a session interactively",
            f"{accent('upgrade')} {bold('<id|tag>')}": "Upgrade session to a full PTY",
            f"{accent('kill')} {bold('<id|tag>')}": "Terminate and remove a session",
            f"{accent('tag')} {bold('<id|tag>')} {bold('[name]')}": "Assign or clear a tag on a session",
            f"{accent('payload')} {bold('[iface]')}": "Show reverse shell payloads",
            f"{accent('obfuscator')} {bold('[iface]')}": "Interactive payload obfuscator",
            f"{accent('modules')}": "List available modules",
            f"{accent('reload')}": "Reload modules from disk (useful during development)",
            f"{accent('run')} {bold('<module>')} {bold('<id>')} {bold('[args...]')}": "Run a module against a session",
            f"{accent('setshell')} {bold('<id>')} {bold('<os_type>')}": "Manually set the OS type of a session",
            f"{accent('logs')}": "List recorded session logs",
            f"{accent('start/stop')}": "Start or stop the listener",
            f"{accent('help')}": "Show this message",
            f"{accent('exit')}": "Shut down the listener",
        },
        "Session Signals": {
            f"{alert('Ctrl+Z')}": "Background, return to listener shell",
            f"{alert('Ctrl+C')}": "Send SIGINT to remote (keeps session alive)",
            f"{alert('Ctrl+T')}": "Toggle screenable mode, masks IPs for screenshots",
            f"{alert('Ctrl+W')}": "Toggle listener on/off (pause/resume accepting connections)",
        },
    }
    print_report_box("help", data)