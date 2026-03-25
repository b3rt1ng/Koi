from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from koi.main import Session
    from koi.shell_handler.core import ShellHandler

from koi.utils import ui

import argparse


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

    Then register it in src/koi/modules/__init__.py (see loader pattern below).
    """

    #: Short identifier used to call the module from the CLI (e.g. "enum_linux")
    name: str = "unnamed_module"

    #: One-line summary shown in the module list
    description: str = "No description provided."

    #: Optional longer help text shown with `module help <name>`
    usage: str = ""
    
    #: Optional list of argument specifications
    arguments: list[dict] = []

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
        self.breaker = ui.breaker
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
        import select
        import time
        import uuid
        from koi.shell_handler.result import CommandResult

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
                from koi.shell_handler.exceptions import CommandTimeout
                raise CommandTimeout(command, timeout)

            ready, _, _ = select.select([self.session.conn], [], [], min(remaining, 0.1))
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
                        stderr="",
                        duration=time.monotonic() - (deadline - timeout),
                        pid=None,
                    )
                output_lines.append(text)

        from koi.shell_handler.result import CommandResult
        return CommandResult(
            command=command, returncode=1,
            stdout="\n".join(output_lines), stderr="",
            duration=0, pid=None,
        )

    def exec_stream(self, command: str, timeout: float = 30.0):
        """
        Stream output of *command* line-by-line from the remote session as
        :class:`~koi.shell_handler.result.StreamLine` objects.

        Example::

            for line in self.exec_stream("find / -name '*.conf' 2>/dev/null"):
                self.notify('info', line.text)
        """
        import select
        import time
        import uuid
        from koi.shell_handler.result import StreamLine

        sentinel = uuid.uuid4().hex
        marker   = f"__KOI_DONE_{sentinel}__"
        wrapped  = f'( {command} ); printf "\\n{marker}\\n"\n'
        self.session.conn.sendall(wrapped.encode("utf-8"))

        buf      = b""
        deadline = time.monotonic() + timeout
        line_number = 0

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                from koi.shell_handler.exceptions import CommandTimeout
                raise CommandTimeout(command, timeout)

            ready, _, _ = select.select([self.session.conn], [], [], min(remaining, 0.1))
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
                yield StreamLine(text=text, source="stdout", line_number=line_number)
                line_number += 1

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

    def __str__(self) -> str:
        return f"<KoiModule {self.name!r} on session #{self.session.id}>"

    def __repr__(self) -> str:
        return self.__str__()