"""Re-export full VBA builder (+ thin helpers used by workflows)."""

from __future__ import annotations

from cst_mcp.vba_builder import (  # noqa: F401
    VBABuilder,
    VBAScript,
    component_name_pair,
    solid_ref,
)
from cst_mcp.vba_builder import _escape_vba_string as vba_str  # type: ignore
from cst_mcp.vba_builder import _format_number as fmt_num  # type: ignore

__all__ = [
    "VBABuilder",
    "VBAScript",
    "component_name_pair",
    "fmt_num",
    "solid_ref",
    "vba_str",
]
