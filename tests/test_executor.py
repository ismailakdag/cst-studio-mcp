"""Tool handlers run on the single CST worker thread, never on the server loop."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from mcp.types import TextContent, Tool

from cst_mcp.tools.registry import CST_WORKER, CSTWorker, ToolRegistry


def _is_error(result) -> bool:
    return getattr(result, "isError", getattr(result, "is_error", None)) is True


class V1Server:
    """MCP Python 1.x low-level registration surface."""

    def __init__(self) -> None:
        self.callbacks: dict = {}

    def list_tools(self):
        return lambda cb: self.callbacks.setdefault("list", cb)

    def call_tool(self):
        return lambda cb: self.callbacks.setdefault("call", cb)

    async def call(self, name: str, arguments: dict):
        return await self.callbacks["call"](name, arguments)


class V2Server:
    """MCP Python 2.x ``add_request_handler`` registration surface."""

    def __init__(self) -> None:
        self.handlers: dict = {}

    def add_request_handler(self, method, params_type, handler) -> None:
        self.handlers[method] = (params_type, handler)

    async def call(self, name: str, arguments: dict):
        params_type, handler = self.handlers["tools/call"]
        return await handler(None, params_type(name=name, arguments=arguments))


def _v2_available() -> bool:
    try:
        from mcp.types import CallToolRequestParams, PaginatedRequestParams  # noqa: F401
    except ImportError:
        return False
    return True


SERVERS = [V1Server, pytest.param(V2Server, marks=pytest.mark.skipif(
    not _v2_available(), reason="mcp.types lacks v2 request param types"))]


def _tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=f"{name} test tool.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    )


def _bind(server_cls, handler, names=("probe",), worker: CSTWorker | None = None):
    registry = ToolRegistry()
    registry.add_module([_tool(n) for n in names], handler)
    server = server_cls()
    registry.bind(server, object(), toolsets=None, worker=worker)
    return server


def _text(payload: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload))]


@pytest.mark.asyncio
@pytest.mark.parametrize("server_cls", SERVERS)
async def test_blocking_handler_does_not_block_server_loop(server_cls) -> None:
    async def handler(name, arguments, client):
        time.sleep(1.0)  # noqa: ASYNC251 - simulates a blocking CST call
        return _text({"status": "ok"})

    server = _bind(server_cls, handler)
    ticks = 0
    stop = asyncio.Event()

    async def ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.02)

    tick_task = asyncio.create_task(ticker())
    started = time.monotonic()
    result = await server.call("probe", {})
    stop.set()
    await tick_task
    assert not _is_error(result)
    assert time.monotonic() - started >= 0.95
    # The main loop kept running while the handler blocked its own thread.
    assert ticks >= 15


@pytest.mark.asyncio
@pytest.mark.parametrize("server_cls", SERVERS)
async def test_all_handlers_run_on_one_worker_thread(server_cls) -> None:
    seen: list[int] = []

    async def handler(name, arguments, client):
        seen.append(threading.get_ident())
        await asyncio.sleep(0.01)  # handlers may await on the worker loop
        seen.append(threading.get_ident())
        return _text({"status": "ok", "tool": name})

    server = _bind(server_cls, handler, names=("probe_a", "probe_b"))
    results = await asyncio.gather(*(server.call(n, {}) for n in ("probe_a", "probe_b") * 3))
    assert not any(_is_error(r) for r in results)
    connect_thread = await CST_WORKER.call(threading.get_ident)
    assert len(set(seen)) == 1
    assert seen[0] == CST_WORKER.thread_id == connect_thread
    assert seen[0] != threading.get_ident()


@pytest.mark.asyncio
@pytest.mark.parametrize("server_cls", SERVERS)
async def test_handler_exception_becomes_is_error(server_cls) -> None:
    async def handler(name, arguments, client):
        raise RuntimeError("CST exploded")

    server = _bind(server_cls, handler)
    result = await server.call("probe", {})
    assert _is_error(result)
    body = json.loads(result.content[0].text)
    assert body["status"] == "error"
    assert body["message"] == "CST exploded"
    # The worker survives a crashing handler.
    assert await CST_WORKER.call(lambda: 42) == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("server_cls", SERVERS)
async def test_error_envelope_still_marks_is_error(server_cls) -> None:
    async def handler(name, arguments, client):
        return _text({"status": "busy", "message": "solver running"})

    server = _bind(server_cls, handler)
    result = await server.call("probe", {})
    assert _is_error(result)
    assert json.loads(result.content[0].text)["status"] == "busy"


@pytest.mark.asyncio
async def test_calls_are_serialized_on_the_worker() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    async def handler(name, arguments, client):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.1)  # noqa: ASYNC251 - blocking on purpose
        with lock:
            active -= 1
        return _text({"status": "ok"})

    server = _bind(V1Server, handler)
    await asyncio.gather(*(server.call("probe", {}) for _ in range(4)))
    assert peak == 1


@pytest.mark.asyncio
async def test_cancellation_reaches_awaiting_handler() -> None:
    worker = CSTWorker(name="cst-test-cancel")
    entered = threading.Event()
    cancelled = threading.Event()

    async def handler(name, arguments, client):
        entered.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _text({"status": "ok"})

    server = _bind(V1Server, handler, worker=worker)
    task = asyncio.create_task(server.call("probe", {}))
    while not entered.is_set():
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(cancelled.wait, 5)


@pytest.mark.asyncio
async def test_nested_run_on_worker_does_not_deadlock() -> None:
    async def inner() -> int:
        return threading.get_ident()

    async def outer() -> tuple[int, int]:
        return threading.get_ident(), await CST_WORKER.run(inner())

    outer_id, inner_id = await asyncio.wait_for(CST_WORKER.run(outer()), timeout=5)
    assert outer_id == inner_id == CST_WORKER.thread_id
