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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._uid_cache: dict[int, str] | None = None

    def _load_uid_map(self) -> dict[int, str]:
        """Load /etc/passwd once to map UID -> username (expensive call, cached)."""
        if self._uid_cache is not None:
            return self._uid_cache

        self._uid_cache = {}
        raw = self._try_exec("cat /etc/passwd", timeout=TIMEOUTS["exec_query"])
        for line in raw.splitlines():
            parts = line.split(":")
            if len(parts) >= 3:
                try:
                    self._uid_cache[int(parts[2])] = parts[0]
                except ValueError:
                    pass
        return self._uid_cache

    def _uid_to_user(self, uid: int) -> str:
        """Map UID to username using cached /etc/passwd."""
        uid_map = self._load_uid_map()
        return uid_map.get(uid, str(uid))

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

    @staticmethod
    def _hex_port_to_decimal(hex_port: str) -> int:
        return int(hex_port, 16)

    @staticmethod
    def _hex_ipv4_to_dotted(hex_ip: str) -> str:
        bytes_list = bytes.fromhex(hex_ip)
        return ".".join(str(b) for b in reversed(bytes_list))

    @staticmethod
    def _hex_ipv6_to_colon(hex_ip: str) -> str:
        words = [hex_ip[i:i+4] for i in range(0, 32, 4)]
        addr = ":".join(words)
        try:
            import ipaddress
            return str(ipaddress.IPv6Address(addr))
        except (ValueError, ImportError):
            return addr

    def _parse_proc_net_line(self, line: str, is_ipv6: bool = False) -> tuple[str, str, int, str] | None:
        parts = line.split()
        if len(parts) < 12:
            return None
        try:
            local_addr_str = parts[1]
            rem_addr_str = parts[2]
            state = parts[3]
            uid = int(parts[7])

            if ":" not in local_addr_str:
                return None

            local_ip_hex, local_port_hex = local_addr_str.rsplit(":", 1)

            if not local_port_hex or not local_ip_hex:
                return None

            local_port = self._hex_port_to_decimal(local_port_hex)

            if is_ipv6:
                if len(local_ip_hex) != 32:
                    return None
                local_ip = self._hex_ipv6_to_colon(local_ip_hex)
            else:
                if len(local_ip_hex) != 8:
                    return None
                local_ip = self._hex_ipv4_to_dotted(local_ip_hex)

            return f"{local_ip}:{local_port}", state, uid, rem_addr_str
        except (ValueError, IndexError, OSError):
            return None

    def _read_proc_net(self, filename: str) -> list[tuple[str, str, int, str]]:
        entries = []
        try:
            raw = self._try_exec(f"cat /proc/net/{filename}", timeout=TIMEOUTS["exec_query"])
            if not raw:
                return []
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("sl"):
                    continue
                is_ipv6 = "6" in filename
                result = self._parse_proc_net_line(line, is_ipv6)
                if result:
                    addr, state, uid, rem_addr = result
                    entries.append((addr, state, uid, rem_addr))
        except Exception:
            return []
        return entries

    def _section_listening(self) -> dict:
        box: dict[str, str] = {}
        listen_state = "0A"

        for filename in ("tcp", "tcp6"):
            entries = self._read_proc_net(filename)
            for addr, state, uid, _ in entries:
                if state == listen_state:
                    user = self._uid_to_user(uid)
                    box[addr] = f"uid={uid}  user={user}"

        if box:
            return box

        ss_output = self._try_exec("ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null", timeout=TIMEOUTS["exec_query"])
        pids_to_fetch = set()
        lines_with_pids = []

        for line in ss_output.splitlines():
            line = self._clean(line)
            if not line or line.startswith(("State", "Proto", "Netid")):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            if parts[0] in ("LISTEN", "tcp", "tcp6"):
                proc_m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
                if proc_m:
                    pids_to_fetch.add(proc_m.group(2))
                    lines_with_pids.append((line, parts, proc_m.group(2), proc_m.group(1)))
            elif re.match(r'tcp6?', parts[0]) and len(parts) >= 7:
                # netstat-style: process name/pid already embedded in parts[6],
                # no _pid_info() lookup needed
                lines_with_pids.append((line, parts, None, None))

        pid_info = self._pid_info(list(pids_to_fetch)) if pids_to_fetch else {}

        for line, parts, pid, name in lines_with_pids:
            if parts[0] in ("LISTEN", "tcp", "tcp6"):
                addr = parts[3]
                if pid and pid in pid_info:
                    user, cmd = pid_info[pid]
                    box[addr] = f"{name or cmd}  pid={pid}  user={user}"
                elif pid and name:
                    box[addr] = f"{name}  pid={pid}".strip()
                elif name:
                    box[addr] = name
            elif re.match(r'tcp6?', parts[0]) and len(parts) >= 7:
                addr = parts[3]
                netstat_pid, _, proc_name = parts[6].partition("/")
                if proc_name:
                    box[addr] = f"{proc_name}  pid={netstat_pid}".strip() if netstat_pid else proc_name
                elif netstat_pid:
                    box[addr] = f"pid={netstat_pid}"

        return box

    def _section_connections(self) -> dict:
        box: dict[str, str] = {}
        established_state = "01"

        for filename in ("tcp", "tcp6"):
            entries = self._read_proc_net(filename)
            for addr, state, uid, rem_addr_str in entries:
                if state == established_state:
                    try:
                        if ":" in rem_addr_str:
                            rem_ip_hex, rem_port_hex = rem_addr_str.rsplit(":", 1)
                            rem_port = self._hex_port_to_decimal(rem_port_hex)
                            if "6" in filename:
                                rem_ip = self._hex_ipv6_to_colon(rem_ip_hex)
                            else:
                                rem_ip = self._hex_ipv4_to_dotted(rem_ip_hex)
                            user = self._uid_to_user(uid)
                            box[f"{addr} -> {rem_ip}:{rem_port}"] = f"uid={uid}  user={user}"
                    except (ValueError, IndexError):
                        pass

        if box:
            return box

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