from __future__ import annotations

from pathlib import Path
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

def purge_cache() -> None:
    try:
        for file in _cache_dir().glob("*"):
            notify('info', f"Removing cache file: {file.name}")
            if file.is_file():
                file.unlink()
        return True
    except Exception as e:
        notify('error', f"Error purging cache: {e}")
        return False
        
