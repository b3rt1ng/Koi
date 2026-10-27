from __future__ import annotations

import getpass
import select
import socket
import threading
from dataclasses import dataclass, field
from typing import Optional

from koi.utils.connect import ntlm
from koi.utils.connect.base import Target, Transport, TransportError
from koi.utils.connect.wsman import WsManClient
from koi.utils.ui import muted, notify


@dataclass
class WinrmTarget(Target):
    user: str = ''
    domain: str = ''
    port: int = 5985
    nt_hash_bytes: Optional[bytes] = field(default=None, repr=False)


class WinrmTransport(Transport):
    name = "winrm"
    syntax = "<[domain\\\\]user[:pass|%nthash]@host[:port]>"
    summary = "Open a session over WinRM (NTLMv2, pure Python, no deps)"

    direct = True

    def parse(self, argv: list[str]) -> Optional[WinrmTarget]:
        if not argv:
            return None

        raw = argv[0]
        userinfo, at, hostpart = raw.rpartition('@')
        if not at or not userinfo:
            return None

        host, port = hostpart, 5985
        if ':' in hostpart:
            host, _, port_s = hostpart.rpartition(':')
            try:
                port = int(port_s)
            except ValueError:
                return None

        domain = ''
        if '\\' in userinfo:
            domain, _, userinfo = userinfo.partition('\\')

        if '%' in userinfo:
            user, _, hash_hex = userinfo.partition('%')
            try:
                nt_h = bytes.fromhex(hash_hex)
            except ValueError:
                notify('error', 'Invalid NT hash (expected 32 hex characters).')
                return None
            if len(nt_h) != 16:
                notify('error', 'NT hash must be exactly 16 bytes (32 hex chars).')
                return None
            return WinrmTarget(
                destination=raw, host=host, user=user,
                domain=domain, port=port, nt_hash_bytes=nt_h,
            )

        password = None
        if ':' in userinfo:
            user, _, password = userinfo.partition(':')
        else:
            user = userinfo

        return WinrmTarget(
            destination=raw, host=host, password=password or None,
            user=user, domain=domain, port=port,
        )

    def resolve_auth(self, target: Target) -> bool:
        t: WinrmTarget = target  # type: ignore[assignment]
        if t.password is None and t.nt_hash_bytes is None:
            pwd = getpass.getpass(f'Password for {t.user}@{t.host}: ')
            if not pwd:
                notify('warning', 'No password provided.')
                return False
            t.password = pwd
        return True

    def remote_script(self, local_ip: str, port: int) -> str:
        self._listener_port = port
        return ''

    def help_detail(self) -> dict[str, str]:
        return {
            "Usage": f"connect {self.name} {self.syntax}",
            "Description": (
                "Open an interactive PowerShell session over WinRM (WS-Man).\n"
                "Authentication uses NTLMv2 (pure Python, no external deps).\n"
                "Port 5986 auto-enables HTTPS/TLS."
            ),
            "Auth modes": (
                "user:password@host        plaintext password\n"
                "DOMAIN\\user:password@host  domain account\n"
                "user%NTHASH@host           pass-the-hash (32 hex chars)\n"
                "user@host                  prompts for password"
            ),
            "Examples": (
                "connect winrm admin:P@ss@10.0.0.5\n"
                "connect winrm CORP\\svc_sql:Summer2024@dc01\n"
                "connect winrm admin%aad3b435b51404eeaad3b435b51404ee@10.0.0.5\n"
                "connect winrm admin@host:5986"
            ),
        }

    def execute(self, target: Target, remote_script: str) -> int:
        t: WinrmTarget = target  # type: ignore[assignment]
        nt_h = t.nt_hash_bytes or ntlm.nt_hash(t.password)
        use_ssl = t.port == 5986

        client = WsManClient(
            t.host, t.port, t.user, nt_h, t.domain, use_ssl=use_ssl,
        )

        notify('status', muted(f'Authenticating to {t.host}:{t.port} ...'))
        try:
            shell_id = client.create_shell()
        except OSError as exc:
            raise TransportError(f'Cannot reach {t.host}:{t.port} ({exc})') from exc

        command_id = client.run_command(
            shell_id, 'powershell', '-NoProfile -NoLogo',
        )

        # Connect back to Koi's own listener to register as a session.
        bridge = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            bridge.connect(('127.0.0.1', self._listener_port))
        except OSError as exc:
            client.signal_terminate(shell_id, command_id)
            client.delete_shell(shell_id)
            client.close()
            raise TransportError(f'Cannot connect to local listener ({exc})') from exc

        stop = threading.Event()

        def _recv_loop():
            """WS-Man -> bridge socket: poll output and forward."""
            try:
                while not stop.is_set():
                    try:
                        data, done = client.receive_output(shell_id, command_id)
                    except (TransportError, OSError):
                        break
                    if data:
                        try:
                            bridge.sendall(data)
                        except OSError:
                            break
                    if done:
                        break
            finally:
                stop.set()
                try:
                    bridge.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        def _send_loop():
            """Bridge socket -> WS-Man: read input and send."""
            try:
                while not stop.is_set():
                    ready, _, _ = select.select([bridge], [], [], 0.5)
                    if not ready:
                        continue
                    try:
                        chunk = bridge.recv(4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    try:
                        if b'\x03' in chunk:
                            parts = chunk.split(b'\x03')
                            for i, part in enumerate(parts):
                                if part:
                                    client.send_input(shell_id, command_id, part)
                                if i < len(parts) - 1:
                                    client.signal_ctrl_c(shell_id, command_id)
                        else:
                            client.send_input(shell_id, command_id, chunk)
                    except (TransportError, OSError):
                        break
            finally:
                stop.set()

        t_recv = threading.Thread(target=_recv_loop, daemon=True)
        t_send = threading.Thread(target=_send_loop, daemon=True)
        t_recv.start()
        t_send.start()

        def _cleanup():
            """Wait for bridge death, then tear down the WS-Man shell."""
            stop.wait()
            t_recv.join(timeout=5)
            t_send.join(timeout=5)
            try:
                client.signal_terminate(shell_id, command_id)
            except Exception:
                pass
            try:
                client.delete_shell(shell_id)
            except Exception:
                pass
            try:
                bridge.close()
            except Exception:
                pass

        threading.Thread(target=_cleanup, daemon=True).start()

        return 0

    _listener_port: int = 0
