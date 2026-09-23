"""Explicit CST attachment; ordinary MCP initialization stays side-effect free."""
from __future__ import annotations

from mcp.types import Tool

from cst_mcp.tools.registry import as_json, err

TOOLS = [
    Tool(
        name="cst_connect",
        description="Explicitly attach to a running CST Design Environment or start one. Disabled mode never connects.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
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
        if client.connected:
            return as_json({"status": "connected", "message": "Already connected; session preserved."})
        result = client.connect()
        if result.get("status") != "connected":
            return err(result.get("message", "Could not connect to CST"), connection=result)
        return as_json(result)
    if name == "cst_disconnect":
        return as_json(client.disconnect())
    return err(f"Unknown connection tool: {name}")


from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
