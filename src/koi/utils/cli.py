from __future__ import annotations

import difflib
import readline
import shlex
from typing import Callable, Optional

from koi.modules.loader import load_modules
from koi.utils.connect import TRANSPORTS, get_transport
from koi.utils.payloads import get_interfaces
from koi.utils.ui import (
    print_report_box,
    bold, accent, alert,
)

ALIASES: dict[str, list[str]] = {
    "help":       ["help", "h", "?"],
    "exit":       ["exit"],
    "quit":       ["quit"],
    "stop":       ["stop"],
    "start":      ["start"],
    "ls":         ["ls", "l", "list"],
    "go":         ["go", "g", "interact"],
    "upgrade":    ["upgrade", "u"],
    "kill":       ["kill", "rm", "terminate"],
    "payload":    ["payload", "p"],
    "obfuscator": ["obfuscator", "obs", "cook"],
    "logs":       ["logs", "log"],
    "modules":    ["modules", "mdls", "mods"],
    "reload":     ["reload", "refresh", "rl"],
    "run":        ["run"],
    "setshell":   ["setshell", "sh"],
    "tag":        ["tag"],
    "connect":    ["connect", "conn"],
}

_ALIAS_TO_CANON: dict[str, str] = {
    alias: canon for canon, aliases in ALIASES.items() for alias in aliases
}


def tokenize(raw: str) -> list[str]:
    """Split a command line into tokens, honouring quotes, backslashes literal.

    Backslashes are left alone so Windows paths survive: ``shlex.split`` would
    turn ``"C:\\Users\\my dir"`` into ``C:Usersmy dir``. An unbalanced quote
    falls back to a whitespace split instead of raising.
    """
    lexer = shlex.shlex(raw, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    try:
        return list(lexer)
    except ValueError:
        return raw.split()


def resolve_command(cmd: str) -> str:
    """Map a typed command (or alias) to its canonical name, case-insensitive.

    Unknown commands pass through unchanged so the caller can still report
    them as invalid.
    """
    return _ALIAS_TO_CANON.get(cmd.lower(), cmd.lower())


COMMANDS = list(ALIASES.keys())

OS_ALIASES: dict[str, list[str]] = {
    "linux":       ["linux"],
    "windows_ps":  ["windows_ps", "ps", "powershell"],
    "windows_cmd": ["windows_cmd", "cmd"],
}

_OS_ALIAS_TO_CANON: dict[str, str] = {
    alias: canon for canon, aliases in OS_ALIASES.items() for alias in aliases
}


def resolve_os_type(os_arg: str) -> Optional[str]:
    """Map an OS-type alias to its canonical name, or None if unknown."""
    return _OS_ALIAS_TO_CANON.get(os_arg.lower())


_OS_TYPES = list(OS_ALIASES.keys())
_SESSION_ARG1_CMDS = {
    alias for canon in ("go", "upgrade", "kill", "tag") for alias in ALIASES[canon]
}
_PAYLOAD_LIKE_CMDS = set(ALIASES["payload"]) | set(ALIASES["obfuscator"])

USAGE: dict[str, tuple[int, str]] = {
    "go":       (1, f"Usage: go {accent('<id|tag>')}"),
    "upgrade":  (1, f"Usage: upgrade {accent('<id|tag>')}"),
    "kill":     (1, f"Usage: kill {accent('<id|tag>')}"),
    "setshell": (2, f"Usage: setshell {accent('<id|tag>')} {accent('<linux|windows_ps|windows_cmd>')}"),
    "tag":      (1, f"Usage: tag {accent('<id|tag>')} {accent('[name]')}"),
    "connect":  (2, f"Usage: connect {accent('|'.join(TRANSPORTS))} {accent('<target>')} {accent('[args...]')}"),
}


def check_usage(canon: str, parts: list[str]) -> Optional[str]:
    """Return a usage error message if `parts` (command included) doesn't
    meet canon's minimum argument count, else None.
    """
    spec = USAGE.get(canon)
    if spec is None:
        return None
    min_args, message = spec
    return message if len(parts) - 1 < min_args else None


SCREENABLE_SENTINEL = "_koi_screenable_"
TOGGLE_SENTINEL = "_koi_toggle_"

_session_provider: Optional[Callable[[], list[str]]] = None


def set_session_provider(fn: Callable[[], list[str]]) -> None:
    global _session_provider
    _session_provider = fn


def _session_refs() -> list[str]:
    return _session_provider() if _session_provider else []


def _transport_hosts(name: str) -> list[str]:
    transport = get_transport(name)
    return transport.completions() if transport else []


_READLINE_HISTORY_LENGTH = 200
readline.set_history_length(_READLINE_HISTORY_LENGTH)
readline.parse_and_bind("tab: complete")
readline.parse_and_bind(rf'"\C-t": "\C-e\C-u{SCREENABLE_SENTINEL}\n"')
readline.parse_and_bind(rf'"\C-o": "\C-e\C-u{TOGGLE_SENTINEL}\n"')


def _fuzzy_match(text: str, candidates: list[str], cutoff: float = 0.35) -> list[str]:
    """Typo-tolerant fallback ('paload' -> 'payload').

    A clear winner is returned alone so tab jumps straight to it.
    """
    if not text or not candidates:
        return []
    t = text.lower()
    scored = sorted(
        ((difflib.SequenceMatcher(None, t, c.lower()).ratio(), c) for c in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    scored = [(score, c) for score, c in scored if score >= cutoff]
    if not scored:
        return []
    best_score, best = scored[0]
    if len(scored) == 1 or best_score >= scored[1][0] * 1.3:
        return [best]
    return [c for _, c in scored]


def _match(text: str, candidates: list[str]) -> list[str]:
    """Prefix matches first, then substring, then typo-tolerant fuzzy fallback."""
    if not text:
        return list(candidates)
    t = text.lower()
    prefix = [c for c in candidates if c.lower().startswith(t)]
    substr = [c for c in candidates if t in c.lower() and not c.lower().startswith(t)]
    if prefix or substr:
        return prefix + substr
    return _fuzzy_match(text, candidates)


def completer(text: str, state: int):
    line = readline.get_line_buffer()
    parts = line.strip().split()
    if parts:
        parts[0] = resolve_command(parts[0])

    if len(parts) == 0 or (len(parts) == 1 and not line.endswith(" ")):
        alias_hit = _ALIAS_TO_CANON.get(text.lower())
        if alias_hit and alias_hit != text.lower():
            options = [alias_hit]
        else:
            options = _match(text, COMMANDS)

    elif parts[0] in _PAYLOAD_LIKE_CMDS and (
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

    elif parts[0] in ALIASES["connect"] and (
        (len(parts) == 1 and line.endswith(" ")) or
        (len(parts) == 2 and not line.endswith(" "))
    ):
        options = _match(text, list(TRANSPORTS))

    elif parts[0] in ALIASES["connect"] and (
        (len(parts) == 2 and line.endswith(" ")) or
        (len(parts) == 3 and not line.endswith(" "))
    ):
        options = _match(text, _transport_hosts(parts[1]))

    elif parts[0] in _SESSION_ARG1_CMDS and (
        (len(parts) == 1 and line.endswith(" ")) or
        (len(parts) == 2 and not line.endswith(" "))
    ):
        options = _match(text, _session_refs())

    elif parts[0] in ALIASES["setshell"] and (
        (len(parts) == 1 and line.endswith(" ")) or
        (len(parts) == 2 and not line.endswith(" "))
    ):
        options = _match(text, _session_refs())

    elif parts[0] in ALIASES["setshell"] and (
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
            **{
                f"{accent('connect')} {bold(t.name)} {bold(t.syntax)}": t.summary
                for t in TRANSPORTS.values()
            },
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
            f"{alert('Ctrl+O')}": "Toggle listener on/off (pause/resume accepting connections)",
        },
    }
    print_report_box("help", data)