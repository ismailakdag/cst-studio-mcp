"""Boolean operation tools for CST Studio solids.

Provides Add, Subtract, Intersect, and Insert operations on solid pairs.
Boolean ops use direct ``Solid.<Op>`` VBA calls (no With blocks).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.types import TextContent, Tool

from cst_mcp.validators import validate_component_path
from cst_mcp.vba_builder import VBABuilder

if TYPE_CHECKING:
    from mcp.server import Server

    from cst_mcp.cst_client import CSTClient

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

_SOLID_SCHEMA = {
    "type": "string",
    "description": 'Solid reference in "Component:Solid" format',
}


def _boolean_input_schema(desc1: str, desc2: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "solid1": {**_SOLID_SCHEMA, "description": desc1},
            "solid2": {**_SOLID_SCHEMA, "description": desc2},
        },
        "required": ["solid1", "solid2"],
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="cst_boolean_add",
        description=(
            "Unite/add two solids together. The result replaces solid1 with the "
            "combined volume of both shapes."
        ),
        inputSchema=_boolean_input_schema(
            'First solid (result kept here) in "Component:Solid" format',
            'Second solid (merged into first) in "Component:Solid" format',
        ),
    ),
    Tool(
        name="cst_boolean_subtract",
        description=(
            "Subtract solid2 from solid1. The overlapping volume of solid2 is "
            "removed from solid1. Solid2 is deleted."
        ),
        inputSchema=_boolean_input_schema(
            'Solid to subtract from in "Component:Solid" format',
            'Solid to subtract (removed) in "Component:Solid" format',
        ),
    ),
    Tool(
        name="cst_boolean_intersect",
        description=(
            "Intersect two solids. Only the overlapping volume is kept, "
            "replacing solid1. Solid2 is deleted."
        ),
        inputSchema=_boolean_input_schema(
            'First solid in "Component:Solid" format',
            'Second solid in "Component:Solid" format',
        ),
    ),
    Tool(
        name="cst_boolean_insert",
        description=(
            "Insert solid2 into solid1. Solid2 is embedded within solid1, "
            "maintaining both material regions at the overlap."
        ),
        inputSchema=_boolean_input_schema(
            'Host solid in "Component:Solid" format',
            'Solid to insert in "Component:Solid" format',
        ),
    ),
]

# Maps tool name → CST VBA Solid method name
_OPERATION_MAP: dict[str, str] = {
    "cst_boolean_add": "Add",
    "cst_boolean_subtract": "Subtract",
    "cst_boolean_intersect": "Intersect",
    "cst_boolean_insert": "Insert",
}

_TOOL_NAMES: set[str] = set(_OPERATION_MAP)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a boolean operation tool call."""
    try:
        operation = _OPERATION_MAP.get(name)
        if operation is None:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown boolean tool: {name}"}),
                )
            ]

        solid1: str = arguments.get("solid1", "")
        solid2: str = arguments.get("solid2", "")

        # Validate both solid references (raises ValidationError on bad input)
        validate_component_path(solid1)
        validate_component_path(solid2)

        # Boolean ops use direct Solid.<Op> calls — no With block needed
        vba = VBABuilder("Solid")
        vba.raw_line(f'Solid.{operation} "{solid1}", "{solid2}"')
        script = vba.build()

        result = client.execute_vba(script)
        result["operation"] = operation.lower()
        result["solid1"] = solid1
        result["solid2"] = solid2

        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


# ---------------------------------------------------------------------------
# Registration helper (called from tools/__init__.py)
# ---------------------------------------------------------------------------


def register_boolean_tools(server: Server, client: CSTClient) -> None:
    """Register boolean tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
