from __future__ import annotations

import base64
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from koi.session import Session

_LOG_DIR = Path.home() / ".koi" / "logs"

_ANSI = re.compile(r"\x1b(?:\][^\x07]*\x07|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])")


def log_dir() -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


class SessionLogger:
    def __init__(self, path: Path):
        self.path = path
        self._f = open(path, "a", buffering=1)

    def _write(self, entry: dict) -> None:
        self._f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_meta(self, sess: "Session") -> None:
        self._write({
            "ts":       time.time(),
            "type":     "meta",
            "id":       sess.id,
            "ip":       sess.addr[0],
            "port":     sess.addr[1],
            "os":       sess.os_type,
            "upgraded": sess.upgraded,
        })

    def log_input(self, data: bytes) -> None:
        if data:
            self._write({
                "ts":   time.time(),
                "type": "input",
                "data": base64.b64encode(data).decode(),
            })

    def log_output(self, data: bytes) -> None:
        if data:
            self._write({
                "ts":   time.time(),
                "type": "output",
                "data": base64.b64encode(data).decode(),
            })

    def log_event(self, msg: str) -> None:
        self._write({"ts": time.time(), "type": "event", "msg": msg})

    def close(self) -> None:
        try:
            self._f.close()
        except OSError:
            pass


def start_logger(sess: "Session") -> SessionLogger:
    d = log_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{sess.id}-{sess.addr[0]}.log"
    logger = SessionLogger(d / name)
    logger.log_meta(sess)
    return logger


_RST    = "\033[0m"
_DIM    = "\033[2m"
_BOLD   = "\033[1m"
_ORANGE = "\033[38;2;248;101;70m"
_WHITE  = "\033[38;2;255;255;255m"
_GREY   = "\033[38;2;169;169;169m"
_CORAL  = "\033[38;2;235;111;92m"


def _clean(raw: bytes, encoding: str) -> str:
    text = raw.decode(encoding, errors="replace")
    text = _ANSI.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _printable(text: str) -> bool:
    return any(c.isprintable() and c != " " for c in text)


def list_logs() -> list[Path]:
    d = log_dir()
    return sorted(d.glob("*.log"), reverse=True)


def resolve_log(name: str) -> Path | None:
    p = Path(name)
    if p.exists():
        return p
    matches = sorted(log_dir().glob(f"*{p.name}*"), reverse=True)
    return matches[0] if matches else None

def clear_log(path: Path) -> None:
    try:
        path.unlink()
        print(f"{_CORAL}Log cleared: {path.name}{_RST}")
    except OSError as exc:
        print(f"{_CORAL}Failed to clear log {path.name}: {exc}{_RST}", file=sys.stderr)


_PROMPT_SUFFIXES = ("$", "#", "❯", ">", "% ")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")


def _is_prompt(line: str) -> bool:
    s = line.strip()
    return any(s.endswith(sfx) for sfx in _PROMPT_SUFFIXES)


def review(name: str) -> None:
    path = resolve_log(name)
    if path is None:
        print(f"Log not found: {name}", file=sys.stderr)
        sys.exit(1)

    encoding = "utf-8"
    input_buf = b""
    recent_cmds: set[str] = set()

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

            ts   = datetime.fromtimestamp(entry["ts"]).strftime("%H:%M:%S")
            kind = entry.get("type")

            if kind == "meta":
                encoding = "utf-8" if entry.get("os") == "linux" else "cp1252"
                os_label = entry.get("os") or "?"
                print(f"{_ORANGE}{'─' * 64}{_RST}")
                print(
                    f"  {_BOLD}{_WHITE}Session #{entry['id']}{_RST}"
                    f"  {_ORANGE}{entry['ip']}:{entry['port']}{_RST}"
                    f"  {_GREY}[{os_label}]{_RST}"
                )
                print(f"{_ORANGE}{'─' * 64}{_RST}\n")

            elif kind == "input":
                input_buf += base64.b64decode(entry["data"])
                while b"\n" in input_buf or b"\r" in input_buf:
                    for sep in (b"\r\n", b"\n", b"\r"):
                        if sep in input_buf:
                            cmd_bytes, input_buf = input_buf.split(sep, 1)
                            break
                    cmd = _CTRL.sub("", _clean(cmd_bytes, encoding)).strip()
                    if cmd and _printable(cmd):
                        print(f"  {_DIM}{ts}{_RST}  {_ORANGE}❯{_RST}  {_WHITE}{cmd}{_RST}")
                        recent_cmds.add(cmd.lower())

            elif kind == "output":
                text = _clean(base64.b64decode(entry["data"]), encoding)
                for line in text.splitlines():
                    stripped = _CTRL.sub("", line).strip()
                    if not stripped or not _printable(stripped):
                        continue
                    if stripped.lower() in recent_cmds:
                        continue
                    if _is_prompt(stripped):
                        continue
                    print(f"  {_DIM}{ts}{_RST}     {_GREY}{stripped}{_RST}")
                recent_cmds.clear()

            elif kind == "event":
                input_buf = b""
                recent_cmds.clear()
                print(f"\n  {_DIM}──  {entry['msg']}  ──{_RST}\n")

    print()


def print_log_list() -> None:
    logs = list_logs()
    if not logs:
        print(f"  {_GREY}No logs found in {log_dir()}{_RST}")
        return
    print()
    for p in logs:
        size = p.stat().st_size
        size_str = f"{size // 1024}K" if size >= 1024 else f"{size}B"
        print(f"  {_ORANGE}{p.name}{_RST}  {_GREY}{size_str}{_RST}")
    print()
