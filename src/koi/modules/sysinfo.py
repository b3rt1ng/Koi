from __future__ import annotations
from koi.modules.blueprint import KoiModule


class SysInfoModule(KoiModule):
    name        = "sysinfo"
    description = "Gather basic system information from the target."
    category    = "Enumeration"
    usage       = "sysinfo <id>"
    platform    = "linux"


    def _get(self, cmd: str, fallback: str = "unknown") -> str:
        lines = [l for l in self._try_exec(cmd, timeout=10).splitlines() if l.strip()]
        return lines[-1] if lines else fallback

    def run(self) -> None:
        self.status("Gathering system information...")

        info = {
            "hostname":    self._get("hostname"),
            "OS":          self._get("cat /etc/os-release | grep PRETTY_NAME | cut -d'=' -f2 | tr -d '\"'"),
            "kernel":      self._get("uname -r"),
            "arch":        self._get("uname -m"),
            "uptime":      self._get("uptime -p 2>/dev/null || uptime"),
            "CPU":         self._get("grep 'model name' /proc/cpuinfo | head -1 | cut -d':' -f2"),
            "RAM":         self._get("free -h | awk '/^Mem:/ {print $2 \" total, \" $3 \" used, \" $4 \" free\"}'"),
            "disk":        self._get("df -h / | awk 'NR==2 {print $2 \" total, \" $3 \" used, \" $4 \" free\"}'"),
            "logged in users": self._get("who | awk '{print $1}' | sort -u"),
            "current user": self._get("id"),
            "shell":       self._get("echo $SHELL"),
            "IP":          self._get("hostname -I 2>/dev/null || ip -4 addr show | grep inet | awk '{print $2}' | tr '\\n' ' '"),
        }

        self.box(f"System Info #{self.session.id}", {
            k: v for k, v in info.items() if v and v.strip()
        })