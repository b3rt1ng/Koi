from __future__ import annotations
from dataclasses import dataclass


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration: float

    @property
    def success(self) -> bool:
        return self.returncode == 0

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAIL({self.returncode})"
        return (
            f"<CommandResult [{status}] cmd={self.command!r} "
            f"duration={self.duration:.3f}s>"
        )


@dataclass
class StreamLine:
    text: str

    def __str__(self) -> str:
        return self.text
