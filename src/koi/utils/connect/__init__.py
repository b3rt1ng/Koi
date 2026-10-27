from __future__ import annotations

from typing import Optional

from koi.utils.connect.base import Target, Transport, TransportError
from koi.utils.connect.ssh import SshTransport
from koi.utils.connect.winrm import WinrmTransport

TRANSPORTS: dict[str, Transport] = {t.name.lower(): t for t in (SshTransport(), WinrmTransport())}


def get_transport(name: str) -> Optional[Transport]:
    return TRANSPORTS.get(name.lower())


__all__ = ["TRANSPORTS", "Target", "Transport", "TransportError", "get_transport"]
