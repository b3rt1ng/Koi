from __future__ import annotations

from pathlib import Path

_CACHE_DIR = Path.home() / ".koi" / "cache"
_CONPTY_FILENAME = "Invoke-ConPtyShell.ps1"


def cache_dir() -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def conpty_cache_path() -> Path:
    return cache_dir() / _CONPTY_FILENAME


def save_conptyshell(data: bytes) -> None:
    """Persist a fresh copy of ConPtyShell to the local cache."""
    conpty_cache_path().write_bytes(data)


def load_conptyshell() -> bytes | None:
    """Return the cached ConPtyShell bytes, or None if no cache exists."""
    p = conpty_cache_path()
    if p.exists():
        return p.read_bytes()
    return None


def cache_exists() -> bool:
    return conpty_cache_path().exists()