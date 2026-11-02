from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import logging
import os
import pkgutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Type

logger = logging.getLogger("koi.modules.loader")

_cache: Optional[Dict[str, Type]] = None

_MODULES_JSON = Path.home() / ".koi" / "modules.json"


def _modules_dir() -> Path:
    return Path(__file__).parent


def _read_external_paths() -> list[str]:
    try:
        data = json.loads(_MODULES_JSON.read_text())
        if isinstance(data, list):
            return [p for p in data if isinstance(p, str)]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _write_external_paths(paths: list[str]) -> None:
    _MODULES_JSON.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(_MODULES_JSON.parent), prefix=".modules.", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(paths, indent=2) + "\n")
        os.replace(tmp, _MODULES_JSON)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ext_mod_id(filepath: str) -> str:
    return f"_koi_ext.{Path(filepath).resolve()}"


def _load_external_file(filepath: str, koi_module_cls: type) -> Optional[type]:
    mod_id = _ext_mod_id(filepath)
    spec = importlib.util.spec_from_file_location(mod_id, filepath)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_id, None)
        raise
    sys.modules[mod_id] = module
    for _attr, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, koi_module_cls)
            and obj is not koi_module_cls
            and obj.__module__ == mod_id
        ):
            return obj
    return None


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

    builtin_names = set(discovered)

    external_paths = _read_external_paths()
    dead: list[str] = []
    for filepath in external_paths:
        if not Path(filepath).is_file():
            dead.append(filepath)
            continue
        try:
            cls = _load_external_file(filepath, KoiModule)
        except Exception as exc:
            logger.warning(f"Could not load external module {filepath!r}: {exc}")
            continue
        if cls is None:
            logger.warning(f"No KoiModule subclass found in {filepath!r}")
            continue
        key = cls.name
        if key in builtin_names:
            logger.warning(f"External {filepath!r} name {key!r} collides with built-in, skipped.")
            continue
        if key in discovered:
            logger.warning(f"External {filepath!r} name {key!r} already loaded, skipped.")
            continue
        discovered[key] = cls
        logger.debug(f"Loaded external module {key!r} from {filepath!r}")

    if dead:
        _write_external_paths([p for p in external_paths if p not in dead])

    _cache = discovered
    return discovered


def import_module(path: str) -> tuple[bool, str]:
    resolved = str(Path(path).resolve())
    if not resolved.endswith(".py"):
        return False, "File must be a .py file."
    if not Path(resolved).is_file():
        return False, f"File not found: {resolved}"

    try:
        source = Path(resolved).read_text()
        compile(source, resolved, "exec")
    except SyntaxError as exc:
        return False, f"Syntax error: {exc}"

    from koi.modules.blueprint import KoiModule
    try:
        cls = _load_external_file(resolved, KoiModule)
    except Exception as exc:
        return False, f"Import failed: {exc}"
    if cls is None:
        return False, "No KoiModule subclass found in file."

    name = cls.name
    if not name:
        return False, "Module has no name attribute."

    current = load_modules()
    existing = current.get(name)
    if existing:
        if existing.__module__.startswith("koi.modules."):
            return False, f"Name {name!r} collides with built-in module."
        ext_path = existing.__module__.removeprefix("_koi_ext.")
        if ext_path != resolved:
            return False, f"Name {name!r} already taken by {ext_path}."

    paths = _read_external_paths()
    if resolved not in paths:
        paths.append(resolved)
        _write_external_paths(paths)

    load_modules(reload=True)
    return True, name


def unimport_module(name: str) -> tuple[bool, str]:
    current = load_modules()
    cls = current.get(name)
    if cls is None:
        return False, f"No module named {name!r}."
    if cls.__module__.startswith("koi.modules."):
        return False, f"{name!r} is a built-in module."

    paths = _read_external_paths()
    ext_path = cls.__module__.removeprefix("_koi_ext.")
    remaining = [p for p in paths if str(Path(p).resolve()) != ext_path]
    if len(remaining) == len(paths):
        return False, f"Could not find {name!r} in external modules registry."
    _write_external_paths(remaining)
    load_modules(reload=True)
    return True, name


def get_module(name: str) -> Optional[Type]:
    return load_modules().get(name)


def collect_external_resources() -> list[dict]:
    """Collect the external resources every loaded module wants pre-cached.

    Goes through ``resolve_external_resources()`` so a module can compute its
    list dynamically. A failing resolver is skipped with a warning rather than
    aborting the whole ``--local-prepare`` run.
    """
    resources = []
    for mod_cls in load_modules().values():
        try:
            module_resources = mod_cls.resolve_external_resources()
        except Exception as exc:
            logger.warning(
                f"Could not resolve external resources for {mod_cls.__name__!r}: {exc}"
            )
            continue
        if module_resources:
            resources.extend(module_resources)
    return resources