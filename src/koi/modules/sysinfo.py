from __future__ import annotations
from koi.modules.blueprint import KoiModule
from koi.utils.config import TIMEOUTS


class SysInfoModule(KoiModule):
    name        = "sysinfo"
    description = "Gather basic system information from the target."
    category    = "Enumeration"
    usage       = "sysinfo <id>"
    platform    = ["linux", "windows_ps"]

    def run(self) -> None:
        if self.session.os_type == "linux":
            self._run_linux()
        else:
            self._run_windows()

    def _run_linux(self) -> None:
        self.status("Gathering system information...")
        with self.spinner("Collecting system info..."):
            raw = self._try_exec(
                "H=$(hostname 2>/dev/null);"
                " P=$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"');"
                " K=$(uname -r 2>/dev/null);"
                " A=$(uname -m 2>/dev/null);"
                " U=$(uptime -p 2>/dev/null || uptime 2>/dev/null);"
                " C=$(grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs);"
                " R=$(free -h 2>/dev/null | awk '/^Mem:/{print $2\" total, \"$3\" used, \"$4\" free\"}');"
                " D=$(df -h / 2>/dev/null | awk 'NR==2{print $2\" total, \"$3\" used, \"$4\" free\"}');"
                " W=$(who 2>/dev/null | awk '{print $1}' | sort -u | tr '\\n' ',');"
                " ME=$(id 2>/dev/null);"
                " SH=$SHELL;"
                " IP=$(hostname -I 2>/dev/null || ip -4 addr show 2>/dev/null | grep inet | awk '{print $2}' | tr '\\n' ' ');"
                " printf '%s§%s§%s§%s§%s§%s§%s§%s§%s§%s§%s§%s\\n'"
                ' "$H" "$P" "$K" "$A" "$U" "$C" "$R" "$D" "$W" "$ME" "$SH" "$IP"',
                timeout=TIMEOUTS["exec_query"],
            )
        keys = ["hostname", "OS", "kernel", "arch", "uptime", "CPU", "RAM", "disk",
                "logged in users", "current user", "shell", "IP"]
        parts = raw.split("§")
        info = {k: parts[i].strip() for i, k in enumerate(keys)
                if i < len(parts) and parts[i].strip()}
        self.box(f"System Info #{self.session.id}", info)

    def _run_windows(self) -> None:
        self.status("Gathering system information...")

        with self.spinner("Collecting system info..."):
            raw = self._win_query(
                "&{$_os=Get-CimInstance Win32_OperatingSystem;"
                "$_up=(Get-Date)-$_os.LastBootUpTime;"
                "$_ips=(Get-NetIPAddress -AddressFamily IPv4"
                "|Where-Object{$_.PrefixOrigin -ne 'WellKnown'}"
                "|Select-Object -ExpandProperty IPAddress) -join ', ';"
                "@($env:COMPUTERNAME,$env:USERDOMAIN,$_os.Caption,$_os.Version,"
                "$env:PROCESSOR_ARCHITECTURE,"
                "\"$($_up.Days)d $($_up.Hours)h $($_up.Minutes)m\","
                "\"$([math]::Round($_os.TotalVisibleMemorySize/1024/1024,1)) GB total,"
                " $([math]::Round($_os.FreePhysicalMemory/1024/1024,1)) GB free\","
                "(whoami),$_ips) -join 'KOISEP'}"
            )

        keys = ["hostname", "domain", "OS", "version", "arch", "uptime", "RAM", "current user", "IP"]
        parts = raw.split("KOISEP")
        info = {k: parts[i].strip() for i, k in enumerate(keys)
                if i < len(parts) and parts[i].strip() and parts[i].strip() != "unknown"}
        self.box(f"System Info #{self.session.id}", info)

        with self.spinner("Collecting users and privileges..."):
            batch = self._win_query(
                "&{$_privs=((whoami /priv)-match 'Enabled'"
                "|ForEach-Object{(($_ -split '\\s{2,}')[0]).Trim()}) -join 'KOISEP';"
                "$_users=(Get-LocalUser|ForEach-Object{"
                "\"$($_.Name)|||$(if($_.Enabled){'enabled'}else{'disabled'})\"}) -join 'KOISEP';"
                "$_admins=(Get-LocalGroupMember -Group 'Administrators'"
                "|ForEach-Object{\"$($_.Name)|||$($_.ObjectClass)\"}) -join 'KOISEP';"
                "@($_privs,$_users,$_admins) -join 'KOISEC'}"
            )

        sections   = batch.split("KOISEC")
        privs_raw  = sections[0] if len(sections) > 0 else ""
        users_raw  = sections[1] if len(sections) > 1 else ""
        admins_raw = sections[2] if len(sections) > 2 else ""

        if privs_raw.strip():
            privs = {p.strip(): "Enabled" for p in privs_raw.split("KOISEP") if p.strip()}
            if privs:
                self.box("Enabled privileges", privs)

        if users_raw.strip():
            users = {}
            for entry in users_raw.split("KOISEP"):
                if "|||" in entry:
                    name, status = entry.strip().split("|||", 1)
                    if name.strip():
                        users[name.strip()] = status.strip()
            if users:
                self.box("Local users", users)

        if admins_raw.strip():
            admins = {}
            for entry in admins_raw.split("KOISEP"):
                if "|||" in entry:
                    name, kind = entry.strip().split("|||", 1)
                    if name.strip():
                        admins[name.strip()] = kind.strip()
            if admins:
                self.box("Administrators", admins)
