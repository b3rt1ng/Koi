from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from koi.utils.ui import accent


@dataclass
class Target:
    """Where a transport should drop the callback payload.

    ``destination`` is what the transport binary itself takes, ``host`` the bare
    hostname Koi resolves to pick the interface the payload calls back to.
    """
    destination: str
    host: str
    password: Optional[str] = field(default=None, repr=False)
    args: list[str] = field(default_factory=list)


class Transport:
    """A way to run one command on a host we already have access to.

    The transport is only the delivery vector: the payload it carries calls back
    to the listener on its own socket, so a subclass never deals with the
    session that lands. Only ``parse`` and ``build_command`` are required.
    """

    name: str = ""
    syntax: str = ""   # destination spec, shown in `help` and usage errors
    summary: str = ""  # one-liner for the help screen

    @property
    def usage(self) -> str:
        return f"Usage: connect {self.name} {accent(self.syntax)} {accent(f'[{self.name} args...]')}"

    def parse(self, argv: list[str]) -> Optional[Target]:
        """Split the destination out of *argv*, None when there is none."""
        raise NotImplementedError

    def build_command(self, target: Target, remote_script: str) -> list[str]:
        """The local argv that runs *remote_script* on *target*."""
        raise NotImplementedError

    def resolve_auth(self, target: Target) -> bool:
        """Settle authentication, prompting if needed. False aborts the connect."""
        return True

    def env(self, target: Target) -> Optional[dict[str, str]]:
        """Environment for the command, None to inherit Koi's."""
        return None

    def explain_exit(self, target: Target, code: int) -> str:
        return f"exit code {code}"

    def completions(self) -> list[str]:
        """Known destinations, tab-completed after the transport name."""
        return []
