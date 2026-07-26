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
            raw = self._try_exec("""
printf 'HOSTNAME=%s\\n' "$(hostname 2>/dev/null)"
grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"' | sed 's/^/OS=/'
printf 'KERNEL=%s\\n' "$(uname -r 2>/dev/null)"
printf 'ARCH=%s\\n' "$(uname -m 2>/dev/null)"
printf 'UPTIME=%s\\n' "$(uptime -p 2>/dev/null || uptime 2>/dev/null)"
grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs | sed 's/^/CPU=/'
free -h 2>/dev/null | awk '/^Mem:/{print "RAM="$2" total, "$3" used, "$4" free"}'
df -h / 2>/dev/null | awk 'NR==2{print "DISK="$2" total, "$3" used, "$4" free"}'
who 2>/dev/null | awk '{print $1}' | sort -u | paste -sd, | sed 's/^/USERS=/'
printf 'CURRENT_USER=%s\\n' "$(id 2>/dev/null)"
printf 'SHELL=%s\\n' "$SHELL"
hostname -I 2>/dev/null | sed 's/^/IPS=/' || ip -4 addr show 2>/dev/null | grep inet | awk '{print $2}' | tr '\\n' ' ' | sed 's/^/IPS=/'
""", timeout=TIMEOUTS["exec_query"])

        info = {}
        for line in raw.strip().split('\n'):
            if '=' in line:
                key, val = line.split('=', 1)
                val = val.strip()
                if val:
                    info[key.lower()] = val

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
                f"(whoami),$_ips) -join '{self.REC_SEP}'}}"
            )

        keys = ["hostname", "domain", "OS", "version", "arch", "uptime", "RAM", "current user", "IP"]
        parts = raw.split(self.REC_SEP)
        info = {k: parts[i].strip() for i, k in enumerate(keys)
                if i < len(parts) and parts[i].strip() and parts[i].strip() != "unknown"}
        self.box(f"System Info #{self.session.id}", info)

        with self.spinner("Collecting users and privileges..."):
            batch = self._win_query(
                "&{$_privs=((whoami /priv)-match 'Enabled'"
                "|ForEach-Object{(($_ -split '\\s{2,}')[0]).Trim()}) -join '"
                f"{self.REC_SEP}';"
                "$_users=(Get-LocalUser|ForEach-Object{"
                f"\"$($_.Name){self.FIELD_SEP}$(if($_.Enabled)"
                "{'enabled'}else{'disabled'})\"}) -join '"
                f"{self.REC_SEP}';"
                "$_admins=(Get-LocalGroupMember -Group 'Administrators'"
                "|ForEach-Object{"
                f"\"$($_.Name){self.FIELD_SEP}$($_.ObjectClass)\""
                "}) -join '"
                f"{self.REC_SEP}';"
                f"@($_privs,$_users,$_admins) -join '{self.SEC_SEP}'}}"
            )

        sections   = batch.split(self.SEC_SEP)
        privs_raw  = sections[0] if len(sections) > 0 else ""
        users_raw  = sections[1] if len(sections) > 1 else ""
        admins_raw = sections[2] if len(sections) > 2 else ""

        if privs_raw.strip():
            privs = {p.strip(): "Enabled" for p in privs_raw.split(self.REC_SEP) if p.strip()}
            if privs:
                self.box("Enabled privileges", privs)

        if users_raw.strip():
            users = {}
            for entry in users_raw.split(self.REC_SEP):
                if self.FIELD_SEP in entry:
                    name, status = entry.strip().split(self.FIELD_SEP, 1)
                    if name.strip():
                        users[name.strip()] = status.strip()
            if users:
                self.box("Local users", users)

        if admins_raw.strip():
            admins = {}
            for entry in admins_raw.split(self.REC_SEP):
                if self.FIELD_SEP in entry:
                    name, kind = entry.strip().split(self.FIELD_SEP, 1)
                    if name.strip():
                        admins[name.strip()] = kind.strip()
            if admins:
                self.box("Administrators", admins)
