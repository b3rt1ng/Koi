from __future__ import annotations
from koi.modules.blueprint import KoiModule


class SysInfoModule(KoiModule):
    name        = "sysinfo"
    description = "Gather basic system information from the target."
    category    = "Enumeration"
    usage       = "sysinfo <id>"
    platform    = ["linux", "windows_ps"]

    def _get(self, cmd: str, fallback: str = "unknown") -> str:
        lines = [ln for ln in self._try_exec(cmd, timeout=10).splitlines() if ln.strip()]
        return lines[-1] if lines else fallback

    def _wget(self, expr: str, fallback: str = "unknown") -> str:
        val = self._win_query(expr).strip()
        return val if val else fallback

    def run(self) -> None:
        if self.session.os_type == "linux":
            self._run_linux()
        else:
            self._run_windows()

    def _run_linux(self) -> None:
        self.status("Gathering system information...")

        info = {
            "hostname":        self._get("hostname"),
            "OS":              self._get("cat /etc/os-release | grep PRETTY_NAME | cut -d'=' -f2 | tr -d '\"'"),
            "kernel":          self._get("uname -r"),
            "arch":            self._get("uname -m"),
            "uptime":          self._get("uptime -p 2>/dev/null || uptime"),
            "CPU":             self._get("grep 'model name' /proc/cpuinfo | head -1 | cut -d':' -f2"),
            "RAM":             self._get("free -h | awk '/^Mem:/ {print $2 \" total, \" $3 \" used, \" $4 \" free\"}'"),
            "disk":            self._get("df -h / | awk 'NR==2 {print $2 \" total, \" $3 \" used, \" $4 \" free\"}'"),
            "logged in users": self._get("who | awk '{print $1}' | sort -u"),
            "current user":    self._get("id"),
            "shell":           self._get("echo $SHELL"),
            "IP":              self._get("hostname -I 2>/dev/null || ip -4 addr show | grep inet | awk '{print $2}' | tr '\\n' ' '"),
        }

        self.box(f"System Info #{self.session.id}", {k: v for k, v in info.items() if v and v.strip()})

    def _run_windows(self) -> None:
        self.status("Gathering system information...")

        with self.spinner("Collecting system info..."):
            info = {
                "hostname":     self._wget("$env:COMPUTERNAME"),
                "domain":       self._wget("$env:USERDOMAIN"),
                "OS":           self._wget("(Get-CimInstance Win32_OperatingSystem).Caption"),
                "version":      self._wget("(Get-CimInstance Win32_OperatingSystem).Version"),
                "arch":         self._wget("$env:PROCESSOR_ARCHITECTURE"),
                "uptime":       self._wget(
                    "(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime"
                    " | ForEach-Object { \"$($_.Days)d $($_.Hours)h $($_.Minutes)m\" }"
                ),
                "RAM":          self._wget(
                    "Get-CimInstance Win32_OperatingSystem | ForEach-Object {"
                    " \"$([math]::Round($_.TotalVisibleMemorySize/1024/1024,1)) GB total,"
                    " $([math]::Round($_.FreePhysicalMemory/1024/1024,1)) GB free\" }"
                ),
                "current user": self._wget("whoami"),
                "IP":           self._wget(
                    "(Get-NetIPAddress -AddressFamily IPv4"
                    " | Where-Object {$_.PrefixOrigin -ne 'WellKnown'}"
                    " | Select-Object -ExpandProperty IPAddress) -join ', '"
                ),
            }

        self.box(f"System Info #{self.session.id}", {k: v for k, v in info.items() if v and v != "unknown"})

        with self.spinner("Collecting enabled privileges..."):
            privs_raw = self._win_query(
                "((whoami /priv) -match 'Enabled'"
                " | ForEach-Object { (($_ -split '\\s{2,}')[0]).Trim() }) -join '§'"
            )
        if privs_raw.strip():
            privs = {p.strip(): "Enabled" for p in privs_raw.split("§") if p.strip()}
            if privs:
                self.box("Enabled privileges", privs)

        with self.spinner("Listing local users..."):
            users_raw = self._win_query(
                "(Get-LocalUser | ForEach-Object {"
                " \"$($_.Name)|||$(if($_.Enabled){'enabled'}else{'disabled'})\" }) -join '§'"
            )
        if users_raw.strip():
            users = {}
            for entry in users_raw.split("§"):
                if "|||" in entry:
                    name, status = entry.strip().split("|||", 1)
                    if name.strip():
                        users[name.strip()] = status.strip()
            if users:
                self.box("Local users", users)

        with self.spinner("Listing administrators..."):
            admins_raw = self._win_query(
                "(Get-LocalGroupMember -Group 'Administrators'"
                " | ForEach-Object { \"$($_.Name)|||$($_.ObjectClass)\" }) -join '§'"
            )
        if admins_raw.strip():
            admins = {}
            for entry in admins_raw.split("§"):
                if "|||" in entry:
                    name, kind = entry.strip().split("|||", 1)
                    if name.strip():
                        admins[name.strip()] = kind.strip()
            if admins:
                self.box("Administrators", admins)
