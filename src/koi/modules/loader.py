from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Dict, Optional, Type

logger = logging.getLogger("koi.modules.loader")

_cache: Optional[Dict[str, Type]] = None


def _modules_dir() -> Path:
    return Path(__file__).parent


def load_modules(reload: bool = False) -> Dict[str, Type]:
    global _cache
    if _cache is not None and not reload:
        return _cache

    from koi.modules.blueprint import KoiModule

    discovered: Dict[str, Type[KoiModule]] = {}
    pkg_path = str(_modules_dir())

    for finder, mod_name, _ in pkgutil.iter_modules([pkg_path]):
        if mod_name.startswith("_") or mod_name in ("blueprint", "loader"):
            continue

        full_name = f"koi.modules.{mod_name}"
        try:
            if full_name in sys.modules:
                module = importlib.reload(sys.modules[full_name])
            else:
                module = importlib.import_module(full_name)
        except Exception as exc:
            logger.warning(f"Could not import module {full_name!r}: {exc}")
            continue

        for _attr_name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, KoiModule)
                and obj is not KoiModule
                and obj.__module__ == full_name
            ):
                key = obj.name
                if key in discovered:
                    logger.warning(
                        f"Name collision: {full_name!r} and "
                        f"{discovered[key].__module__!r} both claim name {key!r}. "
                        "Keeping first one found."
                    )
                    continue
                discovered[key] = obj
                logger.debug(f"Loaded module {key!r} from {full_name!r}")

    _cache = discovered
    return discovered


def get_module(name: str) -> Optional[Type]:
    return load_modules().get(name)