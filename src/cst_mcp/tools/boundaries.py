"""Boundary condition and simulation domain tools for CST Studio Suite."""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.validators import validate_frequency, validate_non_negative, validate_range
from cst_mcp.vba_builder import VBABuilder

_BOUNDARY_TYPES = [
    "open",
    "open (add space)",
    "electric",
    "magnetic",
    "periodic",
    "conducting wall",
    "expanded open",
]

_BACKGROUND_MATERIALS = ["Normal", "PEC", "PMC"]

_SYMMETRY_OPTIONS = ["none", "electric", "magnetic"]

_BOUNDARY_PROPERTY = {
    "type": "string",
    "enum": _BOUNDARY_TYPES,
}

_SYMMETRY_PROPERTY = {
    "type": "string",
    "enum": _SYMMETRY_OPTIONS,
}

TOOLS: list[Tool] = [
    Tool(
        name="cst_set_boundary",
        description=(
            "Set boundary conditions for the simulation domain. Each face of "
            "the bounding box can be assigned an independent boundary type "
            "(open, electric, magnetic, periodic, etc.)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "x_min": {
                    **_BOUNDARY_PROPERTY,
                    "description": "Boundary condition on the -X face",
                },
                "x_max": {
                    **_BOUNDARY_PROPERTY,
                    "description": "Boundary condition on the +X face",
                },
                "y_min": {
                    **_BOUNDARY_PROPERTY,
                    "description": "Boundary condition on the -Y face",
                },
                "y_max": {
                    **_BOUNDARY_PROPERTY,
                    "description": "Boundary condition on the +Y face",
                },
                "z_min": {
                    **_BOUNDARY_PROPERTY,
                    "description": "Boundary condition on the -Z face",
                },
                "z_max": {
                    **_BOUNDARY_PROPERTY,
                    "description": "Boundary condition on the +Z face",
                },
            },
            "required": ["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"],
        },
    ),
    Tool(
        name="cst_set_background",
        description=(
            "Set the background material properties of the simulation domain. "
            "The background fills all space not occupied by defined solids."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "material": {
                    "type": "string",
                    "enum": _BACKGROUND_MATERIALS,
                    "description": "Background material type (default Normal)",
                    "default": "Normal",
                },
                "epsilon": {
                    "type": "number",
                    "description": "Relative permittivity (default 1.0, used when material is Normal)",
                    "default": 1.0,
                },
                "mu": {
                    "type": "number",
                    "description": "Relative permeability (default 1.0, used when material is Normal)",
                    "default": 1.0,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_set_symmetry",
        description=(
            "Set symmetry planes to reduce computation time. Each axis can be "
            "assigned electric or magnetic symmetry, or none. Requires the "
            "model geometry and excitation to be compatible with the chosen symmetry."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "x_plane": {
                    **_SYMMETRY_PROPERTY,
                    "description": "Symmetry condition on the YZ plane (default none)",
                    "default": "none",
                },
                "y_plane": {
                    **_SYMMETRY_PROPERTY,
                    "description": "Symmetry condition on the XZ plane (default none)",
                    "default": "none",
                },
                "z_plane": {
                    **_SYMMETRY_PROPERTY,
                    "description": "Symmetry condition on the XY plane (default none)",
                    "default": "none",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_set_frequency_range",
        description=(
            "Set the simulation frequency range in GHz. This determines the "
            "bandwidth over which the solver computes results."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "f_min": {
                    "type": "number",
                    "description": "Minimum frequency in GHz",
                },
                "f_max": {
                    "type": "number",
                    "description": "Maximum frequency in GHz",
                },
            },
            "required": ["f_min", "f_max"],
        },
    ),
    Tool(
        name="cst_set_periodic_boundary",
        description=(
            "Configure periodic boundary conditions with optional phase shift for "
            "unit cell simulation. Sets X and Y boundaries to periodic and configures "
            "the phase shift for infinite array, FSS, and metasurface analysis."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "phase_x_deg": {
                    "type": "number",
                    "description": "Phase shift in X direction in degrees (default 0)",
                    "default": 0,
                },
                "phase_y_deg": {
                    "type": "number",
                    "description": "Phase shift in Y direction in degrees (default 0)",
                    "default": 0,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_set_floquet_port_advanced",
        description=(
            "Configure advanced Floquet port settings for periodic structures. "
            "Controls the number of Floquet modes and scan angle for phased array "
            "element simulation and oblique incidence analysis."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_modes": {
                    "type": "integer",
                    "description": "Number of Floquet modes (2-20, default 2)",
                    "default": 2,
                },
                "scan_theta_deg": {
                    "type": "number",
                    "description": "Scan elevation angle in degrees (default 0)",
                    "default": 0,
                },
                "scan_phi_deg": {
                    "type": "number",
                    "description": "Scan azimuth angle in degrees (default 0)",
                    "default": 0,
                },
            },
            "required": [],
        },
    ),
]

async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a boundary/domain tool call."""
    try:
        if name == "cst_set_boundary":
            return await _handle_set_boundary(arguments, client)
        if name == "cst_set_background":
            return await _handle_set_background(arguments, client)
        if name == "cst_set_symmetry":
            return await _handle_set_symmetry(arguments, client)
        if name == "cst_set_frequency_range":
            return await _handle_set_frequency_range(arguments, client)
        if name == "cst_set_periodic_boundary":
            return await _handle_set_periodic_boundary(arguments, client)
        if name == "cst_set_floquet_port_advanced":
            return await _handle_set_floquet_port_advanced(arguments, client)

        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": f"Unknown boundary tool: {name}"}, indent=2),
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


async def _handle_set_boundary(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    faces = {}
    for face_key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max"):
        value = arguments[face_key]
        if value not in _BOUNDARY_TYPES:
            raise ValueError(
                f"Invalid boundary type '{value}' for {face_key}. "
                f"Must be one of: {_BOUNDARY_TYPES}"
            )
        faces[face_key] = value

    vba = (
        VBABuilder("Boundary")
        .set("Xmin", faces["x_min"])
        .set("Xmax", faces["x_max"])
        .set("Ymin", faces["y_min"])
        .set("Ymax", faces["y_max"])
        .set("Zmin", faces["z_min"])
        .set("Zmax", faces["z_max"])
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["boundaries"] = faces

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_set_background(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    material = arguments.get("material", "Normal")
    if material not in _BACKGROUND_MATERIALS:
        raise ValueError(
            f"Invalid background material '{material}'. "
            f"Must be one of: {_BACKGROUND_MATERIALS}"
        )
    epsilon = float(arguments.get("epsilon", 1.0))
    mu = float(arguments.get("mu", 1.0))

    validate_non_negative(epsilon, "epsilon")
    validate_non_negative(mu, "mu")

    vba = (
        VBABuilder("Background")
        .call("Reset")
        .set("Type", material)
    )

    if material == "Normal":
        vba.set_number("Epsilon", epsilon)
        vba.set_number("Mu", mu)

    vba.call("Apply")
    script = vba.build()
    result = client.execute_vba(script)
    result["background"] = {
        "material": material,
        "epsilon": epsilon,
        "mu": mu,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_set_symmetry(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    x_plane = arguments.get("x_plane", "none")
    y_plane = arguments.get("y_plane", "none")
    z_plane = arguments.get("z_plane", "none")

    for label, value in [("x_plane", x_plane), ("y_plane", y_plane), ("z_plane", z_plane)]:
        if value not in _SYMMETRY_OPTIONS:
            raise ValueError(
                f"Invalid symmetry '{value}' for {label}. "
                f"Must be one of: {_SYMMETRY_OPTIONS}"
            )

    vba = (
        VBABuilder("Boundary")
        .set("Xsymmetry", x_plane)
        .set("Ysymmetry", y_plane)
        .set("Zsymmetry", z_plane)
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["symmetry"] = {
        "x_plane": x_plane,
        "y_plane": y_plane,
        "z_plane": z_plane,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_set_frequency_range(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    f_min = float(arguments["f_min"])
    f_max = float(arguments["f_max"])

    validate_frequency(f_min)
    validate_frequency(f_max)

    if f_min >= f_max:
        raise ValueError(
            f"f_min ({f_min} GHz) must be less than f_max ({f_max} GHz)"
        )

    vba = (
        VBABuilder("Solver")
        .set_double("FrequencyRange", f_min, f_max)
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["frequency_range"] = {
        "f_min_ghz": f_min,
        "f_max_ghz": f_max,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_set_periodic_boundary(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    phase_x = float(arguments.get("phase_x_deg", 0))
    phase_y = float(arguments.get("phase_y_deg", 0))

    vba = (
        VBABuilder("Boundary")
        .set("Xmin", "periodic")
        .set("Xmax", "periodic")
        .set("Ymin", "periodic")
        .set("Ymax", "periodic")
        .set_number("XPeriodicShift", phase_x)
        .set_number("YPeriodicShift", phase_y)
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["boundary_type"] = "periodic"
    result["phase_x_deg"] = phase_x
    result["phase_y_deg"] = phase_y

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_set_floquet_port_advanced(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    num_modes = int(arguments.get("num_modes", 2))
    scan_theta = float(arguments.get("scan_theta_deg", 0))
    scan_phi = float(arguments.get("scan_phi_deg", 0))

    validate_range(num_modes, 2, 20, "num_modes")
    validate_range(scan_theta, -90, 90, "scan_theta_deg")
    validate_range(scan_phi, -360, 360, "scan_phi_deg")

    vba = (
        VBABuilder("FloquetPort")
        .call("Reset")
        .set_number("SetNumberOfModes", num_modes)
        .set_double("SetScanAngle", scan_theta, scan_phi)
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["floquet_port"] = "advanced"
    result["num_modes"] = num_modes
    result["scan_theta_deg"] = scan_theta
    result["scan_phi_deg"] = scan_phi

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def register_boundary_tools(server: Server, client: CSTClient) -> None:
    """Register boundary/domain tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
