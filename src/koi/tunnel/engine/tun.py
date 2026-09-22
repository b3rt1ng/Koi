from __future__ import annotations

import fcntl
import os
import struct
import subprocess

TUNSETIFF = 0x400454CA
IFF_TUN = 0x0001
IFF_TAP = 0x0002
IFF_NO_PI = 0x1000        # no 4-byte prefix before each packet
IFF_MULTI_QUEUE = 0x0100

CLONE_DEVICE = "/dev/net/tun"


class TunError(RuntimeError):
    pass


class Tun:

    def __init__(self, name: str = "tunel0", mtu: int = 1500, nonblocking: bool = True):
        self.requested_name = name
        self.mtu = mtu
        self.name = name
        self.fd = -1
        self._open(nonblocking)

    def _open(self, nonblocking: bool) -> None:
        if not os.path.exists(CLONE_DEVICE):
            raise TunError(
                f"{CLONE_DEVICE} missing - tun module not loaded? (modprobe tun)"
            )
        try:
            self.fd = os.open(CLONE_DEVICE, os.O_RDWR)
        except PermissionError as exc:
            raise TunError(
                f"access denied to {CLONE_DEVICE} - run as root, or pre-create "
                f"the interface: ip tuntap add dev {self.requested_name} mode tun user $USER"
            ) from exc

        ifreq = struct.pack("16sH", self.requested_name.encode(), IFF_TUN | IFF_NO_PI)
        try:
            res = fcntl.ioctl(self.fd, TUNSETIFF, ifreq)
        except OSError as exc:
            os.close(self.fd)
            self.fd = -1
            raise TunError(f"TUNSETIFF failed on {self.requested_name}: {exc}") from exc

        self.name = res[:16].rstrip(b"\x00").decode()
        if nonblocking:
            os.set_blocking(self.fd, False)

    def read(self) -> bytes:
        return os.read(self.fd, self.mtu + 80)

    def write(self, packet: bytes) -> int:
        return os.write(self.fd, packet)

    def fileno(self) -> int:
        return self.fd

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "Tun":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def configure(self, address: str, netmask: int = 24) -> None:
        self._ip("addr", "add", f"{address}/{netmask}", "dev", self.name)
        self._ip("link", "set", "dev", self.name, "mtu", str(self.mtu))
        self._ip("link", "set", "dev", self.name, "up")

    def add_route(self, cidr: str) -> None:
        self._ip("route", "add", cidr, "dev", self.name)

    @staticmethod
    def _ip(*args: str) -> None:
        cmd = ["ip", *args]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            err = proc.stderr.strip()
            if "File exists" in err or "RTNETLINK answers: File exists" in err:
                return   # already configured, harmless
            raise TunError(f"{' '.join(cmd)} → {err}")

    def __repr__(self) -> str:
        return f"Tun({self.name}, fd={self.fd}, mtu={self.mtu})"
