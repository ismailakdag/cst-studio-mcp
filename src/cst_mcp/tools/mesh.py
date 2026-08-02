"""Mesh control tools for CST Studio Suite."""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.types import MeshType
from cst_mcp.validators import (
    validate_enum_value,
    validate_name,
    validate_positive,
    validate_range,
)
from cst_mcp.vba_builder import VBABuilder

TOOLS: list[Tool] = [
    Tool(
        name="cst_set_mesh_type",
        description=(
            "Set the mesh type for the simulation. Hexahedral is used for time-domain, "
            "Tetrahedral for frequency-domain, Surface for integral-equation, and "
            "Hexahedral TLM for TLM solver."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mesh_type": {
                    "type": "string",
                    "enum": ["Hexahedral", "Tetrahedral", "Surface", "Hexahedral TLM"],
                    "description": "Type of mesh to use",
                },
            },
            "required": ["mesh_type"],
        },
    ),
    Tool(
        name="cst_set_mesh_density",
        description=(
            "Set global mesh density parameters controlling automatic mesh generation. "
            "Higher cells_per_wavelength gives finer mesh and better accuracy at the "
            "cost of longer simulation time."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "cells_per_wavelength": {
                    "type": "integer",
                    "description": "Number of mesh cells per wavelength (default 15)",
                    "default": 15,
                },
                "min_cells": {
                    "type": "integer",
                    "description": "Minimum number of mesh steps across any structure (default 5)",
                    "default": 5,
                },
                "ratio_limit": {
                    "type": "number",
                    "description": "Maximum ratio between adjacent mesh cells (default 20)",
                    "default": 20,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_add_mesh_refinement",
        description=(
            "Add local mesh refinement to a specific solid. This creates finer mesh "
            "around critical geometry features like feed points, gaps, or thin layers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "component": {
                    "type": "string",
                    "description": "Component name containing the solid",
                },
                "solid": {
                    "type": "string",
                    "description": "Solid name to refine mesh around",
                },
                "refinement_factor": {
                    "type": "number",
                    "description": "Refinement factor — mesh cells are divided by this value (default 2.0)",
                    "default": 2.0,
                },
            },
            "required": ["component", "solid"],
        },
    ),
    Tool(
        name="cst_set_adaptive_mesh",
        description=(
            "Configure adaptive mesh refinement. When enabled, the solver runs multiple "
            "passes, refining the mesh in regions of high field gradient until the result "
            "converges within the specified threshold."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "Enable or disable adaptive meshing (default true)",
                    "default": True,
                },
                "max_passes": {
                    "type": "integer",
                    "description": "Maximum number of adaptive mesh refinement passes (default 3)",
                    "default": 3,
                },
                "threshold": {
                    "type": "number",
                    "description": "Convergence threshold in dB — stop when S-parameter change is below this (default 0.02)",
                    "default": 0.02,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_get_mesh_info",
        description=(
            "Get current mesh statistics and settings. In connected mode this queries "
            "the live mesh data; in offline mode it returns the VBA to retrieve mesh info."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_get_mesh_quality",
        description=(
            "Extract mesh quality metrics including total cells, aspect ratios, and cells "
            "per wavelength. In connected mode this queries actual mesh statistics; in "
            "offline mode it describes what metrics would be returned."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_set_pml_properties",
        description=(
            "Configure PML (Perfectly Matched Layer) absorbing boundary properties. "
            "Controls the number of absorbing layers and the target reflection level "
            "for fine-tuning radiation boundary accuracy."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_layers": {
                    "type": "integer",
                    "description": "Number of PML layers (4-12, default 4)",
                    "default": 4,
                },
                "reflection_level_db": {
                    "type": "number",
                    "description": "Target reflection level in dB (-80 to -20, default -40)",
                    "default": -40,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_add_fixpoint_mesh",
        description=(
            "Add a fixed mesh point at specific coordinates for precise field sampling. "
            "Ensures the mesh contains a node exactly at the specified location for "
            "accurate field probing."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "X coordinate in mm",
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate in mm",
                },
                "z": {
                    "type": "number",
                    "description": "Z coordinate in mm",
                },
                "name": {
                    "type": "string",
                    "description": "Optional name for the fixed mesh point",
                },
            },
            "required": ["x", "y", "z"],
        },
    ),
]

async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a mesh tool call."""
    try:
        if name == "cst_set_mesh_type":
            return _set_mesh_type(arguments, client)
        elif name == "cst_set_mesh_density":
            return _set_mesh_density(arguments, client)
        elif name == "cst_add_mesh_refinement":
            return _add_mesh_refinement(arguments, client)
        elif name == "cst_set_adaptive_mesh":
            return _set_adaptive_mesh(arguments, client)
        elif name == "cst_get_mesh_info":
            return _get_mesh_info(arguments, client)
        elif name == "cst_get_mesh_quality":
            return _get_mesh_quality(arguments, client)
        elif name == "cst_set_pml_properties":
            return _set_pml_properties(arguments, client)
        elif name == "cst_add_fixpoint_mesh":
            return _add_fixpoint_mesh(arguments, client)

        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": f"Unknown mesh tool: {name}"}, indent=2),
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


def _set_mesh_type(arguments: dict, client: CSTClient) -> list[TextContent]:
    mesh_type = arguments.get("mesh_type", "")
    validate_enum_value(mesh_type, MeshType, "mesh_type")

    vba = VBABuilder("Mesh")
    vba.set("MeshType", mesh_type)
    script = vba.build()

    result = client.execute_vba(script)
    result["mesh_type"] = mesh_type
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _set_mesh_density(arguments: dict, client: CSTClient) -> list[TextContent]:
    cells_per_wavelength = int(arguments.get("cells_per_wavelength", 15))
    min_cells = int(arguments.get("min_cells", 5))
    ratio_limit = float(arguments.get("ratio_limit", 20))

    validate_positive(cells_per_wavelength, "cells_per_wavelength")
    validate_positive(min_cells, "min_cells")
    validate_positive(ratio_limit, "ratio_limit")

    vba = VBABuilder("Mesh")
    vba.set_number("LinesPerWavelength", cells_per_wavelength)
    vba.set_number("MinimumStepNumber", min_cells)
    vba.set_number("RatioLimit", ratio_limit)
    script = vba.build()

    result = client.execute_vba(script)
    result["cells_per_wavelength"] = cells_per_wavelength
    result["min_cells"] = min_cells
    result["ratio_limit"] = ratio_limit
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _add_mesh_refinement(arguments: dict, client: CSTClient) -> list[TextContent]:
    component = arguments.get("component", "")
    solid = arguments.get("solid", "")
    refinement_factor = float(arguments.get("refinement_factor", 2.0))

    validate_name(component, "component")
    validate_name(solid, "solid")
    validate_positive(refinement_factor, "refinement_factor")

    vba = VBABuilder("MeshAdaption3D")
    vba.set("Name", f"{component}:{solid}")
    vba.set_number("RefinementFactor", refinement_factor)
    vba.call("SetLocalRefinement")
    script = vba.build()

    result = client.execute_vba(script)
    result["component"] = component
    result["solid"] = solid
    result["refinement_factor"] = refinement_factor
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _set_adaptive_mesh(arguments: dict, client: CSTClient) -> list[TextContent]:
    enabled = arguments.get("enabled", True)
    max_passes = int(arguments.get("max_passes", 3))
    threshold = float(arguments.get("threshold", 0.02))

    if max_passes < 1:
        max_passes = 1
    validate_range(max_passes, 1, 100, "max_passes")
    validate_positive(threshold, "threshold")

    vba = VBABuilder("MeshAdaption3D")
    vba.set_bool("Enabled", enabled)
    vba.set_number("MaxPasses", max_passes)
    vba.set_number("ConvergenceThreshold", threshold)
    script = vba.build()

    result = client.execute_vba(script)
    result["enabled"] = enabled
    result["max_passes"] = max_passes
    result["threshold"] = threshold
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _get_mesh_info(arguments: dict, client: CSTClient) -> list[TextContent]:
    # Build VBA that queries mesh statistics
    vba = VBABuilder("Mesh")
    vba.call("Update")
    script = vba.build()

    if client.connected:
        result = client.execute_vba(script)
    else:
        result = {
            "status": "offline",
            "vba": script,
            "description": (
                "In connected mode this would return mesh statistics including: "
                "total number of mesh cells, mesh type, cells per wavelength, "
                "minimum/maximum cell sizes, and mesh quality metrics. "
                "Execute the VBA in CST to update and inspect the mesh."
            ),
            "expected_fields": [
                "total_cells",
                "mesh_type",
                "cells_per_wavelength",
                "min_cell_size",
                "max_cell_size",
                "ratio_limit",
            ],
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _get_mesh_quality(arguments: dict, client: CSTClient) -> list[TextContent]:
    vba = VBABuilder("Mesh")
    vba.call("Update")
    script = vba.build()

    if client.connected:
        result = client.execute_vba(script)
    else:
        result = {
            "status": "offline",
            "vba": script,
            "description": (
                "In connected mode this would return mesh quality metrics including: "
                "total number of mesh cells, minimum and maximum aspect ratios, "
                "cells per wavelength at the highest frequency, and mesh quality "
                "histogram data. Execute the VBA in CST to update and inspect the mesh."
            ),
            "expected_fields": [
                "total_cells",
                "min_aspect_ratio",
                "max_aspect_ratio",
                "cells_per_wavelength",
                "mesh_quality_score",
            ],
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _set_pml_properties(arguments: dict, client: CSTClient) -> list[TextContent]:
    num_layers = int(arguments.get("num_layers", 4))
    reflection_level_db = float(arguments.get("reflection_level_db", -40))

    validate_range(num_layers, 4, 12, "num_layers")
    validate_range(reflection_level_db, -80, -20, "reflection_level_db")

    vba = VBABuilder("Boundary")
    vba.set_number("SetPMLMinimumLayers", num_layers)
    vba.set_number("SetPMLReflectionLevel", reflection_level_db)
    script = vba.build()

    result = client.execute_vba(script)
    result["num_layers"] = num_layers
    result["reflection_level_db"] = reflection_level_db
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _add_fixpoint_mesh(arguments: dict, client: CSTClient) -> list[TextContent]:
    x = float(arguments["x"])
    y = float(arguments["y"])
    z = float(arguments["z"])
    name = arguments.get("name")

    if name is not None:
        validate_name(name, "name")

    vba = VBABuilder("Mesh")
    if name is not None:
        vba.set("FixedPointName", name)
    vba.set_triple("AddFixedPoint", x, y, z)
    script = vba.build()

    result = client.execute_vba(script)
    result["x"] = x
    result["y"] = y
    result["z"] = z
    if name is not None:
        result["name"] = name
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def register_mesh_tools(server: Server, client: CSTClient) -> None:
    """Register mesh tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
