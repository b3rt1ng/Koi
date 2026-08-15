from __future__ import annotations

import socket
import threading
import time
from typing import Callable, Optional
import random

from koi.utils.config import TIMEOUTS
from koi.utils.constants import SOCKET_BUFFER_SIZE


def _try_bind_port(port: int) -> tuple[socket.socket, int] | None:
    """Try to bind to a specific port. Returns (socket, port) or None if port is in use."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("0.0.0.0", port))
        return (srv, port)
    except OSError:
        srv.close()
        return None


def bind_side_channel_port() -> tuple[socket.socket, int]:
    """
    Try to bind to a configured side-channel port.
    Falls back to port 0 (OS-assigned) if all configured ports fail.
    Returns (socket, port).
    """
    from koi.utils.config import SIDETCPS, DEFAULTS
    ports = SIDETCPS if SIDETCPS else DEFAULTS["sidetcps"]

    if not ports or not isinstance(ports, list):
        ports = DEFAULTS["sidetcps"]

    attempts = list(ports)
    random.shuffle(attempts)

    for port in attempts:
        result = _try_bind_port(port)
        if result:
            return result

    fallback = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    fallback.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    fallback.bind(("0.0.0.0", 0))
    return (fallback, fallback.getsockname()[1])


def get_local_ip(remote_addr: str) -> str:
    """Return the local IP that routes toward *remote_addr*."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((remote_addr, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def spawn_send_server(
    data: bytes,
    timeout: float = 30.0,
    on_progress: Optional[Callable[[int], None]] = None,
    expected_ip: Optional[str] = None,
) -> tuple[int, threading.Thread, list[str]]:
    """
    Open a one-shot TCP server that sends *data* to the first incoming connection.

    Returns ``(port, thread, errors)``.
    - *thread* is already started (daemon); join it to wait for completion.
    - *errors* is a list that will contain an error string if the transfer fails.
    - *on_progress*: optional ``callback(bytes_sent)`` called after each chunk.
    - *expected_ip*: when set, connections from any other peer are dropped, so a
      stray scan on this side-channel port cannot steal the payload.
    """
    srv, port = bind_side_channel_port()
    srv.listen(1)

    errors: list[str] = []

    def _run() -> None:
        deadline = time.monotonic() + timeout
        try:
            conn = None
            while conn is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("no matching connection before timeout")
                srv.settimeout(remaining)
                candidate, peer = srv.accept()
                if expected_ip is not None and peer[0] != expected_ip:
                    candidate.close()
                    continue
                conn = candidate
            conn.settimeout(timeout)
            sent = 0
            while sent < len(data):
                chunk = data[sent:sent + SOCKET_BUFFER_SIZE]
                conn.sendall(chunk)
                sent += len(chunk)
                if on_progress:
                    on_progress(sent)
            conn.close()
        except Exception as exc:
            errors.append(str(exc))
        finally:
            srv.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return port, t, errors


class TCPReceiveServer:
    """One-shot TCP server that collects bytes from the first incoming connection."""

    def __init__(self, timeout: float = TIMEOUTS["download"], on_progress=None):
        self._timeout     = timeout
        self._on_progress = on_progress
        self._sock        = None
        self._done        = threading.Event()
        self._data        = b""
        self._error       = None
        self.port: int    = 0

    def start(self) -> "TCPReceiveServer":
        self._sock, self.port = bind_side_channel_port()
        self._sock.listen(1)
        self._sock.settimeout(self._timeout)
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self) -> None:
        buf = b""
        try:
            conn, _ = self._sock.accept()
            conn.settimeout(self._timeout)
            try:
                while chunk := conn.recv(SOCKET_BUFFER_SIZE):
                    buf += chunk
                    if self._on_progress:
                        self._on_progress(len(buf))
            except socket.timeout:
                pass
            conn.close()
        except Exception as exc:
            self._error = str(exc)
        finally:
            self._data = buf
            self._close()
            self._done.set()

    def collect(self) -> bytes:
        """Block until all data is received. Raises RuntimeError or TimeoutError."""
        self._done.wait(timeout=self._timeout + 2)
        if self._error:
            raise RuntimeError(self._error)
        if not self._done.is_set():
            raise TimeoutError("TCP receive server timed out")
        return self._data

    def stop(self) -> None:
        self._close()

    def _close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self) -> "TCPReceiveServer":
        return self.start()

    def __exit__(self, *_) -> None:
        self.stop()
