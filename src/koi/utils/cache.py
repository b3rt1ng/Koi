from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import koi.utils.config as config_module
from koi.utils.config import TIMEOUTS
from koi.utils.ui import notify

_CACHE_DIR = Path.home() / ".koi" / "cache"


def _cache_dir() -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def cache_path(name: str) -> Path:
    """Resolve *name* inside the cache directory.

    Cache keys come from modules, third-party ones included, so a key holding
    ``..`` or an absolute path must not escape ``~/.koi/cache``.
    """
    root = _cache_dir().resolve()
    candidate = (root / name).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Cache key escapes the cache directory: {name!r}")
    return candidate


def put_cache(name: str, data: bytes) -> None:
    path = cache_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def get_cache(name: str) -> bytes | None:
    p = cache_path(name)
    return p.read_bytes() if p.exists() else None


def fetch_or_cache(
    url: str,
    name: str,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    """Download *url* and cache the bytes under *name*.

    Returns ``(data, source)``, *source* being ``"remote"`` or ``"cache"`` when
    the download failed but a copy exists. Re-raises if neither works.
    LOCAL_MODE skips the network entirely.
    """
    if config_module.LOCAL_MODE:
        cached = get_cache(name)
        if cached is not None:
            return cached, "cache"
        raise Exception(f"LOCAL_MODE enabled but cache miss for {name}")

    if timeout is None:
        timeout = TIMEOUTS["http_fetch"]
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Refusing to fetch non-HTTP(S) URL: {url!r}")
    request = urllib.request.Request(url, headers=headers) if headers else url
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = resp.read()
    except Exception:
        cached = get_cache(name)
        if cached is None:
            raise
        return cached, "cache"
    put_cache(name, data)
    return data, "remote"


def purge_cache() -> bool:
    try:
        for file in _cache_dir().rglob("*"):
            if file.is_file():
                notify('info', f"Removing cache file: {file.name}")
                file.unlink()
        return True
    except Exception as e:
        notify('error', f"Error purging cache: {e}")
        return False
        
