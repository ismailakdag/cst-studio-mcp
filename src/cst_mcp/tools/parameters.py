"""Parametric design tools for CST Studio Suite.

Provides 6 MCP tools for managing design parameters, setting up parameter
sweeps, and configuring optimizations in CST Studio.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Callable

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBAScript, _escape_vba_string
from cst_mcp.validators import validate_name, validate_positive


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # 1. Set parameter
    Tool(
        name="cst_set_parameter",
        description=(
            "Set or create a design parameter in CST Studio. Parameters can hold "
            "numeric values or string expressions referencing other parameters. "
            "The value is stored through the parameter list (never as a model-history "
            "step) and the model is rebuilt. A parameter change invalidates results: "
            "on a solved project pass delete_results=true (results are deleted first), "
            "otherwise the call is refused with code results_exist."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Parameter name (e.g. 'patch_length', 'substrate_h').",
                },
                "value": {
                    "description": (
                        "Parameter value — a number (e.g. 10.5) or a string expression "
                        "referencing other parameters (e.g. 'patch_length / 2')."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Optional human-readable description of the parameter.",
                },
                "rebuild": {
                    "type": "boolean",
                    "default": True,
                    "description": "Rebuild the model after storing the value (default true).",
                },
                "delete_results": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Required when the project already has simulation results: they are "
                        "deleted first (export anything you need). Without it the call is refused "
                        "with code results_exist, because CST would block on a modal dialog."
                    ),
                },
            },
            "required": ["name", "value"],
        },
    ),

    # 2. Get parameter
    Tool(
        name="cst_get_parameter",
        description=(
            "Get the current value of a design parameter. Returns both the stored "
            "expression and the evaluated numeric value."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the parameter to retrieve.",
                },
            },
            "required": ["name"],
        },
    ),

    # 3. List parameters
    Tool(
        name="cst_list_parameters",
        description=(
            "List all design parameters in the current CST project with their "
            "names, expressions, and evaluated numeric values."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # 4. Delete parameter
    Tool(
        name="cst_delete_parameter",
        description=(
            "Delete a design parameter from the CST project. The parameter must not "
            "be referenced by other parameters or geometry. Uses the parameter list "
            "(no model-history step) and rebuilds; refused with code results_exist on a "
            "solved project unless delete_results=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the parameter to delete.",
                },
                "delete_results": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Required when the project already has simulation results: they are "
                        "deleted first (export anything you need). Without it the call is refused "
                        "with code results_exist, because CST would block on a modal dialog."
                    ),
                },
            },
            "required": ["name"],
        },
    ),

    # 5. Parameter sweep
    Tool(
        name="cst_parameter_sweep",
        description=(
            "Configure a CST parameter sweep (ParameterSweep object; not a model-history "
            "step) that solves once per sample of the parameter. By default only configures "
            "(status 'configured'); with run=true it also starts the sweep and returns "
            "status 'started' quickly while CST keeps solving: poll cst_wait_for_simulation, "
            "then compare runs via cst_list_saved_results (run_ids) and cst_plot_1d_results "
            "(run_ids) or cst_parameter_interpolation. Replaces previously configured sweep "
            "sequences (clear_existing)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "parameter": {
                    "type": "string",
                    "description": "Name of the parameter to sweep.",
                },
                "start": {
                    "type": "number",
                    "description": "Start value of the sweep range.",
                },
                "stop": {
                    "type": "number",
                    "description": "Stop value of the sweep range.",
                },
                "steps": {
                    "type": "integer",
                    "description": "Number of steps in the sweep (minimum 2).",
                },
                "simulation_type": {
                    "type": "string",
                    "enum": ["Transient", "Frequency Domain", "Eigenmode"],
                    "description": (
                        "Solver used by the sweep. Omit to follow the project's active solver "
                        "(HF Time Domain -> Transient, HF Frequency Domain, HF Eigenmode); "
                        "Transient when it cannot be detected."
                    ),
                },
                "clear_existing": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Delete all previously configured sweep sequences first so that "
                        "Start runs exactly this sweep (default true)."
                    ),
                },
                "run": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Also start it (ParameterSweep.Start). Returns status 'started' within ~15 s while "
                        "CST keeps running; poll cst_wait_for_simulation until finished. "
                        "Requires a project without results (see delete_results)."
                    ),
                },
                "delete_results": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Required when the project already has simulation results: they are "
                        "deleted first (export anything you need). Without it the call is refused "
                        "with code results_exist, because CST would block on a modal dialog."
                    ),
                },
            },
            "required": ["parameter", "start", "stop", "steps"],
        },
    ),

    # 6. Optimizer
    Tool(
        name="cst_optimizer",
        description=(
            "Configure the native CST optimizer (Optimizer object; not a model-history "
            "step). Define a goal (minimize, maximize, or target a value for a result), "
            "the parameters to vary with bounds, and an evaluation-capped algorithm. "
            "Repeated calls replace the previous optimizer settings. Status 'configured' "
            "unless run=true, which starts it and returns 'started' while CST keeps "
            "solving (poll cst_wait_for_simulation). For a bounded, resumable Python loop "
            "use cst_refine_antenna instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "goal_type": {
                    "type": "string",
                    "enum": ["minimize", "maximize", "target"],
                    "description": "Optimization goal type.",
                },
                "goal_value": {
                    "type": "number",
                    "description": (
                        "Target value for 'target' goal type. Ignored for minimize/maximize."
                    ),
                },
                "result_path": {
                    "type": "string",
                    "description": (
                        "Result tree path to optimize, e.g. "
                        "'1D Results\\S-Parameters\\S1,1' or '1D Results\\S-Parameters\\S2,1'."
                    ),
                },
                "parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Parameter name.",
                            },
                            "min": {
                                "type": "number",
                                "description": "Minimum allowed value.",
                            },
                            "max": {
                                "type": "number",
                                "description": "Maximum allowed value.",
                            },
                        },
                        "required": ["name", "min", "max"],
                    },
                    "minItems": 1,
                    "description": "List of parameters to optimize with their min/max bounds.",
                },
                "method": {
                    "type": "string",
                    "enum": [
                        "Trust Region",
                        "CMAES",
                        "Nelder Mead",
                    ],
                    "description": "Optimization algorithm.",
                    "default": "Trust Region",
                },
                "max_evaluations": {
                    "type": "integer",
                    "description": "Maximum number of solver evaluations.",
                    "default": 100,
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Evaluate the goal at this single frequency (default: whole range).",
                },
                "run": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Also start it (Optimizer.Start). Returns status 'started' within ~15 s while "
                        "CST keeps running; poll cst_wait_for_simulation until finished. "
                        "Requires a project without results (see delete_results)."
                    ),
                },
                "delete_results": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Required when the project already has simulation results: they are "
                        "deleted first (export anything you need). Without it the call is refused "
                        "with code results_exist, because CST would block on a modal dialog."
                    ),
                },
            },
            "required": ["goal_type", "result_path", "parameters"],
        },
    ),

    # 7. Multi-objective optimizer
    Tool(
        name="cst_multi_objective_optimizer",
        description=(
            "Set up a multi-objective optimization with weighted goals and optional "
            "constraints. Uses a weighted sum of goals with an evaluation cap; "
            "this is not a Pareto-front search. Native CST Optimizer settings (not a "
            "model-history step); repeated calls replace them. Status 'configured' unless "
            "run=true (then 'started'; poll cst_wait_for_simulation)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "goals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "result_path": {
                                "type": "string",
                                "description": "Result tree path (e.g. '1D Results\\S-Parameters\\S1,1').",
                            },
                            "goal_type": {
                                "type": "string",
                                "enum": ["minimize", "maximize", "target"],
                            },
                            "target_value": {
                                "type": "number",
                                "description": "Target value (for 'target' type only).",
                            },
                            "weight": {
                                "type": "number",
                                "description": "Relative weight for this goal (default 1.0).",
                                "default": 1.0,
                            },
                            "frequency_ghz": {
                                "type": "number",
                                "description": "Frequency at which to evaluate (optional).",
                            },
                        },
                        "required": ["result_path", "goal_type"],
                    },
                    "minItems": 1,
                    "description": "List of optimization goals with weights.",
                },
                "parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "min": {"type": "number"},
                            "max": {"type": "number"},
                        },
                        "required": ["name", "min", "max"],
                    },
                    "minItems": 1,
                },
                "constraints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "result_path": {"type": "string"},
                            "operator": {
                                "type": "string",
                                "enum": ["<", ">", "<=", ">="],
                            },
                            "value": {"type": "number"},
                        },
                        "required": ["result_path", "operator", "value"],
                    },
                    "description": "Optional inequality constraints on results.",
                },
                "method": {
                    "type": "string",
                    "enum": ["Trust Region", "Nelder Mead", "CMAES"],
                    "default": "CMAES",
                    "description": "Evaluation-capped optimization method.",
                },
                "max_evaluations": {
                    "type": "integer",
                    "default": 200,
                },
                "run": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Also start it (Optimizer.Start). Returns status 'started' within ~15 s while "
                        "CST keeps running; poll cst_wait_for_simulation until finished. "
                        "Requires a project without results (see delete_results)."
                    ),
                },
                "delete_results": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Required when the project already has simulation results: they are "
                        "deleted first (export anything you need). Without it the call is refused "
                        "with code results_exist, because CST would block on a modal dialog."
                    ),
                },
            },
            "required": ["goals", "parameters"],
        },
    ),

    # 8. Sensitivity analysis
    Tool(
        name="cst_sensitivity_analysis",
        description=(
            "Set up a one-at-a-time sensitivity analysis to rank parameters by "
            "their impact on a result. Varies each parameter individually while "
            "keeping others at nominal values."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "nominal": {"type": "number"},
                            "perturbation_pct": {
                                "type": "number",
                                "description": "Percentage to vary the parameter (default 5%).",
                                "default": 5.0,
                            },
                        },
                        "required": ["name", "nominal"],
                    },
                    "minItems": 1,
                },
                "result_path": {
                    "type": "string",
                    "description": "Result tree path to monitor.",
                },
            },
            "required": ["parameters", "result_path"],
        },
    ),

    # 9. Yield analysis (Monte Carlo)
    Tool(
        name="cst_yield_analysis",
        description=(
            "Set up a Monte Carlo yield analysis to estimate manufacturing yield. "
            "Randomly varies parameters according to their tolerances and evaluates "
            "pass/fail criteria."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "nominal": {"type": "number"},
                            "tolerance": {
                                "type": "number",
                                "description": "Tolerance range (+/- this value).",
                            },
                            "distribution": {
                                "type": "string",
                                "enum": ["uniform", "gaussian"],
                                "default": "gaussian",
                            },
                        },
                        "required": ["name", "nominal", "tolerance"],
                    },
                    "minItems": 1,
                },
                "pass_criteria": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "result_path": {"type": "string"},
                            "operator": {
                                "type": "string",
                                "enum": ["<", ">", "<=", ">="],
                            },
                            "threshold": {"type": "number"},
                        },
                        "required": ["result_path", "operator", "threshold"],
                    },
                    "minItems": 1,
                },
                "num_samples": {
                    "type": "integer",
                    "default": 50,
                    "description": "Number of Monte Carlo samples.",
                },
            },
            "required": ["parameters", "pass_criteria"],
        },
    ),

    # 10. Constrained optimizer
    Tool(
        name="cst_constrained_optimizer",
        description=(
            "Single-objective optimization with explicit inequality constraints. "
            "Example: minimize S11 subject to gain > 8 dBi and bandwidth > 100 MHz. "
            "Native CST Optimizer settings (not a model-history step); repeated calls "
            "replace them. Status 'configured' unless run=true (then 'started'; poll "
            "cst_wait_for_simulation)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "objective": {
                    "type": "object",
                    "properties": {
                        "result_path": {"type": "string"},
                        "goal_type": {
                            "type": "string",
                            "enum": ["minimize", "maximize"],
                        },
                    },
                    "required": ["result_path", "goal_type"],
                },
                "constraints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "result_path": {"type": "string"},
                            "operator": {
                                "type": "string",
                                "enum": ["<", ">", "<=", ">="],
                            },
                            "value": {"type": "number"},
                        },
                        "required": ["result_path", "operator", "value"],
                    },
                    "minItems": 1,
                },
                "parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "min": {"type": "number"},
                            "max": {"type": "number"},
                        },
                        "required": ["name", "min", "max"],
                    },
                    "minItems": 1,
                },
                "method": {
                    "type": "string",
                    "enum": [
                        "Trust Region",
                        "CMAES",
                        "Nelder Mead",
                    ],
                    "default": "Trust Region",
                },
                "max_evaluations": {
                    "type": "integer",
                    "default": 100,
                },
                "run": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Also start it (Optimizer.Start). Returns status 'started' within ~15 s while "
                        "CST keeps running; poll cst_wait_for_simulation until finished. "
                        "Requires a project without results (see delete_results)."
                    ),
                },
                "delete_results": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Required when the project already has simulation results: they are "
                        "deleted first (export anything you need). Without it the call is refused "
                        "with code results_exist, because CST would block on a modal dialog."
                    ),
                },
            },
            "required": ["objective", "constraints", "parameters"],
        },
    ),

    # 11. Parameter interpolation
    Tool(
        name="cst_parameter_interpolation",
        description=(
            "Read-only: linearly interpolate a saved 1D result between the two parameter "
            "sweep runs that bracket target_value (runs come from a finished "
            "cst_parameter_sweep; see cst_list_saved_results run_ids). No simulation, "
            "no parameter change, no extrapolation outside the swept range. Returns the "
            "interpolated curve (magnitude in dB for complex results) and its minimum."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "parameter": {
                    "type": "string",
                    "description": "Name of the sweep parameter.",
                },
                "target_value": {
                    "type": "number",
                    "description": "Parameter value at which to interpolate results.",
                },
                "result_path": {
                    "type": "string",
                    "description": "1D result tree path, e.g. '1D Results\\S-Parameters\\S1,1'.",
                },
                "max_points": {
                    "type": "integer",
                    "default": 200,
                    "description": "Downsample the returned curve to at most this many points (0 = all).",
                },
            },
            "required": ["parameter", "target_value", "result_path"],
        },
    ),
]


# ---------------------------------------------------------------------------
# VBA generation helpers
# ---------------------------------------------------------------------------

# CST parameter identifiers (stricter than validate_name: no spaces/dots).
_PARAM_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _param_name(name: Any) -> str:
    if not isinstance(name, str) or not _PARAM_NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid CST parameter name: {name!r}")
    return name


def _vba_number(value: Any, label: str) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return repr(number)


def _build_set_parameter(args: dict) -> str:
    """VBA that stores (or creates) a parameter value.

    Runs without history: a ``StoreParameter`` inside a history step is
    ignored on rebuild ("Prevented attempt to change the value ... inside
    history rebuild"), and ``RebuildOnParametricChange`` is rejected inside a
    structure macro.  The rebuild is a separate API call.
    """
    name = _param_name(args["name"])
    value = args["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("value must be a number or a string expression")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("value must be finite")
    safe_value = _escape_vba_string(str(value))
    lines = [f'StoreParameter "{name}", "{safe_value}"']
    description = args.get("description")
    if description:
        lines.append(f'SetParameterDescription "{name}", "{_escape_vba_string(description)}"')
    return "\n".join(lines)


def _build_get_parameter(args: dict) -> str:
    """Build VBA script to retrieve a parameter value."""
    name = validate_name(args["name"], "parameter name")
    safe_name = _escape_vba_string(name)

    script = VBAScript()
    script.add_comment(f"Get parameter: {name}")

    lines = [
        "Dim dValue As Double",
        f'dValue = RestoreParameter("{safe_name}")',
        f'MsgBox "Parameter {safe_name} = " & CStr(dValue)',
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_list_parameters(args: dict) -> str:
    """Build VBA script to list all design parameters."""
    script = VBAScript()
    script.add_comment("List all design parameters")

    lines = [
        "Dim nParams As Long",
        "nParams = GetNumberOfParameters()",
        "Dim i As Long",
        "For i = 0 To nParams - 1",
        "  Dim sName As String",
        "  sName = GetParameterName(i)",
        "  Dim dValue As Double",
        "  dValue = GetParameterNValue(i)",
        '  Debug.Print sName & " = " & CStr(dValue)',
        "Next i",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_delete_parameter(args: dict) -> str:
    """VBA deleting a parameter (no history step; rebuild is separate)."""
    return f'DeleteParameter "{_param_name(args["name"])}"'


_SWEEP_SIMULATION_TYPES = {
    "Transient": "Transient",
    "Frequency Domain": "Frequency",
    "Eigenmode": "Eigenmode",
}


def _build_parameter_sweep(args: dict) -> str:
    """ParameterSweep configuration (no history step, no Start)."""
    parameter = _param_name(args["parameter"])
    start = _vba_number(args["start"], "start")
    stop = _vba_number(args["stop"], "stop")
    steps = int(args["steps"])
    if steps < 2:
        raise ValueError("Parameter sweep requires at least 2 steps")
    # CST 2026 refuses ParameterSweep.Start without a simulation type
    # ("Simulation type is undefined"), so one is always set.
    sim_type = args.get("simulation_type") or "Transient"
    if sim_type not in _SWEEP_SIMULATION_TYPES:
        raise ValueError(f"Unsupported simulation_type {sim_type!r}; "
                         f"use one of {sorted(_SWEEP_SIMULATION_TYPES)}")
    sequence = f"mcp_{parameter}"
    lines = ["With ParameterSweep", f'  .SetSimulationType "{_SWEEP_SIMULATION_TYPES[sim_type]}"']
    if args.get("clear_existing", True):
        lines.append("  .DeleteAllSequences")
    else:
        # Re-configuring the same sequence must not duplicate it.
        lines += ["  On Error Resume Next", f'  .DeleteSequence "{sequence}"', "  On Error GoTo 0"]
    lines += [
        f'  .AddSequence "{sequence}"',
        f'  .AddParameter_Samples "{sequence}", "{parameter}", {start}, {stop}, {steps}, False',
        "End With",
    ]
    return "\n".join(lines)


def _build_optimizer(args: dict) -> str:
    from cst_mcp.execution.native_optimizer import build_optimizer
    return build_optimizer(args, "single")


def _build_multi_objective_optimizer(args: dict) -> str:
    from cst_mcp.execution.native_optimizer import build_optimizer
    return build_optimizer(args, "multi")


def _build_sensitivity_analysis(args: dict) -> str:
    """ParameterSweep sequences for a one-at-a-time sensitivity analysis."""
    parameters = args["parameters"]

    if not parameters:
        raise ValueError("At least one parameter must be specified")

    lines = [f"' Sensitivity analysis: monitor {_escape_vba_string(args['result_path'])}",
             "With ParameterSweep"]
    for param in parameters:
        param_name = _param_name(param["name"])
        nominal = float(param["nominal"])
        perturbation = float(param.get("perturbation_pct", 5.0))
        delta = abs(nominal * perturbation / 100.0)
        sequence = f"mcp_sensitivity_{param_name}"
        lines += [
            "  On Error Resume Next", f'  .DeleteSequence "{sequence}"', "  On Error GoTo 0",
            f'  .AddSequence "{sequence}"',
            f'  .AddParameter_Samples "{sequence}", "{param_name}", '
            f'{_vba_number(nominal - delta, "low")}, {_vba_number(nominal + delta, "high")}, 3, False',
        ]
    lines.append("End With")
    return "\n".join(lines)


def _build_yield_analysis(args: dict) -> str:
    """ParameterSweep sequences for a Monte Carlo yield analysis."""
    parameters = args["parameters"]
    pass_criteria = args["pass_criteria"]
    num_samples = int(args.get("num_samples", 50))

    if not parameters:
        raise ValueError("At least one parameter must be specified")
    if not pass_criteria:
        raise ValueError("At least one pass criterion must be specified")
    validate_positive(num_samples, "num_samples")

    # One sample per sequence avoids a Cartesian product masquerading as Monte Carlo.
    import random
    rng = random.Random(0)
    lines = [
        f"' Monte Carlo yield analysis - {num_samples} samples",
        "' Uniform independent tolerances; reproducible Python seed=0. Configure only, "
        "no solver start. Pass criteria require separate analysis.",
        "With ParameterSweep",
    ]
    for sample in range(num_samples):
        sequence = f"mcp_mc_{sample + 1}"
        lines += ["  On Error Resume Next", f'  .DeleteSequence "{sequence}"', "  On Error GoTo 0",
                  f'  .AddSequence "{sequence}"']
        for param in parameters:
            param_name = _param_name(param["name"])
            nominal, tolerance = float(param["nominal"]), float(param["tolerance"])
            if tolerance < 0:
                raise ValueError("tolerance must be non-negative")
            value = nominal + rng.uniform(-tolerance, tolerance)
            lines.append(f'  .AddParameter_ArbitraryPoints "{sequence}", "{param_name}", '
                         f'"{_vba_number(value, "sample")}"')
    lines.append("End With")
    for criterion in pass_criteria:
        lines.append("' Pass criterion: " + _escape_vba_string(
            f"{criterion['result_path']} {criterion['operator']} {criterion['threshold']}"))
    return "\n".join(lines)


def _build_constrained_optimizer(args: dict) -> str:
    from cst_mcp.execution.native_optimizer import build_optimizer
    return build_optimizer(args, "constrained")


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------

# Tools that only configure CST objects (ParameterSweep / Optimizer).  Their
# VBA is run without history: these settings are not model geometry and a
# history step would be replayed on every rebuild (and would be refused on a
# solved project, see CSTSession.run_history).
_CONFIG_BUILDERS: dict[str, Callable[[dict], str]] = {
    "cst_parameter_sweep": _build_parameter_sweep,
    "cst_optimizer": _build_optimizer,
    "cst_multi_objective_optimizer": _build_multi_objective_optimizer,
    "cst_constrained_optimizer": _build_constrained_optimizer,
    "cst_sensitivity_analysis": _build_sensitivity_analysis,
    "cst_yield_analysis": _build_yield_analysis,
}

_STARTABLE = {
    "cst_parameter_sweep": ("ParameterSweep.Start", "Parameter sweep"),
    "cst_optimizer": ("Optimizer.Start", "Optimizer"),
    "cst_multi_objective_optimizer": ("Optimizer.Start", "Optimizer"),
    "cst_constrained_optimizer": ("Optimizer.Start", "Optimizer"),
}


def _ensure_no_results(client: CSTClient, delete_results: bool) -> dict | None:
    """Return an error payload unless the project holds no results (or they were deleted)."""
    present = client.results_present()
    if present is False:
        return None
    if present is None:
        return {"status": "error", "code": "results_state_unknown",
                "message": "Could not determine whether the project has results; nothing was changed."}
    if not delete_results:
        return {"status": "error", "code": "results_exist",
                "message": ("The project has simulation results. Changing parameters or starting "
                            "a sweep/optimizer invalidates them and CST would block on a modal "
                            "dialog. Export what you need, then retry with delete_results=true "
                            "(or call cst_delete_results first).")}
    deleted = client.delete_results()
    if deleted.get("status") != "ok":
        return {**deleted, "stage": "delete_results"}
    return None


def _handle_parameter_change(name: str, args: dict, client: CSTClient) -> dict:
    """cst_set_parameter / cst_delete_parameter: parameter list + rebuild, no history."""
    vba = _build_set_parameter(args) if name == "cst_set_parameter" else _build_delete_parameter(args)
    if not client.connected or not client.has_project:
        return {"status": "offline", "vba": vba,
                "message": "Run as a macro (not a history step), then rebuild the model."}
    state = client.solver_status()
    if state.get("status") != "ok":
        return state
    if state.get("running"):
        return {"status": "busy", "running": True, "message": "Parameters were not changed"}
    blocked = _ensure_no_results(client, bool(args.get("delete_results", False)))
    if blocked:
        return blocked
    stored = client._run_model3d_vba(vba)
    if stored.get("status") != "executed":
        return {**stored, "stage": "parameters"}
    out = {"status": "ok", "history_written": False, "entrypoint": stored.get("entrypoint")}
    if args.get("rebuild", True):
        rebuilt = client.rebuild()
        if rebuilt.get("status") != "ok":
            return {**rebuilt, "stage": "rebuild", "parameters_changed": True}
        out["rebuilt"] = True
    else:
        out["rebuilt"] = False
    return out


_ACTIVE_SOLVER_SWEEP_TYPES = {
    "HF Time Domain": "Transient",
    "HF Frequency Domain": "Frequency Domain",
    "HF Eigenmode": "Eigenmode",
}


def _default_sweep_type(client: CSTClient) -> str | None:
    """Sweep simulation type matching the project's active solver (best effort)."""
    try:
        name = client.solver_details(timeout_s=10, running=False).get("active_solver")
    except Exception:  # noqa: BLE001
        return None
    return _ACTIVE_SOLVER_SWEEP_TYPES.get(str(name or "").strip())


def _handle_configuration(name: str, args: dict, client: CSTClient) -> dict:
    if (name == "cst_parameter_sweep" and not args.get("simulation_type")
            and client.connected and client.has_project):
        detected = _default_sweep_type(client)
        if detected:
            args = {**args, "simulation_type": detected}
    vba = _CONFIG_BUILDERS[name](args)
    run = bool(args.get("run", False)) and name in _STARTABLE
    if not client.connected or not client.has_project:
        start = _STARTABLE.get(name)
        return {"status": "offline", "vba": vba,
                "next_steps": f"Run as a macro (not a history step), then {start[0]}." if start
                else "Run as a macro (not a history step)."}
    blocked = client._idle_error()
    if blocked:
        return blocked
    # model3d entrypoint (verified for ParameterSweep/Optimizer); never history.
    configured = client._run_model3d_vba(vba)
    if configured.get("status") != "executed":
        return {**configured, "stage": "configure", "vba": vba}
    out: dict[str, Any] = {"status": "configured", "history_written": False,
                           "entrypoint": configured.get("entrypoint")}
    start = _STARTABLE.get(name)
    if not run:
        if start:
            out["next_steps"] = (f"Call again with run=true to start ({start[0]}), or start it from the "
                                 "CST GUI. It then solves once per evaluation; poll "
                                 "cst_wait_for_simulation.")
        return out
    blocked = _ensure_no_results(client, bool(args.get("delete_results", False)))
    if blocked:
        return {**blocked, "configured": True}
    started = client.start_blocking_vba(start[0], what=start[1])
    return {**out, **started, "configured": True}


def _handle_interpolation(args: dict, client: CSTClient) -> dict:
    """Interpolate a saved 1D result between the bracketing sweep runs."""
    from cst_mcp.execution.figures_1d_source import open_reader
    from cst_mcp.execution.sweep_interpolation import interpolate_runs

    parameter = _param_name(args["parameter"])
    target = float(args["target_value"])
    if not math.isfinite(target):
        raise ValueError("target_value must be finite")
    tree_path = str(args["result_path"])
    if not client.has_project or not client.project_path:
        return {"status": "error", "message": "Open a saved project with sweep results first"}
    running = client.is_solver_running(timeout_s=5)
    if running is not False:
        return {"status": "busy", "running": running,
                "message": "Results are not read while the solver is active or its state is unknown"}
    reader = open_reader(client.project_path, allow_interactive=True)
    return interpolate_runs(reader, tree_path, parameter, target,
                            max_points=int(args.get("max_points", 200)))


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def _text(data: dict) -> list[TextContent]:
    """Wrap a dict as a single JSON TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


_QUERY_BUILDERS: dict[str, Callable[[dict], str]] = {
    "cst_get_parameter": _build_get_parameter,
    "cst_list_parameters": _build_list_parameters,
}


async def handle(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle a parameter tool call."""
    try:
        if name in ("cst_set_parameter", "cst_delete_parameter"):
            result = _handle_parameter_change(name, arguments, client)
            result["parameter"] = arguments["name"]
            if name == "cst_set_parameter":
                result["value"] = arguments["value"]
        elif name in _CONFIG_BUILDERS:
            result = _handle_configuration(name, arguments, client)
            if name == "cst_parameter_sweep":
                result.update(parameter=arguments["parameter"], start=arguments["start"],
                              stop=arguments["stop"], steps=arguments["steps"])
            elif name in ("cst_optimizer", "cst_multi_objective_optimizer", "cst_constrained_optimizer"):
                result["parameters"] = [p["name"] for p in arguments["parameters"]]
                if name == "cst_optimizer":
                    result.update(goal_type=arguments["goal_type"], result_path=arguments["result_path"],
                                  method=arguments.get("method", "Trust Region"),
                                  max_evaluations=arguments.get("max_evaluations", 100))
                elif name == "cst_multi_objective_optimizer":
                    result.update(num_goals=len(arguments["goals"]), method=arguments.get("method", "CMAES"))
                else:
                    result.update(objective=arguments["objective"],
                                  num_constraints=len(arguments["constraints"]))
            elif name == "cst_sensitivity_analysis":
                result.update(result_path=arguments["result_path"],
                              parameters=[p["name"] for p in arguments["parameters"]])
            else:
                result.update(num_samples=arguments.get("num_samples", 50),
                              parameters=[p["name"] for p in arguments["parameters"]])
        elif name == "cst_parameter_interpolation":
            result = _handle_interpolation(arguments, client)
            result.update(parameter=arguments["parameter"], target_value=arguments["target_value"])
        elif name in _QUERY_BUILDERS:
            result = client.execute_vba(_QUERY_BUILDERS[name](arguments))
            result["parameter"] = arguments.get("name")
            if name == "cst_list_parameters":
                result.pop("parameter")
        else:
            return _text({"status": "error", "message": f"Unknown parameter tool: {name}"})
        return _text(result)
    except Exception as e:
        return _text({"status": "error", "message": str(e)})



# ---------------------------------------------------------------------------
# Registration helper (called from tools/__init__.py)
# ---------------------------------------------------------------------------


# Reject line breaks and non-numeric values in numeric slots before any VBA
# is generated from the arguments (generated VBA bypasses CST_ALLOW_RAW_VBA).
from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
