from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from koi.utils.ui import accent


@dataclass
class Target:
    """``destination`` goes to the transport binary; ``host`` resolves the callback interface."""
    destination: str
    host: str
    password: Optional[str] = field(default=None, repr=False)
    args: list[str] = field(default_factory=list)


class Transport:
    """``parse`` and ``build_command`` are required; the payload calls back on its own socket."""

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

    def remote_script(self, local_ip: str, port: int) -> str:
        """The payload to run on the target; defaults to the POSIX callback."""
        from koi.utils.payloads import linux_callback_script
        return linux_callback_script(local_ip, port)

    def resolve_host(self, target: Target) -> Optional[str]:
        """Hostname for the callback interface; None when Koi cannot route to the target itself."""
        return target.host

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
