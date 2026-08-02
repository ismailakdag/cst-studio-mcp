"""Geometry creation tools for CST Studio Suite.

Provides 13 MCP tools for creating 3D shapes, curves, and extruded profiles
in CST Studio by generating VBA scripts via VBABuilder.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

from mcp.types import TextContent, Tool

if TYPE_CHECKING:
    from mcp.server import Server

from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBABuilder, VBAScript
from cst_mcp.validators import validate_name, validate_positive, validate_non_negative

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
        description="Extrude a 2D polygon profile into a 3D solid in CST Studio.",
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
            "Convenience tool combining polygon profile creation and extrusion."
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
    axis_map = {"x": ("Xrange", "Xcenter", "Ycenter", "Zcenter"),
                "y": ("Yrange", "Ycenter", "Xcenter", "Zcenter"),
                "z": ("Zrange", "Zcenter", "Xcenter", "Ycenter")}
    range_prop, center1_prop, center2_prop, center3_prop = axis_map[axis]

    vba = (
        VBABuilder("Cylinder")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Axis", axis)
        .set_number("Outerradius", outer_radius)
        .set_number("Innerradius", inner_radius)
        .set_number(center1_prop, cx)
        .set_number(center2_prop, cy)
        .set_number(center3_prop, cz)
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
    axis_map = {"x": ("Xrange", "Xcenter", "Ycenter", "Zcenter"),
                "y": ("Yrange", "Ycenter", "Xcenter", "Zcenter"),
                "z": ("Zrange", "Zcenter", "Xcenter", "Ycenter")}
    range_prop, center1_prop, center2_prop, center3_prop = axis_map[axis]

    vba = (
        VBABuilder("Cone")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Axis", axis)
        .set_number("Bottomradius", bottom_radius)
        .set_number("Topradius", top_radius)
        .set_number(center1_prop, cx)
        .set_number(center2_prop, cy)
        .set_number(center3_prop, cz)
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


def _build_extrude(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    points: list[list[float]] = args["points"]
    height: float = args["height"]

    vba = (
        VBABuilder("Extrude")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set_number("Mode", 0)
        .set_number("Height", height)
        .set("Origin", "0.0, 0.0, 0.0")
        .set("Uvector", "1.0, 0.0, 0.0")
        .set("Vvector", "0.0, 1.0, 0.0")
    )

    # First point
    vba.set_double("Point", points[0][0], points[0][1])
    # Subsequent points as LineTo
    for pt in points[1:]:
        vba.set_double("LineTo", pt[0], pt[1])
    # Close back to first point
    vba.set_double("LineTo", points[0][0], points[0][1])

    vba.call("Create")
    return vba.build()


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
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    radius = validate_positive(args["radius"], "radius")

    vba = (
        VBABuilder("Wire")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set_triple("StartPoint", args["start_x"], args["start_y"], args["start_z"])
        .set_triple("EndPoint", args["end_x"], args["end_y"], args["end_z"])
        .set_number("Radius", radius)
        .call("Create")
    )
    return vba.build()


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
    axis_map = {"x": ("Xrange", "Xcenter", "Ycenter", "Zcenter"),
                "y": ("Yrange", "Ycenter", "Xcenter", "Zcenter"),
                "z": ("Zrange", "Zcenter", "Xcenter", "Ycenter")}
    range_prop, center1_prop, center2_prop, center3_prop = axis_map[axis]

    vba = (
        VBABuilder("ECylinder")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Axis", axis)
        .set_number("XRadius", x_radius)
        .set_number("YRadius", y_radius)
        .set_number(center1_prop, cx)
        .set_number(center2_prop, cy)
        .set_number(center3_prop, cz)
        .set_double(range_prop, args["range_min"], args["range_max"])
        .call("Create")
    )
    return vba.build()


def _build_polygon_extrude(args: dict) -> str:
    component = validate_name(args["component"], "component")
    name = validate_name(args["name"], "name")
    material = args.get("material", "PEC")
    points: list[list[float]] = args["points"]
    height: float = args["height"]
    axis: str = args.get("axis", "z")

    script = VBAScript()
    script.add_comment(f"Polygon extrude: {component}:{name}")

    # Create the polygon curve
    poly_vba = (
        VBABuilder("Polygon")
        .call("Reset")
        .set("Name", f"{name}_profile")
        .set("Curve", f"{name}_curves")
    )
    for pt in points:
        poly_vba.set_double("Point", pt[0], pt[1])
    # Close the polygon
    poly_vba.set_double("Point", points[0][0], points[0][1])
    poly_vba.call("Create")
    script.add_block(poly_vba)

    # Extrude the curve into a solid
    extrude_vba = (
        VBABuilder("ExtrudeCurve")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set_number("Thickness", height)
        .set_double("Twistangle", 0, 0)
        .set_double("Taperangle", 0, 0)
        .set("Curve", f"{name}_curves:{name}_profile")
    )
    # Map axis to DeleteProfile direction
    if axis == "z":
        extrude_vba.set("Axis", "z")
    elif axis == "x":
        extrude_vba.set("Axis", "x")
    elif axis == "y":
        extrude_vba.set("Axis", "y")
    extrude_vba.call("Create")
    script.add_block(extrude_vba)

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


def register_geometry_tools(server: Server, client: CSTClient) -> None:
    """Register geometry tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
