"""Central tool registry — name → handler mapping for all modules."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

from mcp.types import CallToolResult, TextContent, Tool

from cst_mcp.config import ALWAYS_ENABLED_TOOLS
from cst_mcp.tools.annotations import annotations_for

if TYPE_CHECKING:
    from mcp.server import Server

    from cst_mcp.cst_client import CSTClient

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any], "CSTClient"], Awaitable[list[TextContent]]]
T = TypeVar("T")

# Tool module name -> CST_TOOLSETS category where the two differ.
_MODULE_CATEGORIES = {
    "antenna_templates": "antenna",
    "figures_1d": "figures",
    "figures_3d": "figures",
}
_TOOLS_PACKAGE = "cst_mcp.tools."
_UNSET: Any = object()


class CSTWorker:
    """One dedicated thread running its own asyncio loop for all CST access.

    CST's Python API is blocking (a solve can hold a call for an hour) and its
    objects may have thread affinity, so every tool handler, and the optional
    startup connect, runs on this single thread. The MCP server's own loop
    keeps answering pings, cancellations and other requests meanwhile; CST
    tool calls are serialized in arrival order.

    Cancelling a request cancels the handler's task at its next ``await``
    (e.g. the sleep between cst_wait_for_simulation polls). A blocking CST
    call already in progress cannot be interrupted: it runs to its own
    ``timeout`` and later tool calls queue behind it.
    """

    def __init__(self, name: str = "cst-worker") -> None:
        self._name = name
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return self._loop
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def run() -> None:
                asyncio.set_event_loop(loop)
                ready.set()
                loop.run_forever()

            thread = threading.Thread(target=run, name=self._name, daemon=True)
            thread.start()
            ready.wait()
            self._loop, self._thread = loop, thread
            return loop

    @property
    def thread_id(self) -> int | None:
        """``threading.get_ident()`` of the worker thread once started."""
        return self._thread.ident if self._thread is not None else None

    def on_worker(self) -> bool:
        return self._thread is not None and threading.current_thread() is self._thread

    async def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run ``coro`` on the worker loop and await its result from any loop."""
        if self.on_worker():
            # Already on the CST thread (nested call): submitting would deadlock.
            return await coro
        future = asyncio.run_coroutine_threadsafe(coro, self._ensure_loop())
        return await asyncio.wrap_future(future)

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run the blocking ``func(*args, **kwargs)`` on the worker thread."""

        async def invoke() -> T:
            return func(*args, **kwargs)

        return await self.run(invoke())


# All CST access (tool handlers, startup connect) goes through this worker.
CST_WORKER = CSTWorker()


def _module_category(handler: Handler) -> str | None:
    """Derive a tool category from the handler's ``cst_mcp.tools`` module."""
    module = getattr(handler, "__module__", "") or ""
    if not module.startswith(_TOOLS_PACKAGE):
        return None
    short = module[len(_TOOLS_PACKAGE):].split(".", 1)[0]
    return _MODULE_CATEGORIES.get(short, short)


def _tool_schema(tool: Tool, v1_name: str, v2_name: str) -> dict[str, Any] | None:
    # MCP Python 1.x exposed protocol aliases while 2.x exposes Pythonic field
    # names. Both serialize to the same wire-level member.
    schema = getattr(tool, v1_name, None)
    if schema is None:
        schema = getattr(tool, v2_name, None)
    return schema


def _with_annotations(tool: Tool) -> Tool:
    """Attach derived annotations unless the tool module defined its own."""
    if getattr(tool, "annotations", None) is not None:
        return tool
    return tool.model_copy(update={"annotations": annotations_for(tool.name)})


def _validate_tool(tool: Tool) -> None:
    """Fail at startup with a precise message for an unusable tool catalog."""
    from jsonschema import Draft202012Validator, SchemaError

    schema = _tool_schema(tool, "inputSchema", "input_schema")
    if schema is None:
        raise ValueError(f"Tool {tool.name!r} has no inputSchema")
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
    output_schema = _tool_schema(tool, "outputSchema", "output_schema")
    if output_schema is not None:
        try:
            Draft202012Validator.check_schema(output_schema)
        except SchemaError as exc:
            raise ValueError(
                f"Tool {tool.name!r} outputSchema is invalid: {exc.message}"
            ) from exc


def _content_is_error(content: list[TextContent]) -> bool:
    """Recognize the JSON error envelope used by the ported tool handlers."""
    if len(content) != 1 or content[0].type != "text":
        return False
    try:
        payload = json.loads(content[0].text)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("status") in {"error", "busy", "timeout"}


def sanitize_json(value: Any) -> Any:
    """Replace non-finite floats (NaN, +/-Inf) with ``None`` recursively.

    Python's ``json`` module emits bare ``NaN``/``Infinity`` tokens, which are
    not JSON and break strict clients; ``null`` is the portable spelling.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json(v) for v in value]
    return value


def _dumps(data: Any) -> str:
    """Strict JSON text: non-finite floats become ``null``, never ``NaN``."""

    def default(obj: Any) -> Any:
        # Objects such as numpy scalars/arrays: prefer their Python value so
        # NaN inside them is sanitized too; fall back to ``str``.
        for attr in ("tolist", "item"):
            method = getattr(obj, attr, None)
            if callable(method):
                try:
                    return sanitize_json(method())
                except Exception:  # noqa: BLE001
                    break
        return str(obj)

    return json.dumps(sanitize_json(data), indent=2, default=default, allow_nan=False)


def ok(**payload: Any) -> list[TextContent]:
    body = {"status": "ok", **payload}
    return [TextContent(type="text", text=_dumps(body))]


def err(message: str, **payload: Any) -> list[TextContent]:
    body = {"status": "error", "message": message, **payload}
    return [TextContent(type="text", text=_dumps(body))]


def as_json(data: dict[str, Any]) -> list[TextContent]:
    if "status" not in data:
        data = {"status": "ok", **data}
    return [TextContent(type="text", text=_dumps(data))]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: list[Tool] = []
        self._handlers: dict[str, Handler] = {}
        self._categories: dict[str, str | None] = {}
        self._active: list[Tool] | None = None

    def add_module(
        self, tools: list[Tool], handler: Handler, *, category: str | None = None
    ) -> None:
        """Register tools served by ``handler``.

        ``category`` is the ``CST_TOOLSETS`` name; by default it is derived
        from the handler's module. Tools without a category are never filtered.
        Tools without ``annotations`` get name-derived MCP annotations.
        """
        category = category or _module_category(handler)
        for t in tools:
            if t.name in self._handlers:
                raise ValueError(f"Duplicate tool name: {t.name}")
            _validate_tool(t)
            self._tools.append(_with_annotations(t))
            self._handlers[t.name] = handler
            self._categories[t.name] = category

    def enabled_tools(self, toolsets: frozenset[str] | None) -> list[Tool]:
        """Tools exposed for the given categories (``None`` = every tool)."""
        if toolsets is None:
            return list(self._tools)
        return [
            t
            for t in self._tools
            if t.name in ALWAYS_ENABLED_TOOLS
            or self._categories.get(t.name) is None
            or self._categories[t.name] in toolsets
        ]

    def bind(
        self,
        server: Server,
        client: CSTClient,
        toolsets: frozenset[str] | None = _UNSET,
        *,
        worker: CSTWorker | None = None,
    ) -> None:
        """Expose the catalog on ``server``.

        ``toolsets`` defaults to ``client.config.toolsets`` (``CST_TOOLSETS``).
        Filtered tools are absent from tools/list and rejected by tools/call.
        Every handler runs on ``worker`` (default :data:`CST_WORKER`), never on
        the server's event loop.
        """
        worker = worker or CST_WORKER
        if toolsets is _UNSET:
            toolsets = getattr(getattr(client, "config", None), "toolsets", None)
        tools = self.enabled_tools(toolsets)
        self._active = tools
        by_name = {t.name: t for t in tools}
        handlers = {name: self._handlers[name] for name in by_name}
        disabled = set(self._handlers) - set(handlers)
        if disabled:
            logger.info("CST_TOOLSETS exposes %d of %d tools", len(tools), len(self._tools))
        categories = dict(self._categories)

        async def call_tool(name: str, arguments: dict[str, Any] | None) -> CallToolResult:
            args = arguments or {}
            handler = handlers.get(name)
            if handler is None:
                if name in disabled:
                    message = (
                        f"Tool {name} is disabled by CST_TOOLSETS "
                        f"(category {categories.get(name)!r})"
                    )
                    return _call_result(err(message), is_error=True)
                return _call_result(err(f"Unknown tool: {name}"), is_error=True)
            logger.info("tool call: %s", name)
            tool = by_name[name]
            try:
                content = await worker.run(_invoke(handler, name, args, client))
                return _call_result(content, is_error=_content_is_error(content), tool=tool)
            except Exception as exc:
                logger.exception("Handler crash on %s", name)
                return _call_result(err(str(exc)), is_error=True, tool=tool)

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
                if params.name in handlers:
                    schema = _tool_schema(by_name[params.name], "inputSchema", "input_schema")
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
    def tools(self) -> list[Tool]:
        """Every registered (annotated) tool, regardless of CST_TOOLSETS."""
        return list(self._tools)

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self._tools]

    @property
    def active_tool_names(self) -> list[str]:
        """Tools exposed by the last :meth:`bind` (every tool before binding)."""
        tools = self._active if self._active is not None else self._tools
        return [t.name for t in tools]

    def category_of(self, name: str) -> str | None:
        return self._categories.get(name)

    def __len__(self) -> int:
        return len(self._tools)


def _text_payload(content: list[TextContent]) -> tuple[dict[str, Any] | None, bool]:
    """The JSON object behind a single text block and whether it held NaN/Inf.

    Non-finite floats are replaced with ``None``.
    """
    if len(content) != 1 or getattr(content[0], "type", None) != "text":
        return None, False
    try:
        raw = json.loads(content[0].text)
    except (TypeError, ValueError):
        return None, False
    if not isinstance(raw, dict):
        return None, False
    try:
        json.dumps(raw, allow_nan=False)
    except ValueError:
        return sanitize_json(raw), True
    return raw, False


def _call_result(
    content: list[TextContent], *, is_error: bool, tool: Tool | None = None
) -> CallToolResult:
    """Build the tools/call result, attaching ``structuredContent`` when usable.

    * The text block is re-serialized as strict JSON when the handler emitted
      ``NaN``/``Infinity``, so text and ``structuredContent`` agree (``null``).
    * Without an ``outputSchema`` any JSON-object result is mirrored as
      ``structuredContent``.
    * With an ``outputSchema``, a success payload must validate. MCP requires
      conforming ``structuredContent`` and SDK clients raise when it is
      missing, so a mismatch is reported as ``isError=true`` with the
      validation message plus the original payload text.
    * Error results are not checked against the success schema and carry no
      structured copy when the tool declares one.
    """
    payload, sanitized = _text_payload(content)
    if payload is None:
        return CallToolResult(content=content, isError=is_error)
    if sanitized:
        content = [TextContent(type="text", text=_dumps(payload))]

    schema = _tool_schema(tool, "outputSchema", "output_schema") if tool is not None else None
    if schema is None:
        return CallToolResult(content=content, structuredContent=payload, isError=is_error)
    if is_error:
        return CallToolResult(content=content, isError=True)

    from jsonschema import SchemaError, ValidationError, validate

    try:
        validate(instance=payload, schema=schema)
    except (ValidationError, SchemaError) as exc:
        location = "/".join(str(p) for p in getattr(exc, "absolute_path", ())) or "(root)"
        logger.warning(
            "Tool %s result does not match its outputSchema at %s: %s",
            tool.name,
            location,
            exc.message,
        )
        explanation = err(
            f"Tool {tool.name} produced a result that does not match its declared "
            f"outputSchema at {location}: {exc.message}. The raw result follows.",
            error_type="output_schema_mismatch",
            instance_path=location,
        )
        return CallToolResult(content=[*explanation, *content], isError=True)
    return CallToolResult(content=content, structuredContent=payload, isError=is_error)


async def _invoke(
    handler: Handler, name: str, args: dict[str, Any], client: CSTClient
) -> list[TextContent]:
    # Created lazily so the handler's code (including any synchronous prefix
    # before its first await) runs on the worker thread.
    return await handler(name, args, client)


async def _return_tools(tools: list[Tool]) -> list[Tool]:
    return tools
