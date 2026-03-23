from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from koi.main import Session
    from koi.shell_handler.core import ShellHandler

from koi.utils import ui


class KoiModule(ABC):
    #: Short identifier used to call the module from the CLI (e.g. "enum_linux")
    name: str = "unnamed_module"

    #: One-line summary shown in the module list
    description: str = "No description provided."

    #: Optional longer help text shown with `module help <name>`
    usage: str = ""

    def __init__(self, session: "Session", args: Optional[List[str]] = None) -> None:
        self.session = session
        self.args: List[str] = args or []

        # Convenience shortcuts so module authors don't need extra imports
        self.ui = ui
        self.notify = ui.notify
        self.spinner = ui.Spinner
        self.breaker = ui.breaker
        self.box = ui.print_report_box

    @abstractmethod
    def run(self) -> None:
        """
        Entry point for the module.  All business logic goes here.

        Available helpers
        -----------------
        self.exec(cmd) -> CommandResult  (blocking, raises on timeout)
        self.exec_stream(cmd) -> Iterator[StreamLine]
        self.send(data) -> bool
        self.notify(type, msg) -> None
        self.spinner(msg) -> ContextManager
        self.box(title, dict) -> None
        self.breaker() -> None
        self.session
        self.args
        """


    def exec(self, command: str, timeout: float = 30.0):
        """
        Send *command* to the remote session via a fresh :class:`ShellHandler`
        and return a :class:`~koi.shell_handler.result.CommandResult`.

        This is the preferred way to run a single command and capture its output.

        Example::
            result = self.exec("id")
            self.ok(result.stdout.strip())
        """
        from koi.shell_handler.core import ShellHandler

        handler = ShellHandler(default_timeout=timeout)
        # We build the command so it is sent over the session socket.
        # For upgraded (PTY) sessions we write directly; for raw sessions
        # we fall back to the socket send path.
        if self.session.upgraded:
            return handler.run(command, timeout=timeout)
        else:
            return handler.run(command, timeout=timeout)

    def exec_stream(self, command: str, timeout: float = 30.0):
        """
        Stream output of *command* line-by-line as
        :class:`~koi.shell_handler.result.StreamLine` objects.

        Example::

            for line in self.exec_stream("find / -name '*.conf' 2>/dev/null"):
                self.notify('info', line.text)
        """
        from koi.shell_handler.core import ShellHandler

        handler = ShellHandler(default_timeout=timeout)
        yield from handler.stream(command, timeout=timeout)

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