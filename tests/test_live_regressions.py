"""Regressions for bugs found in a live CST 2026 run (fakes only; no CST contacted)."""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.session import CSTSession
from cst_mcp.tools import mesh, official, project, simulation, solvers


def _decode(content) -> dict:
    return json.loads(content[0].text)


class FakeModel:
    """model3d fake: non-history VBA writes canned query output; history is forbidden."""

    def __init__(self, output: str = "", run_info: dict | None = None) -> None:
        self.output = output
        self.run_info = run_info
        self.codes: list[str] = []

    def is_solver_running(self, *, timeout=None) -> bool:
        return False

    def add_to_history(self, *args, **kwargs):
        raise AssertionError("read-only tool wrote to the model history")

    def _execute_vba_code(self, code: str, timeout=None) -> None:
        self.codes.append(code)
        opened = re.search(r'Open "([^"]+)" For Output', code)
        if opened:
            Path(opened[1]).write_text(self.output, encoding="ascii")
        exported = re.search(r'Plot\.ExportImage "([^"]+)"', code)
        if exported:
            Path(exported[1]).write_bytes(b"png")

    def get_active_solver_name(self, *, timeout=None) -> str:
        return "HF Time Domain"

    def get_solver_run_info(self, *, timeout=None) -> dict | None:
        return self.run_info


def _client(tmp_path, model: FakeModel) -> CSTClient:
    client = CSTClient(CSTConfig())
    client.config.work_dir = tmp_path
    client._de = object()
    client._project = SimpleNamespace(model3d=model)
    return client


# 1. MeshSettings needs a setting map before .Set --------------------------------

@pytest.mark.parametrize("mesh_type", ["Hex", "Tet"])
def test_mesh_density_selects_setting_map_first(mesh_type) -> None:
    captured = {}

    class Capture:
        def execute_vba(self, vba):
            captured["vba"] = vba
            return {"status": "offline", "vba": vba}

    result = _decode(mesh._set_mesh_density({"cells_per_wavelength": 12, "mesh_type": mesh_type}, Capture()))
    vba = captured["vba"]
    assert f'.SetMeshType "{mesh_type}"' in vba
    assert vba.index(".SetMeshType") < vba.index('.Set "StepsPerWaveNear"')
    assert ("RatioLimit" in vba) is (mesh_type == "Hex")
    assert result["mesh_type"] == mesh_type


# 2. Sub Main stripping and project tree enumeration -----------------------------

def test_strip_sub_main_tolerates_leading_comments_and_option_lines() -> None:
    code = "\n' header comment\nRem another\nOption Explicit\n\nSub Main()\n  x = 1\nEnd Sub\n"
    bare = CSTSession._strip_sub_main(code)
    assert "Sub Main" not in bare and "End Sub" not in bare and "Option" not in bare
    assert bare.splitlines() == ["' header comment", "Rem another", "x = 1"]
    # Code without a Sub Main wrapper is left untouched.
    assert CSTSession._strip_sub_main("x = 1\n") == "x = 1\n"


def test_project_tree_walks_children_without_history(tmp_path) -> None:
    output = (
        "0\tComponents\n1\tComponents\\component1\n2\tComponents\\component1\\patch\n"
        "0\tPorts\n1\tPorts\\port1\n"
    )
    model = FakeModel(output)
    client = _client(tmp_path, model)
    data = _decode(_run(project.handle("cst_project_tree", {}, client)))
    assert data["status"] == "ok"
    assert [i["path"] for i in data["items"]] == [
        "Components", "Components\\component1", "Components\\component1\\patch", "Ports", "Ports\\port1",
    ]
    code = model.codes[0]
    # Everything is inside exactly one Sub Main (the old wrapper put code outside it).
    assert code.count("Sub Main") == 1 and code.rstrip().endswith("End Sub")
    assert "Resulttree.GetFirstChildName(cur)" in code and "GetNextItemName(child)" in code
    assert "GetNumberOfSelectedTreeItems" not in code


def test_project_tree_subfolder_strips_root(tmp_path) -> None:
    model = FakeModel("0\tComponents\n1\tComponents\\component1\nTRUNCATED\t4\n")
    client = _client(tmp_path, model)
    data = _decode(_run(project.handle("cst_project_tree", {"tree_path": "Components", "max_depth": 1}, client)))
    assert data["items"] == [{"path": "Components\\component1", "name": "component1", "depth": 0}]
    assert data["truncated"] is True
    assert "Const maxDepth = 1" in model.codes[0]


# 3. Read-only info tools use output capture, never history ----------------------

def test_solver_info_reports_values_without_history(tmp_path) -> None:
    model = FakeModel("solver_type\tHF Time Domain\nfmin\t1.5\nfmax\t3\nn_frequency_samples.error\tno ports\n")
    data = _decode(solvers._get_solver_info({}, _client(tmp_path, model)))
    assert data["status"] == "ok"
    assert data["solver_type"] == "HF Time Domain" and data["fmin"] == 1.5 and data["fmax"] == 3
    assert data["unavailable"] == {"n_frequency_samples": "no ports"}
    assert "ReportInformation" not in model.codes[0]


def test_mesh_info_reports_counts_without_update_or_history(tmp_path) -> None:
    model = FakeModel("mesh_type\tPBA\ntotal_cells\t123456\nmin_edge_length\t0.05\n")
    data = _decode(mesh._get_mesh_info({}, _client(tmp_path, model)))
    assert data["status"] == "ok" and data["mesh_type"] == "PBA" and data["total_cells"] == 123456
    assert data["min_edge_length"] == 0.05
    assert ".Update" not in model.codes[0]


def test_capture_never_falls_back_to_history(tmp_path) -> None:
    client = _client(tmp_path, FakeModel())
    client._project = SimpleNamespace(model3d=SimpleNamespace(
        is_solver_running=lambda **kw: False,
        add_to_history=lambda *a, **kw: pytest.fail("history fallback used"),
    ))
    result = client.capture_vba_output('Debug.Print "x"')
    assert result["status"] == "error"


# 4. Structure views reselect the 3D model first ---------------------------------

def test_structure_views_select_components_before_export(tmp_path) -> None:
    model = FakeModel()
    client = _client(tmp_path, model)
    result = client.export_plot_images(tmp_path / "views", views=["front", "custom"])
    assert result["status"] == "ok"
    exports = [c for c in model.codes if "Plot.ExportImage" in c]
    assert len(exports) == 2
    for code in exports:
        assert code.index('SelectTreeItem "Components"') < code.index("Plot.ExportImage")


# 5. Saved results for the session's own open project ----------------------------

def _fake_cst_results(monkeypatch, project_file):
    results = types.ModuleType("cst.results")
    results.ProjectFile = project_file
    package = types.ModuleType("cst")
    package.results = results
    monkeypatch.setitem(sys.modules, "cst", package)
    monkeypatch.setitem(sys.modules, "cst.results", results)


def _own_project_client(tmp_path, monkeypatch):
    path = tmp_path / "model.cst"
    path.touch()
    client = CSTClient(CSTConfig())
    client._project_path = str(path)
    monkeypatch.setattr(client, "is_solver_running", lambda **kw: False)
    return client, path


@pytest.mark.asyncio
async def test_list_saved_results_allows_own_idle_project(tmp_path, monkeypatch) -> None:
    seen = {}

    class ProjectFile:
        def __init__(self, path, allow_interactive=False):
            seen["allow_interactive"] = allow_interactive

        def get_3d(self):
            return SimpleNamespace(get_tree_items=lambda: ["1D Results\\S-Parameters\\S1,1"],
                                   get_run_ids=lambda tree: [0])

    _fake_cst_results(monkeypatch, ProjectFile)
    client, path = _own_project_client(tmp_path, monkeypatch)
    data = _decode(await official.handle("cst_list_saved_results", {"project_path": str(path)}, client))
    assert data["status"] == "ok" and seen["allow_interactive"] is True
    assert data["entries"][0]["run_ids"] == [0]


@pytest.mark.asyncio
async def test_list_saved_results_failure_is_clean_error(tmp_path, monkeypatch) -> None:
    class ProjectFile:
        def __init__(self, path, allow_interactive=False):
            raise UserWarning("Project is opened in CST Studio Suite.")

    _fake_cst_results(monkeypatch, ProjectFile)
    path = tmp_path / "other.cst"
    path.touch()
    data = _decode(await official.handle("cst_list_saved_results", {"project_path": str(path)}, CSTClient(CSTConfig())))
    assert data["status"] == "error" and "opened in CST" in data["message"]


@pytest.mark.asyncio
async def test_read_saved_result_passes_allow_interactive_for_own_project(tmp_path, monkeypatch) -> None:
    seen = {}

    def fake_read(path, tree, run_id, allow_interactive=False):
        seen["allow_interactive"] = allow_interactive
        return {"status": "ok", "n": 1, "x": [1.0], "real": [0.5], "imag": [0.0]}

    monkeypatch.setattr(official, "read_curve", fake_read)
    client, path = _own_project_client(tmp_path, monkeypatch)
    data = _decode(await official.handle(
        "cst_read_saved_result", {"project_path": str(path), "tree_path": "1D Results\\x"}, client))
    assert data["status"] == "ok" and seen["allow_interactive"] is True


# 6. Stale run-info state is labelled -------------------------------------------

@pytest.mark.asyncio
async def test_simulation_status_labels_stale_run_state(tmp_path) -> None:
    model = FakeModel(run_info={"message": "History update failed", "state": "ERROR"})
    client = _client(tmp_path, model)
    data = _decode(await simulation.handle("cst_get_simulation_status", {}, client))
    assert data["running"] is False
    assert "state" not in data["run_info"]
    assert data["run_info"]["last_reported_state"] == "ERROR"
    assert "stale" in data["run_info"]["state_note"]
    jsonschema.validate(data, simulation.SOLVER_STATUS_OUTPUT_SCHEMA)


def test_run_info_with_timestamp_keeps_state() -> None:
    info = CSTSession._label_run_info({"state": "SUCCESS", "end_time": "2026-09-23T20:00"}, False)
    assert info["state"] == "SUCCESS" and info["reported_at"] == "2026-09-23T20:00"


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_mesh_query_marks_stale_zero_cell_count():
    from types import SimpleNamespace

    from cst_mcp.tools import mesh

    client = SimpleNamespace(query_values=lambda fields: {
        "status": "ok",
        "values": {"mesh_type": "PBA", "total_cells": "0", "mesh_points": "27540"},
        "errors": {},
        "source": "test",
    })
    out = mesh._query_mesh(client)
    assert "total_cells" not in out
    assert "total_cells" in out["unavailable"]
    assert out["mesh_points"] == 27540


def test_export_result_never_writes_history():
    import asyncio
    import json

    from cst_mcp.tools import results

    calls = []

    class Client:
        connected = True

        def execute_vba(self, *a, **kw):
            calls.append(("history", kw))
            return {"status": "executed"}

        def execute_vba_silent(self, code, **kw):
            calls.append(("silent", kw))
            return {"status": "executed"}

    res = asyncio.run(results.handle("cst_export_result", {
        "result_path": "1D Results\S-Parameters\S1,1", "output_file": "s11.csv", "format": "csv",
    }, Client()))
    assert json.loads(res[0].text)["status"] == "executed"
    assert calls == [("silent", {"history_fallback": False})]
