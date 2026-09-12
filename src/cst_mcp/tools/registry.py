"""Central tool registry — name → handler mapping for all modules."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from mcp.types import CallToolResult, TextContent, Tool

if TYPE_CHECKING:
    from mcp.server import Server

    from cst_mcp.cst_client import CSTClient

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any], "CSTClient"], Awaitable[list[TextContent]]]


def _validate_tool(tool: Tool) -> None:
    """Fail at startup with a precise message for an unusable tool catalog."""
    from jsonschema import Draft202012Validator, SchemaError

    # MCP Python 1.x exposed protocol aliases while 2.x exposes Pythonic field
    # names. Both serialize to the same wire-level ``inputSchema`` member.
    schema = getattr(tool, "inputSchema", None)
    if schema is None:
        schema = tool.input_schema
    if schema.get("type") != "object":
        raise ValueError(f"Tool {tool.name!r} inputSchema must have type 'object'")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise TypeError(f"Tool {tool.name!r} inputSchema must define object properties")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError(f"Tool {tool.name!r} inputSchema.required must be a string array")
    unknown = sorted(set(required) - set(properties))
    if unknown:
        raise ValueError(
            f"Tool {tool.name!r} requires unknown property/properties: {', '.join(unknown)}"
        )
    try:
        json.dumps(schema, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Tool {tool.name!r} inputSchema is not strict JSON: {exc}") from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"Tool {tool.name!r} inputSchema is invalid: {exc.message}") from exc


def _content_is_error(content: list[TextContent]) -> bool:
    """Recognize the JSON error envelope used by the ported tool handlers."""
    if len(content) != 1 or content[0].type != "text":
        return False
    try:
        payload = json.loads(content[0].text)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("status") in {"error", "busy", "timeout"}


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
            _validate_tool(t)
            self._tools.append(t)
            self._handlers[t.name] = handler

    def bind(self, server: Server, client: CSTClient) -> None:
        tools = list(self._tools)
        handlers = dict(self._handlers)

        async def call_tool(name: str, arguments: dict[str, Any] | None) -> CallToolResult:
            args = arguments or {}
            handler = handlers.get(name)
            if handler is None:
                return _call_result(err(f"Unknown tool: {name}"), is_error=True)
            logger.info("tool call: %s", name)
            try:
                content = await handler(name, args, client)
                return _call_result(content, is_error=_content_is_error(content))
            except Exception as exc:
                logger.exception("Handler crash on %s", name)
                return _call_result(err(str(exc)), is_error=True)

        if hasattr(server, "list_tools"):
            # MCP Python 1.x low-level server API.
            server.list_tools()(lambda: _return_tools(tools))
            server.call_tool()(call_tool)
        else:
            # MCP Python 2.x moved low-level registration to explicit request
            # handlers. Keep the same on-the-wire tools/list and tools/call API.
            from jsonschema import ValidationError, validate
            from mcp.types import CallToolRequestParams, ListToolsResult, PaginatedRequestParams

            async def list_tools_v2(context: Any, params: Any) -> ListToolsResult:
                return ListToolsResult(tools=tools)

            async def call_tool_v2(context: Any, params: CallToolRequestParams) -> CallToolResult:
                handler = handlers.get(params.name)
                if handler is not None:
                    tool = next(tool for tool in tools if tool.name == params.name)
                    schema = getattr(tool, "input_schema", None)
                    if schema is None:
                        schema = tool.inputSchema
                    try:
                        validate(instance=params.arguments or {}, schema=schema)
                    except ValidationError as exc:
                        return _call_result(
                            err(f"Input validation error: {exc.message}"),
                            is_error=True,
                        )
                return await call_tool(params.name, params.arguments)

            server.add_request_handler("tools/list", PaginatedRequestParams, list_tools_v2)
            server.add_request_handler("tools/call", CallToolRequestParams, call_tool_v2)

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self._tools]

    def __len__(self) -> int:
        return len(self._tools)


def _call_result(content: list[TextContent], *, is_error: bool) -> CallToolResult:
    return CallToolResult(content=content, isError=is_error)


async def _return_tools(tools: list[Tool]) -> list[Tool]:
    return tools
