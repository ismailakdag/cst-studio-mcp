"""Geometry creation tools for CST Studio Suite.

Provides 13 MCP tools for creating 3D shapes, curves, and extruded profiles
in CST Studio by generating VBA scripts via VBABuilder.
"""

from __future__ import annotations

import json
from typing import Callable

from mcp.types import TextContent, Tool


from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBABuilder, VBAScript
from cst_mcp.validators import validate_name, validate_positive, validate_non_negative
from cst_mcp.vba_safety import vba_escape as _q
from cst_mcp.vba_safety import vba_number as _vba_number
from cst_mcp.vba_safety import vba_string_literal as _vba_string_literal

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # 1. Brick
    Tool(
        name="cst_create_brick",
        description="Create a rectangular brick (box) in CST Studio.",
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name (e.g. 'Antenna')"},
                "name": {"type": "string", "description": "Solid name (e.g. 'Substrate')"},
                "material": {"type": "string", "description": "Material name", "default": "PEC"},
                "x_min": {"type": "number", "description": "X range minimum"},
                "x_max": {"type": "number", "description": "X range maximum"},
                "y_min": {"type": "number", "description": "Y range minimum"},
                "y_max": {"type": "number", "description": "Y range maximum"},
                "z_min": {"type": "number", "description": "Z range minimum"},
                "z_max": {"type": "number", "description": "Z range maximum"},
            },
            "required": ["component", "name", "x_min", "x_max", "y_min", "y_max", "z_min", "z_max"],
        },
    ),

    # 2. Cylinder
    Tool(
        name="cst_create_cylinder",
        description="Create a cylinder in CST Studio. Use inner_radius=0 for a solid cylinder.",
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Solid name"},
                "material": {"type": "string", "description": "Material name", "default": "PEC"},
                "axis": {"type": "string", "enum": ["x", "y", "z"], "description": "Cylinder axis"},
                "outer_radius": {"type": "number", "description": "Outer radius"},
                "inner_radius": {"type": "number", "description": "Inner radius (0 for solid)", "default": 0},
                "center_x": {"type": "number", "description": "Center X coordinate", "default": 0},
                "center_y": {"type": "number", "description": "Center Y coordinate", "default": 0},
                "center_z": {"type": "number", "description": "Center Z coordinate", "default": 0},
                "range_min": {"type": "number", "description": "Axis range minimum"},
                "range_max": {"type": "number", "description": "Axis range maximum"},
            },
            "required": ["component", "name", "axis", "outer_radius", "range_min", "range_max"],
        },
    ),

    # 3. Cone
    Tool(
        name="cst_create_cone",
        description="Create a cone or truncated cone in CST Studio.",
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Solid name"},
                "material": {"type": "string", "description": "Material name", "default": "PEC"},
                "axis": {"type": "string", "enum": ["x", "y", "z"], "description": "Cone axis"},
                "bottom_radius": {"type": "number", "description": "Bottom radius"},
                "top_radius": {"type": "number", "description": "Top radius (0 for pointed cone)"},
                "center_x": {"type": "number", "description": "Center X coordinate", "default": 0},
                "center_y": {"type": "number", "description": "Center Y coordinate", "default": 0},
                "center_z": {"type": "number", "description": "Center Z coordinate", "default": 0},
                "range_min": {"type": "number", "description": "Axis range minimum"},
                "range_max": {"type": "number", "description": "Axis range maximum"},
            },
            "required": ["component", "name", "axis", "bottom_radius", "top_radius", "range_min", "range_max"],
        },
    ),

    # 4. Sphere
    Tool(
        name="cst_create_sphere",
        description="Create a sphere in CST Studio.",
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Solid name"},
                "material": {"type": "string", "description": "Material name", "default": "PEC"},
                "center_x": {"type": "number", "description": "Center X coordinate", "default": 0},
                "center_y": {"type": "number", "description": "Center Y coordinate", "default": 0},
                "center_z": {"type": "number", "description": "Center Z coordinate", "default": 0},
                "radius": {"type": "number", "description": "Sphere radius"},
                "segments": {"type": "integer", "description": "Number of segments (0=auto)", "default": 0},
            },
            "required": ["component", "name", "radius"],
        },
    ),

    # 5. Torus
    Tool(
        name="cst_create_torus",
        description="Create a torus in CST Studio.",
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Solid name"},
                "material": {"type": "string", "description": "Material name", "default": "PEC"},
                "axis": {"type": "string", "enum": ["x", "y", "z"], "description": "Torus axis"},
                "center_x": {"type": "number", "description": "Center X coordinate", "default": 0},
                "center_y": {"type": "number", "description": "Center Y coordinate", "default": 0},
                "center_z": {"type": "number", "description": "Center Z coordinate", "default": 0},
                "outer_radius": {"type": "number", "description": "Major radius (center to tube center)"},
                "inner_radius": {"type": "number", "description": "Minor radius (tube radius)"},
            },
            "required": ["component", "name", "axis", "outer_radius", "inner_radius"],
        },
    ),

    # 6. Extrude
    Tool(
        name="cst_create_extrude",
        description=(
            "Extrude a 2D polygon profile into a 3D solid in CST Studio (Extrude object, Mode "
            "'pointlist'). The profile lies in the plane normal to 'axis' (default z) at the given "
            "x/y/z_offset; optional 'holes' are extruded the same way and subtracted (Solid.Subtract)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Solid name"},
                "material": {"type": "string", "description": "Material name", "default": "PEC"},
                "points": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 3,
                    "description": "List of [x, y] coordinate pairs forming the profile polygon",
                },
                "height": {"type": "number", "description": "Extrusion height"},
                "axis": {
                    "type": "string",
                    "enum": ["x", "y", "z"],
                    "default": "z",
                    "description": "Extrusion axis (profile plane normal). z: (u,v)=(x,y); x: (u,v)=(y,z); y: (u,v)=(x,-z).",
                },
                "x_offset": {
                    "type": "number",
                    "default": 0,
                    "description": "Base-plane position on the x axis (only valid with axis='x').",
                },
                "y_offset": {
                    "type": "number",
                    "default": 0,
                    "description": "Base-plane position on the y axis (only valid with axis='y').",
                },
                "z_offset": {
                    "type": "number",
                    "default": 0,
                    "description": "Base-plane position on the z axis (only valid with axis='z', the default).",
                },
                "holes": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "minItems": 3,
                    },
                    "default": [],
                    "description": (
                        "Optional holes/slots: each a list of [x, y] pairs in the same profile plane. "
                        "Each hole is extruded with the same height and removed with Solid.Subtract."
                    ),
                },
            },
            "required": ["component", "name", "points", "height"],
        },
    ),

    # 7. Loft
    Tool(
        name="cst_create_loft",
        description="Create a lofted solid between two or more 2D profiles in CST Studio.",
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Solid name"},
                "material": {"type": "string", "description": "Material name", "default": "PEC"},
                "profiles": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "minItems": 3,
                    },
                    "minItems": 2,
                    "description": "List of profiles, each a list of [x, y] coordinate pairs",
                },
            },
            "required": ["component", "name", "profiles"],
        },
    ),

    # 8. Wire
    Tool(
        name="cst_create_wire",
        description="Create a bondwire / wire between two points in CST Studio.",
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Solid name"},
                "start_x": {"type": "number", "description": "Start point X"},
                "start_y": {"type": "number", "description": "Start point Y"},
                "start_z": {"type": "number", "description": "Start point Z"},
                "end_x": {"type": "number", "description": "End point X"},
                "end_y": {"type": "number", "description": "End point Y"},
                "end_z": {"type": "number", "description": "End point Z"},
                "radius": {"type": "number", "description": "Wire radius"},
            },
            "required": ["component", "name", "start_x", "start_y", "start_z",
                          "end_x", "end_y", "end_z", "radius"],
        },
    ),

    # 9. Polygon3D
    Tool(
        name="cst_create_polygon3d",
        description="Create a 3D polygon curve in CST Studio.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Curve name"},
                "points": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "minItems": 2,
                    "description": "List of [x, y, z] coordinate triples",
                },
            },
            "required": ["name", "points"],
        },
    ),

    # 10. Analytical curve
    Tool(
        name="cst_create_analytical_curve",
        description="Create a parametric analytical curve in CST Studio using expressions of parameter t.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Curve name"},
                "x_expr": {"type": "string", "description": "X expression as function of t (e.g. 'cos(t)')"},
                "y_expr": {"type": "string", "description": "Y expression as function of t (e.g. 'sin(t)')"},
                "z_expr": {"type": "string", "description": "Z expression as function of t (e.g. 't')"},
                "t_min": {"type": "number", "description": "Parameter t minimum value"},
                "t_max": {"type": "number", "description": "Parameter t maximum value"},
            },
            "required": ["name", "x_expr", "y_expr", "z_expr", "t_min", "t_max"],
        },
    ),

    # 11. Face from curves
    Tool(
        name="cst_create_face_from_curves",
        description="Create a planar face from one or more closed curves in CST Studio.",
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Face/solid name"},
                "curve_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "List of curve names to form the face boundary",
                },
            },
            "required": ["component", "name", "curve_names"],
        },
    ),

    # 12. Elliptical cylinder
    Tool(
        name="cst_create_ecylinder",
        description="Create an elliptical cylinder in CST Studio.",
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Solid name"},
                "material": {"type": "string", "description": "Material name", "default": "PEC"},
                "axis": {"type": "string", "enum": ["x", "y", "z"], "description": "Cylinder axis"},
                "x_radius": {"type": "number", "description": "Radius in local X direction"},
                "y_radius": {"type": "number", "description": "Radius in local Y direction"},
                "center_x": {"type": "number", "description": "Center X coordinate", "default": 0},
                "center_y": {"type": "number", "description": "Center Y coordinate", "default": 0},
                "center_z": {"type": "number", "description": "Center Z coordinate", "default": 0},
                "range_min": {"type": "number", "description": "Axis range minimum"},
                "range_max": {"type": "number", "description": "Axis range maximum"},
            },
            "required": ["component", "name", "axis", "x_radius", "y_radius", "range_min", "range_max"],
        },
    ),

    # 13. Polygon extrude (convenience)
    Tool(
        name="cst_create_polygon_extrude",
        description=(
            "Create a polygon and extrude it along an axis in CST Studio. "
            "Convenience tool combining polygon profile creation (Polygon3D curve) and extrusion "
            "(ExtrudeCurve). The profile lies at the base plane given by x/y/z_offset for the chosen "
            "axis; optional 'holes' (lists of [x, y]) are extruded the same way and removed with "
            "Solid.Subtract, e.g. for slotted/fractal patches."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "component": {"type": "string", "description": "Component name"},
                "name": {"type": "string", "description": "Solid name"},
                "material": {"type": "string", "description": "Material name", "default": "PEC"},
                "points": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 3,
                    "description": "List of [x, y] coordinate pairs forming the polygon",
                },
                "height": {"type": "number", "description": "Extrusion height"},
                "axis": {"type": "string", "enum": ["x", "y", "z"], "description": "Extrusion axis", "default": "z"},
                "x_offset": {
                    "type": "number",
                    "default": 0,
                    "description": "Base-plane position on the x axis (only valid with axis='x').",
                },
                "y_offset": {
                    "type": "number",
                    "default": 0,
                    "description": "Base-plane position on the y axis (only valid with axis='y').",
                },
                "z_offset": {
                    "type": "number",
                    "default": 0,
                    "description": "Base-plane position on the z axis (only valid with axis='z', the default).",
                },
                "holes": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "minItems": 3,
                    },
                    "default": [],
                    "description": (
                        "Optional holes/slots: each a list of [x, y] pairs in the same profile plane. "
                        "Each hole is extruded with the same height and removed with Solid.Subtract."
                    ),
                },
            },
            "required": ["component", "name", "points", "height"],
        },
    ),
]

# ---------------------------------------------------------------------------
# VBA generation helpers
# ---------------------------------------------------------------------------


def _build_brick(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")

    vba = (
        VBABuilder("Brick")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set_double("Xrange", args["x_min"], args["x_max"])
        .set_double("Yrange", args["y_min"], args["y_max"])
        .set_double("Zrange", args["z_min"], args["z_max"])
        .call("Create")
    )
    return vba.build()


def _build_cylinder(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    axis = args["axis"]
    outer_radius = validate_positive(args["outer_radius"], "outer_radius")
    inner_radius = validate_non_negative(args.get("inner_radius", 0), "inner_radius")
    cx = args.get("center_x", 0)
    cy = args.get("center_y", 0)
    cz = args.get("center_z", 0)

    # Map axis to the correct CST VBA property names
    range_prop = {"x": "Xrange", "y": "Yrange", "z": "Zrange"}[axis]

    vba = (
        VBABuilder("Cylinder")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Axis", axis)
        .set_number("Outerradius", outer_radius)
        .set_number("Innerradius", inner_radius)
        .set_number("Xcenter", cx)
        .set_number("Ycenter", cy)
        .set_number("Zcenter", cz)
        .set_double(range_prop, args["range_min"], args["range_max"])
        .call("Create")
    )
    return vba.build()


def _build_cone(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    axis = args["axis"]
    bottom_radius = validate_non_negative(args["bottom_radius"], "bottom_radius")
    top_radius = validate_non_negative(args["top_radius"], "top_radius")
    cx = args.get("center_x", 0)
    cy = args.get("center_y", 0)
    cz = args.get("center_z", 0)

    # Map axis to the correct CST VBA property names
    range_prop = {"x": "Xrange", "y": "Yrange", "z": "Zrange"}[axis]

    vba = (
        VBABuilder("Cone")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Axis", axis)
        .set_number("Bottomradius", bottom_radius)
        .set_number("Topradius", top_radius)
        .set_number("Xcenter", cx)
        .set_number("Ycenter", cy)
        .set_number("Zcenter", cz)
        .set_double(range_prop, args["range_min"], args["range_max"])
        .call("Create")
    )
    return vba.build()


def _build_sphere(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    radius = validate_positive(args["radius"], "radius")
    cx = args.get("center_x", 0)
    cy = args.get("center_y", 0)
    cz = args.get("center_z", 0)
    segments = args.get("segments", 0)

    # Official CST Sphere API (see vba_cst / Online Help):
    #   .Axis, .CenterRadius, .TopRadius, .BottomRadius, .Center x,y,z, .Segments
    vba = (
        VBABuilder("Sphere")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Axis", "z")
        .set_number("CenterRadius", radius)
        .set_number("TopRadius", 0)
        .set_number("BottomRadius", 0)
        .set_triple("Center", cx, cy, cz)
        .set_number("Segments", segments)
        .call("Create")
    )
    return vba.build()


def _build_torus(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    axis = args["axis"]
    outer_radius = validate_positive(args["outer_radius"], "outer_radius")
    inner_radius = validate_positive(args["inner_radius"], "inner_radius")
    cx = args.get("center_x", 0)
    cy = args.get("center_y", 0)
    cz = args.get("center_z", 0)

    vba = (
        VBABuilder("Torus")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Axis", axis)
        .set_number("OuterRadius", outer_radius)
        .set_number("InnerRadius", inner_radius)
        .set_number("Xcenter", cx)
        .set_number("Ycenter", cy)
        .set_number("Zcenter", cz)
        .call("Create")
    )
    return vba.build()


_OFFSET_KEYS = {"x": "x_offset", "y": "y_offset", "z": "z_offset"}
# Extrude object plane per axis: (Uvector, Vvector); the profile's (u, v)
# map to the same world axes as cst_create_polygon_extrude's Polygon3D points.
_EXTRUDE_PLANES = {
    "z": ((1, 0, 0), (0, 1, 0)),
    "x": ((0, 1, 0), (0, 0, 1)),
    "y": ((1, 0, 0), (0, 0, -1)),
}


def _num(value, field: str) -> float:
    """Coerce through vba_safety.vba_number (finite, non-bool) to a float."""
    return float(_vba_number(value, field))


def _profile_points(points, field: str) -> list[tuple[float, float]]:
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        raise ValueError(f"{field} must contain at least 3 [x, y] points")
    out = []
    for i, pt in enumerate(points):
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            raise ValueError(f"{field}[{i}] must be an [x, y] pair")
        out.append((_num(pt[0], f"{field}[{i}][0]"), _num(pt[1], f"{field}[{i}][1]")))
    return out


def _signed_area(points: list[tuple[float, float]]) -> float:
    return 0.5 * sum(
        x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1])
    )


def _extrude_axis_offset_holes(args: dict):
    """Validate axis, base-plane offset and holes shared by both extrude tools."""
    axis = args.get("axis", "z")
    if axis not in _OFFSET_KEYS:
        raise ValueError("axis must be x, y, or z")
    for other_axis, key in _OFFSET_KEYS.items():
        if other_axis != axis and args.get(key) not in (None, 0):
            raise ValueError(f"{key} only applies to axis='{other_axis}'; use {_OFFSET_KEYS[axis]} for axis='{axis}'")
    offset = _num(args.get(_OFFSET_KEYS[axis], 0) or 0, _OFFSET_KEYS[axis])
    points = _profile_points(args["points"], "points")
    outer_area = _signed_area(points)
    if outer_area == 0:
        raise ValueError("points must enclose a non-zero area")
    # Live CST 2026: ExtrudeCurve extrudes along the Polygon3D curve normal,
    # which follows the winding (a clockwise square at z=1.6 went to
    # z=1.565..1.6).  Normalise to counter-clockwise in (u, v) so the solid
    # always grows towards +axis; the Extrude object is winding-independent.
    if outer_area < 0:
        points = points[::-1]
        outer_area = -outer_area
    holes = []
    raw_holes = args.get("holes") or []
    if not isinstance(raw_holes, (list, tuple)):
        raise ValueError("holes must be a list of point lists")
    for h, raw in enumerate(raw_holes):
        hole = _profile_points(raw, f"holes[{h}]")
        area = _signed_area(hole)
        if area == 0:
            raise ValueError(f"holes[{h}] must enclose a non-zero area")
        # Same (counter-clockwise) winding as the outline so the hole is
        # extruded in the same direction as the main solid.
        if area < 0:
            hole = hole[::-1]
        holes.append(hole)
    return axis, offset, points, holes


def _subtract_block(component: str, name: str, tool_name: str) -> str:
    target = _vba_string_literal(f"{component}:{name}", "solid")
    tool = _vba_string_literal(f"{component}:{tool_name}", "solid")
    return f"Solid.Subtract {target}, {tool}"


def _extrude_block(name, component, material, height, axis, offset, points) -> VBABuilder:
    u_vec, v_vec = _EXTRUDE_PLANES[axis]
    origin = {"z": (0, 0, offset), "x": (offset, 0, 0), "y": (0, offset, 0)}[axis]
    vba = (
        VBABuilder("Extrude")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Mode", "pointlist")
        .set_number("Height", height)
        .set_triple("Origin", *origin)
        .set_triple("Uvector", *u_vec)
        .set_triple("Vvector", *v_vec)
    )
    # First point, subsequent points as LineTo, closed back to the first point.
    vba.set_double("Point", *points[0])
    for pt in points[1:]:
        vba.set_double("LineTo", *pt)
    vba.set_double("LineTo", *points[0])
    vba.call("Create")
    return vba


def _build_extrude(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    height = _num(args["height"], "height")
    axis, offset, points, holes = _extrude_axis_offset_holes(args)

    main = _extrude_block(name, component, material, height, axis, offset, points)
    if not holes:
        return main.build()
    script = VBAScript()
    script.add_comment(f"Extrude with {len(holes)} hole(s): {component}:{name}")
    script.add_block(main)
    for h, hole in enumerate(holes):
        hole_name = validate_name(f"{name}_hole{h + 1}", "hole name")
        script.add_block(_extrude_block(hole_name, component, material, height, axis, offset, hole))
        script.add_raw(_subtract_block(component, name, hole_name))
    return script.build()


def _build_loft(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    profiles: list[list[list[float]]] = args["profiles"]

    script = VBAScript()
    script.add_comment(f"Loft: {component}:{name}")

    # Create each profile as a named curve
    for i, profile in enumerate(profiles):
        curve_name = f"{name}_profile{i}"
        curve_vba = (
            VBABuilder("Polygon")
            .call("Reset")
            .set("Name", curve_name)
            .set("Curve", f"{name}_curves")
        )
        for pt in profile:
            curve_vba.set_double("Point", pt[0], pt[1])
        # Close the polygon
        curve_vba.set_double("Point", profile[0][0], profile[0][1])
        curve_vba.call("Create")
        script.add_block(curve_vba)

    # Create the loft
    loft_vba = (
        VBABuilder("Loft")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
    )
    for i in range(len(profiles)):
        curve_name = f"{name}_profile{i}"
        loft_vba.set("AddCurve", f"{name}_curves:{curve_name}")
    loft_vba.call("Create")
    script.add_block(loft_vba)

    return script.build()


def _build_wire(args: dict) -> str:
    """Straight round solid conductor, using Cylinder and rigid transforms.

    Avoid the Wire-to-solid conversion, which stalled the CST 2026 live test.
    """
    import math
    from cst_mcp.tools.transforms import _build_rotate, _build_translate

    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    radius = validate_positive(args["radius"], "radius")
    start = [float(args[f"start_{axis}"]) for axis in "xyz"]
    delta = [float(args[f"end_{axis}"]) - start[i] for i, axis in enumerate("xyz")]
    length = math.hypot(*delta)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("Wire endpoints must be finite and distinct")
    solid = f"{component}:{name}"
    code = [_build_cylinder(dict(component=component, name=name,
        material=args.get("material", "PEC"), axis="z", outer_radius=radius,
        range_min=0, range_max=length))]
    theta = math.degrees(math.acos(max(-1, min(1, delta[2]/length))))
    phi = math.degrees(math.atan2(delta[1], delta[0]))
    for axis, angle in (("y", theta), ("z", phi)):
        if abs(angle) > 1e-12:
            code.append(_build_rotate(dict(solid=solid, axis=axis, angle=angle)))
    code.append(_build_translate(dict(solid=solid, dx=start[0], dy=start[1], dz=start[2])))
    return "\n".join(code)


def _build_polygon3d(args: dict) -> str:
    name = validate_name(args["name"], "name")
    points: list[list[float]] = args["points"]

    vba = (
        VBABuilder("Polygon3D")
        .call("Reset")
        .set("Name", name)
        .set("Curve", "Curves")
    )
    for pt in points:
        vba.set_triple("Point", pt[0], pt[1], pt[2])
    vba.call("Create")
    return vba.build()


def _build_analytical_curve(args: dict) -> str:
    name = validate_name(args["name"], "name")

    vba = (
        VBABuilder("AnalyticalCurve")
        .call("Reset")
        .set("Name", name)
        .set("Curve", "Curves")
        .set("LawX", args["x_expr"])
        .set("LawY", args["y_expr"])
        .set("LawZ", args["z_expr"])
        .set_double("ParameterRange", args["t_min"], args["t_max"])
        .call("Create")
    )
    return vba.build()


def _build_face_from_curves(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    curve_names: list[str] = args["curve_names"]

    vba = (
        VBABuilder("CoverCurve")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
    )
    for curve_name in curve_names:
        validate_name(curve_name, "curve_name")
        vba.set("AddCurve", curve_name)
    vba.call("Create")
    return vba.build()


def _build_ecylinder(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    axis = args["axis"]
    x_radius = validate_positive(args["x_radius"], "x_radius")
    y_radius = validate_positive(args["y_radius"], "y_radius")
    cx = args.get("center_x", 0)
    cy = args.get("center_y", 0)
    cz = args.get("center_z", 0)

    # Map axis to the correct CST VBA property names
    range_prop = {"x": "Xrange", "y": "Yrange", "z": "Zrange"}[axis]

    vba = (
        VBABuilder("ECylinder")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Axis", axis)
        .set_number("XRadius", x_radius)
        .set_number("YRadius", y_radius)
        .set_number("Xcenter", cx)
        .set_number("Ycenter", cy)
        .set_number("Zcenter", cz)
        .set_double(range_prop, args["range_min"], args["range_max"])
        .call("Create")
    )
    return vba.build()


def _polygon_curve_extrude(script: VBAScript, name, curve, item, component, material,
                           height, point_fn, points) -> None:
    poly_vba = (
        VBABuilder("Polygon3D")
        .call("Reset")
        .set("Name", item)
        .set("Curve", curve)
    )
    for pt in points:
        poly_vba.set_triple("Point", *point_fn(pt))
    # Close the polygon
    poly_vba.set_triple("Point", *point_fn(points[0]))
    poly_vba.call("Create")
    script.add_block(poly_vba)

    # Extrude the closed planar curve item into a solid (the curve item is consumed).
    extrude_vba = (
        VBABuilder("ExtrudeCurve")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set_number("Thickness", height)
        .set_number("Twistangle", 0)
        .set_number("Taperangle", 0)
        .set("Curve", f"{curve}:{item}")
    )
    # The closed curve's plane sets the extrusion direction in CST.
    extrude_vba.call("Create")
    script.add_block(extrude_vba)


def _build_polygon_extrude(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    height = _num(args["height"], "height")
    axis, offset, points, holes = _extrude_axis_offset_holes(args)

    def point(pt):
        if axis == "x":
            return (offset, pt[0], pt[1])
        if axis == "y":
            return (pt[0], offset, -pt[1])
        return (pt[0], pt[1], offset)

    curve = f"{name}_curves"
    script = VBAScript()
    script.add_comment(f"Polygon extrude: {component}:{name}")
    script.add_raw(f'Curve.NewCurve "{_q(curve, "name")}"')
    _polygon_curve_extrude(script, name, curve, f"{name}_profile", component, material,
                           height, point, points)
    for h, hole in enumerate(holes):
        hole_name = validate_name(f"{name}_hole{h + 1}", "hole name")
        _polygon_curve_extrude(script, hole_name, curve, f"{hole_name}_profile", component,
                               material, height, point, hole)
        script.add_raw(_subtract_block(component, name, hole_name))
    return script.build()


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[[dict], str]] = {
    "cst_create_brick": _build_brick,
    "cst_create_cylinder": _build_cylinder,
    "cst_create_cone": _build_cone,
    "cst_create_sphere": _build_sphere,
    "cst_create_torus": _build_torus,
    "cst_create_extrude": _build_extrude,
    "cst_create_loft": _build_loft,
    "cst_create_wire": _build_wire,
    "cst_create_polygon3d": _build_polygon3d,
    "cst_create_analytical_curve": _build_analytical_curve,
    "cst_create_face_from_curves": _build_face_from_curves,
    "cst_create_ecylinder": _build_ecylinder,
    "cst_create_polygon_extrude": _build_polygon_extrude,
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


async def handle(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle a geometry tool call.

    Generates VBA via VBABuilder, executes through the CSTClient, and
    returns the result wrapped in TextContent.
    """
    builder_fn = _HANDLERS.get(name)
    if builder_fn is None:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Unknown geometry tool: {name}",
        }))]

    try:
        vba_code = builder_fn(arguments)
        result = client.execute_vba(vba_code)
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": str(e),
        }))]


# Reject line breaks and non-numeric values in numeric slots before any VBA
# is generated from the arguments (generated VBA bypasses CST_ALLOW_RAW_VBA).
from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
