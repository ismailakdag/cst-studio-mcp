"""CAD import/export tools for CST Studio Suite.

Provides 5 MCP tools for importing CAD files (STEP, IGES, STL, SAT, DXF, OBJ),
exporting models, and handling Touchstone and far-field data files.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBABuilder, VBAScript
from cst_mcp.validators import validate_file_path, validate_name

if TYPE_CHECKING:
    from mcp.server import Server

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # 1. Import CAD
    Tool(
        name="cst_import_cad",
        description=(
            "Import a CAD file into CST Studio. Supports STEP (.stp/.step), "
            "IGES (.igs/.iges), STL (.stl), SAT/ACIS (.sat), DXF (.dxf), "
            "and OBJ (.obj) formats."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Full path to the CAD file to import.",
                },
                "format": {
                    "type": "string",
                    "enum": ["stp", "igs", "stl", "sat", "dxf", "obj"],
                    "description": "CAD file format: stp (STEP), igs (IGES), stl, sat (ACIS), dxf, obj.",
                },
                "component": {
                    "type": "string",
                    "description": "Target component name for the imported geometry.",
                    "default": "Import",
                },
            },
            "required": ["file_path", "format"],
        },
    ),

    # 2. Export CAD
    Tool(
        name="cst_export_cad",
        description=(
            "Export the current CST model (or a specific component) to a CAD format. "
            "Supports STL, SAT/ACIS, STEP, IGES, OBJ, and NASTRAN."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Destination file path for the exported CAD file.",
                },
                "format": {
                    "type": "string",
                    "enum": ["stl", "sat", "stp", "igs", "obj", "nas"],
                    "description": "Export format: stl, sat, stp (STEP), igs (IGES), obj, nas (NASTRAN).",
                },
                "component": {
                    "type": "string",
                    "description": (
                        "Optional component name to export. If omitted, the entire model is exported."
                    ),
                },
            },
            "required": ["file_path", "format"],
        },
    ),

    # 3. Import Touchstone
    Tool(
        name="cst_import_touchstone",
        description=(
            "Import a Touchstone S-parameter file (.s1p, .s2p, .snp) into CST Studio "
            "for use as a reference or circuit element."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Full path to the Touchstone file (.s1p, .s2p, etc.).",
                },
                "port_number": {
                    "type": "integer",
                    "description": "Port number to associate the imported data with.",
                    "default": 1,
                },
            },
            "required": ["file_path"],
        },
    ),

    # 4. Export Touchstone
    Tool(
        name="cst_export_touchstone",
        description=(
            "Export S-parameter simulation results to a Touchstone file. "
            "Requires a completed simulation with S-parameter data."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Destination file path for the Touchstone file.",
                },
                "format": {
                    "type": "string",
                    "enum": ["s1p", "s2p", "snp"],
                    "description": "Touchstone format: s1p (1-port), s2p (2-port), snp (n-port).",
                    "default": "s2p",
                },
            },
            "required": ["file_path"],
        },
    ),

    # 5. Export far-field
    Tool(
        name="cst_export_farfield",
        description=(
            "Export far-field radiation pattern data to a file. "
            "Requires a completed simulation with far-field monitor results."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Destination file path for the far-field data.",
                },
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz for the far-field data to export.",
                },
                "format": {
                    "type": "string",
                    "enum": ["csv", "ffs", "nsf"],
                    "description": (
                        "Export format: csv (comma-separated), ffs (CST far-field source), "
                        "nsf (NSI near-to-far-field)."
                    ),
                    "default": "csv",
                },
            },
            "required": ["file_path", "frequency"],
        },
    ),
]


# ---------------------------------------------------------------------------
# VBA generation helpers
# ---------------------------------------------------------------------------

# Maps import format to CST VBA import object name
_IMPORT_OBJECTS: dict[str, str] = {
    "sat": "SAT",
    "stp": "STEP",
    "stl": "STL",
    "igs": "IGES",
    "dxf": "DXF",
    "obj": "OBJ",
}

# Maps export format to CST VBA export object name
_EXPORT_OBJECTS: dict[str, str] = {
    "stl": "STL",
    "sat": "SAT",
    "stp": "STEP",
    "igs": "IGES",
    "obj": "OBJ",
    "nas": "NASTRAN",
}


def _build_import_cad(args: dict) -> str:
    """Build VBA script for CAD file import."""
    file_path = validate_file_path(args["file_path"])
    fmt = args["format"]
    component = validate_name(args.get("component", "Import"), "component")

    cst_object = _IMPORT_OBJECTS.get(fmt, fmt.upper())

    script = VBAScript()
    script.add_comment(f"Import {fmt.upper()} file: {file_path}")

    vba = (
        VBABuilder(cst_object)
        .call("Reset")
        .set("FileName", file_path)
        .set("Name", component)
        .set("Component", component)
    )

    # Format-specific options
    if fmt == "stl":
        vba.set("ScaleToUnit", "True")
    elif fmt in ("stp", "sat"):
        vba.set_bool("Healing", True)
    elif fmt == "igs":
        vba.set_bool("Healing", True)

    vba.call("Read")
    script.add_block(vba)
    return script.build()


def _build_export_cad(args: dict) -> str:
    """Build VBA script for CAD file export."""
    file_path = validate_file_path(args["file_path"])
    fmt = args["format"]
    component = args.get("component")

    if component:
        validate_name(component, "component")

    cst_object = _EXPORT_OBJECTS.get(fmt, fmt.upper())

    script = VBAScript()
    script.add_comment(f"Export model to {fmt.upper()}: {file_path}")

    vba = (
        VBABuilder(cst_object)
        .call("Reset")
        .set("FileName", file_path)
    )

    if component:
        vba.set("Component", component)

    vba.call("Write")
    script.add_block(vba)
    return script.build()


def _build_import_touchstone(args: dict) -> str:
    """Build VBA script for Touchstone file import."""
    file_path = validate_file_path(args["file_path"])
    port_number = int(args.get("port_number", 1))

    script = VBAScript()
    script.add_comment(f"Import Touchstone file: {file_path}")

    vba = (
        VBABuilder("TouchstoneImport")
        .call("Reset")
        .set("FileName", file_path)
        .set_number("PortNumber", port_number)
        .set("Impedance", "50")
        .set("FrequencyUnit", "GHz")
        .call("Execute")
    )

    script.add_block(vba)
    return script.build()


def _build_export_touchstone(args: dict) -> str:
    """Build VBA script for Touchstone S-parameter export."""
    file_path = validate_file_path(args["file_path"])
    fmt = args.get("format", "s2p")

    script = VBAScript()
    script.add_comment(f"Export S-parameters as Touchstone ({fmt}): {file_path}")

    vba = (
        VBABuilder("TouchstoneExport")
        .call("Reset")
        .set("FileName", file_path)
        .set("Format", fmt)
        .set("Impedance", "50")
        .set("FrequencyUnit", "GHz")
        .call("Execute")
    )

    script.add_block(vba)
    return script.build()


def _build_export_farfield(args: dict) -> str:
    """Build VBA script for far-field data export."""
    file_path = validate_file_path(args["file_path"])
    frequency = float(args["frequency"])
    fmt = args.get("format", "csv")

    if frequency <= 0:
        raise ValueError("Frequency must be positive")
    if frequency > 1000:
        raise ValueError(f"Frequency {frequency} GHz exceeds 1 THz maximum")

    script = VBAScript()
    script.add_comment(f"Export far-field data at {frequency} GHz: {file_path}")

    # CST far-field export uses the FarfieldPlot object
    vba = (
        VBABuilder("FarfieldPlot")
        .call("Reset")
        .set("Frequency", str(frequency))
    )

    # Set export type based on format
    if fmt == "ffs":
        vba.set("ExportType", "FarfieldSource")
    elif fmt == "nsf":
        vba.set("ExportType", "NSI")
    else:
        vba.set("ExportType", "ASCII")

    vba.set("FileName", file_path)
    vba.call("Export")

    script.add_block(vba)
    return script.build()


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[..., str]] = {
    "cst_import_cad": _build_import_cad,
    "cst_export_cad": _build_export_cad,
    "cst_import_touchstone": _build_import_touchstone,
    "cst_export_touchstone": _build_export_touchstone,
    "cst_export_farfield": _build_export_farfield,
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def _text(data: dict) -> list[TextContent]:
    """Wrap a dict as a single JSON TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


async def handle(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle an import/export tool call.

    Generates VBA via VBABuilder, executes through the CSTClient, and
    returns the result wrapped in TextContent.
    """
    try:
        builder_fn = _HANDLERS.get(name)
        if builder_fn is None:
            return _text({"status": "error", "message": f"Unknown import/export tool: {name}"})

        vba_code = builder_fn(arguments)
        result = client.execute_vba(vba_code)

        # Annotate result with tool-specific metadata
        if name == "cst_import_cad":
            result["imported_file"] = arguments["file_path"]
            result["format"] = arguments["format"]
            result["component"] = arguments.get("component", "Import")
        elif name == "cst_export_cad":
            result["exported_file"] = arguments["file_path"]
            result["format"] = arguments["format"]
            if arguments.get("component"):
                result["component"] = arguments["component"]
        elif name == "cst_import_touchstone":
            result["imported_file"] = arguments["file_path"]
            result["port_number"] = arguments.get("port_number", 1)
        elif name == "cst_export_touchstone":
            result["exported_file"] = arguments["file_path"]
            result["format"] = arguments.get("format", "s2p")
        elif name == "cst_export_farfield":
            result["exported_file"] = arguments["file_path"]
            result["frequency_ghz"] = arguments["frequency"]
            result["format"] = arguments.get("format", "csv")

        return _text(result)
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


# ---------------------------------------------------------------------------
# Registration helper (called from tools/__init__.py)
# ---------------------------------------------------------------------------


def register_import_export_tools(server: Server, client: CSTClient) -> None:
    """Register import/export tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
