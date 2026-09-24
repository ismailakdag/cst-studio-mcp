"""CAD import/export tools for CST Studio Suite.

Provides 5 MCP tools for importing CAD files (STEP, IGES, STL, SAT, DXF, OBJ),
exporting models, and handling Touchstone and far-field data files.
"""

from __future__ import annotations

import json
from typing import Callable

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBABuilder, VBAScript
from cst_mcp.validators import validate_file_path, validate_name
from cst_mcp.vba_safety import validate_file_path as _vba_file_path
from cst_mcp.vba_safety import vba_escape, vba_number


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
                        "Export format: csv = realized-gain table of the selected farfield via the "
                        "ASCIIExport object; ffs = farfield SOURCE file via "
                        "FarfieldPlot.ASCIIExportAsSource (for excitation, not a gain table); "
                        "nsf is not documented in CST 2026 and returns an error."
                    ),
                    "default": "csv",
                },
                "monitor_name": {
                    "type": "string",
                    "description": "Exact farfield tree name under Farfields (e.g. 'farfield (f=2.4) [1]').",
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
    raise ValueError("TouchstoneImport is not a documented 3D VBA object. A Touchstone network needs an explicit schematic block or lumped-element pin mapping, which this tool's port_number-only schema cannot represent. No project was changed. Use cst_read_help for LumpedElement or the schematic API before defining the connection.")


def _build_export_touchstone(args: dict) -> str:
    """Build VBA script for Touchstone S-parameter export."""
    file_path = validate_file_path(args["file_path"])
    fmt = args.get("format", "s2p")

    script = VBAScript()
    script.add_comment(f"Export S-parameters as Touchstone ({fmt}): {file_path}")

    vba = (
        VBABuilder("TOUCHSTONE")
        .call("Reset")
        .set("FileName", file_path)
        .set("Format", "RI")
        .set("Impedance", "50")
        .set("ExportType", "S")
        .set("FrequencyRange", "Full")
        .set_bool("Renormalize", True)
        .call("Write")
    )

    script.add_block(vba)
    return script.build()


def _farfield_export_tree(args: dict) -> str:
    monitor = args.get("monitor_name")
    if monitor:
        return f"Farfields\\{vba_escape(monitor, 'monitor_name')}"
    return f"Farfields\\farfield (f={vba_number(args['frequency'], 'frequency')})"


def _build_export_farfield(args: dict) -> str:
    """Far-field export using only documented CST 2026 VBA.

    * ``csv`` (gain table): SelectTreeItem + ``FarfieldPlot.Plot`` + the
      ``ASCIIExport`` object (help: supports "1D and 2D/3D farfields").
      ``FarfieldPlot`` itself has no ``ASCIIExport``/``Export`` method.
    * ``ffs``: ``FarfieldPlot.ASCIIExportAsSource`` -- a farfield *source*
      file for excitation, not a gain table.
    * ``nsf``: no documented FarfieldPlot export exists -> error.
    """
    file_path = _vba_file_path(validate_file_path(args["file_path"]))
    frequency = float(vba_number(args["frequency"], "frequency"))
    fmt = args.get("format", "csv")

    if frequency <= 0:
        raise ValueError("Frequency must be positive")
    if frequency > 1000:
        raise ValueError(f"Frequency {frequency} GHz exceeds 1 THz maximum")
    if fmt == "nsf":
        raise ValueError(
            "format 'nsf' is not supported: the CST 2026 FarfieldPlot object documents no NSI "
            "export. Use 'csv' (gain table via ASCIIExport) or 'ffs' (ASCIIExportAsSource)."
        )
    if fmt not in {"csv", "ffs"}:
        raise ValueError("format must be 'csv' or 'ffs'")

    tree = _farfield_export_tree(args)
    script = VBAScript()
    script.add_comment(f"Export far-field data at {frequency} GHz ({fmt}): {file_path}")
    lines = [
        f'If Not SelectTreeItem("{tree}") Then',
        f'  Err.Raise vbObjectError + 1, , "Farfield tree item not found: {tree}"',
        "End If",
    ]
    if fmt == "ffs":
        lines += [
            "With FarfieldPlot",
            '  .Plottype ("3d")',
            "  .Plot",
            f'  .ASCIIExportAsSource ("{file_path}")',
            "End With",
        ]
    else:
        lines += [
            "With FarfieldPlot",
            '  .Plottype ("3d")',
            '  .SetPlotMode ("realized gain")',
            "  .SetScaleLinear (False)",
            "  .Plot",
            "End With",
            "With ASCIIExport",
            "  .Reset",
            f'  .FileName ("{file_path}")',
            "  .Execute",
            "End With",
        ]
    script.add_raw("\n".join(lines))
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
        if name == "cst_export_farfield" and getattr(client, "connected", False):
            fmt = arguments.get("format", "csv")
            if fmt == "csv" and hasattr(client, "export_farfield_ascii"):
                # Documented, history-free path (SelectTreeItem + Plot + ASCIIExport)
                # with farfield tree-name discovery.
                result = client.export_farfield_ascii(
                    float(arguments["frequency"]),
                    filepath=arguments["file_path"],
                    monitor_name=arguments.get("monitor_name"),
                )
            elif fmt == "ffs" and not arguments.get("monitor_name"):
                # Live CST 2026: after a TD solve the item is "farfield (f=X) [1]";
                # try the documented tree-name variants until SelectTreeItem succeeds.
                from cst_mcp.execution.farfield import farfield_tree_candidates

                tried = []
                result = {"status": "error", "message": "No farfield tree item found"}
                for tree in farfield_tree_candidates(float(arguments["frequency"])):
                    if not tree.startswith("Farfields\\"):
                        continue
                    label = tree.split("\\", 1)[1]
                    tried.append(tree)
                    result = client.execute_vba_silent(
                        builder_fn({**arguments, "monitor_name": label}), history_fallback=False
                    )
                    if result.get("status") == "executed":
                        result["tree_path"] = tree
                        break
                result["tried_paths"] = tried
            else:
                result = client.execute_vba_silent(vba_code, history_fallback=False)
        else:
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


# Reject line breaks and non-numeric values in numeric slots before any VBA
# is generated from the arguments (generated VBA bypasses CST_ALLOW_RAW_VBA).
from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
