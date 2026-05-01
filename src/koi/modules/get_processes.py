from __future__ import annotations

from koi.modules.blueprint import KoiModule

# Linux: process names worth flagging
_LINUX_NETWORK    = {"nc", "ncat", "netcat", "socat", "nmap"}
_LINUX_SERVICES   = {
    "apache", "apache2", "httpd", "nginx", "lighttpd", "caddy",
    "mysqld", "postgres", "mongod", "redis-server",
    "sshd", "vsftpd", "ftpd", "telnetd",
    "dockerd", "containerd", "kubelet",
}
_LINUX_INTERP     = {"python", "python2", "python3", "perl", "ruby", "php"}
_LINUX_PRIV       = {"sudo", "su", "cron", "crond", "atd"}
_LINUX_TEMP_PATHS = ("/tmp/", "/dev/shm/", "/var/tmp/", "/run/shm/")

# Windows: LOLBins and well-known noise to exclude from SYSTEM-owned highlight
_WIN_LOLBINS      = {
    "wscript", "cscript", "mshta", "regsvr32", "rundll32", "msiexec",
    "certutil", "bitsadmin", "powershell", "cmd", "wmic", "msbuild",
}


class GetProcessesModule(KoiModule):
    name        = "get_processes"
    description = "List running processes and highlight interesting/privileged ones."
    category    = "Enumeration"
    platform    = ["linux", "windows_ps"]
    usage       = "get_processes <id> [-a] [-f KEYWORD]"
    arguments   = [
        {
            "flags": ["-a", "--all"],
            "action": "store_true",
            "default": False,
            "help": "Show all processes instead of only interesting ones.",
        },
        {
            "flags": ["-f", "--filter"],
            "default": None,
            "metavar": "KEYWORD",
            "help": "Filter by name, user, or path keyword.",
        },
    ]

    def _parse_linux(self, raw: str) -> list[dict]:
        procs = []
        for line in raw.splitlines():
            line = self._clean(line)
            if not line:
                continue
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            user, pid, cpu, mem, cmd = parts[0], parts[1], parts[2], parts[3], parts[10]
            if user == "USER":   # header line
                continue
            procs.append({"user": user, "pid": pid, "cpu": cpu, "mem": mem, "cmd": cmd})
        return procs

    def _is_interesting_linux(self, p: dict) -> bool:
        user = p["user"]
        cmd  = p["cmd"]
        name = cmd.split()[0].split("/")[-1].lower() if cmd else ""

        # Running from a temp / in-memory path
        if any(path in cmd for path in _LINUX_TEMP_PATHS):
            return True
        # Network tools (any user)
        if name in _LINUX_NETWORK:
            return True
        # Interpreters with script arguments (not idle interactive shells)
        if name in _LINUX_INTERP and len(cmd.split()) > 1:
            return True
        # Privilege-escalation helpers
        if name in _LINUX_PRIV:
            return True
        # Root-owned services worth noting
        if user == "root" and name in _LINUX_SERVICES:
            return True
        return False

    def _run_linux(self) -> None:
        with self.spinner("Collecting processes…"):
            raw = self._exec_clean(
                "ps aux --no-headers 2>/dev/null || ps aux 2>/dev/null",
                timeout=15,
            )

        procs = self._parse_linux(raw)
        if not procs:
            self.err("Failed to retrieve process list.")
            return

        self._dispatch(
            procs,
            total=len(procs),
            is_interesting=self._is_interesting_linux,
            key_fn=lambda p: f"PID {p['pid']}  ({p['user']})  CPU:{p['cpu']}%  MEM:{p['mem']}%",
            val_fn=lambda p: p["cmd"],
        )

    _WIN_SYSTEM_USERS = frozenset({
        "n/a", "nt authority\\system", "nt authority\\local service",
        "nt authority\\network service",
    })

    def _parse_windows_tasklist(self, raw: str) -> list[dict]:
        procs = []
        for entry in raw.split("§"):
            entry = self._clean(entry)
            if not entry or not entry.startswith('"'):
                continue
            fields = entry.strip('"').split('","')
            if len(fields) < 5:
                continue
            name    = fields[0]
            pid     = fields[1]
            session = fields[2]          # "Services" | "Console"
            mem     = fields[4]          # "31,516 K"
            user    = fields[6].strip() if len(fields) > 6 else "N/A"
            if not pid.isdigit():
                continue
            procs.append({
                "pid": pid, "name": name,
                "user": user, "session": session, "mem": mem,
            })
        return procs

    def _is_interesting_windows(self, p: dict) -> bool:
        name_lower = p["name"].lower().removesuffix(".exe")
        user_lower = p["user"].lower()

        # LOLBins regardless of user
        if name_lower in _WIN_LOLBINS:
            return True
        # Processes owned by a real (non-system) account
        if user_lower not in self._WIN_SYSTEM_USERS:
            return True
        return False

    def _run_windows(self) -> None:
        ps_expr = "(tasklist /fo csv /nh /v) -join '§'"
        with self.spinner("Collecting processes via tasklist…"):
            raw = self._win_query(ps_expr, timeout=30)

        procs = self._parse_windows_tasklist(raw)
        if not procs:
            self.err("Failed to retrieve process list.")
            return

        self._dispatch(
            procs,
            total=len(procs),
            is_interesting=self._is_interesting_windows,
            key_fn=lambda p: f"PID {p['pid']}  {p['name']}  ({p['user']})",
            val_fn=lambda p: f"session={p['session']}  mem={p['mem']}",
        )

    def _dispatch(self, procs, total, is_interesting, key_fn, val_fn) -> None:
        keyword  = getattr(self.args, "filter", None)
        show_all = getattr(self.args, "all", False)

        if keyword:
            kw = keyword.lower()
            matches = [
                p for p in procs
                if kw in p.get("user", "").lower()
                or kw in p.get("name", p.get("cmd", "")).lower()
                or kw in p.get("cmd", "").lower()
            ]
            label = f"Processes matching '{keyword}'  ({len(matches)} of {total})"
            self.box(label, {key_fn(p): val_fn(p) for p in matches})
            return

        if show_all:
            self.box(f"All processes  ({total})", {key_fn(p): val_fn(p) for p in procs})
            return

        interesting = [p for p in procs if is_interesting(p)]

        if interesting:
            label = (
                f"Interesting processes  ({len(interesting)} of {total} total)"
                f"  —  use -a to show all"
            )
            self.box(label, {key_fn(p): val_fn(p) for p in interesting})
        else:
            self.ok(f"No noteworthy processes found ({total} total). Use -a to list all.")

    def run(self) -> None:
        if self.session.os_type == "linux":
            self._run_linux()
        else:
            self._run_windows()
