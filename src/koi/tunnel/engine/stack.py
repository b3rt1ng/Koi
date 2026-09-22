from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Callable

from . import packet as P
from .packet import ICMP, TCP, UDP, IPv4
from .tcp import TCB, State

log = logging.getLogger("tunel.stack")

HIGH_WATER = 256 * 1024
LOW_WATER = 64 * 1024
UDP_IDLE_TIMEOUT = 60.0
CONNECT_TIMEOUT = 10.0
TICK_INTERVAL = 0.1


class TcpBridge:

    def __init__(self, stack: "Stack", tcb: TCB, dst: str, dport: int):
        self.stack = stack
        self.tcb = tcb
        self.dst = dst
        self.dport = dport
        self.writer: asyncio.StreamWriter | None = None
        self.drained = asyncio.Event()
        self.drained.set()
        self._closed = False

        tcb.on_data = self._to_socket
        tcb.on_close = self._peer_finished
        tcb.on_reset = self.abort

    def _to_socket(self, data: bytes) -> None:
        if self.writer is None or self._closed:
            return
        try:
            self.writer.write(data)
        except (OSError, RuntimeError):
            self.abort()
            return
        transport = self.writer.transport
        if transport.get_write_buffer_size() > HIGH_WATER and not self.tcb.paused:
            self.tcb.pause()
            asyncio.ensure_future(self._resume_when_drained())

    async def _resume_when_drained(self) -> None:
        try:
            await self.writer.drain()
        except (OSError, RuntimeError):
            self.abort()
            return
        self.tcb.resume(time.monotonic())
        self.stack.flush()

    def _peer_finished(self) -> None:
        if self.writer is None or self._closed:
            return
        try:
            if self.writer.can_write_eof():
                self.writer.write_eof()
        except (OSError, RuntimeError):
            self.abort()

    async def run(self) -> None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.dst, self.dport), CONNECT_TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as exc:
            log.debug("connect %s:%d refused (%s)", self.dst, self.dport, exc)
            self.tcb.reset()
            self.stack.forget(self.tcb)
            return

        self.writer = writer
        self.tcb.send_syn_ack(time.monotonic())
        self.stack.flush()
        log.info("open %s:%d -> %s:%d", self.tcb.raddr, self.tcb.rport, self.dst, self.dport)

        try:
            while not self._closed:
                if len(self.tcb.send_buf) > HIGH_WATER:
                    self.drained.clear()
                    await self.drained.wait()
                data = await reader.read(65536)
                if not data:
                    break
                self.tcb.write(data, time.monotonic())
                self.stack.flush()
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            self._finish()

    def _finish(self) -> None:
        if self._closed:
            return
        self.tcb.close(time.monotonic())
        self.stack.flush()

    def maybe_resume_reading(self) -> None:
        if len(self.tcb.send_buf) <= LOW_WATER:
            self.drained.set()

    def abort(self) -> None:
        self._closed = True
        self.drained.set()
        if self.writer is not None:
            try:
                self.writer.close()
            except (OSError, RuntimeError):
                pass
            self.writer = None
        self.stack.forget(self.tcb)


class UdpBridge:

    def __init__(self, stack: "Stack", key: tuple, src: str, sport: int, dst: str, dport: int):
        self.stack = stack
        self.key = key
        self.src, self.sport = src, sport
        self.dst, self.dport = dst, dport
        self.sock: socket.socket | None = None
        self.last_seen = time.monotonic()
        self._task: asyncio.Task | None = None
        self._pending: list[bytes] = []
        self._ready = False

    async def start(self) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            await asyncio.get_running_loop().sock_connect(sock, (self.dst, self.dport))
        except OSError as exc:
            log.debug("udp %s:%d injoignable (%s)", self.dst, self.dport, exc)
            return False
        self.sock = sock
        self._ready = True
        self._task = asyncio.ensure_future(self._recv_loop())
        queued, self._pending = self._pending, []
        for payload in queued:
            self.send(payload)
        return True

    def send(self, payload: bytes) -> None:
        self.last_seen = time.monotonic()
        if not self._ready:
            if len(self._pending) < 16:
                self._pending.append(payload)
            return
        if self.sock is None:
            return
        try:
            self.sock.send(payload)
        except OSError:
            self.close()

    async def _recv_loop(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while self.sock is not None:
                data = await loop.sock_recv(self.sock, 65535)
                if not data:
                    break
                self.last_seen = time.monotonic()
                dg = UDP(sport=self.dport, dport=self.sport, payload=data)
                self.stack.emit_ip(self.dst, self.src, P.PROTO_UDP, dg.build(self.dst, self.src))
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            self.close()

    @property
    def idle(self) -> bool:
        return time.monotonic() - self.last_seen > UDP_IDLE_TIMEOUT

    def close(self) -> None:
        self._ready = False
        self._pending.clear()
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        self.stack.udp_flows.pop(self.key, None)


class Stack:

    def __init__(self, send_packet: Callable[[bytes], None], mtu: int = 1500):
        self.send_packet = send_packet
        self.mtu = mtu
        self.conns: dict[tuple, TcpBridge] = {}
        self.udp_flows: dict[tuple, UdpBridge] = {}
        self._ident = 0
        self._timer: asyncio.Task | None = None

    def emit_ip(self, src: str, dst: str, proto: int, payload: bytes) -> None:
        self._ident = (self._ident + 1) & 0xFFFF
        self.send_packet(IPv4(src=src, dst=dst, proto=proto, payload=payload, ident=self._ident).build())

    def _emitter(self, laddr: str, raddr: str):
        def emit(seg: TCP) -> None:
            self.emit_ip(laddr, raddr, P.PROTO_TCP, seg.build(laddr, raddr))
        return emit

    def flush(self) -> None:
        for bridge in list(self.conns.values()):
            bridge.maybe_resume_reading()

    def handle_packet(self, data: bytes) -> None:
        try:
            ip = IPv4.parse(data)
        except P.ParseError as exc:
            log.debug("packet dropped: %s", exc)
            return

        if ip.proto in (P.PROTO_TCP, P.PROTO_UDP) and not P.verify_transport_checksum(ip):
            log.debug("packet dropped: invalid transport checksum")
            return
        if ip.proto == P.PROTO_ICMP and not P.verify_checksum(ip.payload):
            log.debug("packet dropped: invalid ICMP checksum")
            return

        if ip.proto == P.PROTO_TCP:
            self._handle_tcp(ip)
        elif ip.proto == P.PROTO_UDP:
            self._handle_udp(ip)
        elif ip.proto == P.PROTO_ICMP:
            self._handle_icmp(ip)

    def _handle_tcp(self, ip: IPv4) -> None:
        try:
            seg = TCP.parse(ip.payload)
        except P.ParseError as exc:
            log.debug("TCP segment dropped: %s", exc)
            return

        key = (ip.src, seg.sport, ip.dst, seg.dport)
        bridge = self.conns.get(key)

        if bridge is not None:
            bridge.tcb.on_segment(seg, time.monotonic())
            self.flush()
            if bridge.tcb.closed:
                bridge.abort()
            return

        if seg.flags & P.SYN and not seg.flags & P.ACK:
            self._open(ip, seg, key)
        elif not seg.flags & P.RST:
            self._reject(ip, seg)

    def _open(self, ip: IPv4, seg: TCP, key: tuple) -> None:
        tcb = TCB.accept(
            seg, laddr=ip.dst, raddr=ip.src,
            emit=self._emitter(ip.dst, ip.src), mtu=self.mtu,
        )
        bridge = TcpBridge(self, tcb, dst=ip.dst, dport=seg.dport)
        self.conns[key] = bridge
        asyncio.ensure_future(bridge.run())

    def _reject(self, ip: IPv4, seg: TCP) -> None:
        if seg.flags & P.ACK:
            rst = TCP(sport=seg.dport, dport=seg.sport, seq=seg.ack, flags=P.RST)
        else:
            rst = TCP(
                sport=seg.dport, dport=seg.sport, seq=0,
                ack=(seg.seq + seg.seq_len) % (1 << 32), flags=P.RST | P.ACK,
            )
        self.emit_ip(ip.dst, ip.src, P.PROTO_TCP, rst.build(ip.dst, ip.src))

    def forget(self, tcb: TCB) -> None:
        self.conns.pop((tcb.raddr, tcb.rport, tcb.laddr, tcb.lport), None)

    def _handle_udp(self, ip: IPv4) -> None:
        try:
            dg = UDP.parse(ip.payload)
        except P.ParseError as exc:
            log.debug("UDP datagram dropped: %s", exc)
            return

        key = (ip.src, dg.sport, ip.dst, dg.dport)
        flow = self.udp_flows.get(key)
        if flow is not None:
            flow.send(dg.payload)
            return

        flow = UdpBridge(self, key, src=ip.src, sport=dg.sport, dst=ip.dst, dport=dg.dport)
        self.udp_flows[key] = flow
        flow.send(dg.payload)
        asyncio.ensure_future(self._start_udp(flow, key))

    async def _start_udp(self, flow: UdpBridge, key: tuple) -> None:
        if not await flow.start():
            self.udp_flows.pop(key, None)

    def _handle_icmp(self, ip: IPv4) -> None:
        try:
            msg = ICMP.parse(ip.payload)
        except P.ParseError:
            return
        if msg.type != P.ICMP_ECHO_REQUEST:
            return
        reply = ICMP(type=P.ICMP_ECHO_REPLY, code=0, rest=msg.rest, payload=msg.payload)
        self.emit_ip(ip.dst, ip.src, P.PROTO_ICMP, reply.build())

    def start_timer(self) -> None:
        if self._timer is None:
            self._timer = asyncio.ensure_future(self._tick_loop())

    async def _tick_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(TICK_INTERVAL)
                now = time.monotonic()
                for bridge in list(self.conns.values()):
                    bridge.tcb.tick(now)
                    if bridge.tcb.state is State.CLOSED:
                        bridge.abort()
                for flow in list(self.udp_flows.values()):
                    if flow.idle:
                        flow.close()
        except asyncio.CancelledError:
            pass

    def shutdown(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        for bridge in list(self.conns.values()):
            bridge.abort()
        for flow in list(self.udp_flows.values()):
            flow.close()

    @property
    def stats(self) -> dict:
        return {"tcp": len(self.conns), "udp": len(self.udp_flows)}
