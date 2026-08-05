from __future__ import annotations

import io
import os
import shlex
import tarfile
import zipfile

from koi.modules.blueprint import KoiModule
from koi.utils.config import TIMEOUTS

_DIR_TIMEOUT = max(TIMEOUTS.get("download", 300) * 2, 600)


def _shell_quote(path: str) -> str:
    return shlex.quote(path)


def _ps_quote(path: str) -> str:
    return path.replace("'", "''")


class UploadModule(KoiModule):
    name = "upload"
    description = "Upload a file or directory to the target."
    usage = "upload <id> <local_path> [-o <remote_path>]"
    category = "File transfer"
    platform = ["linux", "windows_ps"]
    arguments = [
        {"flags": ["local_path"], "help": "Local file or directory to upload"},
        {"flags": ["-o", "--output"], "default": None, "help": "Remote destination path"},
    ]

    def run(self) -> None:
        local_path = self.args.local_path.rstrip("/\\")
        os_type    = self.session.os_type
        basename   = os.path.basename(local_path) or os.path.basename(os.path.abspath(local_path))

        # 1. Detect local type
        is_dir  = os.path.isdir(local_path)
        is_file = os.path.isfile(local_path)

        if not is_dir and not is_file:
            self.err(f"Local path not found: {local_path}")
            return

        # 2. Determine remote destination
        if self.args.output:
            remote_dest = self.args.output
        elif os_type == "linux":
            remote_dest = f"./{basename}"
        else:
            remote_dest = f".\\{basename}"

        if is_file:
            with open(local_path, "rb") as f:
                raw = f.read()

            total = len(raw)
            bar   = self.ui.ProgressBar(total=total)
            self.status(f"Uploading {local_path} → {remote_dest} ({total:,} bytes)...")
            ok = self._upload_bytes(
                raw, remote_dest,
                timeout=TIMEOUTS.get("upload", 30),
                on_progress=bar.update,
            )
            bar.done()
            print()

            if not ok:
                self.err("Transfer failed.")
                return

            self.box("Upload complete", {
                "local path":  os.path.abspath(local_path),
                "remote path": remote_dest,
                "size":        f"{total:,} bytes  ({total / 1024:.1f} KB)",
            })

        else:
            file_count = sum(len(files) for _, _, files in os.walk(local_path))
            if file_count == 0:
                self.warn(f"Directory is empty: {local_path}")

            # 3. Build archive in memory
            with self.spinner(f"Archiving {file_count} file(s)..."):
                try:
                    buf = io.BytesIO()
                    if os_type == "linux":
                        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                            tar.add(local_path, arcname=".", recursive=True)
                    else:
                        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                            for root, _dirs, files in os.walk(local_path):
                                for filename in sorted(files):
                                    abs_path = os.path.join(root, filename)
                                    arcname  = os.path.relpath(abs_path, local_path)
                                    zf.write(abs_path, arcname)
                    raw = buf.getvalue()
                except Exception as exc:
                    self.err(f"Could not build archive: {exc}")
                    return

            total = len(raw)
            self.status(
                f"Uploading {local_path}/ → {remote_dest} "
                f"({file_count} file(s), {total:,} bytes)..."
            )

            # 4. Choose temp path on target
            if os_type == "linux":
                remote_tmp = f"/tmp/.koi_upload_{self.session.id}.tar.gz"
            else:
                temp_dir = self._win_query("$env:TEMP", timeout=10).strip() or "C:\\Windows\\Temp"
                remote_tmp = f"{temp_dir}\\koi_upload_{self.session.id}.zip"

            # 5. Upload archive
            bar = self.ui.ProgressBar(total=total)
            ok  = self._upload_bytes(raw, remote_tmp, timeout=_DIR_TIMEOUT, on_progress=bar.update)
            bar.done()
            print()

            if not ok:
                self.err("Transfer failed — archive not delivered to target.")
                return

            # 6. Extract on target
            with self.spinner("Extracting on target..."):
                if os_type == "linux":
                    quoted_dest = _shell_quote(remote_dest)
                    quoted_tmp  = _shell_quote(remote_tmp)
                    result = self.exec(
                        f"mkdir -p {quoted_dest} "
                        f"&& tar xzf {quoted_tmp} -C {quoted_dest} "
                        f"&& rm -f {quoted_tmp}",
                        timeout=_DIR_TIMEOUT,
                    )
                    if not result.success:
                        self.err(
                            f"Extraction failed (rc={result.returncode}): "
                            f"{result.stdout.strip()[:120]}"
                        )
                        self._try_exec(f"rm -f {quoted_tmp}")
                        return
                    count_raw = self._try_exec(f"find {quoted_dest} -type f | wc -l")
                    try:
                        extracted_count: int | None = int(count_raw.split()[0])
                    except (ValueError, IndexError):
                        extracted_count = None
                    resolved = self._try_exec(f"realpath {quoted_dest} 2>/dev/null").strip()
                    if resolved:
                        remote_dest = resolved

                else:
                    ps_dest = _ps_quote(remote_dest)
                    ps_tmp  = _ps_quote(remote_tmp)
                    result_raw = self._win_query(
                        f"try{{"
                        f"New-Item -ItemType Directory -Path '{ps_dest}' -Force|Out-Null;"
                        f"Expand-Archive -LiteralPath '{ps_tmp}' -DestinationPath '{ps_dest}' -Force;"
                        f"Remove-Item '{ps_tmp}' -EA SilentlyContinue;"
                        f"(Get-ChildItem -LiteralPath '{ps_dest}' -Recurse -File -EA SilentlyContinue).Count"
                        f"}}catch{{'err:'+$_.Exception.Message}}",
                        timeout=_DIR_TIMEOUT,
                    ).strip()
                    if result_raw.startswith("err:"):
                        self.err(f"Extraction failed: {result_raw[4:120]}")
                        self._win_query(f"Remove-Item '{ps_tmp}' -EA SilentlyContinue", timeout=10)
                        return
                    try:
                        extracted_count = int(result_raw)
                    except (ValueError, AttributeError):
                        extracted_count = None
                    resolved = self._win_query(
                        f"(Get-Item -LiteralPath '{ps_dest}' -Force -EA SilentlyContinue).FullName",
                        timeout=10,
                    ).strip()
                    if resolved:
                        remote_dest = resolved

            summary: dict[str, str] = {
                "local path":  os.path.abspath(local_path),
                "remote path": remote_dest,
                "uploaded":    f"{total:,} bytes  ({total / 1024:.1f} KB)",
                "files sent":  str(file_count),
            }
            if extracted_count is not None:
                summary["files on target"] = str(extracted_count)
            self.box("Upload complete", summary)