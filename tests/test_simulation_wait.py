"""Bounded cst_wait_for_simulation behaviour using fakes; no CST process is contacted."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate

from cst_mcp.session import CSTSession
from cst_mcp.tools import simulation
from cst_mcp.tools.registry import _tool_schema


class FakeClock:
    """Deterministic monotonic clock advanced by the fake sleep and status calls."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(simulation, "_clock", fake)
    monkeypatch.setattr(simulation, "_sleep", fake.sleep)
    return fake


class StatusClient:
    """Client whose solver finishes after ``running_polls`` status queries.

    ``query_cost_s`` is the simulated duration of each CST call; ``None``
    simulates the worst case where every call runs to its full (whole-second,
    >= 1 s) CST timeout.
    """

    def __init__(
        self,
        clock: FakeClock,
        running_polls: int,
        query_cost_s: float | None = 0.1,
        pending: dict | None = None,
    ) -> None:
        self.clock = clock
        self.running_polls = running_polls
        self.query_cost_s = query_cost_s
        self.timeouts: list[float] = []
        self.running_only: list[bool] = []
        self.detail_timeouts: list[float] = []
        self._pending = pending
        self.cleared = False

    def _spend(self, timeout_s: float) -> None:
        cost = self.query_cost_s
        self.clock.now += max(1, int(timeout_s)) if cost is None else cost

    def solver_status(self, timeout_s: float = 30.0, *, running_only: bool = False) -> dict:
        self.timeouts.append(timeout_s)
        self.running_only.append(running_only)
        self._spend(timeout_s)
        running = len(self.timeouts) <= self.running_polls
        if running and self._pending is not None:
            self._pending["seen_running"] = True
        out = {"status": "ok", "running": running}
        if not running_only:
            out.update(self.solver_details(timeout_s))
        return out

    def solver_details(self, timeout_s: float = 30.0, *, running=None) -> dict:
        # Two CST calls (active solver name + run info).
        self.detail_timeouts.append(timeout_s)
        self._spend(timeout_s)
        self._spend(timeout_s)
        return {"active_solver": "HF Time Domain", "run_info": {"last_reported_state": "OK"}}

    @property
    def pending_solve(self) -> dict | None:
        return dict(self._pending) if self._pending is not None else None

    def clear_pending_solve(self) -> None:
        self._pending = None
        self.cleared = True


async def call(arguments: dict, client) -> dict:
    content = await simulation.handle("cst_wait_for_simulation", arguments, client)
    data = json.loads(content[0].text)
    if data["status"] != "error":
        validate(instance=data, schema=simulation.WAIT_OUTPUT_SCHEMA)
    return data


def test_wait_tool_is_registered_with_bounded_input() -> None:
    tool = next(t for t in simulation.TOOLS if t.name == "cst_wait_for_simulation")
    prop = _tool_schema(tool, "inputSchema", "input_schema")["properties"]["max_wait_s"]
    assert prop["default"] == 45
    assert prop["maximum"] == 55
    assert "max_wait_s + 2 s" in tool.description
    assert "safe for MCP clients" not in tool.description
    enum = simulation.WAIT_OUTPUT_SCHEMA["properties"]["status"]["enum"]
    assert "starting" in enum
    run = next(t for t in simulation.TOOLS if t.name == "cst_run_simulation")
    run_async = next(t for t in simulation.TOOLS if t.name == "cst_run_simulation_async")
    assert "cst_wait_for_simulation" in run.description
    assert "cst_run_simulation_async" in run.description
    assert "cst_stop_simulation" in run.description
    assert "cst_wait_for_simulation" in run_async.description


@pytest.mark.asyncio
async def test_wait_returns_finished_when_solver_goes_idle(clock) -> None:
    client = StatusClient(clock, running_polls=3, pending={"t0": clock.now, "seen_running": False})
    data = await call({"max_wait_s": 30}, client)
    assert data["status"] == "finished"
    assert data["running"] is False
    assert data["polls"] == 4
    assert data["active_solver"] == "HF Time Domain"
    assert data["confirmed"] is True
    assert data["solve_observed"] is True
    assert client.cleared is True
    assert clock.sleeps == [2.0, 2.0, 2.0]
    assert 6.0 <= data["elapsed_s"] < 7.0


@pytest.mark.asyncio
async def test_intermediate_polls_are_lightweight_and_details_read_once(clock) -> None:
    client = StatusClient(clock, running_polls=5)
    data = await call({"max_wait_s": 30}, client)
    assert data["status"] == "finished"
    assert client.running_only == [True] * 6
    assert len(client.detail_timeouts) == 1
    assert data["run_info"] == {"last_reported_state": "OK"}


@pytest.mark.asyncio
async def test_wait_returns_running_within_bound(clock) -> None:
    client = StatusClient(clock, running_polls=10_000)
    start = clock.now
    data = await call({"max_wait_s": 9}, client)
    assert data["status"] == "running"
    assert data["running"] is True
    assert "again" in data["hint"]
    assert clock.now - start <= 9 + client.query_cost_s + 1e-9
    assert data["elapsed_s"] <= 9 + client.query_cost_s + 1e-9
    assert all(0 < s <= 2.0 for s in clock.sleeps)
    # Status queries never get a timeout longer than the remaining budget (floor 1 s).
    assert all(1.0 <= t <= 10.0 for t in client.timeouts)
    assert client.detail_timeouts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("max_wait_s", [0, 0.4, 1, 1.5, 2.7, 5, 9.3, 29.9, 45, 55])
@pytest.mark.parametrize("running_polls", [0, 1, 3, 10_000])
async def test_worst_case_cst_timeouts_stay_within_bound(
    clock, max_wait_s: float, running_polls: int
) -> None:
    """Every CST call running to its full timeout still ends by max_wait_s + 2 s."""
    client = StatusClient(clock, running_polls=running_polls, query_cost_s=None)
    start = clock.now
    data = await call({"max_wait_s": max_wait_s}, client)
    assert data["status"] in {"finished", "running"}
    assert clock.now - start <= max_wait_s + simulation._WAIT_OVERRUN_S + 1e-9
    assert data["elapsed_s"] <= max_wait_s + simulation._WAIT_OVERRUN_S + 1e-9
    # A single poll per call, each with a timeout cut to the remaining budget.
    assert all(t <= simulation._WAIT_STATUS_TIMEOUT_S for t in client.timeouts)


@pytest.mark.asyncio
async def test_wait_clamps_max_wait_to_55_seconds(clock) -> None:
    client = StatusClient(clock, running_polls=10_000, query_cost_s=0.0)
    start = clock.now
    data = await call({"max_wait_s": 600}, client)
    assert data["status"] == "running"
    assert data["max_wait_s"] == 55
    assert clock.now - start <= 55 + 1e-9


@pytest.mark.asyncio
async def test_wait_zero_performs_single_check(clock) -> None:
    client = StatusClient(clock, running_polls=10_000, query_cost_s=0.0)
    data = await call({"max_wait_s": 0}, client)
    assert data["status"] == "running"
    assert data["polls"] == 1
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_wait_default_is_45_seconds(clock) -> None:
    client = StatusClient(clock, running_polls=10_000, query_cost_s=0.0)
    start = clock.now
    data = await call({}, client)
    assert data["status"] == "running"
    assert data["max_wait_s"] == 45
    # The last poll is not started with less than 1 s of budget left.
    assert 44 - 1e-9 <= clock.now - start <= 45 + 1e-9


@pytest.mark.asyncio
async def test_solve_not_yet_started_is_starting_not_finished(clock) -> None:
    """Idle right after cst_run_simulation_async means 'starting' within the grace."""
    client = StatusClient(clock, running_polls=0, pending={"t0": clock.now, "seen_running": False})
    data = await call({"max_wait_s": 5}, client)
    assert data["status"] == "starting"
    assert data["running"] is False
    assert data["polls"] > 1
    assert client.cleared is False
    assert client.pending_solve is not None


@pytest.mark.asyncio
async def test_solve_that_starts_late_is_confirmed(clock) -> None:
    class LateStart(StatusClient):
        def solver_status(self, timeout_s: float = 30.0, *, running_only: bool = False) -> dict:
            state = super().solver_status(timeout_s, running_only=running_only)
            n = len(self.timeouts)
            state["running"] = 3 <= n <= 5  # idle, idle, running x3, idle
            if state["running"]:
                self._pending["seen_running"] = True
            return state

    client = LateStart(clock, running_polls=0, pending={"t0": clock.now, "seen_running": False})
    data = await call({"max_wait_s": 30}, client)
    assert data["status"] == "finished"
    assert data["polls"] == 6
    assert data["confirmed"] is True
    assert client.cleared is True


@pytest.mark.asyncio
async def test_solve_never_seen_running_after_grace_warns(clock) -> None:
    client = StatusClient(clock, running_polls=0, pending={"t0": clock.now, "seen_running": False})
    data = await call({"max_wait_s": 30}, client)
    assert data["status"] == "finished"
    assert data["confirmed"] is False
    assert data["solve_observed"] is False
    assert "never seen running" in data["warning"]
    assert data["elapsed_s"] >= simulation._WAIT_START_GRACE_S
    assert client.cleared is True


@pytest.mark.asyncio
async def test_finished_without_recorded_solve_is_unconfirmed(clock) -> None:
    client = StatusClient(clock, running_polls=0)
    data = await call({"max_wait_s": 30}, client)
    assert data["status"] == "finished"
    assert data["polls"] == 1
    assert data["confirmed"] is False
    assert data["solve_observed"] is False
    assert "No solve started" in data["warning"]


@pytest.mark.asyncio
async def test_wait_supports_clients_without_running_only(clock) -> None:
    client = SimpleNamespace(solver_status=lambda timeout_s=30.0: {
        "status": "ok", "running": False, "active_solver": "HF Time Domain",
    })
    data = await call({"max_wait_s": 4}, client)
    assert data["status"] == "finished"
    assert data["active_solver"] == "HF Time Domain"


@pytest.mark.asyncio
async def test_wait_propagates_unknown_solver_state_as_error(clock) -> None:
    client = SimpleNamespace(
        solver_status=lambda timeout_s=30.0: {
            "status": "error", "message": "CST status channel unavailable", "running": None,
        }
    )
    data = await call({"max_wait_s": 10}, client)
    assert data["status"] == "error"
    assert data["message"] == "CST status channel unavailable"
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_wait_offline_session_returns_error(clock) -> None:
    cfg = SimpleNamespace(
        cst_available=False, cst_path=None, python_lib_path=None, version="2026",
        work_dir=Path("."),
    )
    session = CSTSession(config=cfg)
    data = await call({"max_wait_s": 20}, session)
    assert data["status"] == "error"
    assert data["code"] == "offline"
    assert "connected mode" in data["message"]
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_wait_rejects_non_numeric_max_wait(clock) -> None:
    client = StatusClient(clock, running_polls=0)
    data = await call({"max_wait_s": "soon"}, client)
    assert data["status"] == "error"
    assert client.timeouts == []


# -- CSTSession: lightweight status + pending-solve bookkeeping ---------------


class FakeModel3D:
    def __init__(self) -> None:
        self.running = False
        self.calls: list[tuple[str, object]] = []

    def is_solver_running(self, *, timeout=None) -> bool:
        self.calls.append(("is_solver_running", timeout))
        return self.running

    def get_active_solver_name(self, *, timeout=None) -> str:
        self.calls.append(("get_active_solver_name", timeout))
        return "HF Time Domain"

    def get_solver_run_info(self, *, timeout=None) -> dict:
        self.calls.append(("get_solver_run_info", timeout))
        return {"state": "OK"}

    def start_solver(self, *, timeout=None) -> None:
        self.calls.append(("start_solver", timeout))

    def abort_solver(self, *, timeout=None) -> None:
        self.calls.append(("abort_solver", timeout))


def make_session(model: FakeModel3D) -> CSTSession:
    cfg = SimpleNamespace(
        cst_available=True, cst_path=None, python_lib_path=None, version="2026",
        work_dir=Path("."),
    )
    session = CSTSession(config=cfg)
    session._de = SimpleNamespace(is_connected=lambda: True)
    session._project = SimpleNamespace(model3d=model)
    session._project_path = "fake.cst"
    return session


def test_running_only_status_makes_one_cst_call() -> None:
    model = FakeModel3D()
    session = make_session(model)
    assert session.solver_status(timeout_s=4, running_only=True) == {
        "status": "ok", "running": False,
    }
    assert model.calls == [("is_solver_running", 4)]
    full = session.solver_status(timeout_s=4)
    assert full["active_solver"] == "HF Time Domain"
    assert full["run_info"]["last_reported_state"] == "OK"


def test_start_solver_records_pending_and_running_is_observed() -> None:
    model = FakeModel3D()
    session = make_session(model)
    assert session.pending_solve is None
    assert session.start_solver(timeout_s=5)["status"] == "started"
    pending = session.pending_solve
    assert pending is not None and pending["seen_running"] is False
    assert math.isfinite(pending["t0"])
    model.running = True
    session.solver_status(timeout_s=2, running_only=True)
    assert session.pending_solve["seen_running"] is True
    session.clear_pending_solve()
    assert session.pending_solve is None


def test_abort_and_disconnect_clear_pending_solve() -> None:
    model = FakeModel3D()
    session = make_session(model)
    session.start_solver(timeout_s=5)
    assert session.abort_solver(timeout_s=3)["status"] == "executed"
    assert session.pending_solve is None
    session.start_solver(timeout_s=5)
    session.disconnect()
    assert session.pending_solve is None


@pytest.mark.asyncio
async def test_wait_on_real_session_right_after_async_start(clock, monkeypatch) -> None:
    """End to end on CSTSession: idle-before-start is not reported as finished."""
    model = FakeModel3D()
    session = make_session(model)
    session.start_solver(timeout_s=5)
    # Align the session's pending timestamp with the fake clock.
    session._pending_solve["t0"] = clock.now
    data = await call({"max_wait_s": 3}, session)
    assert data["status"] == "starting"
    model.running = True
    data = await call({"max_wait_s": 3}, session)
    assert data["status"] == "running"
    model.running = False
    data = await call({"max_wait_s": 3}, session)
    assert data["status"] == "finished"
    assert data["confirmed"] is True
    assert data["active_solver"] == "HF Time Domain"
    assert session.pending_solve is None
