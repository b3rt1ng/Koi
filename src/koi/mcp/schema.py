"""Translate a module's declarative argparse spec into a JSON Schema, and back.

Tools are derived from the class, so a new module becomes callable over MCP the
moment it lands in ``koi/modules/``. Stdlib only: no dependency on ``mcp``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type

_ARRAY_NARGS = ("+", "*")

# argparse `type=` callables we can express in JSON Schema. Anything else is
# passed through as a string and left for argparse to coerce on the way back in.
_SCALAR_TYPES: Dict[Any, str] = {
    int: "integer",
    float: "number",
    str: "string",
}


def _dest(flags: List[str]) -> str:
    """argparse's `dest`: long option over short, dashes to underscores."""
    if not flags:
        raise ValueError("argument spec has no flags")

    if not flags[0].startswith("-"):
        return flags[0].replace("-", "_")

    for flag in flags:
        if flag.startswith("--"):
            return flag[2:].replace("-", "_")
    return flags[0].lstrip("-").replace("-", "_")


def _is_positional(flags: List[str]) -> bool:
    return bool(flags) and not flags[0].startswith("-")


def _primary_flag(flags: List[str]) -> str:
    """The flag to emit on a command line: prefer the long form."""
    for flag in flags:
        if flag.startswith("--"):
            return flag
    return flags[0]


def _scalar_schema(spec: Dict[str, Any]) -> Dict[str, Any]:
    """JSON Schema fragment for a single (non-array) value."""
    if spec.get("action") in ("store_true", "store_false"):
        return {"type": "boolean"}

    schema: Dict[str, Any] = {"type": _SCALAR_TYPES.get(spec.get("type"), "string")}
    if spec.get("choices"):
        schema["enum"] = list(spec["choices"])
    return schema


def argument_schema(spec: Dict[str, Any]) -> Tuple[str, Dict[str, Any], bool]:
    """Convert one ``arguments`` entry to ``(name, schema, required)``."""
    flags = spec.get("flags") or []
    name = _dest(flags)

    nargs = spec.get("nargs")
    if nargs in _ARRAY_NARGS or isinstance(nargs, int) and nargs > 1:
        schema: Dict[str, Any] = {"type": "array", "items": _scalar_schema(spec)}
    else:
        schema = _scalar_schema(spec)

    if spec.get("help"):
        schema["description"] = spec["help"]

    default = spec.get("default")
    if default is not None:
        schema["default"] = default

    # Only a positional with no default is truly required; nargs='*' tolerates empty.
    required = (
        _is_positional(flags)
        and default is None
        and nargs != "*"
    )
    return name, schema, required


def module_input_schema(mod_cls: Type) -> Dict[str, Any]:
    """Build the full JSON Schema for a module's arguments.

    The caller adds the session reference: it belongs to the tool, not the spec.
    """
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for spec in getattr(mod_cls, "arguments", None) or []:
        try:
            name, schema, is_required = argument_schema(spec)
        except ValueError:
            continue
        properties[name] = schema
        if is_required:
            required.append(name)

    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def schema_to_argv(mod_cls: Type, values: Optional[Dict[str, Any]]) -> List[str]:
    """Turn a validated MCP argument dict back into an argparse argv list.

    Optionals go first: a ``nargs='+'`` positional would swallow trailing flags.
    """
    values = values or {}
    optionals: List[str] = []
    positionals: List[str] = []

    for spec in getattr(mod_cls, "arguments", None) or []:
        flags = spec.get("flags") or []
        if not flags:
            continue
        name = _dest(flags)
        if name not in values:
            continue

        value = values[name]
        if value is None:
            continue

        action = spec.get("action")
        if action in ("store_true", "store_false"):
            # Presence is the signal; store_false inverts it.
            wants_flag = bool(value) if action == "store_true" else not bool(value)
            if wants_flag:
                optionals.append(_primary_flag(flags))
            continue

        parts = [str(v) for v in value] if isinstance(value, list) else [str(value)]
        if _is_positional(flags):
            positionals.extend(parts)
        else:
            optionals.append(_primary_flag(flags))
            optionals.extend(parts)

    return optionals + positionals
