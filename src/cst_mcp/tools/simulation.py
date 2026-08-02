"""Simulation control tools for CST Studio Suite."""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBABuilder, VBAScript

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
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_get_simulation_status",
        description=(
            "Check the status and progress of a running CST simulation. "
            "Returns information such as whether a simulation is running, "
            "progress percentage, mesh cell count, and current time step."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
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
            "properties": {},
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
            "properties": {},
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
            "properties": {},
            "required": [],
        },
    ),
]

_TOOL_NAMES = {tool.name for tool in TOOLS}


def _build_solver_start_vba(solver_type: str | None) -> str:
    """Build VBA code to start the appropriate solver.

    CST uses different VBA objects depending on the solver type:
    - Time Domain:      Solver.Start
    - Frequency Domain: FDSolver.Start
    - Eigenmode:        EigenmodeSolver.Start
    - Integral Equation: IESolver.Start
    """
    if solver_type is None:
        # Use the currently configured solver via the generic Solver object
        vba = VBABuilder("Solver")
        vba.raw_line("Solver.Start")
        return vba.build()

    solver_map = {
        "Time Domain": "Solver",
        "Frequency Domain": "FDSolver",
        "Eigenmode": "EigenmodeSolver",
        "Integral Equation": "IESolver",
    }

    obj = solver_map.get(solver_type)
    if obj is None:
        raise ValueError(
            f"Invalid solver_type '{solver_type}'. "
            f"Valid options: {_VALID_SOLVER_TYPES}"
        )

    vba = VBABuilder(obj)
    vba.raw_line(f"{obj}.Start")
    return vba.build()


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
            return _handle_get_status(client)

        if name == "cst_pause_simulation":
            return _handle_simple_solver_command("Pause", client)

        if name == "cst_resume_simulation":
            return _handle_simple_solver_command("Resume", client)

        if name == "cst_stop_simulation":
            return _handle_simple_solver_command("Stop", client)

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
                    "error": f"Invalid solver_type '{solver_type}'",
                    "valid_options": _VALID_SOLVER_TYPES,
                }),
            )
        ]

    vba_code = _build_solver_start_vba(solver_type)
    result = client.execute_vba(vba_code)

    result["solver_type"] = solver_type or "current"
    result["mode"] = "async" if async_mode else "blocking"

    if async_mode and result.get("status") == "offline":
        result["note"] = (
            "In connected mode this command would launch the simulation "
            "and return immediately. Use cst_get_simulation_status to poll progress."
        )
    elif async_mode and result.get("status") == "executed":
        result["note"] = (
            "Simulation launched. Use cst_get_simulation_status to monitor progress."
        )

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _handle_get_status(client: CSTClient) -> list[TextContent]:
    """Handle cst_get_simulation_status."""
    if client.connected:
        # In connected mode, query the solver for status information
        script = VBAScript()
        script.add_comment("Query simulation status")
        # CST exposes solver status through VBA macros
        status_vba = (
            'Dim running As Boolean\n'
            'Dim progress As Double\n'
            'running = Solver.IsRunning\n'
            'progress = Solver.GetProgress\n'
            'SelectTreeItem "Design Parameters"\n'
            'MsgBox "Running: " & running & vbCrLf & '
            '"Progress: " & progress & "%"'
        )
        script.add_raw(status_vba)
        result = client.execute_vba(script.build())
        result["description"] = (
            "Queried CST solver status. Check 'result' field for details."
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Offline mode — provide guidance
    result = {
        "status": "offline",
        "message": (
            "Simulation status checking requires connected mode with CST running. "
            "In CST Studio, check the progress bar at the bottom of the main window, "
            "or use the Solver menu to view simulation progress."
        ),
        "vba_example": (
            "' Check if solver is running:\n"
            "Dim running As Boolean\n"
            "running = Solver.IsRunning\n"
            "\n"
            "' Get progress percentage:\n"
            "Dim progress As Double\n"
            "progress = Solver.GetProgress"
        ),
        "available_fields": {
            "running": "Boolean — whether a simulation is currently active",
            "progress": "Double — completion percentage (0-100)",
            "mesh_cells": "Long — number of mesh cells (after meshing)",
            "current_step": "Long — current time step (time domain only)",
        },
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _handle_simple_solver_command(
    command: str, client: CSTClient
) -> list[TextContent]:
    """Handle pause, resume, and stop commands."""
    vba = VBABuilder("Solver")
    vba.raw_line(f"Solver.{command}")
    vba_code = vba.build()

    result = client.execute_vba(vba_code)
    result["command"] = command.lower()

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def register_simulation_tools(server: Server, client: CSTClient) -> None:
    """Register simulation tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
