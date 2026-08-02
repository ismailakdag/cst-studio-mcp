"""Diagnostic tools for CST Studio Suite.

Provides tools for managing simulation results, reading project
messages/logs, and handling CST dialog windows — essential for
preventing blocking popups during automation.

- ``cst_delete_results``: Delete simulation results (prevents stale-result dialogs)
- ``cst_read_project_log``: Read solver log and project messages
- ``cst_dismiss_dialogs``: Find and dismiss CST dialog windows (read their content)
- ``cst_start_dialog_watcher``: Auto-dismiss dialogs in background during long ops
- ``cst_stop_dialog_watcher``: Stop the background dialog watcher and get its log
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient

if TYPE_CHECKING:
    from mcp.server import Server

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="cst_delete_results",
        description=(
            "Delete simulation results from the current CST project. "
            "This prevents the 'Results May Get Incompatible With Model' "
            "dialog that blocks automation when modifying a model with "
            "existing results. Call before making parameter or geometry "
            "changes on a project that has been solved."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_read_project_log",
        description=(
            "Read solver log files and project status information from "
            "the current CST project. Returns solver running state and "
            "the contents of the most recent log file. Useful for "
            "diagnosing solver errors, checking simulation progress, "
            "and understanding what happened during a failed run."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_dismiss_dialogs",
        description=(
            "Find and dismiss any visible CST dialog windows (error popups, "
            "'Results Incompatible' dialogs, solver warnings). Returns the "
            "title and text content of each dialog before dismissing it. "
            "Use this to unblock CST when a modal dialog is preventing "
            "further automation. Uses Win32 API on Windows."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "read_only": {
                    "type": "boolean",
                    "description": (
                        "If true, only read dialog content without dismissing. "
                        "Default: false (read and dismiss)."
                    ),
                    "default": False,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_start_dialog_watcher",
        description=(
            "Start a background thread that automatically detects and "
            "dismisses CST dialog windows as they appear. Essential for "
            "long-running operations like optimization loops where dialogs "
            "would otherwise block execution. The watcher logs every dialog "
            "it dismisses — retrieve the log with cst_stop_dialog_watcher."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_stop_dialog_watcher",
        description=(
            "Stop the background dialog watcher and return its log of all "
            "dialogs that were auto-dismissed. Use after completing an "
            "operation that required the watcher."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]

_TOOL_NAMES = {t.name for t in TOOLS}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _text(data: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a diagnostics tool call."""
    try:
        if name == "cst_delete_results":
            return _text(client.delete_results())

        if name == "cst_read_project_log":
            return _text(client.read_project_messages())

        if name == "cst_dismiss_dialogs":
            read_only = arguments.get("read_only", False)
            if read_only:
                return _text(client.read_dialogs())
            return _text(client.dismiss_dialogs())

        if name == "cst_start_dialog_watcher":
            return _text(client.start_dialog_watcher())

        if name == "cst_stop_dialog_watcher":
            return _text(client.stop_dialog_watcher())

        return _text({"status": "error", "message": f"Unknown diagnostics tool: {name}"})
    except Exception as e:
        return _text({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_diagnostics_tools(server: Server, client: CSTClient) -> None:
    """Register diagnostics tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
