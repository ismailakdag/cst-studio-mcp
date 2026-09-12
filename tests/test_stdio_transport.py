"""End-to-end MCP stdio compatibility tests without loading or starting CST."""

from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from cst_mcp import server as server_module


@pytest.mark.asyncio
@pytest.mark.parametrize("noisy_vendor", [False, True])
async def test_real_stdio_initialize_list_and_call(tmp_path: Path, noisy_vendor):
    repo_root = Path(__file__).resolve().parents[1]
    source_dir = repo_root / "src"
    env = os.environ.copy()
    env.update(
        {
            "CST_CONNECT_MODE": "disabled",
            "CST_PATH": str(tmp_path / "cst-not-installed"),
            "CST_WORK_DIR": str(tmp_path / "projects"),
            "CST_LOG_LEVEL": "DEBUG",
            "PYTHONPATH": os.pathsep.join([str(source_dir), env.get("PYTHONPATH", "")]).rstrip(
                os.pathsep
            ),
        }
    )
    script = """
import os
from cst_mcp import server as module
real_create = module.create_server
def noisy_create():
    print('vendor Python startup diagnostic', flush=True)
    os.write(1, b'vendor native startup diagnostic\\n')
    server, client = real_create()
    original_status = client.status
    def noisy_status():
        print('vendor Python call diagnostic', flush=True)
        os.write(1, b'vendor native call diagnostic\\n')
        return original_status()
    client.status = noisy_status
    return server, client
module.create_server = noisy_create
module.main()
"""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", script] if noisy_vendor else ["-m", "cst_mcp.server"],
        cwd=repo_root,
        env=env,
        encoding="utf-8",
        encoding_error_handler="strict",
    )

    async with stdio_client(params) as (read_stream, write_stream):  # noqa: SIM117
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            server_info = getattr(
                initialized, "serverInfo", getattr(initialized, "server_info", None)
            )
            assert server_info.name == "cst-studio-mcp"
            assert server_info.version == "1.0.0"

            catalog = await session.list_tools()
            assert len(catalog.tools) >= 170
            assert len({tool.name for tool in catalog.tools}) == len(catalog.tools)
            for tool in catalog.tools:
                # This also proves every schema survived JSON-RPC encoding.
                schema = getattr(tool, "inputSchema", getattr(tool, "input_schema", None))
                json.dumps(schema, allow_nan=False)
                assert schema["type"] == "object"
                assert isinstance(schema["properties"], dict)

            status_result = await session.call_tool("cst_connection_status", {})
            assert (
                getattr(status_result, "isError", getattr(status_result, "is_error", None)) is False
            )
            status = json.loads(status_result.content[0].text)
            assert status["mode"] == "offline"
            assert status["cst_available"] is False

            invalid_result = await session.call_tool("cst_create_project", {})
            assert (
                getattr(invalid_result, "isError", getattr(invalid_result, "is_error", None))
                is True
            )
            assert "Input validation error" in invalid_result.content[0].text

            unknown_result = await session.call_tool("not_a_cst_tool", {})
            assert (
                getattr(unknown_result, "isError", getattr(unknown_result, "is_error", None))
                is True
            )
            unknown = json.loads(unknown_result.content[0].text)
            assert unknown["status"] == "error"


@pytest.mark.asyncio
async def test_connection_exception_does_not_prevent_mcp_startup(monkeypatch):
    ran = False

    class Config:
        connect_on_startup = True
        connect_mode = "auto"

    class Client:
        config = Config()

        def connect(self):
            raise RuntimeError("mock CST loader failure")

        def status(self):
            return {"mode": "offline"}

    class Server:
        def create_initialization_options(self):
            return object()

        async def run(self, read_stream, write_stream, options):
            nonlocal ran
            ran = True

    @asynccontextmanager
    async def fake_stdio_server(*, stdout):
        yield object(), object()

    monkeypatch.setattr(server_module, "create_server", lambda: (Server(), Client()))
    monkeypatch.setattr(server_module, "stdio_server", fake_stdio_server)

    await server_module.run_server()
    assert ran is True
