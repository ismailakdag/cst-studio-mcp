"""Tool annotations, CST_TOOLSETS filtering, and structuredContent plumbing."""

from __future__ import annotations

import json
import logging

import pytest
from mcp.server import Server
from mcp.types import TextContent, Tool, ToolAnnotations

from cst_mcp.config import ALWAYS_ENABLED_TOOLS, CSTConfig, parse_toolsets
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import register_all_tools
from cst_mcp.tools.annotations import annotations_for
from cst_mcp.tools.registry import ToolRegistry, as_json, ok


def _hint(annotations, v1: str, v2: str):
    value = getattr(annotations, v1, None)
    return getattr(annotations, v2, None) if value is None else value


def _registry(toolsets=None) -> ToolRegistry:
    config = CSTConfig(connect_mode="disabled", toolsets=toolsets)
    return register_all_tools(Server("annotations-test"), CSTClient(config))


class FakeServer:
    """MCP 1.x-style decorator registration, independent of the installed SDK."""

    def __init__(self):
        self.callbacks = {}

    def list_tools(self):
        return lambda callback: self.callbacks.setdefault("list", callback)

    def call_tool(self):
        return lambda callback: self.callbacks.setdefault("call", callback)


def _is_error(result) -> bool:
    return getattr(result, "isError", getattr(result, "is_error", None))


def _structured(result):
    value = getattr(result, "structuredContent", None)
    return getattr(result, "structured_content", None) if value is None else value


def _mock_tool(name: str, **extra) -> Tool:
    return Tool(
        name=name,
        description="Mock tool.",
        inputSchema={"type": "object", "properties": {}, "required": []},
        **extra,
    )


# -- annotations -------------------------------------------------------------


def test_every_registered_tool_has_annotations():
    registry = _registry()
    assert len(registry) >= 180
    for tool in registry.tools:
        ann = tool.annotations
        assert ann is not None, tool.name
        assert ann.title, tool.name
        assert _hint(ann, "readOnlyHint", "read_only_hint") is not None, tool.name
        assert _hint(ann, "destructiveHint", "destructive_hint") is not None, tool.name
        assert _hint(ann, "openWorldHint", "open_world_hint") is False, tool.name
        if _hint(ann, "readOnlyHint", "read_only_hint"):
            assert not _hint(ann, "destructiveHint", "destructive_hint"), tool.name


@pytest.mark.parametrize(
    ("name", "read_only", "destructive"),
    [
        ("cst_get_s_parameters", True, False),
        ("cst_search_help", True, False),
        ("cst_matching_l_network", True, False),
        ("cst_delete_port", False, True),
        ("cst_stop_simulation", False, True),
        ("cst_boolean_subtract", False, True),
        ("cst_execute_vba", False, True),
        ("cst_create_brick", False, False),
        ("cst_stop_dialog_watcher", False, False),
        ("cst_set_parameter", False, True),
        ("cst_parameter_interpolation", False, True),
        ("cst_run_simulation", False, True),
        ("cst_run_simulation_async", False, True),
        ("cst_start_dialog_watcher", False, True),
        ("cst_save_project", False, True),
        ("cst_export_project", False, True),
        ("cst_export_cad", False, True),
        ("cst_export_touchstone", False, True),
        ("cst_export_farfield", False, True),
        ("cst_export_result", False, True),
        ("cst_export_structure_views", False, True),
        ("cst_get_farfield", False, False),
        ("cst_get_radiation_pattern_3d", False, False),
        ("cst_get_farfield_metrics", False, False),
    ],
)
def test_annotation_spot_checks(name, read_only, destructive):
    tool = next(t for t in _registry().tools if t.name == name)
    assert _hint(tool.annotations, "readOnlyHint", "read_only_hint") is read_only
    assert _hint(tool.annotations, "destructiveHint", "destructive_hint") is destructive


@pytest.mark.parametrize(
    "name", ["cst_get_mesh_info", "cst_get_mesh_quality", "cst_get_solver_info"]
)
def test_history_writing_queries_are_not_read_only(name):
    """These match the ``_get_``/``_info`` read-only rules but append model history."""
    tool = next(t for t in _registry().tools if t.name == name)
    ann = tool.annotations
    assert _hint(ann, "readOnlyHint", "read_only_hint") is False
    assert _hint(ann, "idempotentHint", "idempotent_hint") is False
    assert _hint(ann, "destructiveHint", "destructive_hint") is False


@pytest.mark.parametrize(
    "name", ["cst_technical_drawing", "cst_plot_1d_results", "cst_plot_farfield"]
)
def test_figure_tools_write_files_without_touching_the_project(name):
    # Checked by name so the rule holds before/without the figure modules.
    ann = annotations_for(name)
    assert _hint(ann, "readOnlyHint", "read_only_hint") is False
    assert _hint(ann, "destructiveHint", "destructive_hint") is False
    assert _hint(ann, "idempotentHint", "idempotent_hint") is True


def test_open_project_is_not_idempotent_but_connect_is():
    # A repeated open can open a second copy; a repeated connect is a no-op.
    assert _hint(annotations_for("cst_open_project"), "idempotentHint", "idempotent_hint") is False
    assert _hint(annotations_for("cst_connect"), "idempotentHint", "idempotent_hint") is True


def test_set_tools_are_idempotent_and_titles_are_human():
    tool = next(t for t in _registry().tools if t.name == "cst_set_frequency_range")
    assert _hint(tool.annotations, "idempotentHint", "idempotent_hint") is True
    assert tool.annotations.title == "Set Frequency Range"


def test_existing_annotations_are_not_overwritten():
    async def handler(name, arguments, client):
        return []

    own = ToolAnnotations(title="Custom", readOnlyHint=False, destructiveHint=True)
    registry = ToolRegistry()
    registry.add_module([_mock_tool("cst_get_custom", annotations=own)], handler)
    assert registry.tools[0].annotations.title == "Custom"
    assert _hint(registry.tools[0].annotations, "readOnlyHint", "read_only_hint") is False


# -- CST_TOOLSETS ------------------------------------------------------------


def test_toolsets_default_is_all(tmp_path, monkeypatch):
    monkeypatch.delenv("CST_TOOLSETS", raising=False)
    monkeypatch.setenv("CST_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("CST_PATH", str(tmp_path / "missing"))
    assert CSTConfig.from_env().toolsets is None
    assert parse_toolsets("") is None
    assert parse_toolsets("all") is None
    registry = _registry()
    assert registry.active_tool_names == registry.tool_names


def test_core_toolset_subset():
    toolsets = parse_toolsets("core")
    assert toolsets == {
        "connection", "official", "project", "workflows", "simulation", "results",
        "parameters", "diagnostics",
    }
    assert not {"drawing", "figures"} & toolsets
    registry = _registry(toolsets)
    active = set(registry.active_tool_names)
    assert ALWAYS_ENABLED_TOOLS <= active
    assert {
        "cst_get_s_parameters", "cst_run_simulation", "cst_search_help",
        "cst_set_parameter", "cst_list_parameters", "cst_dismiss_dialogs",
    } <= active
    assert "cst_create_brick" not in active
    assert "cst_pcb_create_trace" not in active
    assert len(active) < len(registry)
    assert {registry.category_of(name) for name in active} <= toolsets


def test_drawing_and_figures_are_selectable_categories():
    assert parse_toolsets("drawing,figures") == {"drawing", "figures", "connection"}


def test_connection_tools_always_present():
    registry = _registry(parse_toolsets("pcb"))
    active = set(registry.active_tool_names)
    assert ALWAYS_ENABLED_TOOLS <= active
    assert "cst_pcb_create_trace" in active
    assert "cst_get_s_parameters" not in active


def test_unknown_toolset_name_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="cst_mcp.config"):
        toolsets = parse_toolsets("geometry, bogus , Setup")
    assert toolsets == {"geometry", "boundaries", "connection"}
    assert "bogus" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="cst_mcp.config"):
        assert parse_toolsets("nope") is None  # nothing valid -> keep every tool
    assert "nope" in caplog.text


@pytest.mark.asyncio
async def test_filtered_tools_absent_from_list_and_rejected():
    registry = _registry(parse_toolsets("core"))
    server = FakeServer()
    registry.bind(server, CSTClient(CSTConfig(connect_mode="disabled")), parse_toolsets("core"))
    listed = {tool.name for tool in await server.callbacks["list"]()}
    assert "cst_create_brick" not in listed
    assert "cst_connection_status" in listed

    rejected = await server.callbacks["call"]("cst_create_brick", {})
    assert _is_error(rejected) is True
    assert "CST_TOOLSETS" in json.loads(rejected.content[0].text)["message"]


# -- structuredContent -------------------------------------------------------


def _bound(tools: list[Tool], payload: dict) -> FakeServer:
    async def handler(name, arguments, client):
        return [TextContent(type="text", text=json.dumps(payload))]

    registry = ToolRegistry()
    registry.add_module(tools, handler)
    server = FakeServer()
    registry.bind(server, object())
    return server


@pytest.mark.asyncio
async def test_json_result_gets_structured_content():
    server = _bound([_mock_tool("mock_json")], {"status": "ok", "value": 3})
    result = await server.callbacks["call"]("mock_json", {})
    assert _is_error(result) is False
    assert _structured(result) == {"status": "ok", "value": 3}
    assert json.loads(result.content[0].text)["value"] == 3


@pytest.mark.asyncio
async def test_error_result_still_flagged():
    server = _bound([_mock_tool("mock_err")], {"status": "error", "message": "boom"})
    result = await server.callbacks["call"]("mock_err", {})
    assert _is_error(result) is True
    assert _structured(result)["message"] == "boom"


@pytest.mark.asyncio
async def test_output_schema_gates_structured_content(caplog):
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}, "value": {"type": "integer"}},
        "required": ["status", "value"],
    }
    good = _bound([_mock_tool("mock_good", outputSchema=schema)], {"status": "ok", "value": 1})
    result = await good.callbacks["call"]("mock_good", {})
    assert _structured(result) == {"status": "ok", "value": 1}

    bad = _bound([_mock_tool("mock_bad", outputSchema=schema)], {"status": "ok", "value": "x"})
    with caplog.at_level(logging.WARNING, logger="cst_mcp.tools.registry"):
        result = await bad.callbacks["call"]("mock_bad", {})
    # SDK clients reject a success result without conforming structuredContent,
    # so a schema mismatch must surface as a tool error with the raw payload.
    assert _is_error(result) is True
    assert _structured(result) is None
    assert "outputSchema" in caplog.text
    explanation = json.loads(result.content[0].text)
    assert explanation["status"] == "error"
    assert explanation["error_type"] == "output_schema_mismatch"
    assert explanation["instance_path"] == "value"
    assert "is not of type 'integer'" in explanation["message"]
    assert json.loads(result.content[1].text) == {"status": "ok", "value": "x"}

    failed = _bound([_mock_tool("mock_fail", outputSchema=schema)], {"status": "error"})
    result = await failed.callbacks["call"]("mock_fail", {})
    assert _is_error(result) is True
    assert _structured(result) is None


@pytest.mark.asyncio
async def test_real_server_call_returns_structured_content():
    """Round-trip through the installed SDK's server path (v1 or v2)."""
    from mcp.types import CallToolRequestParams

    server = Server("structured-test")
    register_all_tools(server, CSTClient(CSTConfig(connect_mode="disabled")))
    if hasattr(server, "list_tools"):
        pytest.skip("MCP 1.x server wiring is covered by the FakeServer tests")
    entry = getattr(server, "_request_handlers", {}).get("tools/call")
    if entry is None:
        pytest.skip("installed SDK does not expose request handlers for inspection")
    params = CallToolRequestParams(name="cst_design_patch_only", arguments={"frequency_ghz": 2.45})
    result = await getattr(entry, "handler", entry)(None, params)
    assert _is_error(result) is False
    assert _structured(result)["status"] == "ok"


# -- non-finite floats ---------------------------------------------------------


def _strict_loads(text: str):
    def reject(token):
        raise AssertionError(f"non-strict JSON token {token}")

    return json.loads(text, parse_constant=reject)


def test_json_helpers_emit_strict_json_for_nan():
    for content in (
        ok(values=[1.0, float("nan"), float("inf")], nested={"x": float("-inf")}),
        as_json({"values": (float("nan"),)}),
    ):
        _strict_loads(content[0].text)
    assert json.loads(ok(values=[1.0, float("nan")])[0].text)["values"] == [1.0, None]


def _bound_text(tools: list[Tool], text: str) -> FakeServer:
    async def handler(name, arguments, client):
        return [TextContent(type="text", text=text)]

    registry = ToolRegistry()
    registry.add_module(tools, handler)
    server = FakeServer()
    registry.bind(server, object())
    return server


@pytest.mark.asyncio
async def test_nan_payload_is_sanitized_in_text_and_structured_content():
    # Handlers that call json.dumps themselves may still emit NaN tokens.
    raw = json.dumps({"status": "ok", "gain": float("nan"), "curve": [1.0, float("inf")]})
    assert "NaN" in raw
    server = _bound_text([_mock_tool("mock_nan")], raw)
    result = await server.callbacks["call"]("mock_nan", {})
    assert _is_error(result) is False
    expected = {"status": "ok", "gain": None, "curve": [1.0, None]}
    assert _structured(result) == expected
    assert _strict_loads(result.content[0].text) == expected


@pytest.mark.asyncio
async def test_nan_payload_against_number_schema_is_a_tool_error():
    number_curve = {"type": "array", "items": {"type": "number"}}
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}, "curve": number_curve},
        "required": ["status", "curve"],
    }
    raw = json.dumps({"status": "ok", "curve": [1.0, float("nan")]})
    server = _bound_text([_mock_tool("mock_nan_schema", outputSchema=schema)], raw)
    result = await server.callbacks["call"]("mock_nan_schema", {})
    assert _is_error(result) is True
    assert _structured(result) is None
    assert json.loads(result.content[0].text)["instance_path"] == "curve/1"
    assert _strict_loads(result.content[1].text) == {"status": "ok", "curve": [1.0, None]}

    nullable_curve = {"type": "array", "items": {"type": ["number", "null"]}}
    nullable = {**schema, "properties": {"status": {"type": "string"}, "curve": nullable_curve}}
    server = _bound_text([_mock_tool("mock_nan_nullable", outputSchema=nullable)], raw)
    result = await server.callbacks["call"]("mock_nan_nullable", {})
    assert _is_error(result) is False
    assert _structured(result) == {"status": "ok", "curve": [1.0, None]}
