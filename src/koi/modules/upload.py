from __future__ import annotations

import os

from koi.modules.blueprint import KoiModule


class UploadModule(KoiModule):
    name = "upload"
    description = "Upload a local file to the target via a dedicated TCP connection."
    usage = "upload <id> <local_path> [-o <remote_path>]"
    category = "File transfer"
    platform = ["linux", "windows_ps"]
    arguments = [
        {"flags": ["local_path"], "help": "Path of the local file to upload"},
        {"flags": ["-o", "--output"], "default": None, "help": "Remote destination path"},
    ]

    def run(self) -> None:
        local_path  = self.args.local_path
        os_type     = self.session.os_type
        basename    = os.path.basename(local_path)
        if self.args.output:
            remote_path = self.args.output
        elif os_type == "linux":
            cwd = self._exec_clean("pwd").strip() or "/tmp"
            remote_path = f"{cwd}/{basename}"
        else:
            cwd = self._win_query("(Get-Location).Path").strip() or "C:\\Windows\\Temp"
            remote_path = f"{cwd}\\{basename}"

        if not os.path.isfile(local_path):
            self.err(f"Local file not found: {local_path}")
            return

        with open(local_path, "rb") as f:
            raw = f.read()

        total = len(raw)
        bar = self.ui.ProgressBar(total=total)
        self.status(f"Uploading {local_path} -> {remote_path} ({total} bytes)…")
        ok = self._upload_bytes(raw, remote_path, timeout=30, on_progress=bar.update)
        bar.done()
        print()

        if not ok:
            self.err("Transfer failed.")
            return

        self.box("Upload complete", {
            "local path":  os.path.abspath(local_path),
            "remote path": remote_path,
            "size":        f"{total} bytes  ({total/1024:.1f} KB)",
        })
