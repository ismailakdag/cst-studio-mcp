"""Helpers for embedding caller-supplied values into generated VBA safely.

Every tool that builds VBA text from MCP arguments and runs it through
``execute_vba`` / ``add_to_history`` bypasses the ``CST_ALLOW_RAW_VBA`` gate,
so each interpolated value must be unable to terminate its string literal or
start a new statement:

* strings go through :func:`vba_string_literal` / :func:`vba_escape`, which
  double embedded ``"`` (the only VBA string escape) and reject line breaks
  and NUL (a VBA string literal cannot span lines, so a newline would end the
  statement and start attacker-controlled code);
* numbers go through :func:`vba_number` / :func:`vba_int`, which coerce with
  ``float()`` / ``int()`` so a string such as ``"1 : RunAndWait ..."`` in a
  numeric slot is rejected instead of pasted verbatim.
"""

from __future__ import annotations

import math
from typing import Any

# Characters that end a VBA logical line (or confuse the COM string marshaller).
_FORBIDDEN_CHARS = {
    "\r": "carriage return",
    "\n": "line feed",
    "\x00": "NUL",
    chr(0x2028): "line separator",
    chr(0x2029): "paragraph separator",
    "\x0b": "vertical tab",
    "\x0c": "form feed",
    "\x85": "next line",
}


def vba_escape(value: Any, field: str = "value") -> str:
    """Return *value* escaped for use between VBA double quotes (no quotes added).

    Raises ``ValueError`` for non-string input or line-breaking characters.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {type(value).__name__}")  # noqa: TRY004 - callers catch ValueError
    for ch, label in _FORBIDDEN_CHARS.items():
        if ch in value:
            raise ValueError(f"{field} must not contain a {label} character")
    return value.replace('"', '""')


def vba_string_literal(value: Any, field: str = "value") -> str:
    """Return a complete, quoted VBA string literal for *value*."""
    return '"' + vba_escape(value, field) + '"'


def validate_tree_path(value: Any, field: str = "tree_path") -> str:
    """Validate a CST navigation-tree path (e.g. ``1D Results\\S-Parameters\\S1,1``).

    Returns the escaped path body (quotes doubled) ready for ``"...``" embedding.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > 1024:
        raise ValueError(f"{field} is too long (max 1024 characters)")
    return vba_escape(value, field)


def validate_file_path(value: Any, field: str = "file_path") -> str:
    """Validate a filesystem path destined for a VBA string literal.

    Returns the escaped path body (quotes doubled). ``"`` is never legal in a
    Windows path, so it is rejected outright rather than escaped.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > 4096:
        raise ValueError(f"{field} is too long (max 4096 characters)")
    if '"' in value:
        raise ValueError(f"{field} must not contain a double quote")
    return vba_escape(value, field)


def vba_number(value: Any, field: str = "value") -> str:
    """Coerce *value* to a finite float and format it for VBA source."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number, not a boolean")  # noqa: TRY004
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number, got {value!r}") from None
    if math.isnan(num) or math.isinf(num):
        raise ValueError(f"{field} must be a finite number")
    if num == int(num) and abs(num) < 1e15:
        return str(int(num))
    return repr(num)


def vba_int(value: Any, field: str = "value") -> int:
    """Coerce *value* to an ``int`` (rejecting non-integral numbers and strings)."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer, not a boolean")  # noqa: TRY004
    if isinstance(value, int):
        return value
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer, got {value!r}") from None
    if not math.isfinite(num) or num != int(num):
        raise ValueError(f"{field} must be an integer, got {value!r}")
    return int(num)


def vba_bool(value: Any) -> str:
    """Return ``True`` / ``False`` for VBA source."""
    return "True" if bool(value) else "False"


# ---------------------------------------------------------------------------
# Handler-level guard: schema-driven type checks + line-break rejection
# ---------------------------------------------------------------------------

_NUMERIC_TYPES = {"number", "integer"}


def _schema_types(schema: Any) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    t = schema.get("type")
    if isinstance(t, str):
        return {t}
    if isinstance(t, list):
        return {x for x in t if isinstance(x, str)}
    return set()


def _check_value(value: Any, schema: Any, path: str, allow_multiline: frozenset[str]) -> None:
    types = _schema_types(schema)
    if types and types <= _NUMERIC_TYPES | {"null"} and value is not None:
        # A numeric slot must hold a real number: a string like
        # "1 : RunAndWait ..." would otherwise be pasted into VBA verbatim.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path} must be a number, got {type(value).__name__}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{path} must be a finite number")
        if types == {"integer"} and isinstance(value, float) and value != int(value):
            raise ValueError(f"{path} must be an integer")
        return
    if isinstance(value, str):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if leaf not in allow_multiline:
            vba_escape(value, path)
        return
    if isinstance(value, dict):
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        extra = schema.get("additionalProperties") if isinstance(schema, dict) else None
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            vba_escape(key, f"{path}.{key}" if path else key)
            sub = props.get(key, extra if isinstance(extra, dict) else None)
            _check_value(item, sub, f"{path}.{key}" if path else key, allow_multiline)
        return
    if isinstance(value, (list, tuple)):
        items = schema.get("items") if isinstance(schema, dict) else None
        for i, item in enumerate(value):
            _check_value(item, items, f"{path}[{i}]", allow_multiline)


def check_arguments(
    tools: Any,
    name: str,
    arguments: Any,
    allow_multiline: frozenset[str] = frozenset(),
) -> None:
    """Validate *arguments* of tool *name* before any VBA is generated.

    * every string (at any depth) must be free of line breaks / NUL, except
      top-level-or-nested fields whose key is in *allow_multiline*;
    * every value whose schema type is only ``number`` / ``integer`` must be an
      actual JSON number (strings are rejected even when numeric-looking).

    Raises ``ValueError`` with a caller-facing message.
    """
    if not isinstance(arguments, dict):
        return
    schema: Any = None
    for tool in tools or ():
        if getattr(tool, "name", None) == name:
            schema = getattr(tool, "inputSchema", None)
            break
    _check_value(arguments, schema or {}, "", allow_multiline)


def guard_handler(tools: Any, handler: Any, allow_multiline: frozenset[str] = frozenset()) -> Any:
    """Wrap an async tool ``handle(name, arguments, client)`` with :func:`check_arguments`.

    Rejected calls return the standard ``{"status": "error"}`` JSON envelope so
    the registry reports them as ``isError`` results.
    """
    import functools
    import json

    from mcp.types import TextContent

    @functools.wraps(handler)
    async def guarded(name: str, arguments: Any, client: Any, *a: Any, **kw: Any) -> Any:
        try:
            check_arguments(tools, name, arguments, allow_multiline)
        except ValueError as exc:
            body = {"status": "error", "tool": name, "message": f"Invalid argument: {exc}"}
            return [TextContent(type="text", text=json.dumps(body, indent=2))]
        return await handler(name, arguments, client, *a, **kw)

    guarded.__wrapped_unguarded__ = handler  # type: ignore[attr-defined]
    return guarded


__all__ = [
    "check_arguments",
    "guard_handler",
    "validate_file_path",
    "validate_tree_path",
    "vba_bool",
    "vba_escape",
    "vba_int",
    "vba_number",
    "vba_string_literal",
]
