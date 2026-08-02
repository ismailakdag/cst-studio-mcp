"""Project management tools for CST Studio MCP server.

Provides 8 tools for creating, opening, saving, closing, inspecting,
navigating, exporting, and checking connection status of CST projects.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.types import ExportFormat, ProjectType
from cst_mcp.validators import validate_file_path, ValidationError
from cst_mcp.vba_builder import VBABuilder, VBAScript, _escape_vba_string

if TYPE_CHECKING:
    from mcp.server import Server

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="cst_create_project",
        description=(
            "Create a new CST Studio Suite project file. "
            "In connected mode the project is created directly; "
            "in offline mode a VBA script is returned for manual execution."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Full file path for the new project, "
                        "e.g. 'C:/cst_projects/MyAntenna.cst'."
                    ),
                },
                "project_type": {
                    "type": "string",
                    "description": (
                        "CST project type. One of: MWS (Microwave Studio), "
                        "EMS (EM Studio), PS (Particle Studio), "
                        "MPS (Mphysics Studio), CS (Cable Studio), "
                        "DS (Design Studio), PCB (PCB Studio)."
                    ),
                    "default": "MWS",
                    "enum": [e.value for e in ProjectType],
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="cst_open_project",
        description=(
            "Open an existing CST Studio Suite project. "
            "In connected mode the project is opened in the running instance; "
            "in offline mode a reference is stored for subsequent operations."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Full file path of the existing .cst project to open.",
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="cst_save_project",
        description=(
            "Save the currently open CST project. "
            "Optionally provide a new path to 'Save As'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Optional file path for 'Save As'. "
                        "If omitted, saves to the current project path."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_close_project",
        description=(
            "Close the currently open CST project and release its resources."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_project_info",
        description=(
            "Get information about the currently open CST project, "
            "including connection mode, project path, and status."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_project_tree",
        description=(
            "List items in the CST project navigation tree. "
            "Optionally specify a subtree path such as 'Components', "
            "'Materials', 'Ports', 'Monitors', or 'Results'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tree_path": {
                    "type": "string",
                    "description": (
                        "Navigation tree path to list, e.g. 'Components', "
                        "'Results', or '2D/3D Results'. "
                        "Omit for the root tree."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_export_project",
        description=(
            "Export the current CST project or its geometry to another format "
            "such as STL, STEP, IGES, SAT, OBJ, or NASTRAN."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Destination file path for the exported file.",
                },
                "format": {
                    "type": "string",
                    "description": (
                        "Export format. One of: stl, sat, stp, igs, obj, nas."
                    ),
                    "enum": [e.value for e in ExportFormat],
                },
            },
            "required": ["path", "format"],
        },
    ),
    Tool(
        name="cst_connection_status",
        description=(
            "Get the current CST Studio connection status, including mode "
            "(connected/offline), CST availability, version, and work directory."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(data: dict) -> list[TextContent]:
    """Wrap a dict as a single JSON TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


def _build_create_vba(path: str, project_type: str) -> str:
    """Build VBA script for creating a new CST project."""
    script = VBAScript()
    script.add_comment(f"Create new CST {project_type} project: {path}")
    script.add_blank()

    # The VBA to create a project from scratch uses the application object.
    # Different project types map to different CST template strings.
    type_templates = {
        "MWS": "MW & RF & Optical",
        "EMS": "EDA / Electronics",
        "PS": "Charged Particle Dynamics",
        "MPS": "Statics and Low Frequency",
        "CS": "Cable & Harness",
        "DS": "Design Studio",
        "PCB": "EDA / Electronics",
    }
    template = type_templates.get(project_type, "MW & RF & Optical")

    lines = [
        "Sub Main()",
        '  Dim sPath As String',
        f'  sPath = "{path}"',
        "",
        "  ' Open a new project from the appropriate template",
        f'  StoreTemplateSetting "TemplateType", "{template}"',
        "  OpenNewProject",
        "",
        "  ' Save the project to the specified path",
        '  SaveAs sPath, False',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_open_vba(path: str) -> str:
    """Build VBA script for opening a CST project."""
    script = VBAScript()
    script.add_comment(f"Open CST project: {path}")
    script.add_blank()
    lines = [
        "Sub Main()",
        f'  OpenFile("{path}")',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_save_vba(path: str | None) -> str:
    """Build VBA script for saving a CST project."""
    script = VBAScript()
    if path:
        script.add_comment(f"Save CST project as: {path}")
        script.add_blank()
        lines = [
            "Sub Main()",
            f'  SaveAs "{path}", False',
            "End Sub",
        ]
    else:
        script.add_comment("Save current CST project")
        script.add_blank()
        lines = [
            "Sub Main()",
            "  Save",
            "End Sub",
        ]
    script.add_raw("\n".join(lines))
    return script.build()


# Regex for valid tree paths: alphanumeric, spaces, backslashes, forward slashes,
# underscores, hyphens, dots, and commas (for result paths like "S1,1")
_VALID_TREE_PATH_RE = re.compile(r"^[A-Za-z0-9 \\/_.,-]{0,200}$")


def _validate_tree_path(path: str) -> str:
    """Validate a CST navigation tree path."""
    if not _VALID_TREE_PATH_RE.match(path):
        raise ValidationError(
            f"Invalid tree path '{path}': must contain only alphanumeric, "
            "spaces, backslashes, forward slashes, underscores, hyphens, "
            "dots, and commas (max 200 chars)"
        )
    return path


def _build_tree_vba(tree_path: str | None) -> str:
    """Build VBA script for listing navigation tree items."""
    script = VBAScript()
    root = tree_path or ""
    if root:
        _validate_tree_path(root)
        script.add_comment(f"List CST navigation tree items under: {root}")
    else:
        script.add_comment("List CST navigation tree root items")
    script.add_blank()

    safe_root = _escape_vba_string(root)

    lines = [
        "Sub Main()",
        '  Dim sPath As String',
        f'  sPath = "{safe_root}"',
        "",
        "  SelectTreeItem sPath",
        "  Dim nItems As Long",
        "  nItems = GetNumberOfSelectedTreeItems()",
        "  Dim i As Long",
        "  For i = 0 To nItems - 1",
        "    Dim sItem As String",
        "    sItem = GetSelectedTreeItem(i)",
        '    Debug.Print sItem',
        "  Next i",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_export_vba(path: str, fmt: str) -> str:
    """Build VBA script for exporting project geometry."""
    script = VBAScript()
    script.add_comment(f"Export CST geometry to {fmt.upper()}: {path}")
    script.add_blank()

    # Map format to the CST VBA export command
    format_commands = {
        "stl": "STL",
        "sat": "SAT",
        "stp": "STEP",
        "igs": "IGES",
        "obj": "OBJ",
        "nas": "NASTRAN",
    }
    cst_format = format_commands.get(fmt, fmt.upper())

    builder = (
        VBABuilder(f"{cst_format}")
        .set("FileName", path)
        .call("Write")
    )
    script.add_block(builder)
    return script.build()


# ---------------------------------------------------------------------------
# Common tree items returned in offline mode
# ---------------------------------------------------------------------------

_DEFAULT_TREE_ITEMS: dict[str, list[str]] = {
    "": [
        "Components",
        "Materials",
        "Ports",
        "Excitation Signals",
        "Boundary Conditions",
        "Monitors",
        "Lumped Elements",
        "Mesh",
        "Solver",
        "2D/3D Results",
        "Tables",
        "Farfields",
    ],
    "Components": [
        "component1",
    ],
    "Materials": [
        "Vacuum",
        "PEC",
    ],
    "Ports": [],
    "Monitors": [],
    "Results": [],
    "2D/3D Results": [],
    "Mesh": [
        "Global Mesh Properties",
        "Local Mesh Properties",
    ],
    "Solver": [
        "Time Domain Solver",
        "Frequency Domain Solver",
        "Eigenmode Solver",
        "Integral Equation Solver",
    ],
}

# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------


async def handle(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle a project management tool call.

    Returns a list of TextContent with JSON-encoded results.
    """
    try:
        return _handle_impl(name, arguments, client)
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


def _handle_impl(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    # ------------------------------------------------------------------
    # cst_create_project
    # ------------------------------------------------------------------
    if name == "cst_create_project":
        path = arguments["path"]
        project_type = arguments.get("project_type", "MWS")

        validate_file_path(path)
        # Validate project_type against the enum
        valid_types = [e.value for e in ProjectType]
        if project_type not in valid_types:
            return _text({
                "status": "error",
                "message": f"Invalid project_type '{project_type}'. Must be one of: {valid_types}",
            })

        result = client.new_project(path, project_type)

        if not client.connected:
            vba = _build_create_vba(path, project_type)
            result["vba_script"] = vba
            result["instructions"] = (
                "Copy the VBA script above and run it in CST Studio Suite "
                "(Macros > Run Macro) on a Windows machine with CST installed."
            )

        return _text(result)

    # ------------------------------------------------------------------
    # cst_open_project
    # ------------------------------------------------------------------
    if name == "cst_open_project":
        path = arguments["path"]
        validate_file_path(path)

        result = client.open_project(path)

        if not client.connected:
            vba = _build_open_vba(path)
            result["vba_script"] = vba
            result["instructions"] = (
                "In offline mode the project path has been stored as a reference. "
                "To actually open this project, run the VBA script in CST Studio Suite."
            )

        return _text(result)

    # ------------------------------------------------------------------
    # cst_save_project
    # ------------------------------------------------------------------
    if name == "cst_save_project":
        path = arguments.get("path")
        if path:
            validate_file_path(path)

        result = client.save_project(path)

        if not client.connected:
            vba = _build_save_vba(path)
            result["vba_script"] = vba
            result["instructions"] = (
                "Save requires a connected CST instance. "
                "Run the VBA script in CST Studio Suite to perform the save."
            )

        return _text(result)

    # ------------------------------------------------------------------
    # cst_close_project
    # ------------------------------------------------------------------
    if name == "cst_close_project":
        result = client.close_project()
        return _text(result)

    # ------------------------------------------------------------------
    # cst_project_info
    # ------------------------------------------------------------------
    if name == "cst_project_info":
        status = client.status()
        info = {
            "mode": status["mode"],
            "project_path": status["project_path"],
            "project_open": status["project_open"],
            "cst_version": status["cst_version"],
            "work_dir": status["work_dir"],
        }

        if not client.connected:
            info["note"] = (
                "Running in offline mode. VBA scripts are generated but not "
                "executed. Connect to a Windows machine with CST installed for "
                "live project interaction."
            )

        return _text(info)

    # ------------------------------------------------------------------
    # cst_project_tree
    # ------------------------------------------------------------------
    if name == "cst_project_tree":
        tree_path = arguments.get("tree_path", "")

        if client.connected:
            # In connected mode, use VBA to query the actual tree
            vba = _build_tree_vba(tree_path or None)
            result = client.execute_vba(vba)
            return _text(result)

        # Offline mode: return known default tree items and a VBA script
        items = _DEFAULT_TREE_ITEMS.get(tree_path, [])
        vba = _build_tree_vba(tree_path or None)
        return _text({
            "status": "offline",
            "tree_path": tree_path or "(root)",
            "items": items,
            "note": (
                "These are default tree items for a new project. "
                "The actual tree depends on your project content."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite to get the actual "
                "project tree contents."
            ),
        })

    # ------------------------------------------------------------------
    # cst_export_project
    # ------------------------------------------------------------------
    if name == "cst_export_project":
        path = arguments["path"]
        fmt = arguments["format"]

        validate_file_path(path)
        valid_formats = [e.value for e in ExportFormat]
        if fmt not in valid_formats:
            return _text({
                "status": "error",
                "message": f"Invalid format '{fmt}'. Must be one of: {valid_formats}",
            })

        vba = _build_export_vba(path, fmt)

        if client.connected:
            result = client.execute_vba(vba)
            if result.get("status") != "error":
                result["exported_path"] = path
                result["format"] = fmt
            return _text(result)

        return _text({
            "status": "offline",
            "path": path,
            "format": fmt,
            "vba_script": vba,
            "instructions": (
                "Export requires a connected CST instance with an open project. "
                "Run the VBA script in CST Studio Suite to export the geometry."
            ),
        })

    # ------------------------------------------------------------------
    # cst_connection_status
    # ------------------------------------------------------------------
    if name == "cst_connection_status":
        return _text(client.status())

    # ------------------------------------------------------------------
    # Unknown tool
    # ------------------------------------------------------------------
    return _text({
        "status": "error",
        "message": f"Unknown project tool: {name}",
    })


# ---------------------------------------------------------------------------
# Registration helper (used by tools/__init__.py)
# ---------------------------------------------------------------------------


def register_project_tools(server: Server, client: CSTClient) -> None:
    """Register project management tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
