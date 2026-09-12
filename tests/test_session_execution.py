"""CST session execution tests using fakes only; no CST process is contacted."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from cst_mcp.session import CSTSession
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import simulation
from cst_mcp.tools import mesh


class FakeModel3D:
    def __init__(self, *, running: bool = False) -> None:
        self.running = running
        self.calls: list[tuple[str, object]] = []
        self.raise_timeout = False

    def is_solver_running(self, *, timeout: int | None = None) -> bool:
        self.calls.append(("is_solver_running", timeout))
        return self.running

    def get_active_solver_name(self, *, timeout: int | None = None) -> str:
        self.calls.append(("get_active_solver_name", timeout))
        return "HF Time Domain"

    def get_solver_run_info(self, *, timeout: int | None = None) -> dict:
        self.calls.append(("get_solver_run_info", timeout))
        return {"progress": 25.0, "native": Path("run")}

    def run_solver(self, *, timeout: int | None = None) -> None:
        self.calls.append(("run_solver", timeout))
        if self.raise_timeout:
            self.running = True
            raise TimeoutError("CST command timeout")

    def start_solver(self, *, timeout: int | None = None) -> None:
        self.calls.append(("start_solver", timeout))
        self.running = True

    def pause_solver(self, *, timeout: int | None = None) -> None:
        self.calls.append(("pause_solver", timeout))

    def resume_solver(self, *, timeout: int | None = None) -> None:
        self.calls.append(("resume_solver", timeout))

    def abort_solver(self, *, timeout: int | None = None) -> None:
        self.calls.append(("abort_solver", timeout))

    def _execute_vba_code(self, vba: str) -> None:
        self.calls.append(("_execute_vba_code", vba))

    def full_history_rebuild(self, *, timeout: int | None = None) -> None:
        self.calls.append(("full_history_rebuild", timeout))


class FakeDesignEnvironment:
    def __init__(self, connected: bool = True) -> None:
        self._connected = connected
        self.close_called = False

    def is_connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        self.close_called = True


def make_session(model: FakeModel3D) -> tuple[CSTSession, FakeDesignEnvironment]:
    cfg = SimpleNamespace(
        cst_available=True,
        cst_path=None,
        python_lib_path=None,
        version="2026",
        work_dir=Path("."),
    )
    session = CSTSession(config=cfg)
    de = FakeDesignEnvironment()
    session._de = de
    session._project = SimpleNamespace(model3d=model)
    session._project_path = "fake.cst"
    return session, de


def decode_text(content) -> dict:
    return json.loads(content[0].text)


def test_connection_health_and_disconnect_never_close_cst() -> None:
    session, de = make_session(FakeModel3D())
    assert session.is_connected is True
    de._connected = False
    assert session.is_connected is False
    de._connected = True

    assert session.disconnect()["status"] == "disconnected"
    assert de.close_called is False
    assert session.has_project is False


def test_connect_does_not_change_design_environment_quiet_mode(monkeypatch) -> None:
    de = FakeDesignEnvironment()
    de.get_open_projects = lambda: []
    de.set_quiet_mode = lambda enabled: (_ for _ in ()).throw(
        AssertionError("connect must not change the user's Design Environment mode")
    )

    class FakeDesignEnvironmentFactory:
        @staticmethod
        def connect_to_any_or_new():
            return de

    interface = SimpleNamespace(DesignEnvironment=FakeDesignEnvironmentFactory)
    package = SimpleNamespace(interface=interface)
    monkeypatch.setitem(sys.modules, "cst", package)
    monkeypatch.setitem(sys.modules, "cst.interface", interface)

    config = SimpleNamespace(
        cst_available=True,
        cst_path=None,
        python_lib_path=None,
        version="2026",
        work_dir=Path("."),
        quiet_mode=True,
    )
    session = CSTSession(config=config)
    result = session.connect()
    assert result["status"] == "connected"
    assert session._de is de


def test_connect_is_idempotent_for_live_session() -> None:
    session, de = make_session(FakeModel3D())
    result = session.connect()
    assert result["status"] == "connected"
    assert result["message"] == "Already connected"
    assert session._de is de


def test_open_project_reference_accepts_handle_or_path() -> None:
    handle = SimpleNamespace(model3d=FakeModel3D())
    de = SimpleNamespace(get_open_project=lambda path: handle if path == "demo.cst" else None)
    assert CSTSession._project_from_open_ref(de, handle) is handle
    assert CSTSession._project_from_open_ref(de, "demo.cst") is handle


def test_blocking_run_uses_python_api_and_rejects_busy_solver() -> None:
    model = FakeModel3D(running=True)
    session, _ = make_session(model)
    result = session.run_solver(timeout_s=123)
    assert result["status"] == "busy"
    assert not any(name == "run_solver" for name, _ in model.calls)

    model.running = False
    result = session.run_solver(timeout_s=123)
    assert result["status"] == "executed"
    assert ("run_solver", 123) in model.calls


def test_async_start_rejects_busy_solver() -> None:
    model = FakeModel3D(running=True)
    session, _ = make_session(model)
    result = session.start_solver(timeout_s=17)
    assert result["status"] == "busy"
    assert not any(name == "start_solver" for name, _ in model.calls)


def test_blocking_timeout_reports_solver_state_without_aborting() -> None:
    model = FakeModel3D()
    model.raise_timeout = True
    session, _ = make_session(model)
    result = session.run_solver(timeout_s=5)
    assert result == {
        "status": "timeout",
        "message": "CST command timeout",
        "running": True,
    }
    assert not any(name == "abort_solver" for name, _ in model.calls)


def test_solver_status_is_read_only_and_json_safe() -> None:
    model = FakeModel3D(running=True)
    session, _ = make_session(model)
    result = session.solver_status(timeout_s=9)
    assert result["running"] is True
    assert result["active_solver"] == "HF Time Domain"
    assert result["run_info"]["native"] == "run"
    assert not any(name in {"run_solver", "start_solver", "abort_solver"} for name, _ in model.calls)


def test_parameter_solve_does_not_mutate_while_busy() -> None:
    model = FakeModel3D(running=True)
    session, _ = make_session(model)
    result = session.set_params_rebuild_solve({"gap": 0.2}, export_s11=False)
    assert result["status"] == "busy"
    assert all(name == "is_solver_running" or name.startswith("get_") for name, _ in model.calls)


def test_parameter_solve_uses_modeler_vba_and_documented_rebuild() -> None:
    model = FakeModel3D()
    session, _ = make_session(model)
    result = session.set_params_rebuild_solve({"gap": 0.2}, export_s11=False, timeout_s=44)
    assert result["status"] == "ok"
    vba = next(value for name, value in model.calls if name == "_execute_vba_code")
    assert 'StoreParameter "gap", "0.2"' in vba
    assert "DeleteResults" in vba
    assert ("full_history_rebuild", 30) in model.calls
    assert ("run_solver", 44) in model.calls


def test_parameter_vba_rejects_multiline_injection() -> None:
    try:
        CSTSession._parameter_vba({"gap": '1"\nDeleteResults'})
    except ValueError as exc:
        assert "control character" in str(exc)
    else:
        raise AssertionError("multiline parameter value was accepted")


def test_parameter_solve_honors_optimizer_export_path(tmp_path, monkeypatch) -> None:
    model = FakeModel3D()
    session, _ = make_session(model)
    session.config.work_dir = tmp_path
    output = tmp_path / "optimizer_s11.csv"

    def fake_export(tree_path: str, filepath: str) -> dict:
        Path(filepath).write_text("Frequency,dB\n2.4,-12\n", encoding="utf-8")
        return {"status": "exported", "tree_path": tree_path, "path": filepath}

    monkeypatch.setattr(session, "export_tree_csv", fake_export)
    result = session.set_params_rebuild_solve(
        {"gap": 0.3}, export_path=str(output), export_s11=True, timeout_s=20
    )
    assert result["status"] == "ok"
    assert output.is_file()
    assert result["s_parameters"]["metrics"]["min_db"] == -12.0


def test_simulation_adapter_uses_session_api_without_modal_vba() -> None:
    model = FakeModel3D()
    session, _ = make_session(model)
    status = decode_text(simulation._handle_get_status({"timeout_s": 7}, session))
    assert status["status"] == "ok"
    assert status["running"] is False
    assert not any(name in {"run_solver", "start_solver"} for name, _ in model.calls)

    blocking = decode_text(
        simulation._handle_run_simulation({"timeout_s": 11}, session, async_mode=False)
    )
    assert blocking["status"] == "executed"
    assert blocking["mode"] == "blocking"
    assert ("run_solver", 11) in model.calls

    asynchronous = decode_text(
        simulation._handle_run_simulation({"timeout_s": 13}, session, async_mode=True)
    )
    assert asynchronous["status"] == "started"
    assert asynchronous["mode"] == "async"
    assert ("start_solver", 13) in model.calls

    paused = decode_text(simulation._handle_simple_solver_command("pause", {"timeout_s": 3}, session))
    stopped = decode_text(simulation._handle_simple_solver_command("abort", {"timeout_s": 4}, session))
    assert paused["command"] == "pause"
    assert stopped["command"] == "stop"
    assert ("pause_solver", 3) in model.calls
    assert ("abort_solver", 4) in model.calls


def test_simulation_adapter_rejects_busy_before_solver_selection() -> None:
    class BusyClient:
        def __init__(self) -> None:
            self.execute_calls = 0

        def solver_status(self, timeout_s: float) -> dict:
            return {"status": "ok", "running": True}

        def execute_vba(self, *args, **kwargs) -> dict:
            self.execute_calls += 1
            return {"status": "executed"}

    client = BusyClient()
    result = decode_text(
        simulation._handle_run_simulation(
            {"solver_type": "Frequency Domain", "timeout_s": 10}, client, async_mode=False
        )
    )
    assert result["status"] == "busy"
    assert client.execute_calls == 0


def test_integral_equation_uses_official_cst_solver_name() -> None:
    class SelectionClient:
        def __init__(self) -> None:
            self.vba = ""

        def execute_vba(self, vba: str, history_label: str) -> dict:
            self.vba = vba
            return {"status": "executed", "label": history_label}

    client = SelectionClient()
    result = simulation._select_solver("Integral Equation", client)
    assert result["status"] == "executed"
    assert client.vba == 'ChangeSolverType "HF IntegralEq"'


def test_execute_vba_does_not_start_implicit_dialog_watcher(monkeypatch) -> None:
    class ExplodingWatcher:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("dialog watcher must be explicit")

    monkeypatch.setattr("cst_mcp.cst_client.DialogWatcher", ExplodingWatcher)
    model = SimpleNamespace(add_to_history=lambda label, vba: None)
    session, _ = make_session(model)
    client = CSTClient(config=session.config)
    client._de = session._de
    client._project = session._project
    result = client.execute_vba("With Brick\nEnd With", history_label="brick")
    assert result["status"] == "executed"


def test_mesh_density_uses_cst_2026_meshsettings() -> None:
    class CaptureClient:
        def __init__(self) -> None:
            self.vba = ""

        def execute_vba(self, vba: str) -> dict:
            self.vba = vba
            return {"status": "offline", "vba": vba}

    client = CaptureClient()
    result = decode_text(
        mesh._set_mesh_density(
            {"cells_per_wavelength": 24, "min_cells": 12, "ratio_limit": 18}, client
        )
    )
    assert 'MeshSettings' in client.vba
    assert '.Set "StepsPerWaveNear", "24"' in client.vba
    assert '.Set "StepsPerWaveFar", "24"' in client.vba
    assert '.Set "StepsPerBoxNear", "12"' in client.vba
    assert "LinesPerWavelength" not in client.vba
    assert result["density_api"] == "MeshSettings.Set"
