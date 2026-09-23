"""Raw VBA access tools for CST Studio Suite.

Provides 3 MCP tools for executing arbitrary VBA code (with best-effort denylist
validation, disabled by default behind ``CST_ALLOW_RAW_VBA``), looking up VBA object
reference documentation, and listing available CST VBA objects.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.validators import (
    RAW_VBA_ENV,
    raw_vba_disabled_message,
    raw_vba_enabled,
    validate_vba_input,
)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # 1. Execute raw VBA
    Tool(
        name="cst_execute_vba",
        description=(
            "Execute raw VBA code in CST Studio Suite (history VBA). DISABLED BY "
            "DEFAULT in connected mode: it only runs when the server process has "
            f"the environment variable {RAW_VBA_ENV}=1 (or true); otherwise an "
            "error is returned. The code is screened by a best-effort denylist, "
            "which is NOT a sandbox and can be evaded: enabling "
            f"{RAW_VBA_ENV} effectively grants the MCP client arbitrary code "
            "execution on this machine with the CST user's privileges. Only "
            "enable it for fully trusted clients. In offline mode the screened "
            "script is returned for manual execution. Prefer the higher-level tools."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "VBA code to execute in CST Studio. Code matching the "
                        "best-effort denylist (program launching, COM objects, "
                        "file I/O, native API declarations, ...) is rejected; this "
                        "screening is not a sandbox."
                    ),
                },
            },
            "required": ["code"],
        },
    ),

    # 2. VBA help / reference
    Tool(
        name="cst_vba_help",
        description=(
            "Get VBA reference documentation for a CST Studio object. Returns "
            "the object description and a list of its common methods and properties."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": (
                        "Name of the CST VBA object to look up, e.g. 'Brick', "
                        "'Solver', 'Material', 'Port', 'Mesh', 'FarfieldPlot'."
                    ),
                },
            },
            "required": ["object_name"],
        },
    ),

    # 3. List VBA objects
    Tool(
        name="cst_list_vba_objects",
        description=(
            "List available CST Studio VBA objects, optionally filtered by category. "
            "Returns object names with brief descriptions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "geometry",
                        "solver",
                        "material",
                        "mesh",
                        "boundary",
                        "excitation",
                        "monitor",
                        "postprocessing",
                        "optimization",
                        "settings",
                        "interaction",
                    ],
                    "description": (
                        "Optional category filter. If omitted, all categories are returned."
                    ),
                },
            },
            "required": [],
        },
    ),
]


# ---------------------------------------------------------------------------
# VBA reference data loader
# ---------------------------------------------------------------------------

_vba_reference: dict | None = None


def _load_vba_reference() -> dict:
    """Load the bundled VBA reference data and group by category.

    The raw JSON has structure ``{"objects": {"Brick": {"category": "geometry", ...}}}``.
    This function returns ``{"geometry": {"Brick": {...}}, ...}`` for easy lookup.
    """
    global _vba_reference
    if _vba_reference is not None:
        return _vba_reference

    raw: dict = {}
    # Locate data/vba_reference.json relative to the package
    data_path = Path(__file__).resolve().parent.parent / "data" / "vba_reference.json"
    if data_path.exists():
        with open(data_path, "r") as f:
            raw = json.load(f)
    else:
        # Fallback: try importlib.resources for installed packages
        try:
            ref = resources.files("cst_mcp") / "data" / "vba_reference.json"
            raw = json.loads(ref.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

    # Restructure from flat {"objects": {name: {category, ...}}} to {category: {name: {...}}}
    grouped: dict[str, dict] = {}
    objects = raw.get("objects", raw)  # support both flat and already-grouped formats
    if isinstance(objects, dict) and all(
        isinstance(v, dict) and "category" in v for v in list(objects.values())[:1]
    ):
        # Flat format: group by category field
        for obj_name, obj_data in objects.items():
            cat = obj_data.get("category", "other")
            if cat not in grouped:
                grouped[cat] = {}
            grouped[cat][obj_name] = obj_data
    else:
        # Already grouped or unknown format — use as-is
        grouped = raw

    _vba_reference = grouped
    return _vba_reference


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


def _handle_execute_vba(args: dict, client: CSTClient) -> dict:
    """Validate and execute raw VBA code."""
    code = args.get("code", "")
    if not code.strip():
        return {"status": "error", "message": "VBA code cannot be empty"}

    # Safety validation — raises ValidationError on dangerous patterns.
    # Best-effort denylist only; the env-var gate below is the real control.
    validate_vba_input(code)

    if not raw_vba_enabled():
        if getattr(client, "is_connected", False):
            return {
                "status": "error",
                "code": "raw_vba_disabled",
                "message": raw_vba_disabled_message(),
            }
        # Offline: never touches CST; hand the validated script back for manual paste.
        return {
            "status": "offline",
            "vba": code,
            "message": (
                "VBA validated but not executed (offline). Paste it into CST manually. "
                f"Connected execution additionally requires {RAW_VBA_ENV}=1."
            ),
        }

    result = client.execute_vba(code)
    return result


def _handle_vba_help(args: dict) -> dict:
    """Look up VBA reference for a specific object."""
    object_name = args.get("object_name", "")
    if not object_name:
        return {"status": "error", "message": "object_name is required"}

    ref = _load_vba_reference()

    # Search across all categories for the object
    for category, objects in ref.items():
        if object_name in objects:
            obj_data = objects[object_name]
            return {
                "status": "ok",
                "object_name": object_name,
                "category": category,
                "description": obj_data.get("description", ""),
                "methods": obj_data.get("methods", []),
                "usage_example": _build_usage_example(object_name, obj_data.get("methods", [])),
            }

    # Try case-insensitive search
    for category, objects in ref.items():
        for name, obj_data in objects.items():
            if name.lower() == object_name.lower():
                return {
                    "status": "ok",
                    "object_name": name,
                    "category": category,
                    "description": obj_data.get("description", ""),
                    "methods": obj_data.get("methods", []),
                    "usage_example": _build_usage_example(name, obj_data.get("methods", [])),
                }

    # Not found — list available objects as suggestion
    all_objects = []
    for category, objects in ref.items():
        all_objects.extend(objects.keys())

    return {
        "status": "not_found",
        "message": f"VBA object '{object_name}' not found in reference.",
        "available_objects": sorted(all_objects),
        "hint": "Use cst_list_vba_objects to browse objects by category.",
    }


def _handle_list_vba_objects(args: dict) -> dict:
    """List VBA objects, optionally filtered by category."""
    category = args.get("category")
    ref = _load_vba_reference()

    if category:
        if category not in ref:
            return {
                "status": "error",
                "message": f"Unknown category '{category}'.",
                "valid_categories": sorted(ref.keys()),
            }
        objects = ref[category]
        return {
            "status": "ok",
            "category": category,
            "objects": {
                name: data.get("description", "")
                for name, data in objects.items()
            },
        }

    # Return all categories with their objects
    result = {"status": "ok", "categories": {}}
    for cat, objects in ref.items():
        result["categories"][cat] = {  # type: ignore[index]
            name: data.get("description", "")
            for name, data in objects.items()
        }
    return result


_NO_ARG_METHODS = frozenset({
    "Reset", "Create", "Delete", "Start", "Execute", "Apply",
    "Update", "Write", "Read", "Export",
})


def _build_usage_example(object_name: str, methods: list) -> str:
    """Build a simple VBA usage example for an object.

    *methods* may be a list of strings or a list of dicts with ``name``/``args`` keys.
    """
    if not methods:
        return ""

    lines = [f"With {object_name}"]
    for method in methods[:5]:  # Show first 5 methods as example
        # Handle both dict ({"name": ..., "args": ...}) and plain string formats
        if isinstance(method, dict):
            name = method.get("name", "")
            has_args = bool(method.get("args"))
        else:
            name = str(method)
            has_args = name not in _NO_ARG_METHODS

        if not name:
            continue

        if name in _NO_ARG_METHODS or not has_args:
            lines.append(f"  .{name}")
        else:
            lines.append(f'  .{name} "value"')
    if len(methods) > 5:
        lines.append(f"  ' ... and {len(methods) - 5} more methods")
    lines.append("End With")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def _text(data: dict) -> list[TextContent]:
    """Wrap a dict as a single JSON TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


async def handle(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle a VBA tool call.

    Routes to the appropriate handler and returns results wrapped in TextContent.
    """
    try:
        if name == "cst_execute_vba":
            result = _handle_execute_vba(arguments, client)
            return _text(result)

        elif name == "cst_vba_help":
            import re
            from cst_mcp.tools.official import handle as official_help
            if client.config.cst_path:
                search = await official_help("cst_search_help", {"query": arguments["object_name"], "limit": 50}, client)
                candidates = json.loads(search[0].text).get("topics", [])
                for topic in candidates:
                    if re.search(re.escape(arguments["object_name"]) + r"(?:_object)?\.html?$", topic, re.I):
                        return await official_help("cst_read_help", {"topic": topic}, client)
            result = _handle_vba_help(arguments)
            result["source"] = "bundled legacy reference; not verified against installed CST"
            result["hint"] = "Prefer cst_search_help / cst_read_help. Example generation is illustrative, not an executable API signature check."
            return _text(result)

        elif name == "cst_list_vba_objects":
            result = _handle_list_vba_objects(arguments)
            return _text(result)

        return _text({"status": "error", "message": f"Unknown VBA tool: {name}"})

    except Exception as e:
        return _text({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# Registration helper (called from tools/__init__.py)
# ---------------------------------------------------------------------------


from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle, allow_multiline=frozenset({"code"}))
