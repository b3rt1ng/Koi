from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path

_CONFIG_PATH = Path.home() / ".koi" / "config.json"

DEFAULTS = {
    "host": "0.0.0.0",
    "port": 4010,

    "display_art": True,

    "logging":      True,
    "keep_history": False,
    "local_mode":   False,

    "colors": {
        "pumpkin": [248, 101, 70],
        "white":   [255, 255, 255],
        "silver":  [169, 169, 169],
        "coral":   [235, 111, 92],
        "umber":   [123, 62, 0],
        "blue":    [118, 241, 245],
    },

    "timeouts": {
        "exec_command":   30,
        "exec_query":     10,
        "upload":         30,
        "download":       300,
        "http_fetch":     60,
        "session_detect": 4.0,
    },

    "sidetcps": [5985, 5986, 445, 3389],

    "mcp_activate":   False,
    "mcp_exec_allow": False,
    "mcp_port":       7331,
    "mcp_token":      None,
}


def _deep_merge(defaults: dict, overrides: dict) -> dict:
    merged = dict(defaults)
    for key, value in overrides.items():
        default_value = merged.get(key)
        if isinstance(default_value, dict):
            if isinstance(value, dict):
                merged[key] = _deep_merge(default_value, value)
        else:
            merged[key] = value
    return merged


def _coerce(cfg: dict) -> dict:
    """Repair values whose type would crash a consumer that reads them raw."""
    st = cfg.get("sidetcps")
    if not isinstance(st, list) or not all(
        isinstance(x, int) and not isinstance(x, bool) for x in st
    ):
        cfg["sidetcps"] = list(DEFAULTS["sidetcps"])

    to = cfg.get("timeouts")
    if isinstance(to, dict):
        for k, dv in DEFAULTS["timeouts"].items():
            v = to.get(k, dv)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                to[k] = dv
    else:
        cfg["timeouts"] = dict(DEFAULTS["timeouts"])

    for k in ("port", "mcp_port"):
        v = cfg.get(k)
        if isinstance(v, bool) or not isinstance(v, int):
            try:
                cfg[k] = int(v)
            except (TypeError, ValueError):
                cfg[k] = DEFAULTS[k]
    return cfg


def _load() -> dict:
    if _CONFIG_PATH.exists():
        try:
            data = json.loads(_CONFIG_PATH.read_text())
            if isinstance(data, dict):
                return _coerce(_deep_merge(DEFAULTS, data))
        except (json.JSONDecodeError, OSError):
            pass
        return copy.deepcopy(DEFAULTS)

    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(json.dumps(DEFAULTS, indent=4) + "\n")
    except OSError:
        pass
    return copy.deepcopy(DEFAULTS)


def persist(key: str, value) -> bool:
    """Re-reads first so a concurrent edit is kept; 0600 because the config holds the MCP token."""
    try:
        data = {}
        if _CONFIG_PATH.exists():
            try:
                loaded = json.loads(_CONFIG_PATH.read_text())
                if isinstance(loaded, dict):
                    data = loaded
                else:
                    try:
                        _CONFIG_PATH.replace(_CONFIG_PATH.with_name(_CONFIG_PATH.name + ".bak"))
                    except OSError:
                        pass
            except json.JSONDecodeError:
                try:
                    _CONFIG_PATH.replace(_CONFIG_PATH.with_name(_CONFIG_PATH.name + ".bak"))
                except OSError:
                    pass
        data[key] = value
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(_CONFIG_PATH.parent), prefix=".config.", suffix=".tmp")
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=4) + "\n")
            os.replace(tmp, _CONFIG_PATH)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        CONFIG[key] = value
        return True
    except OSError:
        return False


CONFIG   = _load()
COLORS   = CONFIG["colors"]
TIMEOUTS = CONFIG["timeouts"]
SIDETCPS = CONFIG.get("sidetcps", DEFAULTS["sidetcps"])

LOCAL_MODE = False


def color(name: str) -> tuple[int, int, int]:
    value = COLORS.get(name, DEFAULTS["colors"][name])
    try:
        r, g, b = value
        return (int(r), int(g), int(b))
    except (TypeError, ValueError):
        r, g, b = DEFAULTS["colors"][name]
        return (r, g, b)


def timeout(name: str) -> float:
    value = TIMEOUTS.get(name, DEFAULTS["timeouts"][name])
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(DEFAULTS["timeouts"][name])
