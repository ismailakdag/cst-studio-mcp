"""Explicit CST attachment; ordinary MCP initialization stays side-effect free."""
from __future__ import annotations

from mcp.types import Tool

from cst_mcp.tools.registry import as_json, err

TOOLS = [
    Tool(
        name="cst_connect",
        description=(
            "Explicitly attach to a CST Design Environment (DE). Disabled mode never connects. "
            "mode='any' (default) uses connect_to_any_or_new(): it attaches to ANY running DE, "
            "including one the user opened interactively (and adopts its active project), or starts "
            "a new DE when none is running. mode='new' always starts a fresh DE via "
            "DesignEnvironment.new() and never touches an existing DE or its projects; prefer it for "
            "unattended/batch work while the user may have CST open. The response reports de_pid, "
            "newly_started, running_des_before and open_project_paths so you can see what was attached; "
            "a 'warning' is added when the DE may be a pre-existing (user) session."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["any", "new"],
                    "default": "any",
                    "description": "'any' = attach to any running DE or start one; 'new' = always start a fresh DE.",
                }
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="cst_disconnect",
        description="Detach this MCP session without closing CST, projects, or a running solver.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
]


async def handle(name, arguments, client):
    if name == "cst_connect":
        if client.config.connect_mode == "disabled":
            return err("CST connection is disabled. Set CST_CONNECT_MODE=manual and restart the MCP server.")
        mode = (arguments or {}).get("mode", "any")
        if mode not in ("any", "new"):
            return err(f"Unknown mode {mode!r}; use 'any' or 'new'.")
        if client.connected:
            pid = None
            try:
                pid = client._de_pid(getattr(client, "_de", None))
            except Exception:  # noqa: BLE001
                pid = None
            message = "Already connected; session preserved."
            if mode == "new":
                message += " Call cst_disconnect first to start a fresh Design Environment with mode='new'."
            return as_json(
                {
                    "status": "connected",
                    "message": message,
                    "de_pid": pid,
                    "project_path": getattr(client, "project_path", None),
                }
            )
        result = client.connect(mode=mode)
        if result.get("status") != "connected":
            return err(result.get("message", "Could not connect to CST"), connection=result)
        return as_json(result)
    if name == "cst_disconnect":
        return as_json(client.disconnect())
    return err(f"Unknown connection tool: {name}")


from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
