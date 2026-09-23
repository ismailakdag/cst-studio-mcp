"""Simulation control tools for CST Studio Suite."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import time
from typing import Any

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient

logger = logging.getLogger(__name__)

_VALID_SOLVER_TYPES = [
    "Time Domain",
    "Frequency Domain",
    "Eigenmode",
    "Integral Equation",
]

_SOLVER_TYPE_SCHEMA = {
    "type": "string",
    "enum": _VALID_SOLVER_TYPES,
    "description": (
        "Solver type to use. If omitted, the currently configured solver is used. "
        "Options: 'Time Domain', 'Frequency Domain', 'Eigenmode', 'Integral Equation'."
    ),
}

# Upper bound for one cst_wait_for_simulation call. Many MCP clients abort a
# single tools/call after ~60 s, so one wait must stay below that. Every CST
# call made by the wait gets a timeout derived from the remaining budget, so
# a call returns within max_wait_s + _WAIT_OVERRUN_S (plus the CST API's own
# timeout-enforcement latency).
_WAIT_DEFAULT_S = 45.0
_WAIT_MAX_S = 55.0
_WAIT_POLL_S = 2.0
_WAIT_STATUS_TIMEOUT_S = 10.0
# The CST API takes whole-second timeouts (minimum 1 s). No further poll is
# started once less than this remains, so a poll never outlives the budget.
_WAIT_MIN_CALL_S = 1.0
# Documented worst-case overrun of max_wait_s: the first check always runs
# (>= 1 s timeout even for max_wait_s=0) and the final active-solver/run-info
# read gets at most 2 x 1 s when little budget is left.
_WAIT_OVERRUN_S = 2.0
# After cst_run_simulation_async, CST may report "not running" for a moment
# before the solver actually starts. Within this grace period an idle state
# is reported as "starting", not "finished".
_WAIT_START_GRACE_S = 15.0

# Injectable for tests: monotonic clock and awaitable sleep.
_clock = time.monotonic
_sleep = asyncio.sleep

# CST's get_solver_run_info reports the outcome of the LAST run / history
# update and carries no timestamp, so its state is exposed as
# last_reported_state (with state_note) rather than as the current state.
_RUN_INFO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "last_reported_state": {"type": ["string", "null"]},
        "state_note": {"type": "string"},
        "reported_at": {},
        "message": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}

SOLVER_STATUS_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "description": (
        "Solver state. status='ok' always carries running; status='offline' "
        "means there is no connected CST project."
    ),
    "properties": {
        "status": {"type": "string"},
        "running": {"type": ["boolean", "null"]},
        "active_solver": {"type": "string"},
        "run_info": _RUN_INFO_SCHEMA,
        "message": {"type": "string"},
    },
    "required": ["status"],
    "if": {"properties": {"status": {"const": "ok"}}, "required": ["status"]},
    "then": {"required": ["running"]},
    "additionalProperties": True,
}

WAIT_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "description": (
        "status='finished' when the solver is no longer running; status='running' "
        "when max_wait_s elapsed first (call cst_wait_for_simulation again); "
        "status='starting' when an async solve was launched but CST has not yet "
        "reported it running (call again). confirmed=true only when this server "
        "started the solve and observed it running before it went idle."
    ),
    "properties": {
        "status": {"type": "string", "enum": ["finished", "running", "starting", "error"]},
        "confirmed": {"type": "boolean"},
        "solve_observed": {"type": "boolean"},
        "warning": {"type": "string"},
        "running": {"type": ["boolean", "null"]},
        "elapsed_s": {"type": "number", "minimum": 0},
        "max_wait_s": {"type": "number", "minimum": 0},
        "polls": {"type": "integer", "minimum": 0},
        "active_solver": {"type": "string"},
        "run_info": _RUN_INFO_SCHEMA,
        "hint": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["status", "elapsed_s"],
    "additionalProperties": True,
}

TOOLS: list[Tool] = [
    Tool(
        name="cst_run_simulation",
        description=(
            "Start a CST simulation with the current solver settings and block "
            "until it completes (up to timeout_s). The server stays responsive, "
            "but other CST tool calls queue behind the solve, and cancelling the "
            "request does not stop a solve already running in CST (use "
            "cst_stop_simulation). Many MCP clients abort a single tool call "
            "after about a minute, so for any solve that may take longer than "
            "~60 s prefer cst_run_simulation_async followed by repeated "
            "cst_wait_for_simulation calls."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "solver_type": _SOLVER_TYPE_SCHEMA,
                "timeout_s": {
                    "type": "number",
                    "default": 3600,
                    "exclusiveMinimum": 0,
                    "description": "Maximum CST Python API call duration in seconds.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_run_simulation_async",
        description=(
            "Start a CST simulation asynchronously (non-blocking). "
            "The simulation launches and control returns immediately. "
            "Then call cst_wait_for_simulation (bounded wait, returns within "
            "about max_wait_s) repeatedly until it reports status 'finished'; "
            "cst_get_simulation_status gives a single instant snapshot."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "solver_type": _SOLVER_TYPE_SCHEMA,
                "timeout_s": {
                    "type": "number",
                    "default": 30,
                    "exclusiveMinimum": 0,
                    "description": "Maximum CST Python API start-command duration in seconds.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_get_simulation_status",
        description=(
            "Read whether a CST simulation is running and return any solver-run "
            "metadata exposed by the CST Python API. This does not show a dialog "
            "or change the simulation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "timeout_s": {"type": "number", "default": 30, "exclusiveMinimum": 0},
            },
            "required": [],
        },
        outputSchema=SOLVER_STATUS_OUTPUT_SCHEMA,
    ),
    Tool(
        name="cst_wait_for_simulation",
        description=(
            "Wait a bounded time for the running CST solve to finish, polling only "
            "the read-only 'is solver running' flag about every 2 s. Returns status "
            "'finished' once the solver is idle (confirmed=true when the solve "
            "started by cst_run_simulation_async was seen running), 'starting' "
            "while a just-launched solve has not begun yet, or 'running' once "
            "max_wait_s (default 45, max 55) has passed; for 'running'/'starting' "
            "call this tool again. Each CST query's timeout is cut to the remaining "
            "budget, so the call returns within about max_wait_s + 2 s. Use after "
            "cst_run_simulation_async. Does not start, stop or change the "
            "simulation. Requires connected mode."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "max_wait_s": {
                    "type": "number",
                    "default": _WAIT_DEFAULT_S,
                    "minimum": 0,
                    "maximum": _WAIT_MAX_S,
                    "description": (
                        "Maximum seconds to wait in this call (0-55). "
                        "0 performs a single status check."
                    ),
                },
            },
            "required": [],
        },
        outputSchema=WAIT_OUTPUT_SCHEMA,
    ),
    Tool(
        name="cst_pause_simulation",
        description=(
            "Pause a currently running CST simulation. "
            "The simulation can be resumed later with cst_resume_simulation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "timeout_s": {"type": "number", "default": 30, "exclusiveMinimum": 0},
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_resume_simulation",
        description=(
            "Resume a previously paused CST simulation. "
            "Use after cst_pause_simulation to continue from where it stopped."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "timeout_s": {"type": "number", "default": 30, "exclusiveMinimum": 0},
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_stop_simulation",
        description=(
            "Stop and abort a running CST simulation. "
            "Unlike pause, a stopped simulation cannot be resumed — "
            "it must be restarted from the beginning."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "timeout_s": {"type": "number", "default": 30, "exclusiveMinimum": 0},
            },
            "required": [],
        },
    ),
]

_TOOL_NAMES = {tool.name for tool in TOOLS}


_SOLVER_VBA_NAMES = {
    "Time Domain": "HF Time Domain",
    "Frequency Domain": "HF Frequency Domain",
    "Eigenmode": "HF Eigenmode",
    "Integral Equation": "HF IntegralEq",
}


def _select_solver(solver_type: str | None, client: CSTClient) -> dict | None:
    """Select an explicitly requested solver before using the Python run API."""
    if solver_type is None:
        return None
    vba_name = _SOLVER_VBA_NAMES[solver_type]
    return client.execute_vba(
        f'ChangeSolverType "{vba_name}"',
        history_label="select_solver_type",
    )


async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a simulation control tool call."""
    try:
        if name == "cst_run_simulation":
            return _handle_run_simulation(arguments, client, async_mode=False)

        if name == "cst_run_simulation_async":
            return _handle_run_simulation(arguments, client, async_mode=True)

        if name == "cst_get_simulation_status":
            return _handle_get_status(arguments, client)

        if name == "cst_wait_for_simulation":
            return await _handle_wait_for_simulation(arguments, client)

        if name == "cst_pause_simulation":
            return _handle_simple_solver_command("pause", arguments, client)

        if name == "cst_resume_simulation":
            return _handle_simple_solver_command("resume", arguments, client)

        if name == "cst_stop_simulation":
            return _handle_simple_solver_command("abort", arguments, client)

        return [
            TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown simulation tool: {name}"}),
            )
        ]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


def _handle_run_simulation(
    arguments: dict, client: CSTClient, *, async_mode: bool
) -> list[TextContent]:
    """Handle cst_run_simulation and cst_run_simulation_async."""
    solver_type = arguments.get("solver_type")

    if solver_type is not None and solver_type not in _VALID_SOLVER_TYPES:
        return [
            TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "error": f"Invalid solver_type '{solver_type}'",
                    "valid_options": _VALID_SOLVER_TYPES,
                }),
            )
        ]

    timeout_default = 30.0 if async_mode else 3600.0
    timeout_s = float(arguments.get("timeout_s", timeout_default))
    state = client.solver_status(timeout_s=min(timeout_s, 30.0))
    if state.get("status") == "ok" and state.get("running"):
        state.update(
            {
                "status": "busy",
                "message": "A solver is already running; no second solve was started.",
                "solver_type": solver_type or "current",
                "mode": "async" if async_mode else "blocking",
            }
        )
        return [TextContent(type="text", text=json.dumps(state, indent=2))]
    if state.get("status") not in {"ok", "offline"}:
        return [TextContent(type="text", text=json.dumps(state, indent=2))]

    selection = _select_solver(solver_type, client)
    if selection is not None and selection.get("status") not in {"executed", "offline"}:
        result = selection
    else:
        result = (
            client.start_solver(timeout_s=timeout_s)
            if async_mode
            else client.run_solver(timeout_s=timeout_s)
        )

    result["solver_type"] = solver_type or "current"
    result["mode"] = "async" if async_mode else "blocking"
    if selection is not None:
        result["solver_selection"] = selection

    if async_mode and result.get("status") == "offline":
        result["note"] = (
            "In connected mode this command would launch the simulation "
            "and return immediately. Use cst_wait_for_simulation to wait for it."
        )
    elif async_mode and result.get("status") == "started":
        result["note"] = (
            "Simulation launched. Call cst_wait_for_simulation repeatedly until "
            "it reports status 'finished'."
        )

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _handle_get_status(arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle cst_get_simulation_status."""
    result = client.solver_status(timeout_s=float(arguments.get("timeout_s", 30)))
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _json(data: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _supports_running_only(client: CSTClient) -> bool:
    """Whether ``client.solver_status`` accepts ``running_only`` (test fakes may not)."""
    try:
        params = inspect.signature(client.solver_status).parameters
    except (TypeError, ValueError):
        return False
    return "running_only" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )


def _call_timeout(remaining: float) -> float:
    """Per-CST-call timeout: the remaining budget, capped at 10 s, floor 1 s."""
    return max(_WAIT_MIN_CALL_S, min(_WAIT_STATUS_TIMEOUT_S, remaining))


def _pending_solve(client: CSTClient) -> dict | None:
    pending = getattr(client, "pending_solve", None)
    return pending if isinstance(pending, dict) else None


def _finished_payload(client: CSTClient, pending: dict | None) -> dict[str, Any]:
    """confirmed / solve_observed / warning for a finished wait; clears the record."""
    if pending is not None:
        clear = getattr(client, "clear_pending_solve", None)
        if callable(clear):
            clear()
    if pending is not None and pending.get("seen_running"):
        return {"confirmed": True, "solve_observed": True}
    if pending is not None:
        warning = (
            "The solve started by cst_run_simulation_async was never seen running "
            f"within {_WAIT_START_GRACE_S:g} s: it either finished very quickly or did "
            "not start. Check run_info / cst_get_messages before reading results."
        )
    else:
        warning = (
            "No solve started by cst_run_simulation_async is pending in this server "
            "session, so the idle state may predate any solve. Verify results are current."
        )
    return {"confirmed": False, "solve_observed": False, "warning": warning}


async def _handle_wait_for_simulation(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle cst_wait_for_simulation: a bounded poll of the solver state.

    Intermediate polls read only the running flag (one CST call, timeout cut to
    the remaining budget). ``active_solver``/``run_info`` are read once, at the
    end of a finished wait and only when budget remains, so the call returns
    within ``max_wait_s + _WAIT_OVERRUN_S``.
    """
    raw = arguments.get("max_wait_s")
    try:
        max_wait_s = _WAIT_DEFAULT_S if raw is None else float(raw)
    except (TypeError, ValueError):
        return _json({"status": "error", "message": f"max_wait_s must be a number, got {raw!r}"})
    if not math.isfinite(max_wait_s):
        return _json({"status": "error", "message": "max_wait_s must be a finite number"})
    max_wait_s = min(max(max_wait_s, 0.0), _WAIT_MAX_S)

    lightweight = _supports_running_only(client)
    start = _clock()
    deadline = start + max_wait_s
    polls = 0

    def elapsed() -> float:
        return round(max(0.0, _clock() - start), 3)

    def details(state: dict) -> dict:
        extra = {key: state[key] for key in ("active_solver", "run_info") if key in state}
        get_details = getattr(client, "solver_details", None)
        remaining = deadline - _clock()
        if lightweight and callable(get_details) and remaining >= _WAIT_MIN_CALL_S:
            # Two CST calls: split what is left of the budget between them.
            try:
                extra.update(get_details(timeout_s=_call_timeout(remaining / 2), running=False))
            except Exception:  # details are best-effort
                logger.debug("solver_details failed after wait", exc_info=True)
        return extra

    while True:
        timeout = _call_timeout(deadline - _clock())
        state = (
            client.solver_status(timeout_s=timeout, running_only=True)
            if lightweight
            else client.solver_status(timeout_s=timeout)
        )
        polls += 1
        status = state.get("status")

        if status == "offline":
            return _json({
                "status": "error",
                "code": "offline",
                "message": (
                    "cst_wait_for_simulation requires connected mode with an open "
                    "project; call cst_connect first."
                ),
                "running": None,
                "elapsed_s": elapsed(),
                "polls": polls,
                "solver_status": state,
            })
        if status != "ok":
            return _json({
                "status": "error",
                "message": state.get("message") or "CST solver state is unknown",
                "running": state.get("running"),
                "elapsed_s": elapsed(),
                "polls": polls,
                "solver_status": state,
            })

        running = bool(state.get("running"))
        pending = _pending_solve(client)
        starting = (
            not running
            and pending is not None
            and not pending.get("seen_running")
            and _clock() - float(pending.get("t0", 0.0)) < _WAIT_START_GRACE_S
        )

        if not running and not starting:
            extra = details(state)
            return _json({
                "status": "finished",
                "running": False,
                "elapsed_s": elapsed(),
                "max_wait_s": max_wait_s,
                "polls": polls,
                **extra,
                **_finished_payload(client, pending),
                "hint": (
                    "Solver is idle. Read results, e.g. with cst_get_s_parameters "
                    "or cst_get_farfield_metrics."
                ),
            })

        remaining = deadline - _clock()
        if remaining <= _WAIT_MIN_CALL_S:
            if starting:
                return _json({
                    "status": "starting",
                    "running": False,
                    "elapsed_s": elapsed(),
                    "max_wait_s": max_wait_s,
                    "polls": polls,
                    "hint": (
                        "The solve was launched but CST has not reported it running "
                        "yet; call cst_wait_for_simulation again."
                    ),
                })
            return _json({
                "status": "running",
                "running": True,
                "elapsed_s": elapsed(),
                "max_wait_s": max_wait_s,
                "polls": polls,
                **{key: state[key] for key in ("active_solver", "run_info") if key in state},
                "hint": "Solver still running; call cst_wait_for_simulation again.",
            })
        # Keep at least _WAIT_MIN_CALL_S for the next poll so its CST timeout
        # (whole seconds, >= 1) still fits inside the budget.
        pause = min(_WAIT_POLL_S, remaining - _WAIT_MIN_CALL_S)
        if pause > 0:
            await _sleep(pause)


def _handle_simple_solver_command(
    command: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle pause, resume, and stop commands."""
    timeout_s = float(arguments.get("timeout_s", 30))
    method = getattr(client, f"{command}_solver")
    result = method(timeout_s=timeout_s)
    result["command"] = "stop" if command == "abort" else command

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
