from __future__ import annotations

import os
import re
import select
import signal
import threading
import time
import uuid
from typing import Iterator, Optional

from .exceptions import SessionClosed, SessionTimeout
from .result import CommandResult, StreamLine


_SENTINEL_PREFIX = "__SHELL_HANDLER_DONE__"


class PersistentSession:

    def __init__(
        self,
        shell: str = "/bin/bash",
        timeout: float = 30.0,
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
        encoding: str = "utf-8",
    ):
        self._shell = shell
        self._timeout = timeout
        self._env = {**os.environ, **(env or {})}
        self._cwd = cwd
        self._encoding = encoding
        self._closed = False
        self._lock = threading.Lock()
        self._proc = self._spawn()

    def _spawn(self):
        import subprocess
        proc = subprocess.Popen(
            [self._shell],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=self._env,
            cwd=self._cwd,
            bufsize=0,
            preexec_fn=os.setsid,
        )
        self._proc = proc
        init_sentinel = str(uuid.uuid4()).replace("-", "")
        init_cmd = (
            f"stty -echo 2>/dev/null; PS1=''; PS2=''; "
            f'echo "{_SENTINEL_PREFIX}:0:sentinel={init_sentinel}"\n'
        )
        self._proc.stdin.write(init_cmd.encode(self._encoding))
        self._proc.stdin.flush()
        self._drain_until_sentinel(init_sentinel, timeout=5.0)
        return proc

    def close(self, force: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if force:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            else:
                self._proc.stdin.write(b"exit 0\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except Exception:
                pass

    def __enter__(self) -> "PersistentSession":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _raw_write(self, text: str) -> None:
        self._proc.stdin.write(text.encode(self._encoding))
        self._proc.stdin.flush()

    def _drain_until_sentinel(
        self, sentinel: str, timeout: float
    ) -> tuple[str, int]:
        buf: list[str] = []
        deadline = time.monotonic() + timeout
        exit_code = 0
        pattern = re.compile(
            rf"^{re.escape(_SENTINEL_PREFIX)}:(\d+):sentinel={re.escape(sentinel)}$"
        )

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SessionTimeout(
                    f"Timed out waiting for sentinel after {timeout}s"
                )
            ready, _, _ = select.select([self._proc.stdout], [], [], min(remaining, 0.1))
            if not ready:
                if self._proc.poll() is not None:
                    raise SessionClosed("Shell process died unexpectedly")
                continue

            line_bytes = self._proc.stdout.readline()
            if not line_bytes:
                raise SessionClosed("Shell process closed stdout unexpectedly")

            line = line_bytes.decode(self._encoding, errors="replace").rstrip("\n")
            m = pattern.match(line)
            if m:
                exit_code = int(m.group(1))
                break
            buf.append(line)

        return "\n".join(buf), exit_code

    def run(
        self,
        command: str,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        if self._closed:
            raise SessionClosed("Session is already closed")

        timeout = timeout or self._timeout
        sentinel = str(uuid.uuid4()).replace("-", "")

        with self._lock:
            start = time.monotonic()
            wrapped = (
                f"( {command} ); "
                f'echo "{_SENTINEL_PREFIX}:$?:sentinel={sentinel}"\n'
            )
            self._raw_write(wrapped)

            try:
                output, returncode = self._drain_until_sentinel(sentinel, timeout=timeout)
            except SessionTimeout as exc:
                self._raw_write("kill %1 2>/dev/null; true\n")
                raise exc

            duration = time.monotonic() - start

        return CommandResult(
            command=command,
            returncode=returncode,
            stdout=output,
            stderr="",
            duration=duration,
            pid=self._proc.pid,
        )

    def stream(
        self,
        command: str,
        timeout: Optional[float] = None,
    ) -> Iterator[StreamLine]:
        if self._closed:
            raise SessionClosed("Session is already closed")

        timeout = timeout or self._timeout
        sentinel = str(uuid.uuid4()).replace("-", "")
        pattern = re.compile(
            rf"^{re.escape(_SENTINEL_PREFIX)}:(\d+):sentinel={re.escape(sentinel)}$"
        )
        deadline = time.monotonic() + timeout

        with self._lock:
            wrapped = (
                f"( {command} ); "
                f'echo "{_SENTINEL_PREFIX}:$?:sentinel={sentinel}"\n'
            )
            self._raw_write(wrapped)

            line_number = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SessionTimeout(
                        f"Stream timed out after {timeout}s"
                    )
                ready, _, _ = select.select(
                    [self._proc.stdout], [], [], min(remaining, 0.05)
                )
                if not ready:
                    if self._proc.poll() is not None:
                        raise SessionClosed("Shell process died during stream")
                    continue

                line_bytes = self._proc.stdout.readline()
                if not line_bytes:
                    raise SessionClosed("Shell closed stdout during stream")

                line = line_bytes.decode(self._encoding, errors="replace").rstrip("\n")
                if pattern.match(line):
                    return
                yield StreamLine(text=line, source="stdout", line_number=line_number)
                line_number += 1

    @property
    def is_alive(self) -> bool:
        return not self._closed and self._proc.poll() is None

    def get_env_var(self, name: str) -> str:
        result = self.run(f"echo ${name}")
        return result.stdout.strip()

    def cd(self, path: str) -> CommandResult:
        return self.run(f"cd {path!r}")

    def export(self, key: str, value: str) -> CommandResult:
        return self.run(f"export {key}={value!r}")