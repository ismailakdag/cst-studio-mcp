"""Safe VBA code generation using builder pattern.

All VBA code destined for CST Studio is generated through this module.
Direct string interpolation of user input into VBA is forbidden — use
VBABuilder methods which handle escaping and validation.
"""

from __future__ import annotations

import re

from cst_mcp.validators import validate_name, validate_vba_input

_DANGEROUS_IN_STRINGS = re.compile(
    r'"\s*[&+]\s*(Shell|CreateObject|GetObject)', re.IGNORECASE
)


def _escape_vba_string(value: str) -> str:
    """Escape a string for safe embedding in VBA."""
    escaped = value.replace('"', '""')
    # Block VBA string concatenation injection attempts
    if _DANGEROUS_IN_STRINGS.search(f'"{escaped}"'):
        raise ValueError(f"Potentially dangerous pattern in VBA string value: {value!r}")
    return escaped


def _format_number(value: float) -> str:
    """Format a number for VBA, avoiding scientific notation for small values."""
    import math

    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"Cannot format {value} for VBA: must be a finite number")
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


class VBABuilder:
    """Builder for constructing safe VBA code blocks.

    Usage::

        vba = (VBABuilder("Brick")
            .set("Name", "MyBrick")
            .set("Component", "Antenna")
            .set_double("Xrange", -10, 10)
            .call("Create"))
        script = vba.build()
    """

    def __init__(self, obj_name: str) -> None:
        self._obj_name = obj_name
        self._lines: list[str] = []
        self._with_block: list[str] = []

    def reset(self) -> VBABuilder:
        """Clear the builder and start a new object."""
        self._lines = []
        self._with_block = []
        return self

    def raw_line(self, line: str) -> VBABuilder:
        """Add a raw VBA line (validated for safety)."""
        validate_vba_input(line)
        self._lines.append(line)
        return self

    def set(self, prop: str, value: str) -> VBABuilder:
        """Set a string property: .Name "value" """
        safe_value = _escape_vba_string(value)
        self._with_block.append(f'.{prop} "{safe_value}"')
        return self

    def set_number(self, prop: str, value: float) -> VBABuilder:
        """Set a numeric property: .Prop "value" (as string, CST convention)."""
        self._with_block.append(f'.{prop} "{_format_number(value)}"')
        return self

    def set_double(self, prop: str, v1: float, v2: float) -> VBABuilder:
        """Set a double-value property: .Prop "v1", "v2" """
        self._with_block.append(f'.{prop} "{_format_number(v1)}", "{_format_number(v2)}"')
        return self

    def set_triple(self, prop: str, v1: float, v2: float, v3: float) -> VBABuilder:
        """Set a triple-value property: .Prop "v1", "v2", "v3" """
        self._with_block.append(
            f'.{prop} "{_format_number(v1)}", "{_format_number(v2)}", "{_format_number(v3)}"'
        )
        return self

    def set_bool(self, prop: str, value: bool) -> VBABuilder:
        """Set a boolean property: .Prop "True"/"False" """
        self._with_block.append(f'.{prop} "{value}"')
        return self

    def set_raw(self, prop: str, raw_value: str) -> VBABuilder:
        """Set a property with a raw value (no quotes): .Prop value"""
        validate_vba_input(raw_value)
        self._with_block.append(f".{prop} {raw_value}")
        return self

    def call(self, method: str) -> VBABuilder:
        """Call a method: .Method"""
        self._with_block.append(f".{method}")
        return self

    def call_with_args(self, method: str, *args: str) -> VBABuilder:
        """Call a method with arguments: .Method arg1, arg2"""
        validate_vba_input(method)
        arg_str = ", ".join(f'"{_escape_vba_string(a)}"' for a in args)
        self._with_block.append(f".{method} {arg_str}")
        return self

    def build(self) -> str:
        """Build the complete VBA script."""
        lines = list(self._lines)

        if self._with_block:
            lines.append(f"With {self._obj_name}")
            for stmt in self._with_block:
                lines.append(f"  {stmt}")
            lines.append("End With")

        return "\n".join(lines)


class VBAScript:
    """Compose multiple VBABuilder blocks into a complete script."""

    def __init__(self) -> None:
        self._blocks: list[str] = []

    def add_block(self, builder: VBABuilder) -> VBAScript:
        self._blocks.append(builder.build())
        return self

    def add_raw(self, code: str) -> VBAScript:
        validate_vba_input(code)
        self._blocks.append(code)
        return self

    def add_comment(self, comment: str) -> VBAScript:
        safe = _escape_vba_string(comment)
        self._blocks.append(f"' {safe}")
        return self

    def add_blank(self) -> VBAScript:
        self._blocks.append("")
        return self

    def build(self) -> str:
        return "\n\n".join(self._blocks)


def component_name_pair(component: str, solid: str) -> tuple[str, str]:
    """Validate and return a component:solid pair."""
    validate_name(component, "component")
    validate_name(solid, "solid")
    return component, solid


def solid_ref(component: str, solid: str) -> str:
    """Build a CST solid reference string: 'component:solid'."""
    validate_name(component, "component")
    validate_name(solid, "solid")
    return f"{component}:{solid}"
