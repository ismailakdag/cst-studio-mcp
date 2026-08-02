"""Central tool registry — name → handler mapping for all modules."""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent, Tool

if TYPE_CHECKING:
    from mcp.server import Server

    from cst_mcp.cst_client import CSTClient

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any], "CSTClient"], Awaitable[list[TextContent]]]


def ok(**payload: Any) -> list[TextContent]:
    body = {"status": "ok", **payload}
    return [TextContent(type="text", text=json.dumps(body, indent=2, default=str))]


def err(message: str, **payload: Any) -> list[TextContent]:
    body = {"status": "error", "message": message, **payload}
    return [TextContent(type="text", text=json.dumps(body, indent=2, default=str))]


def as_json(data: dict[str, Any]) -> list[TextContent]:
    if "status" not in data:
        data = {"status": "ok", **data}
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: list[Tool] = []
        self._handlers: dict[str, Handler] = {}

    def add_module(self, tools: list[Tool], handler: Handler) -> None:
        for t in tools:
            if t.name in self._handlers:
                raise ValueError(f"Duplicate tool name: {t.name}")
            self._tools.append(t)
            self._handlers[t.name] = handler

    def bind(self, server: Server, client: CSTClient) -> None:
        tools = list(self._tools)
        handlers = dict(self._handlers)

        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return tools

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
            args = arguments or {}
            handler = handlers.get(name)
            if handler is None:
                return err(f"Unknown tool: {name}")
            logger.info("tool call: %s", name)
            try:
                return await handler(name, args, client)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Handler crash on %s", name)
                return err(str(exc), traceback=traceback.format_exc()[-2000:])

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self._tools]

    def __len__(self) -> int:
        return len(self._tools)
