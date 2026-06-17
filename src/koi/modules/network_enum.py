from __future__ import annotations

import re
from koi.modules.blueprint import KoiModule
from koi.utils.config import TIMEOUTS


class NetworkEnumModule(KoiModule):
    name        = "netscan"
    description = "Enumerate interfaces, routes, connections, open ports, and discover live hosts."
    category    = "Enumeration"
    platform    = "linux"
    usage       = "netscan <id> [--no-scan] [-s CIDR] [-t N]"
    arguments   = [
        {"flags": ["--no-scan"], "action": "store_true", "default": False,
         "help": "Skip live host discovery (ping sweep)."},
        {"flags": ["-s", "--subnet"], "default": None, "metavar": "CIDR",
         "help": "Override target subnet for host discovery (e.g. 10.10.0.0/24)."},
        {"flags": ["-t", "--timeout"], "type": int, "default": 1, "metavar": "N",
         "help": "Ping timeout per host for discovery (default: 1s)."},
    ]

    def _section_interfaces(self) -> tuple[dict, list[tuple[str, str]]]:
        grouped: dict[str, list[str]] = {}
        ipv4_ifaces: list[tuple[str, str]] = []
        for line in self._try_exec("ip -o addr show", timeout=TIMEOUTS["exec_query"]).splitlines():
            m = re.search(r'\d+:\s+(\S+)\s+(inet6?)\s+(\S+)', self._clean(line))
            if not m or m.group(1) == "lo":
                continue
            iface, family, addr = m.group(1), m.group(2), m.group(3)
            grouped.setdefault(iface, []).append(addr)
            if family == "inet" and "/" in addr:
                ipv4_ifaces.append((iface, addr))
        return {iface: "  ".join(addrs) for iface, addrs in grouped.items()}, ipv4_ifaces

    def _section_routes(self) -> dict:
        box: dict[str, str] = {}
        for line in self._try_exec("ip route show", timeout=TIMEOUTS["exec_query"]).splitlines():
            line = self._clean(line)
            if line:
                parts = line.split(None, 1)
                box[parts[0]] = parts[1] if len(parts) > 1 else ""
        return box

    def _section_neighbors(self) -> dict:
        box: dict[str, str] = {}
        for line in self._try_exec("ip neigh show 2>/dev/null || arp -a 2>/dev/null", timeout=TIMEOUTS["exec_query"]).splitlines():
            line = self._clean(line)
            m = re.match(r'(\d+\.\d+\.\d+\.\d+)\s+dev\s+(\S+)(?:\s+lladdr\s+([0-9a-fA-F:]{17}))?\s*(\S*)', line)
            if m:
                ip, dev, mac, state = m.groups()
                state = (state or "UNKNOWN").strip()
                if state not in ("FAILED", ""):
                    box[ip] = f"{mac}  [{state}]  dev={dev}" if mac else f"[{state}]  dev={dev}"
                continue
            m = re.search(r'\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]{17}).*on\s+(\S+)', line)
            if m:
                ip, mac, dev = m.groups()
                box[ip] = f"{mac}  dev={dev}"
        return box

    def _pid_info(self, pids: list[str]) -> dict[str, tuple[str, str]]:
        if not pids:
            return {}
        info: dict[str, tuple[str, str]] = {}
        for line in self._try_exec(f"ps -o pid=,user=,comm= -p {','.join(pids)} 2>/dev/null", timeout=TIMEOUTS["exec_query"]).splitlines():
            parts = line.split(None, 2)
            if len(parts) >= 2:
                info[parts[0].strip()] = (parts[1].strip(), parts[2].strip() if len(parts) == 3 else "")
        return info

    def _section_listening(self) -> dict:
        entries: list[tuple[str, str, str]] = []
        for line in self._try_exec("ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null", timeout=TIMEOUTS["exec_query"]).splitlines():
            line = self._clean(line)
            if not line or line.startswith(("State", "Proto", "Netid")):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            if parts[0] in ("LISTEN", "tcp", "tcp6"):
                proc_m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
                entries.append((parts[3], proc_m.group(1) if proc_m else "", proc_m.group(2) if proc_m else ""))
            elif re.match(r'tcp6?', parts[0]) and len(parts) >= 7:
                pid, _, name = parts[6].partition("/")
                entries.append((parts[3], name, pid if name else ""))

        pid_info = self._pid_info([pid for _, _, pid in entries if pid])
        box: dict[str, str] = {}
        for local, name, pid in entries:
            if pid and pid in pid_info:
                user, cmd = pid_info[pid]
                box[local] = f"{name or cmd}  pid={pid}  user={user}"
            else:
                box[local] = f"{name}  pid={pid}".strip() if (name or pid) else "-"
        return box

    def _section_connections(self) -> dict:
        box: dict[str, str] = {}
        for line in self._try_exec("ss -tnp state established 2>/dev/null || netstat -tnp 2>/dev/null | grep ESTABLISHED", timeout=TIMEOUTS["exec_query"]).splitlines():
            line = self._clean(line)
            if not line or line.startswith(("Recv", "Proto")):
                continue
            parts = line.split()
            if len(parts) >= 4 and re.match(r'[\d\[\]:]', parts[2]):
                proc_m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
                box[f"{parts[2]} -> {parts[3]}"] = f"{proc_m.group(1)} pid={proc_m.group(2)}" if proc_m else ""
            elif re.match(r'tcp6?', parts[0]) and len(parts) >= 7:
                box[f"{parts[3]} -> {parts[4]}"] = parts[6]
        return box

    def _section_dns(self) -> dict:
        box: dict[str, str] = {}
        idx: dict[str, int] = {}
        for line in self._try_exec("cat /etc/resolv.conf 2>/dev/null", timeout=TIMEOUTS["exec_query"]).splitlines():
            line = self._clean(line)
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                key, val = parts
                n = idx.get(key, 0)
                idx[key] = n + 1
                box[key if n == 0 else f"{key} {n + 1}"] = val
        return box

    @staticmethod
    def _ip_to_int(ip: str) -> int:
        p = list(map(int, ip.split(".")))
        return (p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]

    def _cidr_to_network(self, cidr: str) -> tuple[str, int]:
        ip_str, prefix_str = cidr.split("/")
        prefix  = int(prefix_str)
        mask    = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        net_int = self._ip_to_int(ip_str) & mask
        return ".".join(str((net_int >> s) & 0xFF) for s in (24, 16, 8, 0)), prefix

    def _ping_sweep(self, network: str, host_count: int, t: int, net: str, prefix: int) -> dict[str, str]:
        net_int  = self._ip_to_int(net)
        ip_list  = " ".join(
            ".".join(str(((net_int + i) >> s) & 0xFF) for s in (24, 16, 8, 0))
            for i in range(1, host_count + 1)
        )
        cmd = (
            f"for ip in {ip_list}; do "
            f"(ping -c 1 -W {t} \"$ip\" 2>/dev/null | grep -q 'bytes from' && echo \"$ip\") & "
            f"done; wait"
        )
        with self.spinner(f"Ping sweeping {network} ({host_count} hosts)..."):
            raw = self._try_exec(cmd, timeout=t * 2 + 30)
        live: dict[str, str] = {}
        for line in raw.splitlines():
            ip = line.strip()
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                live[ip] = "ICMP reply"
        return live

    def _discover_hosts(self, ifaces: list[tuple[str, str]], subnet_override: str | None, t: int) -> None:
        cidrs = [("user-specified", subnet_override)] if subnet_override else ifaces
        for _, cidr in cidrs:
            net, prefix = self._cidr_to_network(cidr)
            network    = f"{net}/{prefix}"
            host_count = max(2 ** (32 - prefix) - 2, 1)
            self.status(f"Host discovery on {network} ({host_count} hosts)...")
            if host_count > 2048:
                self.warn(f"Large subnet ({host_count} hosts), skipping. Use -s to narrow.")
                continue
            hosts = self._ping_sweep(network, host_count, t, net, prefix)
            if hosts:
                self.box(f"Live hosts {network}  ({len(hosts)} up)", dict(sorted(hosts.items())))
            else:
                self.warn(f"No live hosts found on {network}.")

    def run(self) -> None:
        no_scan = getattr(self.args, "no_scan", False)
        subnet  = getattr(self.args, "subnet", None)
        t       = getattr(self.args, "timeout", 1)

        with self.spinner("Enumerating interfaces..."):
            iface_box, ifaces = self._section_interfaces()
        if iface_box:
            self.box("Interfaces", iface_box)

        for spinner_msg, box_title, fn in [
            ("Fetching routing table...",          "Routes",                 self._section_routes),
            ("Reading ARP neighbors...",           "ARP neighbors (cached)", self._section_neighbors),
            ("Listing listening ports...",         "Listening ports",        self._section_listening),
            ("Listing established connections...", "Established connections", self._section_connections),
            ("Reading DNS config...",              "DNS (/etc/resolv.conf)", self._section_dns),
        ]:
            with self.spinner(spinner_msg):
                data = fn()
            if data:
                self.box(box_title, data)

        if no_scan:
            self.status("Skipping live host discovery (--no-scan).")
        elif not ifaces and not subnet:
            self.warn("No interfaces detected, skipping host discovery.")
        else:
            self._discover_hosts(ifaces, subnet, t)