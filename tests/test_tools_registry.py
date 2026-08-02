"""Tool registration smoke tests."""

from __future__ import annotations

import json

import pytest

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import register_all_tools
from mcp.server import Server


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
