from __future__ import annotations

import re
from koi.modules.blueprint import KoiModule

class NetworkEnumModule(KoiModule):
    name        = "network_enum"
    description = "Enumerate interfaces, routes, connections, open ports, and discover live hosts."
    category    = "Enumeration"
    platform    = "linux"
    usage       = "network_enum <id> [--no-scan] [-s CIDR] [-t N]"
    arguments   = [
        {
            "flags": ["--no-scan"],
            "action": "store_true",
            "default": False,
            "help": "Skip live host discovery (ping sweep).",
        },
        {
            "flags": ["-s", "--subnet"],
            "default": None,
            "metavar": "CIDR",
            "help": "Override target subnet for host discovery (e.g. 10.10.0.0/24).",
        },
        {
            "flags": ["-t", "--timeout"],
            "type": int,
            "default": 1,
            "metavar": "N",
            "help": "Ping timeout per host for discovery (default: 1s).",
        },
    ]

    # ── helpers ───────────────────────────────────────────────────────────────

    def _run(self, cmd: str, timeout: float = 15.0) -> str:
        try:
            return self._exec_clean(cmd, timeout=timeout)
        except Exception:
            return ""

    # ── section: interfaces ───────────────────────────────────────────────────

    def _section_interfaces(self) -> tuple[dict, list[tuple[str, str]]]:
        """Return (box_data, [(iface, ipv4_cidr), ...]) for non-loopback interfaces."""
        raw = self._run("ip -o addr show")
        grouped: dict[str, list[str]] = {}
        ipv4_ifaces: list[tuple[str, str]] = []

        for line in raw.splitlines():
            line = self._clean(line)
            m = re.search(r'\d+:\s+(\S+)\s+(inet6?)\s+(\S+)', line)
            if not m:
                continue
            iface, family, addr = m.group(1), m.group(2), m.group(3)
            if iface == "lo":
                continue
            grouped.setdefault(iface, []).append(addr)
            if family == "inet" and "/" in addr:
                ipv4_ifaces.append((iface, addr))

        box = {iface: "  ".join(addrs) for iface, addrs in grouped.items()}
        return box, ipv4_ifaces

    # ── section: routes ───────────────────────────────────────────────────────

    def _section_routes(self) -> dict:
        raw = self._run("ip route show")
        box: dict[str, str] = {}
        for line in raw.splitlines():
            line = self._clean(line)
            if not line:
                continue
            parts = line.split(None, 1)
            dest = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            box[dest] = rest
        return box

    # ── section: ARP neighbors (cached, instant) ──────────────────────────────

    def _section_neighbors(self) -> dict:
        raw = self._run("ip neigh show 2>/dev/null || arp -a 2>/dev/null")
        box: dict[str, str] = {}
        for line in raw.splitlines():
            line = self._clean(line)
            # ip neigh: 192.168.1.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
            m = re.match(
                r'(\d+\.\d+\.\d+\.\d+)\s+dev\s+(\S+)(?:\s+lladdr\s+([0-9a-fA-F:]{17}))?\s*(\S*)',
                line,
            )
            if m:
                ip, dev, mac, state = m.groups()
                if state in ("FAILED", ""):
                    continue
                entry = f"{mac}  [{state}]  dev={dev}" if mac else f"[{state}]  dev={dev}"
                box[ip] = entry
                continue
            # arp -a: ? (192.168.1.1) at aa:bb:cc:dd:ee:ff [ether] on eth0
            m = re.search(r'\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]{17}).*on\s+(\S+)', line)
            if m:
                ip, mac, dev = m.groups()
                box[ip] = f"{mac}  dev={dev}"
        return box

    # ── section: listening ports ──────────────────────────────────────────────

    def _section_listening(self) -> dict:
        raw = self._run("ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null")
        box: dict[str, str] = {}
        for line in raw.splitlines():
            line = self._clean(line)
            if not line or line.startswith(("State", "Proto", "Netid")):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            # ss -tlnp: State Recv-Q Send-Q Local ...
            if parts[0] in ("LISTEN", "tcp", "tcp6"):
                local = parts[3]
                proc_m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
                process = f"{proc_m.group(1)}  pid={proc_m.group(2)}" if proc_m else ""
                box[local] = process or "-"
            # netstat -tlnp: Proto Recv-Q Send-Q Local Foreign State PID/Program
            elif re.match(r'tcp6?', parts[0]) and len(parts) >= 7:
                local   = parts[3]
                process = parts[6]
                box[local] = process
        return box

    # ── section: established connections ─────────────────────────────────────

    def _section_connections(self) -> dict:
        raw = self._run(
            "ss -tnp state established 2>/dev/null || "
            "netstat -tnp 2>/dev/null | grep ESTABLISHED"
        )
        box: dict[str, str] = {}
        for line in raw.splitlines():
            line = self._clean(line)
            if not line or line.startswith(("Recv", "Proto")):
                continue
            parts = line.split()
            # ss: Recv-Q Send-Q Local Remote [users:...]
            if len(parts) >= 4 and re.match(r'[\d\[\]:]', parts[2]):
                local, remote = parts[2], parts[3]
                proc_m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
                process = f"{proc_m.group(1)} pid={proc_m.group(2)}" if proc_m else ""
                box[f"{local} → {remote}"] = process
            # netstat: Proto Recv-Q Send-Q Local Foreign State PID/Program
            elif re.match(r'tcp6?', parts[0]) and len(parts) >= 7:
                local, remote, process = parts[3], parts[4], parts[6]
                box[f"{local} → {remote}"] = process
        return box

    # ── section: DNS ──────────────────────────────────────────────────────────

    def _section_dns(self) -> dict:
        raw = self._run("cat /etc/resolv.conf 2>/dev/null")
        box: dict[str, str] = {}
        idx: dict[str, int] = {}
        for line in raw.splitlines():
            line = self._clean(line)
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                key, val = parts
                # Deduplicate repeated keys (e.g. multiple "nameserver" lines)
                n = idx.get(key, 0)
                idx[key] = n + 1
                box[key if n == 0 else f"{key} {n + 1}"] = val
        return box

    # ── host discovery (ARP scan) ─────────────────────────────────────────────

    @staticmethod
    def _cidr_to_network(cidr: str) -> tuple[str, int]:
        ip_str, prefix_str = cidr.split("/")
        prefix  = int(prefix_str)
        parts   = list(map(int, ip_str.split(".")))
        ip_int  = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]
        mask    = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        net_int = ip_int & mask
        net     = ".".join(str((net_int >> s) & 0xFF) for s in (24, 16, 8, 0))
        return net, prefix

    @staticmethod
    def _in_network(ip: str, net: str, prefix: int) -> bool:
        def to_int(s: str) -> int:
            p = list(map(int, s.split(".")))
            return (p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]
        mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        return (to_int(ip) & mask) == (to_int(net) & mask)

    def _parse_arp_table(self, raw: str, net: str, prefix: int) -> dict[str, str]:
        hosts: dict[str, str] = {}
        for line in raw.splitlines():
            line = self._clean(line)
            if not line:
                continue
            m = re.match(
                r'(\d+\.\d+\.\d+\.\d+)\s+dev\s+(\S+)\s+lladdr\s+([0-9a-fA-F:]{17})\s+(\S+)',
                line,
            )
            if m:
                ip, dev, mac, state = m.groups()
                if state not in ("FAILED", "INCOMPLETE") and self._in_network(ip, net, prefix):
                    hosts[ip] = f"{mac}  [{state}]  dev={dev}"
                continue
            m = re.search(r'\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]{17}).*on\s+(\S+)', line)
            if m:
                ip, mac, dev = m.groups()
                if self._in_network(ip, net, prefix):
                    hosts[ip] = f"{mac}  dev={dev}"
        return hosts

    def _try_arpscan(self, network: str) -> dict[str, str] | None:
        if not self._run("command -v arp-scan 2>/dev/null", timeout=5):
            return None
        raw = self._run(
            f"arp-scan --network={network} 2>/dev/null || arp-scan -l 2>/dev/null",
            timeout=60,
        )
        hosts: dict[str, str] = {}
        for line in raw.splitlines():
            line = self._clean(line)
            m = re.match(r'(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:]{17})\s*(.*)', line)
            if m:
                ip, mac, vendor = m.groups()
                hosts[ip] = f"{mac}  {vendor.strip()}" if vendor.strip() else mac
        return hosts if hosts else None

    def _try_nmap(self, network: str, host_count: int, t: int) -> dict[str, str] | None:
        if not self._run("command -v nmap 2>/dev/null", timeout=5):
            return None
        raw = self._run(f"nmap -sn {network} 2>/dev/null", timeout=host_count * t + 60)
        hosts: dict[str, str] = {}
        current_ip: str | None = None
        for line in raw.splitlines():
            line = self._clean(line)
            m_ip = re.search(r'Nmap scan report for (?:\S+ )?\(?([\d.]+)\)?', line)
            if m_ip:
                current_ip = m_ip.group(1)
            m_mac = re.search(r'MAC Address: ([0-9A-Fa-f:]{17})(?:\s+\(([^)]+)\))?', line)
            if m_mac and current_ip:
                mac, vendor = m_mac.group(1), m_mac.group(2) or ""
                hosts[current_ip] = f"{mac}  {vendor}".strip()
                current_ip = None
            elif current_ip and "Host is up" in line:
                hosts.setdefault(current_ip, "")
        return hosts if hosts else None

    def _ping_sweep(self, network: str, host_count: int, t: int,
                    net: str, prefix: int) -> dict[str, str]:
        with self.spinner(f"Pinging {host_count} hosts…"):
            self._run(
                f"python3 -c '"
                f"import ipaddress,subprocess;"
                f'net=ipaddress.ip_network("{network}",strict=False);'
                f"procs=[subprocess.Popen"
                f'(["ping","-c1","-W","{t}",str(h)],'
                f"stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
                f" for h in net.hosts()];"
                f"[p.wait() for p in procs]"
                f"' 2>/dev/null",
                timeout=host_count * t + 20,
            )
        arp_raw = self._run("ip neigh show 2>/dev/null; arp -a 2>/dev/null", timeout=10)
        return self._parse_arp_table(arp_raw, net, prefix)

    def _discover_hosts(self, ifaces: list[tuple[str, str]], subnet_override: str | None,
                        t: int) -> None:
        cidrs = (
            [("user-specified", subnet_override)]
            if subnet_override
            else [(iface, cidr) for iface, cidr in ifaces]
        )

        for iface_label, cidr in cidrs:
            net, prefix = self._cidr_to_network(cidr)
            network     = f"{net}/{prefix}"
            host_count  = max(2 ** (32 - prefix) - 2, 1)

            self.status(f"Host discovery on {network} ({host_count} hosts)…")

            if host_count > 2048:
                self.warn(f"Large subnet ({host_count} hosts) — skipping. Use -s to narrow.")
                continue

            hosts = (
                self._try_arpscan(network)
                or self._try_nmap(network, host_count, t)
                or self._ping_sweep(network, host_count, t, net, prefix)
            )

            if hosts:
                self.box(
                    f"Live hosts — {network}  ({len(hosts)} up)",
                    dict(sorted(hosts.items())),
                )
            else:
                self.warn(f"No live hosts found on {network}.")

    # ── entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        no_scan = getattr(self.args, "no_scan", False)
        subnet  = getattr(self.args, "subnet", None)
        t       = getattr(self.args, "timeout", 1)

        with self.spinner("Enumerating interfaces…"):
            iface_box, ifaces = self._section_interfaces()
        if iface_box:
            self.box("Interfaces", iface_box)

        with self.spinner("Fetching routing table…"):
            routes = self._section_routes()
        if routes:
            self.box("Routes", routes)

        with self.spinner("Reading ARP neighbors…"):
            neighbors = self._section_neighbors()
        if neighbors:
            self.box("ARP neighbors (cached)", neighbors)

        with self.spinner("Listing listening ports…"):
            listening = self._section_listening()
        if listening:
            self.box("Listening ports", listening)

        with self.spinner("Listing established connections…"):
            connections = self._section_connections()
        if connections:
            self.box("Established connections", connections)

        with self.spinner("Reading DNS config…"):
            dns = self._section_dns()
        if dns:
            self.box("DNS (/etc/resolv.conf)", dns)

        if no_scan:
            self.status("Skipping live host discovery (--no-scan).")
        elif not ifaces and not subnet:
            self.warn("No interfaces detected — skipping host discovery.")
        else:
            self._discover_hosts(ifaces, subnet, t)
