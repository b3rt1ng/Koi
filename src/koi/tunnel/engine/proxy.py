from __future__ import annotations

import asyncio
import logging

from .transport import Channel, server_context
from .tun import Tun

log = logging.getLogger("tunel.proxy")


class Proxy:
    def __init__(
        self,
        psk: str,
        tun_name: str = "tunel0",
        address: str = "240.0.0.1",
        netmask: int = 24,
        routes: list[str] | None = None,
        host: str = "0.0.0.0",
        port: int = 11601,
        mtu: int = 1500,
        configure: bool = True,
    ):
        self.psk = psk
        self.tun_name = tun_name
        self.address = address
        self.netmask = netmask
        self.routes = routes or []
        self.host = host
        self.port = port
        self.mtu = mtu
        self.configure = configure

        self.tun: Tun | None = None
        self.channel: Channel | None = None
        self._loop: asyncio.AbstractEventLoop | None = None


    def _on_tun_readable(self) -> None:
        assert self.tun is not None
        while True:
            try:
                packet = self.tun.read()
            except BlockingIOError:
                return
            except OSError as exc:
                log.error("lecture TUN: %s", exc)
                return
            if not packet:
                return
            if self.channel is None:
                continue          # no agent connected: drop it
            try:
                self.channel.send(packet)
            except (OSError, ValueError) as exc:
                log.debug("tunnel send: %s", exc)


    async def _pump_from_agent(self, channel: Channel) -> None:
        assert self.tun is not None
        while True:
            packet = await channel.recv()
            try:
                self.tun.write(packet)
            except BlockingIOError:
                pass              # TUN saturated: let TCP retransmit
            except OSError as exc:
                log.debug("ecriture TUN: %s", exc)


    async def _handle_agent(self, reader, writer) -> None:
        channel = Channel(reader, writer)
        if self.channel is not None:
            log.warning("an agent is already connected, %s rejected", channel.peer)
            await channel.close()
            return

        self.channel = channel
        log.info("agent connected from %s", channel.peer)
        self._announce()

        try:
            await self._pump_from_agent(channel)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            log.info("agent disconnected")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("session interrupted: %s", exc)
        finally:
            self.channel = None
            await channel.close()
            log.info("session closed (rx=%d tx=%d packets)", channel.rx_packets, channel.tx_packets)

    def _announce(self) -> None:
        log.info("route traffic to %s to send it through the tunnel", self.tun_name)
        for cidr in self.routes:
            log.info("  active route: %s", cidr)
        if not self.routes:
            log.info("  e.g.: sudo ip route add 172.16.0.0/24 dev %s", self.tun_name)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.tun = Tun(self.tun_name, mtu=self.mtu)
        log.info("interface %s opened", self.tun.name)

        if self.configure:
            self.tun.configure(self.address, self.netmask)
            for cidr in self.routes:
                self.tun.add_route(cidr)
            log.info("%s configured as %s/%d", self.tun.name, self.address, self.netmask)

        self._loop.add_reader(self.tun.fileno(), self._on_tun_readable)

        server = await asyncio.start_server(
            self._handle_agent, self.host, self.port, ssl=server_context(self.psk)
        )
        log.info("waiting for an agent on %s:%d (TLS-PSK)", self.host, self.port)

        try:
            async with server:
                await server.serve_forever()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self.tun is not None:
            if self._loop is not None:
                try:
                    self._loop.remove_reader(self.tun.fileno())
                except (ValueError, OSError):
                    pass
            self.tun.close()
            self.tun = None
