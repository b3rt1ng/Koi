from __future__ import annotations

from typing import Optional

from koi.utils.connect.base import Target, Transport
from koi.utils.connect.ssh import SshTransport

TRANSPORTS: dict[str, Transport] = {t.name.lower(): t for t in (SshTransport(),)}


def get_transport(name: str) -> Optional[Transport]:
    return TRANSPORTS.get(name.lower())


__all__ = ["TRANSPORTS", "Target", "Transport", "get_transport"]
