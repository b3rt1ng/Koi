from __future__ import annotations

import asyncio
import hashlib
import ssl
import struct

MAX_FRAME = 65535
IDENTITY = b"tunel"

# Beyond this, drop outgoing packets rather than growing memory.
# This is what a saturated link does: TCP will retransmit.
TX_BUFFER_LIMIT = 4 * 1024 * 1024


def _derive(psk: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", psk.encode(), b"tunel-psk-v1", 200_000, dklen=32)


def server_context(psk: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    key = _derive(psk)
    ctx.set_psk_server_callback(lambda identity: key, IDENTITY.decode())
    return ctx


def client_context(psk: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE      # authentication comes from the PSK
    key = _derive(psk)
    ctx.set_psk_client_callback(lambda hint: (IDENTITY.decode(), key))
    return ctx


def encode(packet: bytes) -> bytes:
    if len(packet) > MAX_FRAME:
        raise ValueError(f"packet too large: {len(packet)}")
    return struct.pack("!H", len(packet)) + packet


class Channel:

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self._lock = asyncio.Lock()
        self.rx_packets = 0
        self.tx_packets = 0
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.dropped = 0

    async def recv(self) -> bytes:
        header = await self.reader.readexactly(2)
        (length,) = struct.unpack("!H", header)
        packet = await self.reader.readexactly(length)
        self.rx_packets += 1
        self.rx_bytes += length
        return packet

    def send(self, packet: bytes) -> None:
        if len(packet) > MAX_FRAME:
            self.dropped += 1
            return
        transport = self.writer.transport
        if transport is not None and transport.get_write_buffer_size() > TX_BUFFER_LIMIT:
            self.dropped += 1
            return
        self.writer.write(encode(packet))
        self.tx_packets += 1
        self.tx_bytes += len(packet)

    async def drain(self) -> None:
        await self.writer.drain()

    async def close(self) -> None:
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except (OSError, ssl.SSLError):
            pass

    @property
    def peer(self) -> str:
        try:
            host, port, *_ = self.writer.get_extra_info("peername")
            return f"{host}:{port}"
        except (TypeError, ValueError):
            return "?"
