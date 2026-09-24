from __future__ import annotations

import asyncio
import logging

from .stack import Stack, raise_fd_limit
from .transport import Channel, client_context

log = logging.getLogger("tunel.agent")


class Agent:
    def __init__(
        self,
        psk: str,
        host: str,
        port: int = 11601,
        mtu: int = 1500,
        retry_delay: float = 5.0,
        max_retries: int | None = None,
    ):
        self.psk = psk
        self.host = host
        self.port = port
        self.mtu = mtu
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.channel: Channel | None = None
        self.stack: Stack | None = None

    def _send(self, packet: bytes) -> None:
        if self.channel is not None:
            try:
                self.channel.send(packet)
            except (OSError, ValueError) as exc:
                log.debug("send to proxy: %s", exc)

    async def _session(self) -> None:
        reader, writer = await asyncio.open_connection(
            self.host, self.port, ssl=client_context(self.psk)
        )
        self.channel = Channel(reader, writer)
        self.stack = Stack(self._send, mtu=self.mtu)
        self.stack.start_timer()
        log.info("connected to proxy %s:%d", self.host, self.port)

        try:
            while True:
                packet = await self.channel.recv()
                self.stack.handle_packet(packet)
        finally:
            log.info("session ended (%s)", self.stack.stats)
            self.stack.shutdown()
            await self.channel.close()
            self.stack = None
            self.channel = None

    async def run(self) -> None:
        raise_fd_limit()   # push the soft fd cap to the hard cap so the stack can hold many sockets
        attempts = 0
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except (OSError, asyncio.IncompleteReadError) as exc:
                log.warning("connection lost: %s", exc)
            except Exception as exc:
                log.error("session error: %s", exc)

            attempts += 1
            if self.max_retries is not None and attempts >= self.max_retries:
                log.error("giving up after %d attempts", attempts)
                return
            log.info("retrying in %.0fs", self.retry_delay)
            await asyncio.sleep(self.retry_delay)
