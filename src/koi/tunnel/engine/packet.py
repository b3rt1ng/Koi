from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field

PROTO_ICMP = 1
PROTO_TCP = 6
PROTO_UDP = 17

FIN = 0x01
SYN = 0x02
RST = 0x04
PSH = 0x08
ACK = 0x10
URG = 0x20

FLAG_NAMES = [(FIN, "FIN"), (SYN, "SYN"), (RST, "RST"), (PSH, "PSH"), (ACK, "ACK"), (URG, "URG")]


def flags_str(flags: int) -> str:
    names = [name for bit, name in FLAG_NAMES if flags & bit]
    return "|".join(names) if names else "-"


def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def _pseudo_header(src: str, dst: str, proto: int, length: int) -> bytes:
    return struct.pack(
        "!4s4sBBH",
        socket.inet_aton(src),
        socket.inet_aton(dst),
        0,
        proto,
        length,
    )


class ParseError(ValueError):
    pass


@dataclass
class IPv4:
    src: str
    dst: str
    proto: int
    payload: bytes
    ttl: int = 64
    ident: int = 0
    dont_fragment: bool = True

    HEADER_LEN = 20

    @classmethod
    def parse(cls, data: bytes) -> "IPv4":
        if len(data) < cls.HEADER_LEN:
            raise ParseError(f"IPv4 truncated: {len(data)} bytes")
        ver_ihl, _tos, total_len, ident, flags_frag, ttl, proto, _csum, src, dst = struct.unpack(
            "!BBHHHBBH4s4s", data[:20]
        )
        if ver_ihl >> 4 != 4:
            raise ParseError(f"not IPv4 (version={ver_ihl >> 4})")
        ihl = (ver_ihl & 0x0F) * 4
        if ihl < cls.HEADER_LEN or len(data) < ihl:
            raise ParseError(f"invalid IHL: {ihl}")
        if total_len < ihl:
            raise ParseError(f"invalid IPv4 length: {total_len} < IHL {ihl}")
        if total_len > len(data):
            raise ParseError(f"IPv4 truncated: announced {total_len} bytes, got {len(data)}")
        if not verify_checksum(data[:ihl]):
            raise ParseError("invalid IPv4 checksum")
        # The stack does not reassemble fragments; treating them as whole
        # TCP/UDP segments would silently corrupt the stream.
        if flags_frag & 0x3FFF:  # MF set or non-zero fragment offset
            raise ParseError("IPv4 fragment not supported")
        return cls(
            src=socket.inet_ntoa(src),
            dst=socket.inet_ntoa(dst),
            proto=proto,
            payload=data[ihl:total_len],
            ttl=ttl,
            ident=ident,
            dont_fragment=bool(flags_frag & 0x4000),
        )

    def build(self) -> bytes:
        total_len = self.HEADER_LEN + len(self.payload)
        flags_frag = 0x4000 if self.dont_fragment else 0
        header = struct.pack(
            "!BBHHHBBH4s4s",
            (4 << 4) | 5,
            0,
            total_len,
            self.ident,
            flags_frag,
            self.ttl,
            self.proto,
            0,
            socket.inet_aton(self.src),
            socket.inet_aton(self.dst),
        )
        csum = checksum(header)
        return header[:10] + struct.pack("!H", csum) + header[12:] + self.payload

    @property
    def is_fragment(self) -> bool:
        return False  # fragments are rejected by parse()


@dataclass
class TCP:
    sport: int
    dport: int
    seq: int = 0
    ack: int = 0
    flags: int = 0
    window: int = 65535
    payload: bytes = b""
    mss: int | None = None
    window_scale: int | None = None
    sack_permitted: bool = False

    HEADER_LEN = 20

    @classmethod
    def parse(cls, data: bytes) -> "TCP":
        if len(data) < cls.HEADER_LEN:
            raise ParseError(f"TCP truncated: {len(data)} bytes")
        sport, dport, seq, ack, off_res, flags, window, _csum, _urg = struct.unpack(
            "!HHIIBBHHH", data[:20]
        )
        offset = (off_res >> 4) * 4
        if offset < cls.HEADER_LEN or len(data) < offset:
            raise ParseError(f"invalid data offset: {offset}")
        seg = cls(
            sport=sport,
            dport=dport,
            seq=seq,
            ack=ack,
            flags=flags,
            window=window,
            payload=data[offset:],
        )
        seg._parse_options(data[cls.HEADER_LEN:offset])
        return seg

    def _parse_options(self, opts: bytes) -> None:
        i = 0
        while i < len(opts):
            kind = opts[i]
            if kind == 0:  # EOL
                break
            if kind == 1:  # NOP
                i += 1
                continue
            if i + 1 >= len(opts):
                break
            length = opts[i + 1]
            if length < 2 or i + length > len(opts):
                break
            body = opts[i + 2:i + length]
            if kind == 2 and length == 4:
                self.mss = struct.unpack("!H", body)[0]
            elif kind == 3 and length == 3:
                self.window_scale = body[0]
            elif kind == 4 and length == 2:
                self.sack_permitted = True
            i += length

    def _build_options(self) -> bytes:
        opts = b""
        if self.mss is not None:
            opts += struct.pack("!BBH", 2, 4, self.mss)
        if self.window_scale is not None:
            opts += struct.pack("!BBB", 3, 3, self.window_scale)
        if self.sack_permitted:
            opts += struct.pack("!BB", 4, 2)
        if len(opts) % 4:
            opts += b"\x00" * (4 - len(opts) % 4)  # EOL padding
        return opts

    def build(self, src: str, dst: str) -> bytes:
        opts = self._build_options()
        offset = (self.HEADER_LEN + len(opts)) // 4
        header = struct.pack(
            "!HHIIBBHHH",
            self.sport,
            self.dport,
            self.seq & 0xFFFFFFFF,
            self.ack & 0xFFFFFFFF,
            offset << 4,
            self.flags,
            self.window,
            0,
            0,
        )
        segment = header + opts + self.payload
        csum = checksum(_pseudo_header(src, dst, PROTO_TCP, len(segment)) + segment)
        return segment[:16] + struct.pack("!H", csum) + segment[18:]

    @property
    def seq_len(self) -> int:
        extra = (1 if self.flags & SYN else 0) + (1 if self.flags & FIN else 0)
        return len(self.payload) + extra

    def __repr__(self) -> str:
        return (
            f"TCP({self.sport}->{self.dport} {flags_str(self.flags)} "
            f"seq={self.seq} ack={self.ack} win={self.window} len={len(self.payload)})"
        )


@dataclass
class UDP:
    sport: int
    dport: int
    payload: bytes = b""

    HEADER_LEN = 8

    @classmethod
    def parse(cls, data: bytes) -> "UDP":
        if len(data) < cls.HEADER_LEN:
            raise ParseError(f"UDP truncated: {len(data)} bytes")
        sport, dport, length, _csum = struct.unpack("!HHHH", data[:8])
        end = min(length, len(data)) if length >= cls.HEADER_LEN else len(data)
        return cls(sport=sport, dport=dport, payload=data[8:end])

    def build(self, src: str, dst: str) -> bytes:
        length = self.HEADER_LEN + len(self.payload)
        header = struct.pack("!HHHH", self.sport, self.dport, length, 0)
        datagram = header + self.payload
        csum = checksum(_pseudo_header(src, dst, PROTO_UDP, length) + datagram)
        if csum == 0:
            csum = 0xFFFF  # 0 means "no checksum" in UDP
        return datagram[:6] + struct.pack("!H", csum) + datagram[8:]


ICMP_ECHO_REPLY = 0
ICMP_ECHO_REQUEST = 8
ICMP_DEST_UNREACH = 3
ICMP_TIME_EXCEEDED = 11

UNREACH_HOST = 1
UNREACH_PORT = 3


@dataclass
class ICMP:
    type: int
    code: int = 0
    rest: bytes = field(default=b"\x00\x00\x00\x00")
    payload: bytes = b""

    HEADER_LEN = 8

    @classmethod
    def parse(cls, data: bytes) -> "ICMP":
        if len(data) < cls.HEADER_LEN:
            raise ParseError(f"ICMP truncated: {len(data)} bytes")
        typ, code, _csum = struct.unpack("!BBH", data[:4])
        return cls(type=typ, code=code, rest=data[4:8], payload=data[8:])

    def build(self) -> bytes:
        header = struct.pack("!BBH", self.type, self.code, 0) + self.rest
        message = header + self.payload
        csum = checksum(message)
        return message[:2] + struct.pack("!H", csum) + message[4:]


def ip_wrap(src: str, dst: str, proto: int, payload: bytes, ident: int = 0) -> bytes:
    return IPv4(src=src, dst=dst, proto=proto, payload=payload, ident=ident).build()


def verify_checksum(data: bytes) -> bool:
    return checksum(data) == 0


def verify_transport_checksum(ip: IPv4) -> bool:
    if ip.proto == PROTO_UDP and struct.unpack("!H", ip.payload[6:8])[0] == 0:
        return True
    pseudo = _pseudo_header(ip.src, ip.dst, ip.proto, len(ip.payload))
    return checksum(pseudo + ip.payload) == 0
