"""Low-level VBA escape hatch for power users."""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from cst_mcp.execution.vba_builder import VBAError, VBAScript
from cst_mcp.session import CSTSession
from cst_mcp.tools.registry import as_json, err

TOOLS: list[Tool] = [
    Tool(
        name="cst_run_vba",
        description=(
            "Execute raw CST history VBA on the active project (add_to_history). "
            "Prefer higher-level tools; use this for advanced CST objects not yet wrapped."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "vba": {"type": "string", "description": "VBA snippet (With blocks, etc.)"},
                "label": {
                    "type": "string",
                    "description": "History list label",
                    "default": "cst_mcp_raw",
                },
                "silent": {
                    "type": "boolean",
                    "description": "If true, run via schematic.execute_vba_code (Sub Main wrap)",
                    "default": False,
                },
            },
            "required": ["vba"],
        },
    ),
]


async def handle(name: str, args: dict[str, Any], session: CSTSession) -> list[TextContent] | None:
    if name != "cst_run_vba":
        return None
    try:
        vba = str(args["vba"])
        # Light safety — block obvious shell/file APIs
        lowered = vba.lower()
        for banned in ("shell ", "createobject", "getobject", "sendkeys", "declare "):
            if banned in lowered:
                return err(f"Blocked potentially dangerous VBA construct: {banned.strip()}")
        label = str(args.get("label") or "cst_mcp_raw")
        if args.get("silent"):
            script = VBAScript().add(vba)
            return as_json(session.run_vba_silent(script.wrap_main()))
        return as_json(session.run_history(vba, label=label))
    except VBAError as exc:
        return err(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err(str(exc))
