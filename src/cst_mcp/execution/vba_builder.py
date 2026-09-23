"""Re-export full VBA builder (+ thin helpers used by workflows)."""

from __future__ import annotations

from cst_mcp.vba_builder import (
    VBABuilder,
    VBAScript,
    component_name_pair,
    solid_ref,
)
from cst_mcp.vba_builder import _escape_vba_string as _legacy_escape  # type: ignore
from cst_mcp.vba_builder import _format_number as fmt_num  # type: ignore
from cst_mcp.vba_safety import vba_escape


def vba_str(value: str) -> str:
    """Escape *value* for a VBA string literal body.

    Rejects line breaks / NUL (which would end the literal and start a new
    statement) before applying the legacy quote-doubling + pattern check.
    """
    vba_escape(value)
    return _legacy_escape(value)


__all__ = [
    "VBABuilder",
    "VBAScript",
    "component_name_pair",
    "fmt_num",
    "solid_ref",
    "vba_str",
]
