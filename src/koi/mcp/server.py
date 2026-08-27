"""MCP server over HTTP, not stdio: stdin/stdout belong to the REPL."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import logging
import ntpath
import posixpath
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from koi.mcp.schema import module_input_schema, schema_to_argv
from koi.modules.blueprint import KoiModule
from koi.session import SessionBusy
from koi.utils.constants import ANSI_RE
from koi.utils.logger import list_logs, log_dir

if TYPE_CHECKING:
    from koi.listener import Listener
    from koi.session import Session

logger = logging.getLogger("koi.mcp")

_IO_TIMEOUT = 10.0

_MODULE_TOOL_PREFIX = "koi_module_"
_LOG_URI_PREFIX = "koi://logs/"

_DEFAULT_EXEC_TIMEOUT = 30.0
_MAX_EXEC_TIMEOUT = 600.0
_MAX_TAG_LEN = 64
_MAX_OUTPUT_BYTES = 256 * 1024

# MCP file transfers are confined here; a CLI operator stays unrestricted.
_DOWNLOAD_ROOT = Path.home() / ".koi" / "downloads"
_UPLOAD_ROOT = Path.home() / ".koi" / "uploads"

# Tools that mutate state or run code: never offered on a read-only connection.
_EXEC_ONLY_TOOLS = {"koi_exec", "koi_tag"}

_REQUIRED_PACKAGES = ("mcp", "uvicorn", "starlette")


def missing_dependencies() -> List[str]:
    import importlib.util

    return [n for n in _REQUIRED_PACKAGES if importlib.util.find_spec(n) is None]


def _cap(text: str) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= _MAX_OUTPUT_BYTES:
        return text, False
    return encoded[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore"), True


def _render_log(path: Path) -> str:
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = entry.get("type")
        if kind in ("input", "output"):
            try:
                text = base64.b64decode(entry["data"]).decode("utf-8", errors="replace")
            except Exception:
                continue
            out.append(_strip_ansi(text))
        elif kind == "event":
            out.append(f"[{entry.get('msg', '')}]")
        elif kind == "meta":
            out.append(f"[session #{entry.get('id')} {entry.get('ip')} {entry.get('os')}]")
    return "".join(out)


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "")


def _exec_timeout(value) -> float:
    if value is None:
        return _DEFAULT_EXEC_TIMEOUT
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"timeout must be a number, got {type(value).__name__}")
    try:
        timeout = float(value)
    except ValueError:
        raise ValueError(f"timeout must be a number, got {value!r}") from None
    if timeout <= 0 or timeout != timeout:  # NaN compares unequal to itself
        raise ValueError(f"timeout must be greater than 0, got {value!r}")
    return min(timeout, _MAX_EXEC_TIMEOUT)


def _confine_download_output(client_value, remote_path: str) -> str:
    _DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    if client_value:
        base = Path(str(client_value)).name  # drop any directory component
    else:
        stripped = remote_path.rstrip("/\\")
        base = ntpath.basename(stripped) or posixpath.basename(stripped)
    return str(_DOWNLOAD_ROOT / (base or "download"))


def _confine_upload_source(client_value) -> str:
    _UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    root = _UPLOAD_ROOT.resolve()
    candidate = Path(str(client_value or ""))
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"upload local_path must stay under {root}")
    return str(candidate)


def _uptime(since: Optional[float]) -> Optional[str]:
    if since is None:
        return None
    secs = int(max(0.0, time.time() - since))
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("koi-handler")
    except PackageNotFoundError:
        return "unknown"


def _tool(name: str, description: str, properties=None, required=None, annotations=None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = required
    tool: Dict[str, Any] = {"name": name, "description": description, "input_schema": schema}
    if annotations:
        tool["annotations"] = annotations
    return tool


class _ThreadStream:
    """Per-thread stdout/stderr stand-in: contextlib.redirect_stdout swaps process-wide and would break the REPL."""

    _THREAD_ATTRS = frozenset({"write", "writelines", "flush", "isatty"})

    def __init__(self, target):
        self._target = target
        self._local = threading.local()

    def for_thread(self):
        """The stream this thread writes to; ui.Spinner calls it to inherit its caller's capture."""
        return getattr(self._local, "buffer", None) or self._target

    @contextlib.contextmanager
    def capture(self, buffer):
        previous = getattr(self._local, "buffer", None)
        self._local.buffer = buffer
        try:
            yield
        finally:
            self._local.buffer = previous

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        target = self.for_thread() if name in self._THREAD_ATTRS else self._target
        return getattr(target, name)


class _ThreadStdin:
    """input() on an MCP worker thread would block forever on the operator's terminal, so reads raise EOFError."""

    def __init__(self, target):
        self._target = target
        self._local = threading.local()

    @contextlib.contextmanager
    def block(self):
        prev = getattr(self._local, "blocked", False)
        self._local.blocked = True
        try:
            yield
        finally:
            self._local.blocked = prev

    def _blocked(self):
        return getattr(self._local, "blocked", False)

    def readline(self, *a):
        if self._blocked():
            raise EOFError("stdin is not available to MCP tools")
        return self._target.readline(*a)

    def read(self, *a):
        if self._blocked():
            raise EOFError("stdin is not available to MCP tools")
        return self._target.read(*a)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._target, name)


_streams_lock = threading.Lock()
_streams: Optional[tuple] = None
_stdin: Optional[_ThreadStdin] = None


@contextlib.contextmanager
def _capture_output():
    global _streams, _stdin
    with _streams_lock:
        if _streams is None:
            _streams = (_ThreadStream(sys.stdout), _ThreadStream(sys.stderr))
            sys.stdout, sys.stderr = _streams
        if _stdin is None:
            _stdin = _ThreadStdin(sys.stdin)
            sys.stdin = _stdin

    out, err = _streams
    buffer = io.StringIO()
    with out.capture(buffer), err.capture(buffer), _stdin.block():
        yield buffer


def resolve_token(explicit: Optional[str] = None) -> str:
    import os

    from koi.utils.config import CONFIG, persist

    if explicit:
        return explicit
    if env := os.environ.get("KOI_MCP_TOKEN"):
        return env
    if saved := CONFIG.get("mcp_token"):
        return saved

    token = secrets.token_urlsafe(24)
    persist("mcp_token", token)
    return token


class KoiMCPServer:
    def __init__(
        self,
        listener: "Listener",
        host: str = "127.0.0.1",
        port: int = 7331,
        token: Optional[str] = None,
        allow_exec: bool = False,
    ):
        self.listener = listener
        self.host = host
        self.port = port
        self.token = resolve_token(token)
        self.allow_exec = allow_exec
        self._thread: Optional[threading.Thread] = None

    def _resolve(self, ref: str) -> "Session":
        sess = self.listener._resolve_session(str(ref))
        if sess is None:
            raise ValueError(f"Session {ref!r} not found")
        if not sess.alive:
            raise ValueError(f"Session {ref!r} is no longer alive")
        return sess

    def _require_exec(self) -> None:
        if not self.allow_exec:
            raise PermissionError(
                "Command execution is disabled. Restart with --mcp-allow-exec "
                "to let MCP clients run commands and modules on live sessions."
            )

    def _session_dict(self, sess: "Session") -> Dict[str, Any]:
        return {
            "id": sess.id,
            "tag": sess.tag,
            "address": self.listener._mask_ip(sess.addr[0]),
            "port": sess.addr[1],
            "os_type": sess.os_type,
            "upgraded": sess.upgraded,
            "alive": sess.alive,
            "uptime": sess._uptime(),
            "connected_at": sess.connected_at.isoformat(timespec="seconds"),
            "busy_with": sess.io_holder,
        }

    def _status(self) -> Dict[str, Any]:
        from koi.utils.config import SIDETCPS
        from koi.utils.payloads import get_interfaces

        lst = self.listener
        sessions = lst._snapshot()
        by_os: Dict[str, int] = {}
        for sess in sessions:
            if sess.alive:
                by_os[sess.os_type or "unknown"] = by_os.get(sess.os_type or "unknown", 0) + 1

        interfaces = {
            name: lst._mask_ip(ip, kind="local") for name, ip in get_interfaces().items()
        }

        return {
            "koi_version": _version(),
            "listener": {
                "bind_host": lst._mask_ip(lst.host, kind="local")
                if lst.host not in ("0.0.0.0", "::")
                else lst.host,
                "port": lst.port,
                "uptime": _uptime(lst.started_at),
                "accepting": lst._accepting,
                "interfaces": interfaces,
                "callback_hint": (
                    "payload must connect back to one of interfaces:port"
                    if lst.host in ("0.0.0.0", "::")
                    else "listener is bound to a single address"
                ),
            },
            "sessions": {
                "alive": sum(1 for s in sessions if s.alive),
                "total": len(sessions),
                "by_os": by_os,
            },
            "modes": {
                "local_offline": lst.local_mode,
                "screenable": lst.screenable_mode,
            },
            "transfers": {
                "side_channel_ports": list(SIDETCPS),
            },
            "mcp": {
                "url": self.url,
                "allow_exec": self.allow_exec,
                "io_timeout": _IO_TIMEOUT,
                "max_exec_timeout": _MAX_EXEC_TIMEOUT,
            },
            "logs": {"dir": str(log_dir()), "count": len(list_logs())},
        }

    def _static_tools(self) -> List[Dict[str, Any]]:
        session = {"type": "string", "description": "Session id (e.g. \"1\") or tag."}
        return [
            _tool(
                "koi_status",
                "Describe the Koi listener itself: version, bind address and port, "
                "local interfaces a payload can call back to, uptime, whether new "
                "connections are accepted, offline/screenable modes, side-channel "
                "transfer ports and what this MCP connection is allowed to do.",
            ),
            _tool(
                "koi_list_sessions",
                "List every reverse shell currently held by Koi, with its OS, "
                "PTY-upgrade state, uptime and whether it is busy.",
            ),
            _tool(
                "koi_list_modules",
                "List available post-exploitation modules and the sessions each "
                "one supports.",
            ),
            _tool(
                "koi_exec",
                "Run a single shell command on a session and return its stdout "
                "and exit code.",
                {
                    "session": session,
                    "command": {"type": "string", "description": "Command to run."},
                    "timeout": {
                        "type": "number",
                        "description": "Seconds to wait for completion.",
                        "default": 30,
                    },
                },
                ["session", "command"],
            ),
            _tool(
                "koi_tag",
                "Attach or clear a human-readable tag on a session.",
                {
                    "session": session,
                    "tag": {"type": "string", "description": "New tag; omit to clear it."},
                },
                ["session"],
            ),
        ]

    def _module_tools(self) -> List[Dict[str, Any]]:
        from koi.modules.loader import load_modules

        tools = []
        for name, cls in sorted(load_modules().items()):
            schema = module_input_schema(cls)
            schema["properties"]["session"] = {
                "type": "string",
                "description": "Session id or tag to run the module against.",
            }
            schema["required"] = ["session"] + [
                r for r in schema.get("required", []) if r != "session"
            ]
            platform = cls.platform
            targets = ", ".join(platform) if isinstance(platform, list) else str(platform)
            tools.append(
                _tool(
                    f"{_MODULE_TOOL_PREFIX}{name}",
                    f"{(cls.description or '').strip()} (targets: {targets})",
                    schema["properties"],
                    schema["required"],
                    # camelCase: ToolAnnotations fields carry no alias in mcp 2.x.
                    annotations={"destructiveHint": True},
                )
            )
        return tools

    def _list_tools(self) -> List[Dict[str, Any]]:
        if self.allow_exec:
            return self._static_tools() + self._module_tools()

        return [t for t in self._static_tools() if t["name"] not in _EXEC_ONLY_TOOLS]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        arguments = arguments or {}

        if name == "koi_status":
            return json.dumps(self._status(), indent=2)

        if name == "koi_list_sessions":
            self.listener._prune(at_prompt=True)
            sessions = sorted(self.listener._snapshot(), key=lambda s: s.id)
            return json.dumps(
                {"sessions": [self._session_dict(s) for s in sessions]}, indent=2
            )

        if name == "koi_list_modules":
            return json.dumps(
                {"modules": self._module_list(), "runnable": self.allow_exec}, indent=2
            )

        if name == "koi_tag":
            self._require_exec()
            sess = self._resolve(arguments["session"])
            raw = arguments.get("tag")
            tag = _strip_ansi(str(raw)).strip()[:_MAX_TAG_LEN] if raw else ""
            if not tag:
                sess.tag = None
                return json.dumps({"id": sess.id, "tag": None})
            if tag.isdigit():
                raise ValueError(
                    f"Tag {tag!r} is numeric and would be unreachable (ids resolve first)"
                )
            conflict = next(
                (s for s in self.listener._snapshot() if s.tag == tag and s.id != sess.id),
                None,
            )
            if conflict is not None:
                raise ValueError(f"Tag {tag!r} already used by session #{conflict.id}")
            sess.tag = tag
            return json.dumps({"id": sess.id, "tag": sess.tag})

        if name == "koi_exec":
            return self._do_exec(arguments)

        if name.startswith(_MODULE_TOOL_PREFIX):
            return self._do_run_module(name[len(_MODULE_TOOL_PREFIX):], arguments)

        raise ValueError(f"Unknown tool: {name}")

    def _module_list(self) -> List[Dict[str, Any]]:
        from koi.modules.loader import load_modules

        mods = []
        for name, cls in sorted(load_modules().items()):
            entry = {
                "name": name,
                "description": (cls.description or "").strip(),
                "platform": cls.platform,
                "usage": cls.usage,
            }
            if self.allow_exec:
                entry["tool"] = f"{_MODULE_TOOL_PREFIX}{name}"
            mods.append(entry)
        return mods

    def _do_exec(self, arguments: Dict[str, Any]) -> str:
        self._require_exec()
        sess = self._resolve(arguments["session"])
        if sess.os_type != "linux":
            raise ValueError(
                f"koi_exec runs POSIX shell and only supports Linux sessions; "
                f"#{sess.id} is {sess.os_type or 'unknown OS'} — use a module instead."
            )

        command = arguments["command"]
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        timeout = _exec_timeout(arguments.get("timeout"))

        self.listener._announce('status', f"MCP: exec on session #{sess.id}")
        with _capture_output():
            logger_obj = self.listener._ensure_logger(sess)
        sess.attach_logger(logger_obj)
        runner = _AdHocRunner(session=sess, args=[], logger=logger_obj)
        try:
            with sess.io(holder="mcp:exec", timeout=_IO_TIMEOUT):
                result = runner.exec(command, timeout=timeout)
        except SessionBusy as exc:
            raise RuntimeError(str(exc)) from exc

        stdout, truncated = _cap(_strip_ansi(result.stdout))
        payload = {
            "session": sess.id,
            "command": result.command,
            "returncode": result.returncode,
            "stdout": stdout,
            "duration": round(result.duration, 3),
        }
        if truncated:
            payload["truncated"] = True
        return json.dumps(payload, indent=2)

    def _do_run_module(self, mod_name: str, arguments: Dict[str, Any]) -> str:
        self._require_exec()
        from koi.modules.loader import get_module

        mod_cls = get_module(mod_name)
        if mod_cls is None:
            raise ValueError(f"Module {mod_name!r} not found")

        sess = self._resolve(arguments.get("session"))
        if not mod_cls.supports(sess.os_type):
            raise ValueError(
                f"Module {mod_name!r} does not support session #{sess.id} "
                f"({sess.os_type or 'unknown OS'})"
            )

        self.listener._announce('status', f"MCP: module {mod_name} on session #{sess.id}")

        # Local paths from an MCP client stay confined to ~/.koi, never the operator's disk at large.
        safe_args = {k: v for k, v in arguments.items() if k != "session"}
        if mod_name == "download":
            remote = safe_args.get("remote_path")
            remote_str = " ".join(remote) if isinstance(remote, list) else str(remote or "")
            safe_args["output"] = _confine_download_output(safe_args.get("output"), remote_str)
        elif mod_name == "upload":
            safe_args["local_path"] = _confine_upload_source(safe_args.get("local_path"))
        argv = schema_to_argv(mod_cls, safe_args)

        error: Optional[str] = None
        logger_obj = None
        with _capture_output() as buffer:
            try:
                logger_obj = self.listener._ensure_logger(sess)
                sess.attach_logger(logger_obj)
                mod_cls(session=sess, args=argv, logger=logger_obj).run_module(
                    io_timeout=_IO_TIMEOUT
                )
            except SessionBusy as exc:
                raise RuntimeError(str(exc)) from exc
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if logger_obj is not None:
                    logger_obj.log_event(f"module_error  {mod_name}  {exc}")

        output, truncated = _cap(_strip_ansi(buffer.getvalue()).strip())
        payload = {
            "session": sess.id,
            "module": mod_name,
            "argv": argv,
            "output": output,
        }
        if truncated:
            payload["truncated"] = True
        if error is not None:
            payload["error"] = error
        return json.dumps(payload, indent=2)

    def list_resources(self) -> List[Dict[str, str]]:
        return [
            {
                "uri": f"{_LOG_URI_PREFIX}{log.name}",
                "name": f"Session log {log.name}",
                "mime_type": "text/plain",
            }
            for log in list_logs()
        ]

    def read_resource(self, uri: str) -> str:
        if not uri.startswith(_LOG_URI_PREFIX):
            raise ValueError(f"Unknown resource: {uri}")

        name = uri[len(_LOG_URI_PREFIX):]
        if not name or name != Path(name).name or name in (".", ".."):
            raise ValueError(f"Invalid log name: {name!r}")

        root = log_dir().resolve()
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            raise ValueError(f"Log not found: {uri}")

        text, _ = _cap(_render_log(path))
        return text

    def _instructions(self) -> str:
        """Sent once at initialize: anything runtime-varying belongs in koi_status."""
        mode = (
            "Command execution is enabled: koi_exec and the koi_module_* tools "
            "act on live targets."
            if self.allow_exec
            else "This connection is read-only. Only introspection tools are "
            "exposed; exec and modules are refused."
        )
        return (
            "Koi is a multi-session reverse shell listener used for authorised "
            "offensive security work. Sessions are real shells on remote hosts "
            f"that called back to this listener. {mode}\n\n"
            "Call koi_status first when you need the operating context: bind "
            "address, listen port, local interfaces to point a payload at, "
            "side-channel ports used for file transfers, offline mode and log "
            "location. Call koi_list_sessions for what is currently connected; "
            "session ids are reused across tools and a tag can replace an id.\n\n"
            "One command runs on a session at a time. A tool call fails fast "
            "with a busy error when the operator is interacting with that shell, "
            "which is expected: retry later rather than escalating. Prefer a "
            "module over a hand-written command when one covers the task, since "
            "modules handle the per-OS quirks and the PTY protocol already."
        )

    def _build_app(self):
        import mcp.types as types
        from mcp.server.lowlevel import Server

        async def on_list_tools(ctx, params) -> types.ListToolsResult:
            return types.ListToolsResult(tools=[types.Tool(**t) for t in self._list_tools()])

        async def on_call_tool(ctx, params) -> types.CallToolResult:
            try:
                text = await asyncio.to_thread(
                    self.call_tool, params.name, params.arguments or {}
                )
            except Exception as exc:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=f"{type(exc).__name__}: {exc}")],
                    is_error=True,
                )
            return types.CallToolResult(content=[types.TextContent(type="text", text=text)])

        async def on_list_resources(ctx, params) -> types.ListResourcesResult:
            return types.ListResourcesResult(
                resources=[types.Resource(**r) for r in self.list_resources()]
            )

        async def on_read_resource(ctx, params) -> types.ReadResourceResult:
            uri = str(params.uri)
            text = await asyncio.to_thread(self.read_resource, uri)
            return types.ReadResourceResult(
                contents=[types.TextResourceContents(uri=uri, mime_type="text/plain", text=text)]
            )

        server = Server(
            "koi",
            version=_version(),
            title="Koi",
            website_url="https://b3rt1ng.github.io/koi-wiki/",
            instructions=self._instructions(),
            on_list_tools=on_list_tools,
            on_call_tool=on_call_tool,
            on_list_resources=on_list_resources,
            on_read_resource=on_read_resource,
        )
        inner = server.streamable_http_app(streamable_http_path="/mcp", host=self.host)

        async def app(scope, receive, send):
            scope_type = scope.get("type")
            if scope_type == "http":
                from starlette.responses import JSONResponse

                headers = dict(scope.get("headers") or [])
                provided = headers.get(b"authorization", b"").decode(errors="replace")
                if not secrets.compare_digest(provided, f"Bearer {self.token}"):
                    await JSONResponse({"error": "unauthorized"}, status_code=401)(
                        scope, receive, send
                    )
                    return
            elif scope_type != "lifespan":
                # Fail closed: any other transport (e.g. websocket) must not bypass the token.
                return
            await inner(scope, receive, send)

        return app

    def _serve(self) -> None:
        try:
            import uvicorn

            config = uvicorn.Config(
                self._build_app(),
                host=self.host,
                port=self.port,
                log_level="error",
                access_log=False,
            )
            server = uvicorn.Server(config)
            server.install_signal_handlers = lambda: None
            asyncio.run(server.serve())
        except Exception as exc:
            from koi.utils.ui import notify

            logger.debug("MCP server stopped", exc_info=True)
            notify('error', f"MCP server stopped: {type(exc).__name__}: {exc}")

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, daemon=True, name="mcp")
        self._thread.start()


class _AdHocRunner(KoiModule):
    """Concrete KoiModule used only to borrow ``exec()`` for one-off commands."""

    name = "mcp"
    description = "ad-hoc command execution"

    def run(self) -> None:
        pass
