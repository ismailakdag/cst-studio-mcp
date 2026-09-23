"""outputSchema contracts: valid Draft 2020-12 schemas that accept real success payloads."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from cst_mcp.session import CSTSession
from cst_mcp.tools import results, simulation, workflows
from cst_mcp.tools.registry import _tool_schema

EXPECTED = {
    "cst_get_s_parameters",
    "cst_workflow_run_and_s11",
    "cst_get_farfield_metrics",
    "cst_get_simulation_status",
    "cst_wait_for_simulation",
}


def _all_tools():
    return [*results.TOOLS, *simulation.TOOLS, *workflows.TOOLS]


def _output_schema(tool) -> dict | None:
    # MCP 1.x exposes ``outputSchema``; 2.x exposes ``output_schema``.
    return _tool_schema(tool, "outputSchema", "output_schema")


def _schema(name: str) -> dict:
    tool = next(t for t in _all_tools() if t.name == name)
    schema = _output_schema(tool)
    assert schema is not None, name
    return schema


def _validate(name: str, payload: dict) -> None:
    Draft202012Validator(_schema(name)).validate(payload)


def _decode(content) -> dict:
    return json.loads(content[0].text)


def _curve() -> dict:
    values = (0.5 + 0.5j, 0.1 + 0.1j, 0.5 + 0.5j)
    return {
        "status": "ok", "source": "cst.results", "tree_path": "1D Results\\S-Parameters\\S1,1",
        "run_id": 0, "n": 3, "x": [1.0, 2.0, 3.0],
        "real": [v.real for v in values], "imag": [v.imag for v in values],
        "xlabel": "Frequency / GHz", "ylabel": "", "title": "S1,1", "snapshot": "saved",
    }


def _offline_session() -> CSTSession:
    cfg = SimpleNamespace(
        cst_available=False, cst_path=None, python_lib_path=None, version="2026",
        work_dir=Path("."),
    )
    return CSTSession(config=cfg)


def test_expected_tools_declare_output_schema() -> None:
    declared = {t.name for t in _all_tools() if _output_schema(t) is not None}
    assert EXPECTED <= declared


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_output_schema_is_valid_draft_2020_12(name: str) -> None:
    schema = _schema(name)
    Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object"
    assert schema.get("additionalProperties", True) is True
    json.dumps(schema, allow_nan=False)
    # Serialized under the protocol field name for both MCP SDK generations.
    tool = next(t for t in _all_tools() if t.name == name)
    assert tool.model_dump(by_alias=True)["outputSchema"] == schema


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["db", "mag", "real_imag", "phase"])
async def test_s_parameters_connected_payload_validates(fmt: str) -> None:
    client = SimpleNamespace(connected=True, get_result=lambda path, run_id=0: _curve())
    data = _decode(await results.handle("cst_get_s_parameters", {"format": fmt}, client))
    assert data["status"] == "ok"
    _validate("cst_get_s_parameters", data)


@pytest.mark.asyncio
async def test_s_parameters_offline_payload_validates() -> None:
    client = SimpleNamespace(connected=False)
    data = _decode(await results.handle("cst_get_s_parameters", {}, client))
    assert data["status"] == "offline"
    _validate("cst_get_s_parameters", data)


def test_s_parameters_schema_rejects_ok_without_curve() -> None:
    with pytest.raises(ValidationError):
        _validate("cst_get_s_parameters", {"status": "ok"})


class FakeWorkflowClient:
    def run_solver(self, timeout_s: float = 3600) -> dict:
        return {"status": "executed", "result": "ok"}

    def get_s_parameters(self, port_out=1, port_in=1, *, max_points=200) -> dict:
        return {
            "status": "ok", "source": "cst.results", "tree_path": "1D Results\\S-Parameters\\S1,1",
            "port_out": port_out, "port_in": port_in, "n_points": 2, "frequency_unit": "GHz",
            "frequency_ghz": [2.3, 2.4], "real": [0.1, 0.0], "imag": [0.0, 0.0],
            "magnitude_db": [-20.0, None], "magnitude_linear": [0.1, 0.0],
            "phase_deg": [0.0, None], "metrics": {"min_db": -20.0, "freq_at_min_ghz": 2.3},
            "snapshot": "saved",
        }

    def get_farfield_metrics(self, frequency_ghz=None, monitor_name=None, *, try_farfield_plot=True):
        if try_farfield_plot:
            return {
                "status": "ok", "method": "farfield_plot_getmax+results_api",
                "metrics": {"max_realized_gain_dbi": 6.1, "rad_efficiency": 0.8},
                "path": None, "tree_path": "Farfields\\farfield (f=2.4) [1]",
                "sources": {"results_api": {"status": "ok"}}, "available": True,
            }
        return {
            "status": "ok", "method": "results_api_1d", "metrics": {"rad_efficiency": 0.8},
            "sources": {"results_api": {"status": "ok"}}, "note": "1D Results only",
        }


@pytest.mark.asyncio
async def test_run_and_s11_payloads_validate() -> None:
    data = _decode(await workflows.handle("cst_workflow_run_and_s11", {}, FakeWorkflowClient()))
    assert data["status"] == "ok"
    _validate("cst_workflow_run_and_s11", data)

    offline = _decode(await workflows.handle("cst_workflow_run_and_s11", {}, _offline_session()))
    assert offline["status"] == "offline"
    _validate("cst_workflow_run_and_s11", offline)


@pytest.mark.asyncio
@pytest.mark.parametrize("plot", [True, False])
async def test_farfield_metrics_payload_validates(plot: bool) -> None:
    data = _decode(await workflows.handle(
        "cst_get_farfield_metrics", {"frequency_ghz": 2.4, "try_farfield_plot": plot},
        FakeWorkflowClient(),
    ))
    assert data["status"] == "ok"
    _validate("cst_get_farfield_metrics", data)


@pytest.mark.asyncio
async def test_simulation_status_payloads_validate() -> None:
    client = SimpleNamespace(solver_status=lambda timeout_s=30.0: {
        "status": "ok", "running": True, "active_solver": "HF Time Domain",
        "run_info": {"progress": 25.0, "native": "run"},
    })
    data = _decode(await simulation.handle("cst_get_simulation_status", {}, client))
    _validate("cst_get_simulation_status", data)

    offline = _decode(await simulation.handle("cst_get_simulation_status", {}, _offline_session()))
    assert offline["status"] == "offline"
    _validate("cst_get_simulation_status", offline)


@pytest.mark.asyncio
@pytest.mark.parametrize("running", [True, False])
async def test_wait_payloads_validate(monkeypatch, running: bool) -> None:
    now = [0.0]

    async def fake_sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(simulation, "_clock", lambda: now[0])
    monkeypatch.setattr(simulation, "_sleep", fake_sleep)
    client = SimpleNamespace(solver_status=lambda timeout_s=30.0: {
        "status": "ok", "running": running, "active_solver": "HF Time Domain",
    })
    data = _decode(await simulation.handle("cst_wait_for_simulation", {"max_wait_s": 4}, client))
    assert data["status"] == ("running" if running else "finished")
    _validate("cst_wait_for_simulation", data)
