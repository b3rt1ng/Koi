from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration: float
    started_at: datetime = field(default_factory=datetime.now)
    attempts: int = 1
    pid: Optional[int] = None

    @property
    def success(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return self.stdout

    @property
    def combined_output(self) -> str:
        parts = [p for p in (self.stdout, self.stderr) if p.strip()]
        return "\n".join(parts)

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAIL({self.returncode})"
        return (
            f"<CommandResult [{status}] cmd={self.command!r} "
            f"duration={self.duration:.3f}s>"
        )

    def raise_for_returncode(self) -> "CommandResult":
        from shell_handler.exceptions import CommandFailed
        if not self.success:
            raise CommandFailed(self.command, self.returncode, self.stderr)
        return self


@dataclass
class StreamLine:
    text: str
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    line_number: int = 0

    def __str__(self) -> str:
        return self.text