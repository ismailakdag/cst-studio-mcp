"""Transform tools for CST Studio solids.

Provides Translate, Rotate, Mirror, and Scale operations.  Each builds a
``With Transform … End With`` VBA block.
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

_COPY_SCHEMA = {
    "type": "boolean",
    "description": "If true, create a copy instead of moving the original",
    "default": False,
}

_CENTER_SCHEMAS = {
    "center_x": {
        "type": "number",
        "description": "X coordinate of the transform center",
        "default": 0,
    },
    "center_y": {
        "type": "number",
        "description": "Y coordinate of the transform center",
        "default": 0,
    },
    "center_z": {
        "type": "number",
        "description": "Z coordinate of the transform center",
        "default": 0,
    },
}

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="cst_transform_translate",
        description=(
            "Translate (move) a solid by a displacement vector (dx, dy, dz). "
            "Optionally create a translated copy."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "solid": _SOLID_SCHEMA,
                "dx": {
                    "type": "number",
                    "description": "Translation distance along X axis",
                },
                "dy": {
                    "type": "number",
                    "description": "Translation distance along Y axis",
                },
                "dz": {
                    "type": "number",
                    "description": "Translation distance along Z axis",
                },
                "copy": _COPY_SCHEMA,
            },
            "required": ["solid", "dx", "dy", "dz"],
        },
    ),
    Tool(
        name="cst_transform_rotate",
        description=(
            "Rotate a solid by a given angle around an axis (x, y, or z). "
            "An optional center point can be specified."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "solid": _SOLID_SCHEMA,
                "angle": {
                    "type": "number",
                    "description": "Rotation angle in degrees",
                },
                "axis": {
                    "type": "string",
                    "enum": ["x", "y", "z"],
                    "description": "Rotation axis",
                },
                **_CENTER_SCHEMAS,
                "copy": _COPY_SCHEMA,
            },
            "required": ["solid", "angle", "axis"],
        },
    ),
    Tool(
        name="cst_transform_mirror",
        description=(
            "Mirror a solid across a plane (xy, xz, or yz). "
            "An optional center point can be specified."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "solid": _SOLID_SCHEMA,
                "plane": {
                    "type": "string",
                    "enum": ["xy", "xz", "yz"],
                    "description": "Mirror plane",
                },
                **_CENTER_SCHEMAS,
                "copy": _COPY_SCHEMA,
            },
            "required": ["solid", "plane"],
        },
    ),
    Tool(
        name="cst_transform_scale",
        description=(
            "Scale a solid by independent factors along each axis. "
            "An optional center point can be specified."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "solid": _SOLID_SCHEMA,
                "scale_x": {
                    "type": "number",
                    "description": "Scale factor along X axis",
                    "default": 1.0,
                },
                "scale_y": {
                    "type": "number",
                    "description": "Scale factor along Y axis",
                    "default": 1.0,
                },
                "scale_z": {
                    "type": "number",
                    "description": "Scale factor along Z axis",
                    "default": 1.0,
                },
                **_CENTER_SCHEMAS,
                "copy": _COPY_SCHEMA,
            },
            "required": ["solid"],
        },
    ),
]

_TOOL_NAMES: set[str] = {t.name for t in TOOLS}

# ---------------------------------------------------------------------------
# VBA generators for each transform type
# ---------------------------------------------------------------------------


def _bool_str(value: bool) -> str:
    """Return CST-style boolean string."""
    return "True" if value else "False"


def _build_translate(args: dict) -> str:
    solid = args["solid"]
    dx = args.get("dx", 0)
    dy = args.get("dy", 0)
    dz = args.get("dz", 0)
    copy = args.get("copy", False)

    validate_component_path(solid)

    # Official Transform API: .Vector u,v,w + .MultipleObjects + .Transform "Shape","Translate"
    vba = (
        VBABuilder("Transform")
        .call("Reset")
        .set("Name", solid)
        .set_triple("Vector", dx, dy, dz)
        .set("MultipleObjects", _bool_str(copy))
        .set("GroupObjects", "False")
        .set("Repetitions", "1")
        .call_with_args("Transform", "Shape", "Translate")
    )
    return vba.build()


def _build_rotate(args: dict) -> str:
    solid = args["solid"]
    angle = args["angle"]
    axis = args["axis"].lower()
    cx = args.get("center_x", 0)
    cy = args.get("center_y", 0)
    cz = args.get("center_z", 0)
    copy = args.get("copy", False)

    validate_component_path(solid)
    if axis not in ("x", "y", "z"):
        raise ValueError(f"axis must be 'x', 'y', or 'z', got '{axis}'")

    ax = float(angle) if axis == "x" else 0.0
    ay = float(angle) if axis == "y" else 0.0
    az = float(angle) if axis == "z" else 0.0

    # Official: Origin enum, Center triple, Angle triple (no spaces in property names)
    vba = (
        VBABuilder("Transform")
        .call("Reset")
        .set("Name", solid)
        .set("Origin", "Free")
        .set_triple("Center", cx, cy, cz)
        .set_triple("Angle", ax, ay, az)
        .set("MultipleObjects", _bool_str(copy))
        .set("GroupObjects", "False")
        .set("Repetitions", "1")
        .call_with_args("Transform", "Shape", "Rotate")
    )
    return vba.build()


def _build_mirror(args: dict) -> str:
    solid = args["solid"]
    plane = args["plane"].lower()
    cx = args.get("center_x", 0)
    cy = args.get("center_y", 0)
    cz = args.get("center_z", 0)
    copy = args.get("copy", False)

    validate_component_path(solid)
    if plane not in ("xy", "xz", "yz"):
        raise ValueError(f"plane must be 'xy', 'xz', or 'yz', got '{plane}'")

    # Mirror plane normal vector (official PlaneNormal u,v,w)
    normals = {"xy": (0.0, 0.0, 1.0), "xz": (0.0, 1.0, 0.0), "yz": (1.0, 0.0, 0.0)}
    nx, ny, nz = normals[plane]

    vba = (
        VBABuilder("Transform")
        .call("Reset")
        .set("Name", solid)
        .set("Origin", "Free")
        .set_triple("Center", cx, cy, cz)
        .set_triple("PlaneNormal", nx, ny, nz)
        .set("MultipleObjects", _bool_str(copy))
        .set("GroupObjects", "False")
        .set("Repetitions", "1")
        .call_with_args("Transform", "Shape", "Mirror")
    )
    return vba.build()


def _build_scale(args: dict) -> str:
    solid = args["solid"]
    sx = args.get("scale_x", 1.0)
    sy = args.get("scale_y", 1.0)
    sz = args.get("scale_z", 1.0)
    cx = args.get("center_x", 0)
    cy = args.get("center_y", 0)
    cz = args.get("center_z", 0)
    copy = args.get("copy", False)

    validate_component_path(solid)

    vba = (
        VBABuilder("Transform")
        .call("Reset")
        .set("Name", solid)
        .set("Origin", "Free")
        .set_triple("Center", cx, cy, cz)
        .set_triple("ScaleFactor", sx, sy, sz)
        .set("MultipleObjects", _bool_str(copy))
        .set("GroupObjects", "False")
        .set("Repetitions", "1")
        .call_with_args("Transform", "Shape", "Scale")
    )
    return vba.build()


_BUILDERS = {
    "cst_transform_translate": _build_translate,
    "cst_transform_rotate": _build_rotate,
    "cst_transform_mirror": _build_mirror,
    "cst_transform_scale": _build_scale,
}

# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a transform tool call."""
    try:
        builder = _BUILDERS.get(name)
        if builder is None:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown transform tool: {name}"}),
                )
            ]

        script = builder(arguments)
        result = client.execute_vba(script)
        result["transform"] = name.replace("cst_transform_", "")
        result["solid"] = arguments.get("solid", "")

        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


# ---------------------------------------------------------------------------
# Registration helper (called from tools/__init__.py)
# ---------------------------------------------------------------------------


def register_transform_tools(server: Server, client: CSTClient) -> None:
    """Register transform tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
