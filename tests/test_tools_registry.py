"""Tool registration smoke tests."""

from __future__ import annotations

import json

import pytest
from mcp.server import Server
from mcp.types import TextContent, Tool

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import register_all_tools
from cst_mcp.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_list_tools_full_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("CST_WORK_DIR", str(tmp_path))
    monkeypatch.delenv("CST_PATH", raising=False)
    cfg = CSTConfig.from_env()
    server = Server("test")
    client = CSTClient(cfg)
    reg = register_all_tools(server, client)
    names = set(reg.tool_names)

    # Full surface: original suite ~170 + a few workflows
    assert len(names) >= 160

    expected = {
        "cst_create_brick",
        "cst_create_cylinder",
        "cst_boolean_add",
        "cst_antenna_patch",
        "cst_get_s_parameters",
        "cst_connection_status",
        "cst_workflow_patch_antenna",
        "cst_pcb_create_stackup",
        "cst_array_linear",
        "cst_execute_vba",
    }
    missing = expected - names
    assert not missing, f"Missing tools: {missing}"

    from cst_mcp.tools import workflows

    result = await workflows.handle(
        "cst_design_patch_only",
        {"frequency_ghz": 2.45},
        client,
    )
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    assert "design" in data


@pytest.mark.asyncio
async def test_registry_marks_tool_error_envelope_as_mcp_error():
    callbacks = {}

    class FakeServer:
        def list_tools(self):
            return lambda callback: callbacks.setdefault("list", callback)

        def call_tool(self):
            return lambda callback: callbacks.setdefault("call", callback)

    async def handler(name, arguments, client):
        return [
            TextContent(
                type="text",
                text=json.dumps({"status": "error", "message": "mock failure"}),
            )
        ]

    registry = ToolRegistry()
    registry.add_module(
        [
            Tool(
                name="mock_tool",
                description="A mock tool.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            )
        ],
        handler,
    )
    registry.bind(FakeServer(), object())

    result = await callbacks["call"]("mock_tool", {})
    assert getattr(result, "isError", getattr(result, "is_error", None)) is True
    assert json.loads(result.content[0].text)["message"] == "mock failure"

    unknown = await callbacks["call"]("does_not_exist", {})
    assert getattr(unknown, "isError", getattr(unknown, "is_error", None)) is True


def test_registry_rejects_malformed_tool_schema():
    registry = ToolRegistry()

    async def handler(name, arguments, client):
        return []

    malformed = Tool(
        name="bad_tool",
        description="Bad schema for a catalog regression test.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": ["missing"],
        },
    )
    with pytest.raises(ValueError, match="unknown property"):
        registry.add_module([malformed], handler)
