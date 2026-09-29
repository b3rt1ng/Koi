from __future__ import annotations

import base64
import os

from koi.modules.blueprint import KoiModule
from koi.utils.config import TIMEOUTS

_DEFAULT_CHUNK = 49152


class Upload64Module(KoiModule):
    name = "upload64"
    description = "Upload a file via base64 chunks (for restricted shells)."
    usage = "upload64 <id> <local_path> [-o <remote_path>] [-c <chunk_size>]"
    category = "File transfer"
    platform = ["linux", "windows_ps", "windows_cmd"]
    arguments = [
        {"flags": ["local_path"], "help": "Local file to upload"},
        {"flags": ["-o", "--output"], "default": None,
         "help": "Remote destination path"},
        {"flags": ["-c", "--chunk-size"], "type": int, "default": _DEFAULT_CHUNK,
         "help": f"Base64 bytes per command (default: {_DEFAULT_CHUNK})"},
    ]

    def run(self) -> None:
        local_path = self.args.local_path.rstrip("/\\")
        chunk_size = self.args.chunk_size

        if chunk_size <= 0:
            self.err("Chunk size must be positive.")
            return

        if not os.path.isfile(local_path):
            self.err(f"Local file not found: {local_path}")
            return

        with open(local_path, "rb") as f:
            raw = f.read()

        total = len(raw)
        b64 = base64.b64encode(raw).decode("ascii")
        basename = os.path.basename(local_path)
        os_type = self.session.os_type

        if self.args.output:
            remote_dest = self.args.output
        elif os_type == "linux":
            remote_dest = f"./{basename}"
        else:
            remote_dest = f".\\{basename}"

        chunks = [b64[i:i + chunk_size] for i in range(0, len(b64), chunk_size)]

        self.status(
            f"Uploading {basename} via base64 "
            f"({total:,} bytes, {len(chunks)} chunk(s))..."
        )

        if os_type == "linux":
            self._upload_linux(chunks, remote_dest, total)
        else:
            self._upload_windows(chunks, remote_dest, total)

    def _upload_linux(self, chunks, dest, expected_size):
        tmp = f"/tmp/.koi_b64_{self.session.id}"
        quoted_tmp = self._shell_quote(tmp)
        quoted_dest = self._shell_quote(dest)
        timeout = max(TIMEOUTS.get("upload", 30), 30)

        self.exec(f"rm -f {quoted_tmp}", timeout=timeout)

        bar = self.ui.ProgressBar(total=expected_size)
        n = len(chunks)

        for i, chunk in enumerate(chunks):
            result = self.exec(
                f"printf '%s' '{chunk}' >> {quoted_tmp}",
                timeout=timeout,
            )
            if not result.success:
                bar.done()
                print()
                self.err(f"Chunk {i + 1}/{n} failed (rc={result.returncode})")
                self.exec(f"rm -f {quoted_tmp}", timeout=5)
                return
            bar.update(min(expected_size, expected_size * (i + 1) // n))

        bar.done()
        print()

        with self.spinner("Decoding on target..."):
            result = self.exec(
                f"base64 -d {quoted_tmp} > {quoted_dest} && rm -f {quoted_tmp}",
                timeout=timeout,
            )

        if not result.success:
            self.err(
                f"Decode failed (rc={result.returncode}): "
                f"{result.stdout.strip()[:200]}"
            )
            self.exec(f"rm -f {quoted_tmp} {quoted_dest}", timeout=5)
            return

        size_str = self._try_exec(f"wc -c < {quoted_dest} 2>/dev/null")
        try:
            remote_size = int(size_str.split()[0])
        except (ValueError, IndexError):
            remote_size = None

        if remote_size is not None and remote_size != expected_size:
            self.err(
                f"Size mismatch: expected {expected_size:,}, "
                f"got {remote_size:,} on target"
            )
            return

        self.box("Upload complete (base64)", {
            "local path":  os.path.abspath(self.args.local_path),
            "remote path": dest,
            "size":        f"{expected_size:,} bytes ({expected_size / 1024:.1f} KB)",
            "chunks":      str(len(chunks)),
            "verified":    "yes" if remote_size == expected_size else "size unknown",
        })

    def _upload_windows(self, chunks, dest, expected_size):
        ps_dest = self._ps_quote(dest)
        tmp_name = f"koi_b64_{self.session.id}.txt"
        timeout = max(TIMEOUTS.get("upload", 30), 30)

        temp_dir = (
            self._win_query("$env:TEMP", timeout=10).strip()
            or "C:\\Windows\\Temp"
        )
        tmp = f"{temp_dir}\\{tmp_name}"
        ps_tmp = self._ps_quote(tmp)

        self._win_query(
            f"Remove-Item '{ps_tmp}' -EA SilentlyContinue", timeout=5,
        )

        bar = self.ui.ProgressBar(total=expected_size)
        n = len(chunks)

        for i, chunk in enumerate(chunks):
            result_raw = self._win_query(
                f"[IO.File]::AppendAllText('{ps_tmp}','{chunk}');'ok'",
                timeout=timeout,
            )
            if "ok" not in result_raw.lower():
                bar.done()
                print()
                self.err(f"Chunk {i + 1}/{n} failed")
                self._win_query(
                    f"Remove-Item '{ps_tmp}' -EA SilentlyContinue", timeout=5,
                )
                return
            bar.update(min(expected_size, expected_size * (i + 1) // n))

        bar.done()
        print()

        resolved = (
            "$ExecutionContext.SessionState.Path."
            f"GetUnresolvedProviderPathFromPSPath('{ps_dest}')"
        )
        with self.spinner("Decoding on target..."):
            result_raw = self._win_query(
                f"try{{"
                f"$_b=[Convert]::FromBase64String("
                f"(Get-Content '{ps_tmp}' -Raw));"
                f"[IO.File]::WriteAllBytes({resolved},$_b);"
                f"Remove-Item '{ps_tmp}' -EA SilentlyContinue;"
                f"'ok'"
                f"}}catch{{'err:'+$_.Exception.Message}}",
                timeout=timeout,
            ).strip()

        if result_raw.startswith("err:"):
            self.err(f"Decode failed: {result_raw[4:120]}")
            self._win_query(
                f"Remove-Item '{ps_tmp}' -EA SilentlyContinue", timeout=5,
            )
            return

        size_str = self._win_query(
            f"(Get-Item -LiteralPath ({resolved}) "
            f"-EA SilentlyContinue).Length",
            timeout=timeout,
        )
        try:
            remote_size = int(size_str.strip())
        except (ValueError, AttributeError):
            remote_size = None

        if remote_size is not None and remote_size != expected_size:
            self.err(
                f"Size mismatch: expected {expected_size:,}, "
                f"got {remote_size:,} on target"
            )
            return

        self.box("Upload complete (base64)", {
            "local path":  os.path.abspath(self.args.local_path),
            "remote path": dest,
            "size":        f"{expected_size:,} bytes ({expected_size / 1024:.1f} KB)",
            "chunks":      str(len(chunks)),
            "verified":    "yes" if remote_size == expected_size else "size unknown",
        })
