from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path.home() / ".koi" / "config.json"

DEFAULTS = {
    "host": "0.0.0.0",
    "port": 4010,

    "display_art": True,

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
}


def _deep_merge(defaults: dict, overrides: dict) -> dict:
    merged = dict(defaults)
    for key, value in overrides.items():
        default_value = merged.get(key)
        if isinstance(default_value, dict):
            if isinstance(value, dict):
                merged[key] = _deep_merge(default_value, value)
            # else: malformed override for a dict-shaped default, keep the default
        else:
            merged[key] = value
    return merged


def _load() -> dict:
    if _CONFIG_PATH.exists():
        try:
            data = json.loads(_CONFIG_PATH.read_text())
            if isinstance(data, dict):
                return _deep_merge(DEFAULTS, data)
        except (json.JSONDecodeError, OSError):
            pass
        return dict(DEFAULTS)

    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(json.dumps(DEFAULTS, indent=4) + "\n")
    except OSError:
        pass
    return dict(DEFAULTS)


CONFIG   = _load()
COLORS   = CONFIG["colors"]
TIMEOUTS = CONFIG["timeouts"]
SIDETCPS = CONFIG.get("sidetcps", DEFAULTS["sidetcps"])


def color(name: str) -> tuple[int, int, int]:
    """Return an RGB tuple for `name`, falling back to the built-in default on bad config."""
    value = COLORS.get(name, DEFAULTS["colors"][name])
    try:
        r, g, b = value
        return (int(r), int(g), int(b))
    except (TypeError, ValueError):
        r, g, b = DEFAULTS["colors"][name]
        return (r, g, b)


def timeout(name: str) -> float:
    """Return a timeout in seconds for `name`, falling back to the built-in default on bad config."""
    value = TIMEOUTS.get(name, DEFAULTS["timeouts"][name])
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(DEFAULTS["timeouts"][name])
