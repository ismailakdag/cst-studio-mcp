"""Parameter / sweep / optimizer / refine tools (fakes only; no CST contacted).

Regressions from a live CST 2026 run: cst_set_parameter put
``RebuildOnParametricChange`` into a history step (rejected by CST), and the
sweep/optimizer tools wrote their configuration into the model history.
"""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.execution.sweep_interpolation import interpolate_runs
from cst_mcp.tools import optimization, parameters


def _starts(code: str) -> bool:
    return re.search(r"\.Start\b", code) is not None


def _decode(content) -> dict:
    return json.loads(content[0].text)


class FakeModel:
    def __init__(self, *, start_timeout: bool = False) -> None:
        self.codes: list[str] = []
        self.rebuilds = 0
        self.running = False
        self.start_timeout = start_timeout

    def is_solver_running(self, *, timeout=None) -> bool:
        return self.running

    def get_active_solver_name(self, *a, **k):
        return "HF Time Domain"

    def add_to_history(self, *args, **kwargs):
        raise AssertionError("tool wrote to the model history")

    def _execute_vba_code(self, code: str, timeout=None) -> None:
        self.codes.append(code)
        if self.start_timeout and _starts(code):
            self.running = True  # the job keeps running inside CST
            raise TimeoutError("Operation timed out.")

    def full_history_rebuild(self, timeout=None) -> None:
        self.rebuilds += 1


def _client(model: FakeModel, results: bool | None = False, tmp_path=None) -> CSTClient:
    client = CSTClient(CSTConfig(work_dir=tmp_path) if tmp_path else CSTConfig())
    client._de = object()
    client._project = SimpleNamespace(model3d=model)
    client._project_path = str(tmp_path / "p.cst") if tmp_path else "p.cst"
    state = {"results": results}

    def results_present():
        return state["results"]

    def delete_results():
        model.codes.append("DeleteResults")
        state["results"] = False
        return {"status": "ok"}

    client.results_present = results_present  # type: ignore[method-assign]
    client.delete_results = delete_results  # type: ignore[method-assign]
    return client


def _call(module, name, args, client):
    return _decode(asyncio.run(module.handle(name, args, client)))


# -- cst_set_parameter / cst_delete_parameter -------------------------------


def test_set_parameter_refuses_on_solved_project_without_touching_cst():
    model = FakeModel()
    out = _call(parameters, "cst_set_parameter", {"name": "inset", "value": 8.8}, _client(model, True))
    assert out["status"] == "error" and out["code"] == "results_exist"
    assert model.codes == [] and model.rebuilds == 0


def test_set_parameter_uses_parameter_list_and_separate_rebuild():
    model = FakeModel()
    out = _call(parameters, "cst_set_parameter",
                {"name": "inset", "value": 8.8, "delete_results": True, "description": "feed"},
                _client(model, True))
    assert out["status"] == "ok" and out["history_written"] is False and out["rebuilt"] is True
    assert model.codes[0] == "DeleteResults"
    code = model.codes[1]
    assert 'StoreParameter "inset", "8.8"' in code and "SetParameterDescription" in code
    assert "RebuildOnParametricChange" not in code
    assert model.rebuilds == 1


def test_set_parameter_without_rebuild_and_unknown_results_state():
    model = FakeModel()
    out = _call(parameters, "cst_set_parameter", {"name": "a", "value": "b/2", "rebuild": False},
                _client(model, False))
    assert out["status"] == "ok" and out["rebuilt"] is False and model.rebuilds == 0
    model = FakeModel()
    out = _call(parameters, "cst_set_parameter", {"name": "a", "value": 1}, _client(model, None))
    assert out["code"] == "results_state_unknown" and model.codes == []


def test_set_parameter_rejects_invalid_name():
    out = _call(parameters, "cst_set_parameter", {"name": "a b", "value": 1}, _client(FakeModel()))
    assert out["status"] == "error"


def test_delete_parameter_has_no_history_rebuild():
    model = FakeModel()
    out = _call(parameters, "cst_delete_parameter", {"name": "old"}, _client(model))
    assert out["status"] == "ok" and 'DeleteParameter "old"' in model.codes[0]
    assert all("RebuildOnParametricChange" not in c for c in model.codes)
    assert model.rebuilds == 1


# -- sweep / optimizer configuration ----------------------------------------


def test_parameter_sweep_configures_without_history():
    model = FakeModel()
    out = _call(parameters, "cst_parameter_sweep",
                {"parameter": "inset", "start": 8, "stop": 9, "steps": 3,
                 "simulation_type": "Frequency Domain"}, _client(model, True))
    assert out["status"] == "configured" and out["history_written"] is False
    code = model.codes[0]
    assert ".DeleteAllSequences" in code and '.SetSimulationType "Frequency"' in code
    assert '.AddParameter_Samples "mcp_inset", "inset", 8.0, 9.0, 3, False' in code
    assert "StartActiveSolver" not in code and not _starts(code)
    assert "next_steps" in out


def test_parameter_sweep_always_sets_a_simulation_type():
    # CST 2026: "Simulation type is undefined" on Start otherwise.
    model = FakeModel()
    _call(parameters, "cst_parameter_sweep",
          {"parameter": "p", "start": 1, "stop": 2, "steps": 2}, _client(model))
    assert '.SetSimulationType "Transient"' in model.codes[0]  # follows HF Time Domain
    model.get_active_solver_name = lambda *a, **k: "HF Frequency Domain"
    _call(parameters, "cst_parameter_sweep",
          {"parameter": "p", "start": 1, "stop": 2, "steps": 2}, _client(model))
    assert '.SetSimulationType "Frequency"' in model.codes[1]
    offline = parameters._build_parameter_sweep({"parameter": "p", "start": 1, "stop": 2, "steps": 2})
    assert '.SetSimulationType "Transient"' in offline


def test_parameter_sweep_without_clear_is_still_idempotent():
    code = parameters._build_parameter_sweep(
        {"parameter": "p", "start": 1, "stop": 2, "steps": 2, "clear_existing": False})
    assert '.DeleteSequence "mcp_p"' in code and "DeleteAllSequences" not in code
    assert code.index("DeleteSequence") < code.index("AddSequence")


def test_parameter_sweep_run_refuses_with_results_after_configuring():
    model = FakeModel()
    out = _call(parameters, "cst_parameter_sweep",
                {"parameter": "p", "start": 1, "stop": 2, "steps": 2, "run": True}, _client(model, True))
    assert out["code"] == "results_exist" and out["configured"] is True
    assert not any(_starts(c) for c in model.codes)


def test_parameter_sweep_run_reports_started_while_cst_keeps_solving():
    model = FakeModel(start_timeout=True)
    client = _client(model, True)
    out = _call(parameters, "cst_parameter_sweep",
                {"parameter": "p", "start": 1, "stop": 2, "steps": 2, "run": True,
                 "delete_results": True}, client)
    assert out["status"] == "started" and out["running"] is True
    assert "DeleteResults" in model.codes and any("ParameterSweep.Start" in c for c in model.codes)
    assert client.pending_solve["seen_running"] is True


def test_start_blocking_vba_completed_and_timeout_without_running():
    model = FakeModel()
    client = _client(model)
    assert client.start_blocking_vba("Optimizer.Start", what="Optimizer")["status"] == "completed"

    class Stuck(FakeModel):
        def _execute_vba_code(self, code, timeout=None):
            raise TimeoutError("timed out")

    client = _client(Stuck())
    out = client.start_blocking_vba("Optimizer.Start", what="Optimizer")
    assert out["status"] == "timeout" and out["execution_state"] == "unknown"


_PARAMS = [{"name": "patch_L", "min": 28.0, "max": 29.8}, {"name": "inset", "min": 5, "max": 12}]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("cst_optimizer", {"goal_type": "minimize", "result_path": "1D Results\\S-Parameters\\S1,1",
                           "parameters": _PARAMS, "method": "Nelder Mead", "max_evaluations": 4,
                           "frequency_ghz": 2.4}),
        ("cst_multi_objective_optimizer", {
            "goals": [{"result_path": "1D Results\\S-Parameters\\S1,1", "goal_type": "minimize",
                       "frequency_ghz": 2.4},
                      {"result_path": "1D Results\\S-Parameters\\S1,1", "goal_type": "target",
                       "target_value": -20, "weight": 0.5}],
            "parameters": _PARAMS, "max_evaluations": 4}),
        ("cst_constrained_optimizer", {
            "objective": {"result_path": "1D Results\\S-Parameters\\S1,1", "goal_type": "minimize"},
            "constraints": [{"result_path": "1D Results\\S-Parameters\\S1,1", "operator": "<",
                             "value": -10}],
            "parameters": _PARAMS, "method": "Nelder Mead", "max_evaluations": 4}),
    ],
)
def test_optimizers_configure_idempotently_without_history(name, args):
    model = FakeModel()
    client = _client(model, True)
    first = _call(parameters, name, args, client)
    second = _call(parameters, name, args, client)
    assert first["status"] == second["status"] == "configured"
    assert first["history_written"] is False
    assert model.codes[0] == model.codes[1]
    code = model.codes[0]
    for reset in (".InitParameterList", ".ResetParameterList", ".DeleteAllGoals"):
        assert reset in code and code.index(reset) < code.index(".SelectParameter")
    assert not _starts(code)


def test_optimizer_run_starts_through_blocking_helper():
    model = FakeModel(start_timeout=True)
    out = _call(parameters, "cst_optimizer",
                {"goal_type": "minimize", "result_path": "1D Results\\S-Parameters\\S1,1",
                 "parameters": _PARAMS, "run": True}, _client(model, False))
    assert out["status"] == "started" and "Optimizer.Start" in model.codes[-1]


def test_sensitivity_and_yield_do_not_write_history():
    model = FakeModel()
    client = _client(model)
    out = _call(parameters, "cst_sensitivity_analysis",
                {"parameters": [{"name": "p", "nominal": 1.0}], "result_path": "x"}, client)
    assert out["status"] == "configured" and "StartActiveSolver" not in model.codes[-1]
    out = _call(parameters, "cst_yield_analysis",
                {"parameters": [{"name": "p", "nominal": 1.0, "tolerance": 0.1}],
                 "pass_criteria": [{"result_path": "x", "operator": "<", "threshold": 1}],
                 "num_samples": 2}, client)
    assert out["status"] == "configured" and model.codes[-1].count(".DeleteSequence") == 2


# -- cst_parameter_interpolation --------------------------------------------


class FakeReader:
    def __init__(self):
        self.runs = {0: 9.0, 1: 8.0, 2: 9.0, 3: 10.0}
        self.reads: list[int] = []

    def run_ids(self, tree):
        return list(self.runs)

    def parameter_combination(self, run_id):
        return {"inset": self.runs[run_id], "patch_L": 28.6}

    def read(self, tree, run_id):
        self.reads.append(run_id)
        level = {1: 0.5, 2: 0.3, 3: 0.1, 0: 0.3}[run_id]
        return {"x": [2.0, 2.4, 2.8], "values": [complex(level, 0.0)] * 2 + [complex(0, level)],
                "xlabel": "Frequency / GHz"}


def test_interpolation_between_bracketing_runs():
    reader = FakeReader()
    out = interpolate_runs(reader, "1D Results\\S-Parameters\\S1,1", "inset", 8.5)
    assert out["status"] == "ok"
    assert out["bracket"]["low"] == {"value": 8.0, "run_id": 1}
    assert out["bracket"]["high"] == {"value": 9.0, "run_id": 2}
    assert out["y_kind"] == "magnitude_db"
    assert out["y"][0] == pytest.approx(20 * __import__("math").log10(0.4))
    assert 0 not in reader.reads and out["warnings"] == []


def test_interpolation_exact_and_out_of_range():
    reader = FakeReader()
    exact = interpolate_runs(reader, "t", "inset", 10.0)
    assert exact["method"] == "exact run" and exact["bracket"]["low"]["run_id"] == 3
    out = interpolate_runs(reader, "t", "inset", 11.0)
    assert out["code"] == "out_of_range" and out["swept_values"] == [8.0, 9.0, 10.0]
    missing = interpolate_runs(reader, "t", "other", 1.0)
    assert missing["code"] == "no_sweep_runs"


def test_interpolation_tool_is_read_only(monkeypatch, tmp_path):
    from cst_mcp.execution import figures_1d_source

    monkeypatch.setattr(figures_1d_source, "open_reader", lambda *a, **k: FakeReader())
    model = FakeModel()
    out = _call(parameters, "cst_parameter_interpolation",
                {"parameter": "inset", "target_value": 9.5, "result_path": "t"},
                _client(model, True, tmp_path))
    assert out["status"] == "ok" and out["target_value"] == 9.5
    assert model.codes == [] and model.rebuilds == 0


# -- cst_evaluate_antenna ---------------------------------------------------


def test_single_frequency_band_is_interpolated():
    freqs = [2.3, 2.3986, 2.4014, 2.5]
    s11 = [-5.0, -20.0, -28.0, -6.0]
    band = optimization._evaluate_bands(freqs, s11, [
        {"name": "center", "f_low_ghz": 2.4, "f_high_ghz": 2.4, "vswr_target": 1.43}])[0]
    assert band["status"] == "PASS" and band["interpolated"] is True
    assert band["worst_s11_db"] == pytest.approx(-24.0, abs=0.01)
    assert band["evaluated_at_ghz"] == [2.4]
    outside = optimization._evaluate_bands(freqs, s11, [
        {"name": "x", "f_low_ghz": 3.0, "f_high_ghz": 3.0}])[0]
    assert outside["status"] == "NO_DATA"


def test_margin_sign_positive_means_pass():
    band = optimization._evaluate_bands([2.39, 2.4, 2.41], [-20.0, -25.0, -21.0], [
        {"name": "b", "f_low_ghz": 2.39, "f_high_ghz": 2.41, "vswr_target": 2.0}])[0]
    assert band["status"] == "PASS" and band["margin_db"] > 0


# -- cst_refine_antenna budget ----------------------------------------------


class RefineClient:
    """Solves instantly; S11 at 2.4 GHz improves as x approaches 5."""

    def __init__(self, tmp_path, clock):
        self._config = SimpleNamespace(work_dir=str(tmp_path))
        self.calls: list[dict] = []
        self.clock = clock

    def delete_results(self):
        return {"status": "ok"}

    def set_params_rebuild_solve(self, params, *, export_path, port):
        self.calls.append(dict(params))
        self.clock.t += 50.0  # each "solve" takes 50 s
        s11 = -3.0 - 30.0 / (1.0 + abs(params["x"] - 5.0))
        with open(export_path, "w") as fh:
            fh.write("Frequency / GHz    S / dB\n")
            for f in (2.3, 2.4, 2.5):
                fh.write(f"{f} {s11 if f == 2.4 else -3.0}\n")
        return {"status": "ok"}


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


_SPEC = [{"name": "x", "initial": 8.0, "min": 0.0, "max": 10.0}]
_BANDS = [{"name": "c", "f_low_ghz": 2.4, "f_high_ghz": 2.4, "vswr_target": 1.2}]


def test_refine_stops_on_time_budget_with_resume_block(tmp_path):
    clock = FakeClock()
    client = RefineClient(tmp_path, clock)
    out = asyncio.run(optimization._optimization_loop(
        client, _SPEC, _BANDS, 20, 1, max_seconds=120, clock=clock))
    assert out["status"] == "partial" and out["stop_reason"] == "max_seconds"
    assert len(client.calls) == 2  # third would end at 150 s > 120 s
    best = min(client.calls, key=lambda p: abs(p["x"] - 5.0))
    assert out["best_params"]["x"] == pytest.approx(best["x"], abs=1e-4)
    assert out["resume_from"]["parameters"][0]["initial"] == pytest.approx(best["x"], abs=1e-6)
    assert out["resume_from"]["bands"] == _BANDS
    assert out["bands"] and out["bands_source"] == "best evaluation so far"


def test_refine_stops_on_evaluation_budget(tmp_path):
    clock = FakeClock()
    client = RefineClient(tmp_path, clock)
    out = asyncio.run(optimization._optimization_loop(
        client, _SPEC, _BANDS, 20, 1, max_evaluations=3, clock=clock))
    assert out["status"] == "partial" and out["stop_reason"] == "max_evaluations"
    assert len(client.calls) == 3


def test_refine_without_budget_reports_final_solve_of_best_params(tmp_path):
    clock = FakeClock()
    client = RefineClient(tmp_path, clock)
    out = asyncio.run(optimization._optimization_loop(client, _SPEC, _BANDS, 3, 1, clock=clock))
    assert out["status"] == "optimized"
    assert client.calls[-1] == {"x": pytest.approx(out["best_params"]["x"], abs=1e-4)}
    assert out["bands_source"] == "final solve with best_params"
