from __future__ import annotations

import http.server
import socket
import threading
from typing import Callable, Optional
import random


def _try_bind_port(port: int) -> tuple[socket.socket, int] | None:
    """Try to bind to a specific port. Returns (socket, port) or None if port is in use."""
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", port))
        return (srv, port)
    except OSError:
        return None


def _bind_side_channel_port() -> tuple[socket.socket, int]:
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
) -> tuple[int, threading.Thread, list[str]]:
    """
    Open a one-shot TCP server that sends *data* to the first incoming connection.

    Returns ``(port, thread, errors)``.
    - *thread* is already started (daemon); join it to wait for completion.
    - *errors* is a list that will contain an error string if the transfer fails.
    - *on_progress*: optional ``callback(bytes_sent)`` called after each chunk.
    """
    srv, port = _bind_side_channel_port()
    srv.listen(1)
    srv.settimeout(timeout)

    errors: list[str] = []

    def _run() -> None:
        try:
            conn, _ = srv.accept()
            sent = 0
            while sent < len(data):
                chunk = data[sent:sent + 65536]
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


def spawn_http_server(
    data: bytes,
    content_type: str = "text/plain; charset=utf-8",
    timeout: float = 60.0,
) -> tuple[int, threading.Thread]:
    """
    One-shot HTTP server that serves *data* to the first GET request then shuts down.
    Returns (port, thread).
    """
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    srv = http.server.HTTPServer(("0.0.0.0", 0), _Handler)
    srv.timeout = timeout
    port = srv.server_address[1]

    def _run():
        srv.handle_request()
        srv.server_close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return port, t


def spawn_recv_server(
    timeout: float = 60.0,
) -> tuple[int, Callable[[], bytes]]:
    """
    Open a one-shot TCP server that collects data from the first incoming connection.

    Returns ``(port, collect)``.
    Call ``collect()`` to block until the connection is received and all data is read;
    returns the raw bytes (empty on timeout or error).
    """
    srv, port = _bind_side_channel_port()
    srv.listen(1)
    srv.settimeout(timeout)

    def collect() -> bytes:
        try:
            conn, _ = srv.accept()
            chunks: list[bytes] = []
            while chunk := conn.recv(4096):
                chunks.append(chunk)
            conn.close()
            return b"".join(chunks)
        except Exception:
            return b""
        finally:
            srv.close()

    return port, collect
