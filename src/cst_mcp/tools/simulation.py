"""Simulation control tools for CST Studio Suite."""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient

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

TOOLS: list[Tool] = [
    Tool(
        name="cst_run_simulation",
        description=(
            "Start a CST simulation with the current solver settings. "
            "This is a blocking call that waits for the simulation to complete. "
            "Use cst_run_simulation_async for long-running simulations."
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
            "Use cst_get_simulation_status to monitor progress."
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
            "and return immediately. Use cst_get_simulation_status to poll progress."
        )
    elif async_mode and result.get("status") == "started":
        result["note"] = (
            "Simulation launched. Use cst_get_simulation_status to monitor progress."
        )

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _handle_get_status(arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle cst_get_simulation_status."""
    result = client.solver_status(timeout_s=float(arguments.get("timeout_s", 30)))
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _handle_simple_solver_command(
    command: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle pause, resume, and stop commands."""
    timeout_s = float(arguments.get("timeout_s", 30))
    method = getattr(client, f"{command}_solver")
    result = method(timeout_s=timeout_s)
    result["command"] = "stop" if command == "abort" else command

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def register_simulation_tools(server: Server, client: CSTClient) -> None:
    """Register simulation tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
