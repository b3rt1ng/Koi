from __future__ import annotations

import enum
import random
from dataclasses import dataclass, field
from typing import Callable

from .packet import ACK, FIN, PSH, RST, SYN, TCP, flags_str

MOD = 1 << 32
MAX_WINDOW = 65535
DEFAULT_MSS = 1460
# RFC 6298 recommends a 1s floor. We tunnel over already-reliable TCP:
# a spurious retransmit pays the same work twice.
MIN_RTO = 1.0
MAX_RTO = 30.0
MAX_RETRIES = 7
TIME_WAIT_DURATION = 10.0  # 2*MSL shortened: we are not a real host


def seq_diff(a: int, b: int) -> int:
    d = (a - b) & 0xFFFFFFFF
    return d - MOD if d >= (1 << 31) else d


def seq_lt(a: int, b: int) -> bool:
    return seq_diff(a, b) < 0


def seq_leq(a: int, b: int) -> bool:
    return seq_diff(a, b) <= 0


def seq_gt(a: int, b: int) -> bool:
    return seq_diff(a, b) > 0


def seq_geq(a: int, b: int) -> bool:
    return seq_diff(a, b) >= 0


class State(enum.Enum):
    SYN_RECEIVED = enum.auto()
    ESTABLISHED = enum.auto()
    FIN_WAIT_1 = enum.auto()
    FIN_WAIT_2 = enum.auto()
    CLOSING = enum.auto()
    TIME_WAIT = enum.auto()
    CLOSE_WAIT = enum.auto()
    LAST_ACK = enum.auto()
    CLOSED = enum.auto()


@dataclass
class Unacked:
    seq: int
    flags: int
    payload: bytes
    sent_at: float
    retries: int = 0

    @property
    def seq_len(self) -> int:
        extra = (1 if self.flags & SYN else 0) + (1 if self.flags & FIN else 0)
        return len(self.payload) + extra


@dataclass
class TCB:

    laddr: str          # address we impersonate (destination the client dialed)
    lport: int
    raddr: str          # the tunneled client
    rport: int
    emit: Callable[[TCP], None]

    on_data: Callable[[bytes], None] = lambda _: None
    on_close: Callable[[], None] = lambda: None       # peer finished sending (FIN)
    on_reset: Callable[[], None] = lambda: None       # abort

    mss: int = DEFAULT_MSS
    state: State = State.SYN_RECEIVED

    iss: int = field(default_factory=lambda: random.randint(0, MOD - 1))
    snd_una: int = 0
    snd_nxt: int = 0
    snd_wnd: int = MAX_WINDOW

    irs: int = 0
    rcv_nxt: int = 0
    rcv_wnd: int = MAX_WINDOW

    send_buf: bytearray = field(default_factory=bytearray)
    unacked: list[Unacked] = field(default_factory=list)
    ooo: dict[int, bytes] = field(default_factory=dict)   # out-of-order reassembly

    rto: float = 1.0
    srtt: float | None = None
    rttvar: float = 0.0
    close_pending: bool = False
    fin_seq: int | None = None
    paused: bool = False
    time_wait_expires: float | None = None
    peer_mss: int = DEFAULT_MSS

    @classmethod
    def accept(cls, syn: TCP, laddr: str, raddr: str, emit, mtu: int = 1500, **kw) -> "TCB":
        our_mss = mtu - 40
        tcb = cls(
            laddr=laddr, lport=syn.dport, raddr=raddr, rport=syn.sport,
            emit=emit, mss=our_mss, **kw,
        )
        tcb.irs = syn.seq
        tcb.rcv_nxt = (syn.seq + 1) % MOD
        tcb.snd_una = tcb.iss
        tcb.snd_nxt = tcb.iss
        tcb.snd_wnd = syn.window
        tcb.peer_mss = syn.mss or DEFAULT_MSS
        # never emit more than the peer accepts
        tcb.mss = max(536, min(our_mss, tcb.peer_mss))
        return tcb

    def send_syn_ack(self, now: float) -> None:
        seg = self._segment(SYN | ACK, b"", seq=self.iss)
        seg.mss = self.mss
        self._transmit(seg, now, track=True)
        self.snd_nxt = (self.iss + 1) % MOD

    def reset(self, now: float = 0.0) -> None:
        if self.state is State.CLOSED:
            return
        seg = self._segment(RST | ACK, b"", seq=self.snd_nxt)
        self.emit(seg)
        self.state = State.CLOSED
        self._clear()

    def write(self, data: bytes, now: float) -> None:
        if self.state in (State.CLOSED, State.LAST_ACK, State.FIN_WAIT_1, State.FIN_WAIT_2):
            return
        self.send_buf += data
        self._flush(now)

    def close(self, now: float) -> None:
        if self.state in (State.CLOSED, State.LAST_ACK, State.FIN_WAIT_1, State.TIME_WAIT):
            return
        self.close_pending = True
        self._flush(now)

    def pause(self) -> None:
        self.paused = True

    def resume(self, now: float) -> None:
        if not self.paused:
            return
        self.paused = False
        self._send_ack()  # window reopened

    def _window(self) -> int:
        return 0 if self.paused else self.rcv_wnd

    def _segment(self, flags: int, payload: bytes, seq: int) -> TCP:
        return TCP(
            sport=self.lport,
            dport=self.rport,
            seq=seq % MOD,
            ack=self.rcv_nxt,
            flags=flags,
            window=self._window(),
            payload=payload,
        )

    def _transmit(self, seg: TCP, now: float, track: bool) -> None:
        self.emit(seg)
        if track and seg.seq_len:
            self.unacked.append(
                Unacked(seq=seg.seq, flags=seg.flags, payload=seg.payload, sent_at=now)
            )

    def _send_ack(self) -> None:
        self.emit(self._segment(ACK, b"", seq=self.snd_nxt))

    def _flush(self, now: float) -> None:
        if self.state not in (State.ESTABLISHED, State.CLOSE_WAIT):
            return

        while self.send_buf:
            in_flight = seq_diff(self.snd_nxt, self.snd_una)
            usable = self.snd_wnd - in_flight
            if usable <= 0:
                break
            n = min(len(self.send_buf), self.mss, usable)
            chunk = bytes(self.send_buf[:n])
            del self.send_buf[:n]
            seg = self._segment(PSH | ACK, chunk, seq=self.snd_nxt)
            self._transmit(seg, now, track=True)
            self.snd_nxt = (self.snd_nxt + n) % MOD

        if self.close_pending and not self.send_buf and self.fin_seq is None:
            self._send_fin(now)

    def _send_fin(self, now: float) -> None:
        self.fin_seq = self.snd_nxt
        seg = self._segment(FIN | ACK, b"", seq=self.snd_nxt)
        self._transmit(seg, now, track=True)
        self.snd_nxt = (self.snd_nxt + 1) % MOD
        if self.state is State.ESTABLISHED:
            self.state = State.FIN_WAIT_1
        elif self.state is State.CLOSE_WAIT:
            self.state = State.LAST_ACK

    def on_segment(self, seg: TCP, now: float) -> None:
        if self.state is State.CLOSED:
            return

        if seg.flags & RST:
            self._abort()
            return

        # SYN re-sent while we still wait: replay the SYN-ACK
        if seg.flags & SYN and self.state is State.SYN_RECEIVED:
            for u in self.unacked:
                if u.flags & SYN:
                    self._retransmit(u, now)
            return

        if not self._acceptable(seg):
            # out of window: remind the peer where we are (RFC 793 p.69)
            self._send_ack()
            return

        if seg.flags & ACK:
            self._process_ack(seg, now)

        if self.state is State.SYN_RECEIVED:
            return  # the 3-way ACK has not been validated yet

        if seg.payload:
            self._process_data(seg)

        if seg.flags & FIN and seq_leq(seg.seq, self.rcv_nxt):
            self._process_fin(seg, now)

        self.snd_wnd = seg.window
        self._flush(now)

    def _acceptable(self, seg: TCP) -> bool:
        wnd = self.rcv_wnd or 1
        end = self.rcv_nxt + wnd
        if seg.seq_len == 0:
            return seq_geq(seg.seq, self.rcv_nxt) and seq_lt(seg.seq, end)
        last = seg.seq + seg.seq_len - 1
        return (seq_geq(seg.seq, self.rcv_nxt) and seq_lt(seg.seq, end)) or (
            seq_geq(last, self.rcv_nxt) and seq_lt(last, end)
        )

    def _process_ack(self, seg: TCP, now: float) -> None:
        if seq_gt(seg.ack, self.snd_nxt):
            return  # acks the future: ignore
        if seq_lt(seg.ack, self.snd_una):
            return  # doublon

        newly_acked = seq_diff(seg.ack, self.snd_una)
        if newly_acked > 0:
            self.snd_una = seg.ack
            self._retire_acked(seg.ack, now)

        if self.state is State.SYN_RECEIVED and seq_gt(seg.ack, self.iss):
            self.state = State.ESTABLISHED

        elif self.state is State.FIN_WAIT_1 and self._fin_acked():
            self.state = State.FIN_WAIT_2
        elif self.state is State.CLOSING and self._fin_acked():
            self._enter_time_wait(now)
        elif self.state is State.LAST_ACK and self._fin_acked():
            self.state = State.CLOSED
            self._clear()

    def _fin_acked(self) -> bool:
        return self.fin_seq is not None and seq_gt(self.snd_una, self.fin_seq)

    def _retire_acked(self, ack: int, now: float) -> None:
        kept = []
        for u in self.unacked:
            if seq_geq(ack, u.seq + u.seq_len):   # seq_geq already handles the modulo
                if u.retries == 0:
                    self._update_rto(now - u.sent_at)   # Karn: only without retransmission
            else:
                kept.append(u)
        self.unacked = kept

    def _update_rto(self, measured: float) -> None:
        if self.srtt is None:
            self.srtt = measured
            self.rttvar = measured / 2
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - measured)
            self.srtt = 0.875 * self.srtt + 0.125 * measured
        self.rto = min(MAX_RTO, max(MIN_RTO, self.srtt + 4 * self.rttvar))

    def _process_data(self, seg: TCP) -> None:
        if seq_lt(seg.seq, self.rcv_nxt):
            # partial overlap: keep only the new part
            drop = seq_diff(self.rcv_nxt, seg.seq)
            if drop >= len(seg.payload):
                self._send_ack()
                return
            data, base = seg.payload[drop:], self.rcv_nxt
        else:
            data, base = seg.payload, seg.seq

        if base != self.rcv_nxt:
            if len(self.ooo) < 64:            # bound the out-of-order buffer
                self.ooo[base] = data
            self._send_ack()
            return

        self.on_data(data)
        self.rcv_nxt = (self.rcv_nxt + len(data)) % MOD
        self._drain_ooo()
        self._send_ack()

    def _drain_ooo(self) -> None:
        while self.rcv_nxt in self.ooo:
            chunk = self.ooo.pop(self.rcv_nxt)
            self.on_data(chunk)
            self.rcv_nxt = (self.rcv_nxt + len(chunk)) % MOD

    def _process_fin(self, seg: TCP, now: float) -> None:
        fin_seq = (seg.seq + len(seg.payload)) % MOD
        if fin_seq != self.rcv_nxt:
            return  # out-of-order FIN: wait for the missing data
        self.rcv_nxt = (self.rcv_nxt + 1) % MOD
        self._send_ack()
        self.on_close()

        if self.state is State.ESTABLISHED:
            self.state = State.CLOSE_WAIT
        elif self.state is State.FIN_WAIT_1:
            self.state = State.CLOSING if not self._fin_acked() else State.TIME_WAIT
            if self.state is State.TIME_WAIT:
                self._enter_time_wait(now)
        elif self.state is State.FIN_WAIT_2:
            self._enter_time_wait(now)

    def _enter_time_wait(self, now: float) -> None:
        self.state = State.TIME_WAIT
        self.time_wait_expires = now + TIME_WAIT_DURATION
        self.unacked.clear()

    def tick(self, now: float) -> None:
        if self.state is State.TIME_WAIT:
            if self.time_wait_expires is not None and now >= self.time_wait_expires:
                self.state = State.CLOSED
                self._clear()
            return

        if self.state is State.CLOSED or not self.unacked:
            return

        oldest = self.unacked[0]
        if now - oldest.sent_at < self.rto * (2 ** oldest.retries):
            return

        if oldest.retries >= MAX_RETRIES:
            self._abort()
            return
        self._retransmit(oldest, now)

    def _retransmit(self, u: Unacked, now: float) -> None:
        u.retries += 1
        u.sent_at = now
        seg = TCP(
            sport=self.lport, dport=self.rport,
            seq=u.seq, ack=self.rcv_nxt, flags=u.flags,
            window=self._window(), payload=u.payload,
        )
        if u.flags & SYN:
            seg.mss = self.mss
        self.emit(seg)

    def _abort(self) -> None:
        self.state = State.CLOSED
        self._clear()
        self.on_reset()

    def _clear(self) -> None:
        self.send_buf.clear()
        self.unacked.clear()
        self.ooo.clear()

    @property
    def closed(self) -> bool:
        return self.state is State.CLOSED

    @property
    def key(self) -> tuple:
        return (self.raddr, self.rport, self.laddr, self.lport)

    def __repr__(self) -> str:
        return (
            f"TCB({self.raddr}:{self.rport} -> {self.laddr}:{self.lport} "
            f"{self.state.name} una={self.snd_una} nxt={self.snd_nxt} rcv={self.rcv_nxt})"
        )
