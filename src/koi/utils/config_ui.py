from __future__ import annotations

import os
import select
import sys
import termios
import tty
from typing import Any

from koi.utils.config import CONFIG, TIMEOUTS, DEFAULTS, persist, _CONFIG_PATH
from koi.utils.ui import (
    bold, accent, dim, muted, plain,
    gradient_text,
    PUMPKIN, CORAL,
    notify,
)

_HIDE       = "\033[?25l"
_SHOW       = "\033[?25h"
_ALT_ON     = "\033[?1049h"
_ALT_OFF    = "\033[?1049l"
_CLEAR      = "\033[2J\033[H"
_RED        = "\033[38;2;255;80;80m"
_RST        = "\033[0m"

_SETTINGS: list[tuple[str, type]] = [
    ("port",            int),
    ("display_art",     bool),
    ("logging",         bool),
    ("keep_history",    bool),
    ("local_mode",      bool),
    ("exec_command",    float),
    ("exec_query",      float),
    ("upload",          float),
    ("download",        float),
    ("http_fetch",      float),
    ("session_detect",  float),
    ("mcp_activate",    bool),
    ("mcp_exec_allow",  bool),
    ("mcp_port",        int),
    ("mcp_token",       str),
]

_PORT_KEYS = {"port", "mcp_port"}


def _get_value(key: str) -> Any:
    if key in DEFAULTS["timeouts"]:
        return TIMEOUTS.get(key, DEFAULTS["timeouts"][key])
    return CONFIG.get(key, DEFAULTS.get(key))


def _set_value(key: str, value: Any) -> None:
    if key in DEFAULTS["timeouts"]:
        TIMEOUTS[key] = value
    else:
        CONFIG[key] = value


def _getch() -> bytes:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1)
        if ch == b'\x1b':
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                nxt = os.read(fd, 1)
                if nxt == b'[':
                    param = bytearray()
                    while True:
                        b = os.read(fd, 1)
                        if not b:
                            break
                        param.extend(b)
                        if 0x40 <= b[0] <= 0x7E:
                            break
                        if len(param) > 16:
                            break
                    return b'\x1b[' + bytes(param)
                return b'\x1b' + nxt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _format_value(value: Any, vtype: type, error: bool = False) -> str:
    if value is None:
        text = "none"
    elif vtype is bool:
        text = "true" if value else "false"
    elif vtype is float and isinstance(value, (int, float)) and value % 1 == 0:
        text = str(int(value))
    else:
        text = str(value)
    if error:
        return f"{_RED}{text}{_RST}"
    return text


def _validate(raw: str, vtype: type, key: str = "") -> tuple[bool, Any]:
    if vtype is bool:
        return True, None
    if vtype is int:
        try:
            v = int(raw)
        except ValueError:
            return False, None
        if key in _PORT_KEYS and not (1 <= v <= 65535):
            return False, None
        return True, v
    if vtype is float:
        try:
            v = float(raw)
        except ValueError:
            return False, None
        if v < 0:
            return False, None
        return True, v
    if vtype is str:
        return True, raw
    return False, None


def _render(cursor: int, editing: int, edit_buf: str, edit_error: bool,
            values: list[Any]) -> None:
    sys.stdout.write(_CLEAR)
    sys.stdout.write("\n")
    sys.stdout.write("  " + gradient_text("Config", PUMPKIN, CORAL) + "\n\n")

    name_w = max(len(s[0]) for s in _SETTINGS) + 2

    for i, (key, vtype) in enumerate(_SETTINGS):
        val = values[i]
        is_cursor = (i == cursor)
        is_editing = (i == editing)

        name_str = f"{key:<{name_w}}"
        restart_hint = dim(" (restart)") if key in _PORT_KEYS else ""

        if is_editing:
            if edit_error:
                val_str = f"{_RED}{edit_buf}_{_RST}"
            else:
                val_str = f"{accent(edit_buf + '_')}"
            sys.stdout.write(f"  {accent('►')} {bold(accent(name_str))} {val_str}{restart_hint}\n")
        elif is_cursor:
            val_str = _format_value(val, vtype)
            sys.stdout.write(f"  {accent('►')} {bold(accent(name_str))} {plain(val_str)}{restart_hint}\n")
        else:
            val_str = _format_value(val, vtype)
            sys.stdout.write(f"    {plain(name_str)} {dim(val_str)}{restart_hint}\n")

    sys.stdout.write(f"\n  {dim('↑/↓')} navigate  ")
    _, vtype = _SETTINGS[cursor]
    if editing >= 0:
        sys.stdout.write(f"{dim('Enter')} confirm  {dim('Esc')} cancel")
    elif vtype is bool:
        sys.stdout.write(f"{dim('Enter')} switch  {dim('Esc')} save & quit")
    else:
        sys.stdout.write(f"{dim('Enter')} edit  {dim('Esc')} save & quit")
    sys.stdout.write("\n")
    sys.stdout.flush()


def run_config_ui() -> None:
    cursor = 0
    editing = -1
    edit_buf = ""
    edit_error = False
    original_values: list[Any] = [_get_value(key) for key, _ in _SETTINGS]
    values: list[Any] = list(original_values)

    sys.stdout.write(_ALT_ON + _HIDE)
    sys.stdout.flush()
    try:
        while True:
            _render(cursor, editing, edit_buf, edit_error, values)
            ch = _getch()

            if editing >= 0:
                key, vtype = _SETTINGS[editing]
                if ch in (b'\r', b'\n'):
                    ok, parsed = _validate(edit_buf, vtype, key)
                    if ok and not edit_error:
                        values[editing] = parsed
                        _set_value(key, parsed)
                        editing = -1
                        edit_buf = ""
                        edit_error = False
                elif ch == b'\x1b':
                    editing = -1
                    edit_buf = ""
                    edit_error = False
                elif ch in (b'\x7f', b'\x08'):
                    edit_buf = edit_buf[:-1]
                    if edit_buf:
                        ok, _ = _validate(edit_buf, vtype, key)
                        edit_error = not ok
                    else:
                        edit_error = False
                else:
                    try:
                        c = ch.decode("utf-8")
                        if c.isprintable():
                            edit_buf += c
                            ok, _ = _validate(edit_buf, vtype, key)
                            edit_error = not ok
                    except UnicodeDecodeError:
                        pass
                continue

            if ch == b'\x1b[A':
                cursor = (cursor - 1) % len(_SETTINGS)
            elif ch == b'\x1b[B':
                cursor = (cursor + 1) % len(_SETTINGS)
            elif ch in (b'\r', b'\n'):
                key, vtype = _SETTINGS[cursor]
                if vtype is bool:
                    new_val = not values[cursor]
                    values[cursor] = new_val
                    _set_value(key, new_val)
                else:
                    editing = cursor
                    current = values[cursor]
                    if current is None:
                        edit_buf = ""
                    elif vtype is float and isinstance(current, (int, float)) and current % 1 == 0:
                        edit_buf = str(int(current))
                    else:
                        edit_buf = str(current)
                    edit_error = False
            elif ch in (b'\x1b', b'\x03'):
                break

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(_SHOW + _ALT_OFF)
        sys.stdout.flush()

    changed = []
    errors = []
    timeouts_dirty = False
    for i, (key, vtype) in enumerate(_SETTINGS):
        if values[i] != original_values[i]:
            if key in DEFAULTS["timeouts"]:
                timeouts_dirty = True
                changed.append(key)
            else:
                if persist(key, values[i]):
                    changed.append(key)
                else:
                    errors.append(key)

    if timeouts_dirty:
        if persist("timeouts", dict(TIMEOUTS)):
            pass
        else:
            errors.extend(k for i, (k, _) in enumerate(_SETTINGS)
                         if k in DEFAULTS["timeouts"] and values[i] != original_values[i])
            changed = [c for c in changed if c not in errors]

    if changed:
        notify('success', f"Configuration saved to {accent(str(_CONFIG_PATH))}")
    if errors:
        notify('error', f"Failed to save: {', '.join(accent(e) for e in errors)}")
    if not changed and not errors:
        notify('status', muted("No changes."))
