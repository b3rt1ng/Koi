from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import (
    Callable,
    Dict,
    Generator,
    Iterator,
    List,
    Optional,
    Union,
)

from .exceptions import (
    CommandFailed,
    CommandTimeout,
    MaxRetriesExceeded,
)
from .result import CommandResult, StreamLine
from .session import PersistentSession

logger = logging.getLogger("shell_handler")

def _build_cmd(command: Union[str, List[str]]) -> Union[str, List[str]]:
    if isinstance(command, list) and len(command) == 0:
        raise ValueError("command list must not be empty")
    return command

def _is_list_cmd(command: Union[str, List[str]]) -> bool:
    return isinstance(command, list)

class ShellHandler:

    def __init__(
        self,
        default_timeout: float = 60.0,
        default_retries: int = 0,
        retry_backoff: float = 1.0,
        raise_on_error: bool = False,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        encoding: str = "utf-8",
        on_start: Optional[Callable[[str], None]] = None,
        on_finish: Optional[Callable[[CommandResult], None]] = None,
    ):
        self.default_timeout = default_timeout
        self.default_retries = default_retries
        self.retry_backoff = retry_backoff
        self.raise_on_error = raise_on_error
        self.encoding = encoding
        self.cwd = cwd
        self.on_start = on_start
        self.on_finish = on_finish

        self._base_env = {**os.environ, **(env or {})}
        self._active_procs: Dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()

        signal.signal(signal.SIGTERM, self._sigterm_handler)

    def with_env(self, **kwargs) -> "ShellHandler":
        merged = {**self._base_env, **kwargs}
        return ShellHandler(
            default_timeout=self.default_timeout,
            default_retries=self.default_retries,
            retry_backoff=self.retry_backoff,
            raise_on_error=self.raise_on_error,
            env=merged,
            cwd=self.cwd,
            encoding=self.encoding,
            on_start=self.on_start,
            on_finish=self.on_finish,
        )

    def with_cwd(self, cwd: str) -> "ShellHandler":
        return ShellHandler(
            default_timeout=self.default_timeout,
            default_retries=self.default_retries,
            retry_backoff=self.retry_backoff,
            raise_on_error=self.raise_on_error,
            env=self._base_env,
            cwd=cwd,
            encoding=self.encoding,
            on_start=self.on_start,
            on_finish=self.on_finish,
        )

    def _sigterm_handler(self, signum, frame) -> None:
        logger.warning("SIGTERM received – killing all active processes")
        self.kill_all()

    def _register(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._active_procs[proc.pid] = proc

    def _unregister(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._active_procs.pop(proc.pid, None)

    def kill_all(self) -> None:
        with self._lock:
            pids = list(self._active_procs.keys())
        for pid in pids:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                logger.debug(f"Killed process group of PID {pid}")
            except Exception:
                pass

    def _execute(
        self,
        command: Union[str, List[str]],
        timeout: float,
        extra_env: Optional[Dict] = None,
        cwd: Optional[str] = None,
    ) -> CommandResult:
        use_shell = not _is_list_cmd(command)
        env = {**self._base_env, **(extra_env or {})}
        cwd = cwd or self.cwd
        cmd_str = command if isinstance(command, str) else " ".join(command)

        if self.on_start:
            try:
                self.on_start(cmd_str)
            except Exception:
                pass

        logger.debug(f"Executing: {cmd_str!r}")
        start = time.monotonic()

        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=use_shell,
            env=env,
            cwd=cwd,
            preexec_fn=os.setsid,
        )
        self._register(proc)

        try:
            stdout_b, stderr_b = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            proc.communicate()
            self._unregister(proc)
            raise CommandTimeout(cmd_str, timeout)
        except Exception:
            proc.kill()
            proc.communicate()
            self._unregister(proc)
            raise
        finally:
            self._unregister(proc)

        duration = time.monotonic() - start
        result = CommandResult(
            command=cmd_str,
            returncode=proc.returncode,
            stdout=stdout_b.decode(self.encoding, errors="replace"),
            stderr=stderr_b.decode(self.encoding, errors="replace"),
            duration=duration,
            started_at=datetime.now(),
            pid=proc.pid,
        )

        if self.on_finish:
            try:
                self.on_finish(result)
            except Exception:
                pass

        logger.debug(f"Finished {cmd_str!r} → rc={proc.returncode} ({duration:.3f}s)")
        return result

    def run(
        self,
        command: Union[str, List[str]],
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
        raise_on_error: Optional[bool] = None,
        extra_env: Optional[Dict] = None,
        cwd: Optional[str] = None,
    ) -> CommandResult:
        timeout = timeout or self.default_timeout
        retries = retries if retries is not None else self.default_retries
        should_raise = raise_on_error if raise_on_error is not None else self.raise_on_error

        last_result: Optional[CommandResult] = None
        last_exc: Optional[Exception] = None

        for attempt in range(retries + 1):
            if attempt > 0:
                delay = self.retry_backoff * (2 ** (attempt - 1))
                logger.info(f"Retry {attempt}/{retries} in {delay:.1f}s …")
                time.sleep(delay)

            try:
                result = self._execute(command, timeout, extra_env, cwd)
                result = CommandResult(
                    command=result.command,
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    duration=result.duration,
                    started_at=result.started_at,
                    pid=result.pid,
                    attempts=attempt + 1,
                )
                if result.success or not should_raise:
                    if not result.success and should_raise:
                        raise CommandFailed(result.command, result.returncode, result.stderr)
                    return result
                last_result = result
                last_exc = CommandFailed(result.command, result.returncode, result.stderr)

            except CommandTimeout as exc:
                last_exc = exc
                logger.warning(str(exc))

        if retries > 0:
            raise MaxRetriesExceeded(
                str(command), retries + 1
            ) from last_exc

        if last_result is not None:
            if should_raise:
                raise CommandFailed(last_result.command, last_result.returncode, last_result.stderr)
            return last_result

        raise last_exc

    def stream(
        self,
        command: Union[str, List[str]],
        timeout: Optional[float] = None,
        include_stderr: bool = True,
        cwd: Optional[str] = None,
        extra_env: Optional[Dict] = None,
        on_line: Optional[Callable[[StreamLine], None]] = None,
    ) -> Iterator[StreamLine]:
        import queue

        timeout = timeout or self.default_timeout
        use_shell = not _is_list_cmd(command)
        env = {**self._base_env, **(extra_env or {})}
        cwd = cwd or self.cwd
        cmd_str = command if isinstance(command, str) else " ".join(command)

        stderr_target = subprocess.PIPE if include_stderr else subprocess.DEVNULL

        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=stderr_target,
            shell=use_shell,
            env=env,
            cwd=cwd,
            preexec_fn=os.setsid,
            bufsize=1,
        )
        self._register(proc)
        q: "queue.Queue[Optional[StreamLine]]" = queue.Queue()
        line_count = {"n": 0}

        def _reader(pipe, source: str):
            for raw in iter(pipe.readline, b""):
                text = raw.decode(self.encoding, errors="replace").rstrip("\n")
                sl = StreamLine(text=text, source=source, line_number=line_count["n"])
                line_count["n"] += 1
                q.put(sl)
            q.put(None)  # sentinel

        threads = [threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True)]
        if include_stderr and proc.stderr:
            threads.append(threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True))

        for t in threads:
            t.start()

        deadline = time.monotonic() + timeout
        done_count = 0
        expected_done = len(threads)

        try:
            while done_count < expected_done:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        pass
                    raise CommandTimeout(cmd_str, timeout)
                try:
                    item = q.get(timeout=min(remaining, 0.1))
                    if item is None:
                        done_count += 1
                    else:
                        if on_line:
                            on_line(item)
                        yield item
                except Exception:
                    continue
        finally:
            proc.wait()
            self._unregister(proc)
            for t in threads:
                t.join(timeout=1)

    async def async_run(
        self,
        command: Union[str, List[str]],
        timeout: Optional[float] = None,
        raise_on_error: Optional[bool] = None,
        extra_env: Optional[Dict] = None,
        cwd: Optional[str] = None,
    ) -> CommandResult:
        timeout = timeout or self.default_timeout
        should_raise = raise_on_error if raise_on_error is not None else self.raise_on_error
        use_shell = not _is_list_cmd(command)
        env = {**self._base_env, **(extra_env or {})}
        cwd = cwd or self.cwd
        cmd_str = command if isinstance(command, str) else " ".join(command)

        start = time.monotonic()

        if use_shell:
            create = asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )
        else:
            create = asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

        proc = await create

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise CommandTimeout(cmd_str, timeout)

        duration = time.monotonic() - start
        result = CommandResult(
            command=cmd_str,
            returncode=proc.returncode,
            stdout=stdout_b.decode(self.encoding, errors="replace"),
            stderr=stderr_b.decode(self.encoding, errors="replace"),
            duration=duration,
            pid=proc.pid,
        )

        if should_raise and not result.success:
            raise CommandFailed(result.command, result.returncode, result.stderr)

        return result

    async def async_stream(
        self,
        command: Union[str, List[str]],
        timeout: Optional[float] = None,
        extra_env: Optional[Dict] = None,
        cwd: Optional[str] = None,
    ):
        timeout = timeout or self.default_timeout
        use_shell = not _is_list_cmd(command)
        env = {**self._base_env, **(extra_env or {})}
        cwd = cwd or self.cwd
        cmd_str = command if isinstance(command, str) else " ".join(command)

        if use_shell:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

        line_number = 0
        deadline = asyncio.get_event_loop().time() + timeout

        async def _read_pipe(pipe, source: str):
            nonlocal line_number
            async for raw_line in pipe:
                text = raw_line.decode(self.encoding, errors="replace").rstrip("\n")
                yield StreamLine(text=text, source=source, line_number=line_number)
                line_number += 1

        try:
            async for line in _read_pipe(proc.stdout, "stdout"):
                if asyncio.get_event_loop().time() > deadline:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    raise CommandTimeout(cmd_str, timeout)
                yield line
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            await proc.wait()

    def session(
        self,
        shell: str = "/bin/bash",
        timeout: Optional[float] = None,
        env: Optional[Dict] = None,
        cwd: Optional[str] = None,
    ) -> PersistentSession:
        return PersistentSession(
            shell=shell,
            timeout=timeout or self.default_timeout,
            env={**self._base_env, **(env or {})},
            cwd=cwd or self.cwd,
            encoding=self.encoding,
        )

    def __enter__(self) -> "ShellHandler":
        return self

    def __exit__(self, *_) -> None:
        self.kill_all()