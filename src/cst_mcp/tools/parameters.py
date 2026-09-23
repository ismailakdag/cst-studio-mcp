"""Parametric design tools for CST Studio Suite.

Provides 6 MCP tools for managing design parameters, setting up parameter
sweeps, and configuring optimizations in CST Studio.
"""

from __future__ import annotations

import json
from typing import Callable

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBABuilder, VBAScript, _escape_vba_string
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
            "numeric values or string expressions referencing other parameters."
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
            "be referenced by other parameters or geometry."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the parameter to delete.",
                },
            },
            "required": ["name"],
        },
    ),

    # 5. Parameter sweep
    Tool(
        name="cst_parameter_sweep",
        description=(
            "Set up a parameter sweep in CST Studio. The sweep runs the simulation "
            "multiple times, varying the specified parameter across a range of values."
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
                    "enum": ["Transient", "Frequency Domain", "Eigenmode", "Integral Equation"],
                    "description": "Solver type for the sweep. Defaults to Transient.",
                },
            },
            "required": ["parameter", "start", "stop", "steps"],
        },
    ),

    # 6. Optimizer
    Tool(
        name="cst_optimizer",
        description=(
            "Set up an optimization in CST Studio. Define a goal (minimize, maximize, "
            "or target a specific value for a result), specify which parameters to vary "
            "with their bounds, and choose an optimization algorithm."
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
            "this is not a Pareto-front search. Configuration only; start explicitly."
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
            "Example: minimize S11 subject to gain > 8 dBi and bandwidth > 100 MHz."
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
            },
            "required": ["objective", "constraints", "parameters"],
        },
    ),

    # 11. Parameter interpolation
    Tool(
        name="cst_parameter_interpolation",
        description=(
            "Interpolate results between parameter sweep data points to estimate "
            "performance at a specific parameter value without running a new simulation."
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
                    "description": "Result tree path to interpolate.",
                },
            },
            "required": ["parameter", "target_value", "result_path"],
        },
    ),
]


# ---------------------------------------------------------------------------
# VBA generation helpers
# ---------------------------------------------------------------------------


def _build_set_parameter(args: dict) -> str:
    """Build VBA script to set or create a design parameter."""
    name = validate_name(args["name"], "parameter name")
    value = args["value"]
    description = args.get("description")

    safe_name = _escape_vba_string(name)
    safe_value = _escape_vba_string(str(value))

    script = VBAScript()
    script.add_comment(f"Set parameter: {name} = {value}")

    # Use MakeSureParameterExists to create if missing, then StoreParameter to set
    lines = [
        f'MakeSureParameterExists "{safe_name}", "{safe_value}"',
        f'StoreParameter "{safe_name}", "{safe_value}"',
    ]
    if description:
        safe_desc = _escape_vba_string(description)
        lines.append(f'SetParameterDescription "{safe_name}", "{safe_desc}"')

    script.add_raw("\n".join(lines))

    # Rebuild to apply the parameter change
    script.add_raw("RebuildOnParametricChange False, True")

    return script.build()


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
    """Build VBA script to delete a parameter."""
    name = validate_name(args["name"], "parameter name")
    safe_name = _escape_vba_string(name)

    script = VBAScript()
    script.add_comment(f"Delete parameter: {name}")
    script.add_raw(f'DeleteParameter "{safe_name}"')
    script.add_raw("RebuildOnParametricChange False, True")
    return script.build()


def _build_parameter_sweep(args: dict) -> str:
    """Build VBA script to configure a parameter sweep."""
    parameter = validate_name(args["parameter"], "parameter name")
    start = float(args["start"])
    stop = float(args["stop"])
    steps = int(args["steps"])
    sim_type = args.get("simulation_type", "Transient")

    if steps < 2:
        raise ValueError("Parameter sweep requires at least 2 steps")

    script = VBAScript()
    script.add_comment(f"Parameter sweep: {parameter} from {start} to {stop} in {steps} steps")

    vba = (
        VBABuilder("ParameterSweep")
        .call_with_args("AddSequence", f"mcp_{parameter}")
        .set_bool("StartActiveSolver", True)
        .call_with_args("AddParameter_Samples", f"mcp_{parameter}", parameter, str(start), str(stop), str(steps), "False")
    )
    script.add_comment(f"Configure only; select requested {sim_type} solver separately before starting the sweep")
    script.add_block(vba)
    return script.build()


def _build_optimizer(args: dict) -> str:
    from cst_mcp.execution.native_optimizer import build_optimizer
    return build_optimizer(args, "single")


def _build_multi_objective_optimizer(args: dict) -> str:
    from cst_mcp.execution.native_optimizer import build_optimizer
    return build_optimizer(args, "multi")


def _build_sensitivity_analysis(args: dict) -> str:
    """Build VBA for one-at-a-time sensitivity analysis via parameter sweep."""
    parameters = args["parameters"]

    if not parameters:
        raise ValueError("At least one parameter must be specified")

    script = VBAScript()
    script.add_comment(
        f"Sensitivity analysis: monitor {args['result_path']}"
    )

    # Set up a parameter sweep with each parameter varied individually
    for param in parameters:
        param_name = validate_name(param["name"], "parameter name")
        nominal = float(param["nominal"])
        perturbation = float(param.get("perturbation_pct", 5.0))
        delta = abs(nominal * perturbation / 100.0)

        low = nominal - delta
        high = nominal + delta

        vba = (
            VBABuilder("ParameterSweep")
            .call_with_args("AddSequence", f"mcp_sensitivity_{param_name}")
            .set_bool("StartActiveSolver", True)
            .call_with_args(
                "AddParameter_Samples", f"mcp_sensitivity_{param_name}", param_name, str(low), str(high), "3", "False"
            )
        )
        script.add_block(vba)

    return script.build()


def _build_yield_analysis(args: dict) -> str:
    """Build VBA for Monte Carlo yield analysis via parameter sweep."""
    parameters = args["parameters"]
    pass_criteria = args["pass_criteria"]
    num_samples = int(args.get("num_samples", 50))

    if not parameters:
        raise ValueError("At least one parameter must be specified")
    if not pass_criteria:
        raise ValueError("At least one pass criterion must be specified")
    validate_positive(num_samples, "num_samples")

    script = VBAScript()
    script.add_comment(f"Monte Carlo yield analysis — {num_samples} samples")

    # One sample per sequence avoids a Cartesian product masquerading as Monte Carlo.
    import random
    rng = random.Random(0)
    script.add_comment("Uniform independent tolerances; reproducible Python seed=0. Configure only, no solver start. Pass criteria require separate analysis.")
    vba = VBABuilder("ParameterSweep").set_bool("StartActiveSolver", True)
    for sample in range(num_samples):
        sequence = f"mcp_mc_{sample + 1}"
        vba.call_with_args("AddSequence", sequence)
        for param in parameters:
            param_name = validate_name(param["name"], "parameter name")
            nominal, tolerance = float(param["nominal"]), float(param["tolerance"])
            if tolerance < 0:
                raise ValueError("tolerance must be non-negative")
            value = nominal + rng.uniform(-tolerance, tolerance)
            vba.call_with_args("AddParameter_ArbitraryPoints", sequence, param_name, str(value))
    script.add_block(vba)

    # Add pass criteria as comments for post-processing reference
    for criterion in pass_criteria:
        c_path = criterion["result_path"]
        c_op = criterion["operator"]
        c_thresh = criterion["threshold"]
        script.add_comment(f"Pass criterion: {c_path} {c_op} {c_thresh}")

    return script.build()


def _build_constrained_optimizer(args: dict) -> str:
    from cst_mcp.execution.native_optimizer import build_optimizer
    return build_optimizer(args, "constrained")


def _build_parameter_interpolation(args: dict) -> str:
    """Build VBA to access interpolated parameter sweep results."""
    parameter = validate_name(args["parameter"], "parameter name")
    target_value = float(args["target_value"])
    result_path = args["result_path"]

    safe_param = _escape_vba_string(parameter)
    safe_path = _escape_vba_string(result_path)

    script = VBAScript()
    script.add_comment(f"Interpolate {result_path} at {parameter} = {target_value}")

    lines = [
        f'StoreParameter "{safe_param}", "{target_value}"',
        "RebuildOnParametricChange False, True",
        f'SelectTreeItem "{safe_path}"',
        "' Read the result at the interpolated parameter value',",
        "' The result tree will update with the new parameter value.',",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[..., str]] = {
    "cst_set_parameter": _build_set_parameter,
    "cst_get_parameter": _build_get_parameter,
    "cst_list_parameters": _build_list_parameters,
    "cst_delete_parameter": _build_delete_parameter,
    "cst_parameter_sweep": _build_parameter_sweep,
    "cst_optimizer": _build_optimizer,
    "cst_multi_objective_optimizer": _build_multi_objective_optimizer,
    "cst_sensitivity_analysis": _build_sensitivity_analysis,
    "cst_yield_analysis": _build_yield_analysis,
    "cst_constrained_optimizer": _build_constrained_optimizer,
    "cst_parameter_interpolation": _build_parameter_interpolation,
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def _text(data: dict) -> list[TextContent]:
    """Wrap a dict as a single JSON TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


async def handle(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle a parameter tool call.

    Generates VBA via VBABuilder, executes through the CSTClient, and
    returns the result wrapped in TextContent.
    """
    builder_fn = _HANDLERS.get(name)
    if builder_fn is None:
        return _text({"status": "error", "message": f"Unknown parameter tool: {name}"})

    try:
        vba_code = builder_fn(arguments)
        result = client.execute_vba(vba_code)

        # Annotate result with tool-specific metadata
        if name == "cst_set_parameter":
            result["parameter"] = arguments["name"]
            result["value"] = arguments["value"]
        elif name == "cst_get_parameter":
            result["parameter"] = arguments["name"]
        elif name == "cst_delete_parameter":
            result["parameter"] = arguments["name"]
        elif name == "cst_parameter_sweep":
            result["parameter"] = arguments["parameter"]
            result["start"] = arguments["start"]
            result["stop"] = arguments["stop"]
            result["steps"] = arguments["steps"]
        elif name == "cst_optimizer":
            result["goal_type"] = arguments["goal_type"]
            result["result_path"] = arguments["result_path"]
            result["method"] = arguments.get("method", "Trust Region")
            result["max_evaluations"] = arguments.get("max_evaluations", 100)
            result["parameters"] = [p["name"] for p in arguments["parameters"]]
        elif name == "cst_multi_objective_optimizer":
            result["num_goals"] = len(arguments["goals"])
            result["method"] = arguments.get("method", "CMAES")
            result["parameters"] = [p["name"] for p in arguments["parameters"]]
        elif name == "cst_sensitivity_analysis":
            result["result_path"] = arguments["result_path"]
            result["parameters"] = [p["name"] for p in arguments["parameters"]]
        elif name == "cst_yield_analysis":
            result["num_samples"] = arguments.get("num_samples", 50)
            result["parameters"] = [p["name"] for p in arguments["parameters"]]
        elif name == "cst_constrained_optimizer":
            result["objective"] = arguments["objective"]
            result["num_constraints"] = len(arguments["constraints"])
            result["parameters"] = [p["name"] for p in arguments["parameters"]]
        elif name == "cst_parameter_interpolation":
            result["parameter"] = arguments["parameter"]
            result["target_value"] = arguments["target_value"]

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
