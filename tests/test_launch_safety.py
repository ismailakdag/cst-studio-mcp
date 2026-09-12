"""Regression tests for opt-in CST and client application launching."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from cst_mcp.tools import workflows


@pytest.mark.asyncio
async def test_patch_workflow_does_not_implicitly_connect_or_launch_cst(tmp_path):
    def forbidden_connect():
        raise AssertionError("workflow must not connect to or launch CST")

    client = SimpleNamespace(
        connected=False,
        connect=forbidden_connect,
        config=SimpleNamespace(work_dir=tmp_path),
        new_project=lambda path, project_type: {
            "status": "offline",
            "path": path,
            "type": project_type,
        },
        execute_vba=lambda vba, history_label=None: {
            "status": "offline",
            "vba": vba,
        },
        list_parameters=dict,
    )

    result = await workflows.handle(
        "cst_workflow_patch_antenna",
        {"frequency_ghz": 2.45},
        client,
    )
    payload = json.loads(result[0].text)

    assert payload["status"] == "offline"
    assert payload["steps"][0]["status"] == "offline"
    assert payload["vba"]
