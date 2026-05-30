from __future__ import annotations

import base64
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from koi.utils.ui import (
    RST, DIM, BOLD, PUMPKIN, WHITE, SILVER, CORAL,
    gradient_text, colored_text, notify,
)

if TYPE_CHECKING:
    from koi.session import Session

_LOG_DIR         = Path.home() / ".koi" / "logs"
_ANSI            = re.compile(r"\x1b(?:\][^\x07]*\x07|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])")
_CTRL            = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")
_PROMPT_SUFFIXES = ("$", "#", "❯", ">", "% ")


def log_dir() -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def _clean(raw: bytes, encoding: str) -> str:
    text = raw.decode(encoding, errors="replace")
    text = _ANSI.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _printable(text: str) -> bool:
    return any(c.isprintable() and c != " " for c in text)


def _is_prompt(line: str) -> bool:
    return any(line.strip().endswith(sfx) for sfx in _PROMPT_SUFFIXES)


def _dim_ts(entry: dict) -> str:
    ts = datetime.fromtimestamp(entry["ts"]).strftime("%H:%M:%S")
    return f"{DIM}{ts}{RST}"


class SessionLogger:
    def __init__(self, path: Path):
        self.path = path
        self._f   = open(path, "a", buffering=1)

    def _write(self, entry: dict) -> None:
        self._f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_meta(self, sess: "Session") -> None:
        self._write({
            "ts": time.time(), "type": "meta",
            "id": sess.id, "ip": sess.addr[0], "port": sess.addr[1],
            "os": sess.os_type, "upgraded": sess.upgraded,
        })

    def log_input(self, data: bytes) -> None:
        if data:
            self._write({"ts": time.time(), "type": "input",
                         "data": base64.b64encode(data).decode()})

    def log_output(self, data: bytes) -> None:
        if data:
            self._write({"ts": time.time(), "type": "output",
                         "data": base64.b64encode(data).decode()})

    def log_event(self, msg: str) -> None:
        self._write({"ts": time.time(), "type": "event", "msg": msg})

    def close(self) -> None:
        try:
            self._f.close()
        except OSError:
            pass


def start_logger(sess: "Session") -> SessionLogger:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    lg    = SessionLogger(log_dir() / f"{stamp}-{sess.id}-{sess.addr[0]}.log")
    lg.log_meta(sess)
    return lg


def list_logs() -> list[Path]:
    return sorted(log_dir().glob("*.log"), reverse=True)


def resolve_log(name: str) -> Path | None:
    p = Path(name)
    if p.exists():
        return p
    matches = sorted(log_dir().glob(f"*{p.name}*"), reverse=True)
    return matches[0] if matches else None


def clear_log(path: Path) -> None:
    try:
        path.unlink()
        notify("success", f"Log cleared: {path.name}")
    except OSError as exc:
        notify("error", f"Failed to clear log {path.name}: {exc}")


def print_log_list() -> None:
    logs = list_logs()
    if not logs:
        notify("status", f"No logs found in {log_dir()}")
        return
    print()
    for p in logs:
        size     = p.stat().st_size
        size_str = f"{size // 1024}K" if size >= 1024 else f"{size}B"
        print(f"  {colored_text(p.name, PUMPKIN)}  {colored_text(size_str, SILVER)}")
    print()


def _render_meta(entry: dict) -> None:
    sid     = entry["id"]
    sep     = colored_text("─" * 64, PUMPKIN)
    sess_id = BOLD + colored_text("Session #" + str(sid), WHITE) + RST
    target  = colored_text(entry["ip"] + ":" + str(entry["port"]), PUMPKIN)
    os_tag  = colored_text("[" + (entry.get("os") or "?") + "]", SILVER)
    print(sep + "\n  " + sess_id + "  " + target + "  " + os_tag + "\n" + sep + "\n")


def _render_cmd(ts_str: str, cmd: str) -> None:
    print(ts_str + "  " + colored_text("❯", PUMPKIN) + "  " + colored_text(cmd, WHITE))


def _render_output_line(ts_str: str, line: str) -> None:
    print(ts_str + "     " + colored_text(line, SILVER))


def _render_event(entry: dict) -> None:
    msg    = entry["msg"]
    ts_str = _dim_ts(entry)

    if msg.startswith("exec  "):
        cmd = msg[6:].strip()
        m   = re.match(r'\(\s*(.+?)\s*\)\s*>\s*/dev/tcp/\S+', cmd)
        _render_cmd(ts_str, m.group(1).strip() if m else cmd)

    elif msg.startswith("module_start  "):
        print("\n" + gradient_text("[+] module " + msg[14:].strip() + " started", PUMPKIN, WHITE))

    elif msg.startswith("module_end  "):
        print(gradient_text("[-] module " + msg[12:].strip() + " end", CORAL, SILVER) + "\n")

    elif msg == "upgrade_start":
        print("\n" + gradient_text("[+] Upgrading to interactive PTY", PUMPKIN, WHITE))

    elif msg == "upgrade_done":
        print(gradient_text("[✔] PTY upgrade done", CORAL, SILVER) + "\n")

    elif not msg.startswith("module_"):
        print("\n" + DIM + "/!\\  " + msg + "  /!\\" + RST + "\n")


def review(name: str) -> None:
    path = resolve_log(name)
    if path is None:
        notify("error", f"Log not found: {name}")
        sys.exit(1)

    encoding    = "utf-8"
    input_buf   = b""
    recent_cmds: set[str] = set()

    def flush_state() -> None:
        nonlocal input_buf
        input_buf = b""
        recent_cmds.clear()

    print()
    with open(path) as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            kind   = entry.get("type")
            ts_str = _dim_ts(entry)

            if kind == "meta":
                encoding = "utf-8" if entry.get("os") == "linux" else "cp1252"
                _render_meta(entry)

            elif kind == "input":
                input_buf += base64.b64decode(entry["data"])
                while b"\n" in input_buf or b"\r" in input_buf:
                    for sep in (b"\r\n", b"\n", b"\r"):
                        if sep in input_buf:
                            cmd_bytes, input_buf = input_buf.split(sep, 1)
                            break
                    cmd = _CTRL.sub("", _clean(cmd_bytes, encoding)).strip()
                    if cmd and _printable(cmd):
                        _render_cmd(ts_str, cmd)
                        recent_cmds.add(cmd.lower())

            elif kind == "output":
                text = _clean(base64.b64decode(entry["data"]), encoding)
                for line in text.splitlines():
                    stripped = _CTRL.sub("", line).strip()
                    if (not stripped or not _printable(stripped)
                            or stripped.lower() in recent_cmds
                            or _is_prompt(stripped)
                            or "__KOI_" in stripped):
                        continue
                    _render_output_line(ts_str, stripped)
                recent_cmds.clear()

            elif kind == "event":
                flush_state()
                _render_event(entry)

    print()