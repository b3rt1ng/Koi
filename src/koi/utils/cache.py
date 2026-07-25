from __future__ import annotations

import urllib.request
from pathlib import Path

from koi.utils.config import TIMEOUTS
from koi.utils.ui import notify

_CACHE_DIR = Path.home() / ".koi" / "cache"


def _cache_dir() -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def cache_path(name: str) -> Path:
    return _cache_dir() / name


def put_cache(name: str, data: bytes) -> None:
    cache_path(name).write_bytes(data)


def get_cache(name: str) -> bytes | None:
    p = cache_path(name)
    return p.read_bytes() if p.exists() else None


def has_cache(name: str) -> bool:
    return cache_path(name).exists()


def fetch_or_cache(
    url: str,
    name: str,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    """Download *url* and cache the response bytes under *name*.

    Returns ``(data, source)`` where *source* is ``"remote"`` when the download
    succeeds (the bytes are also written to the cache) or ``"cache"`` when the
    download fails but a previously cached copy exists. If the download fails
    and nothing is cached, the original download error is re-raised.
    """
    if timeout is None:
        timeout = TIMEOUTS["http_fetch"]
    request = urllib.request.Request(url, headers=headers) if headers else url
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = resp.read()
        put_cache(name, data)
        return data, "remote"
    except Exception:
        cached = get_cache(name)
        if cached is None:
            raise
        return cached, "cache"


def purge_cache() -> None:
    try:
        for file in _cache_dir().glob("*"):
            if file.is_file():
                notify('info', f"Removing cache file: {file.name}")
                file.unlink()
    except Exception as e:
        notify('error', f"Error purging cache: {e}")
        
