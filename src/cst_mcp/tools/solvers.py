"""Solver configuration tools for CST Studio Suite."""

from __future__ import annotations

import json

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.types import ExcitationType
from cst_mcp.validators import (
    validate_enum_value,
    validate_positive,
    validate_range,
)
from cst_mcp.vba_builder import VBABuilder

TOOLS: list[Tool] = [
    Tool(
        name="cst_configure_time_domain_solver",
        description=(
            "Configure the time domain (transient) solver. This is CST's flagship solver "
            "for broadband simulations — it excites the structure with a pulse and computes "
            "S-parameters, fields, and farfield across the entire frequency range in a single run."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "accuracy": {
                    "type": "number",
                    "description": "Steady-state accuracy in dB (Solver.SteadyStateLimit, integer in "
                    "[-80, 0]) — solver stops when energy has decayed to this level (default -40)",
                    "default": -40,
                    "minimum": -80,
                    "maximum": 0,
                },
                "max_time_steps": {
                    "type": "integer",
                    "description": "Deprecated/ignored: CST 2026's Solver has no MaxTimeSteps (a note is "
                    "returned when non-zero). 0 means automatic (default 0)",
                    "default": 0,
                },
                "stimulation_port": {
                    "type": "integer",
                    "description": "Port number used for excitation (default 1)",
                    "default": 1,
                },
                "excitation_type": {
                    "type": "string",
                    "enum": ["Gaussian", "Rectangular", "Smooth"],
                    "description": "Excitation signal shape (default Gaussian). Only Gaussian (CST's default "
                    "signal) is applied; other shapes need an excitation-signal definition and return a note.",
                    "default": "Gaussian",
                },
                "normalize_to_fixed_impedance": {
                    "type": "boolean",
                    "description": "Normalize S-parameters to a fixed reference impedance (default true; "
                    "Solver.AutoNormImpedance True + NormingImpedance). False: port impedance.",
                    "default": True,
                },
                "fixed_impedance": {
                    "type": "number",
                    "description": "Reference impedance in ohms when normalization is enabled (default 50)",
                    "default": 50,
                },
                "activate_power_loss_1d": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Enable Solver.ActivatePowerLoss1DMonitor: 1D 'Loss in Dielectrics/Metals' "
                        "curves. Without it losses exist only at 3D field-monitor frequencies, so the "
                        "power balance (cst_check_power_balance) cannot be checked at farfield "
                        "frequencies. Omitted/false leaves the project setting unchanged."
                    ),
                },
                "power_loss_1d_use_field_monitors": {
                    "type": "boolean", "default": True,
                    "description": "Use3DFieldMonitorForPowerLoss1DMonitor (losses at 3D field-monitor frequencies).",
                },
                "power_loss_1d_use_farfield_monitors": {
                    "type": "boolean", "default": True,
                    "description": "UseFarFieldMonitorForPowerLoss1DMonitor (losses at farfield-monitor "
                    "frequencies; internal full-domain monitors, extra memory).",
                },
                "power_loss_1d_extra_frequencies": {
                    "type": "array", "items": {"type": "number", "exclusiveMinimum": 0}, "maxItems": 64,
                    "default": [],
                    "description": "Extra frequencies (project unit) via UseExtraFreqForPowerLoss1DMonitor "
                    "+ AddPowerLoss1DMonitorExtraFreq.",
                },
                "power_loss_1d_per_solid": {
                    "type": "boolean", "default": False,
                    "description": "PowerLoss1DMonitorPerSolid: extra per-solid loss subfolder.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_configure_frequency_domain_solver",
        description=(
            "Configure the frequency domain solver. Best for narrowband problems, resonant "
            "structures, and when field distributions at specific frequencies are needed. "
            "Supports interpolated, discrete, and general-purpose sweep types."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "accuracy": {
                    "type": "number",
                    "description": "Solver accuracy / residual target (default 1e-6)",
                    "default": 1e-6,
                },
                "f_min": {
                    "type": "number",
                    "description": "Minimum frequency in GHz",
                },
                "f_max": {
                    "type": "number",
                    "description": "Maximum frequency in GHz",
                },
                "samples": {
                    "type": "integer",
                    "description": "Number of frequency samples (default 1001)",
                    "default": 1001,
                },
                "sweep_type": {
                    "type": "string",
                    "enum": ["Interpolated", "Discrete", "General purpose"],
                    "description": "Frequency sweep type (default Interpolated)",
                    "default": "Interpolated",
                },
            },
            "required": ["f_min", "f_max"],
        },
    ),
    Tool(
        name="cst_configure_eigenmode_solver",
        description=(
            "Configure the eigenmode solver. Computes resonant frequencies and field "
            "distributions of cavity structures. Used for filter design, resonator "
            "characterization, and Q-factor extraction."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "number_of_modes": {
                    "type": "integer",
                    "description": "Number of eigenmodes to compute (default 5)",
                    "default": 5,
                },
                "accuracy": {
                    "type": "number",
                    "description": "Solver accuracy target (default 1e-6)",
                    "default": 1e-6,
                },
                "f_min": {
                    "type": "number",
                    "description": "Lower frequency bound in GHz — modes below this are skipped (default 0)",
                    "default": 0,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_configure_integral_equation_solver",
        description=(
            "Configure the integral equation (IE) solver. Best for electrically large, "
            "open-boundary problems like antenna placement on vehicles, RCS computation, "
            "and EMC/EMI analysis where volume meshing would be impractical."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "accuracy": {
                    "type": "number",
                    "description": "Iterative solver residual target (default 1e-3)",
                    "default": 1e-3,
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Maximum number of solver iterations (default 1000)",
                    "default": 1000,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_get_solver_info",
        description=(
            "Get current solver configuration and status. In connected mode this queries "
            "the active solver settings; in offline mode it describes expected parameters."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_configure_eigenmode_advanced",
        description=(
            "Advanced eigenmode solver configuration for higher-order modes. Use this for "
            "waveguide mode analysis, cavity resonator design, and filter characterization "
            "where fine control over mode count, frequency targeting, and solver order is needed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_modes": {
                    "type": "integer",
                    "description": "Number of eigenmodes to compute (1-50, default 5)",
                    "default": 5,
                },
                "frequency_estimate_ghz": {
                    "type": "number",
                    "description": "Frequency estimate in GHz to target specific modes (optional)",
                },
                "accuracy": {
                    "type": "number",
                    "description": "Solver accuracy target (default 1e-6)",
                    "default": 1e-6,
                },
                "solver_order": {
                    "type": "integer",
                    "description": "Solver order 1-3 for higher accuracy (default 1)",
                    "default": 1,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_configure_ie_solver_advanced",
        description=(
            "Advanced Integral Equation solver configuration for electrically large structures. "
            "Provides control over preconditioner, MLFMM acceleration, and low-frequency "
            "stabilization for installed antenna performance and large-platform RCS analysis."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "accuracy": {
                    "type": "number",
                    "description": "Iterative solver residual target (default 1e-3)",
                    "default": 1e-3,
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Maximum number of solver iterations (default 1000)",
                    "default": 1000,
                },
                "preconditioner": {
                    "type": "string",
                    "enum": ["ILU", "Multilevel"],
                    "description": "Preconditioner type (default ILU)",
                    "default": "ILU",
                },
                "low_frequency_stabilization": {
                    "type": "boolean",
                    "description": "Enable low-frequency stabilization for broadband problems (default false)",
                    "default": False,
                },
                "mlfmm": {
                    "type": "boolean",
                    "description": "Enable Multi-Level Fast Multipole Method for large problems (default true)",
                    "default": True,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_configure_multilayer_solver",
        description=(
            "Configure the solver for planar multilayer structures. Optimised for antenna-on-PCB, "
            "frequency selective surfaces (FSS), and radome analysis using the frequency domain "
            "solver with multilayer-specific settings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "f_min": {
                    "type": "number",
                    "description": "Minimum frequency in GHz",
                },
                "f_max": {
                    "type": "number",
                    "description": "Maximum frequency in GHz",
                },
                "num_samples": {
                    "type": "integer",
                    "description": "Number of frequency samples (default 501)",
                    "default": 501,
                },
                "sweep_type": {
                    "type": "string",
                    "enum": ["Interpolated", "Discrete"],
                    "description": "Frequency sweep type (default Interpolated)",
                    "default": "Interpolated",
                },
            },
            "required": ["f_min", "f_max"],
        },
    ),
]

async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a solver configuration tool call."""
    try:
        if name == "cst_configure_time_domain_solver":
            return _configure_time_domain(arguments, client)
        elif name == "cst_configure_frequency_domain_solver":
            return _configure_frequency_domain(arguments, client)
        elif name == "cst_configure_eigenmode_solver":
            return _configure_eigenmode(arguments, client)
        elif name == "cst_configure_integral_equation_solver":
            return _configure_integral_equation(arguments, client)
        elif name == "cst_get_solver_info":
            return _get_solver_info(arguments, client)
        elif name == "cst_configure_eigenmode_advanced":
            return _configure_eigenmode_advanced(arguments, client)
        elif name == "cst_configure_ie_solver_advanced":
            return _configure_ie_solver_advanced(arguments, client)
        elif name == "cst_configure_multilayer_solver":
            return _configure_multilayer_solver(arguments, client)

        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": f"Unknown solver tool: {name}"}, indent=2),
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


def build_power_loss_1d_vba(
    *,
    use_field_monitors: bool = True,
    use_farfield_monitors: bool = True,
    extra_frequencies: list[float] | tuple[float, ...] = (),
    per_solid: bool = False,
) -> str:
    """Solver block enabling the 1D power-loss monitor (CST 2026 Solver object).

    Methods per the installed VBA help (special_vbasolver_solver_object):
    ActivatePowerLoss1DMonitor, PowerLoss1DMonitorPerSolid,
    Use3DFieldMonitorForPowerLoss1DMonitor, UseFarFieldMonitorForPowerLoss1DMonitor,
    UseExtraFreqForPowerLoss1DMonitor, ResetPowerLoss1DMonitorExtraFreq,
    AddPowerLoss1DMonitorExtraFreq.  Same string-argument form as the campaign
    model that computed losses at every farfield frequency.
    """
    from cst_mcp.vba_safety import vba_number

    extras = [vba_number(f, "power_loss_1d_extra_frequencies") for f in extra_frequencies]

    def b(v: bool) -> str:
        return "True" if v else "False"

    lines = [
        "With Solver",
        '  .ActivatePowerLoss1DMonitor "True"',
        f'  .PowerLoss1DMonitorPerSolid "{b(per_solid)}"',
        f'  .Use3DFieldMonitorForPowerLoss1DMonitor "{b(use_field_monitors)}"',
        f'  .UseFarFieldMonitorForPowerLoss1DMonitor "{b(use_farfield_monitors)}"',
        f'  .UseExtraFreqForPowerLoss1DMonitor "{b(bool(extras))}"',
    ]
    if extras:
        lines.append("  .ResetPowerLoss1DMonitorExtraFreq")
        lines += [f'  .AddPowerLoss1DMonitorExtraFreq "{f}"' for f in extras]
    lines.append("End With")
    return "\n".join(lines)


def _configure_time_domain(arguments: dict, client: CSTClient) -> list[TextContent]:
    accuracy = float(arguments.get("accuracy", -40))
    max_time_steps = int(arguments.get("max_time_steps", 0))
    stimulation_port = int(arguments.get("stimulation_port", 1))
    excitation_type = arguments.get("excitation_type", "Gaussian")
    normalize = arguments.get("normalize_to_fixed_impedance", True)
    fixed_impedance = float(arguments.get("fixed_impedance", 50))

    validate_range(accuracy, -80, 0, "accuracy")
    if max_time_steps < 0:
        max_time_steps = 0
    if stimulation_port < 1:
        stimulation_port = 1
    validate_enum_value(excitation_type, ExcitationType, "excitation_type")
    validate_positive(fixed_impedance, "fixed_impedance")

    # Methods of the CST 2026 Solver object (special_vbasolver_solver_object):
    # the steady-state accuracy is SteadyStateLimit (integer dB in [-80, 0]);
    # AutoNormImpedance True normalises to NormingImpedance, False to the
    # port impedance.  AccuracyOrder / MaxTimeSteps / NormalizeToFixedImpedance /
    # FixedImpedance do not exist ("no such property or method", live
    # CST 2026) and Solver.ExcitationType is the Automatic/Standard/Broadband
    # mode setting, not the signal shape, so none of them is emitted.
    notes: list[str] = []
    vba = VBABuilder("Solver")
    vba.set("SteadyStateLimit", str(int(round(accuracy))))
    vba.set_number("StimulationPort", stimulation_port)
    vba.set_bool("AutoNormImpedance", bool(normalize))
    if normalize:
        vba.set_number("NormingImpedance", fixed_impedance)
    script = vba.build()
    if max_time_steps:
        notes.append("max_time_steps is not applied: the CST 2026 Solver object has no MaxTimeSteps "
                     "(the run length is limited by SteadyStateLimit / NumberOfPulseWidths).")
    if excitation_type != "Gaussian":
        notes.append(f"excitation_type '{excitation_type}' is not applied: the signal shape is an "
                     "excitation-signal definition, not a Solver setting; the default Gaussian is used.")
    power_loss = None
    if arguments.get("activate_power_loss_1d"):
        script = script + "\n" + build_power_loss_1d_vba(
            use_field_monitors=bool(arguments.get("power_loss_1d_use_field_monitors", True)),
            use_farfield_monitors=bool(arguments.get("power_loss_1d_use_farfield_monitors", True)),
            extra_frequencies=arguments.get("power_loss_1d_extra_frequencies") or [],
            per_solid=bool(arguments.get("power_loss_1d_per_solid", False)),
        )
        power_loss = {
            "activated": True,
            "use_field_monitors": bool(arguments.get("power_loss_1d_use_field_monitors", True)),
            "use_farfield_monitors": bool(arguments.get("power_loss_1d_use_farfield_monitors", True)),
            "extra_frequencies": list(arguments.get("power_loss_1d_extra_frequencies") or []),
            "result_items": "1D Results\\Power\\Excitation [1]\\Loss in Dielectrics / Loss in Metals",
        }

    result = client.execute_vba(script)
    if power_loss:
        result["power_loss_1d"] = power_loss
    result["solver"] = "Time Domain"
    result["accuracy_db"] = accuracy
    result["max_time_steps"] = max_time_steps
    result["stimulation_port"] = stimulation_port
    result["excitation_type"] = excitation_type
    result["normalize_to_fixed_impedance"] = normalize
    result["fixed_impedance_ohm"] = fixed_impedance
    if notes:
        result["notes"] = notes
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _configure_frequency_domain(arguments: dict, client: CSTClient) -> list[TextContent]:
    accuracy = float(arguments.get("accuracy", 1e-6))
    f_min = float(arguments.get("f_min", 0))
    f_max = float(arguments.get("f_max", 0))
    samples = int(arguments.get("samples", 1001))
    sweep_type = arguments.get("sweep_type", "Interpolated")

    validate_positive(accuracy, "accuracy")
    validate_positive(f_max, "f_max")
    if f_min < 0:
        f_min = 0
    if f_min >= f_max:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"status": "error", "message": f"f_min ({f_min}) must be less than f_max ({f_max})"}
                ),
            )
        ]
    validate_positive(samples, "samples")
    valid_sweeps = ["Interpolated", "Discrete", "General purpose"]
    if sweep_type not in valid_sweeps:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"status": "error", "message": f"Invalid sweep_type '{sweep_type}'. Valid: {valid_sweeps}"}
                ),
            )
        ]

    vba = VBABuilder("FDSolver")
    vba.set_number("Accuracy", accuracy)
    vba.set_number("FrequencyMin", f_min)
    vba.set_number("FrequencyMax", f_max)
    vba.set_number("Samples", samples)
    vba.set("SweepType", sweep_type)
    script = vba.build()

    result = client.execute_vba(script)
    result["solver"] = "Frequency Domain"
    result["accuracy"] = accuracy
    result["f_min_ghz"] = f_min
    result["f_max_ghz"] = f_max
    result["samples"] = samples
    result["sweep_type"] = sweep_type
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _configure_eigenmode(arguments: dict, client: CSTClient) -> list[TextContent]:
    number_of_modes = int(arguments.get("number_of_modes", 5))
    accuracy = float(arguments.get("accuracy", 1e-6))
    f_min = float(arguments.get("f_min", 0))

    validate_range(number_of_modes, 1, 1000, "number_of_modes")
    validate_positive(accuracy, "accuracy")
    if f_min < 0:
        f_min = 0

    vba = VBABuilder("EigenmodeSolver")
    vba.set_number("NumberOfModes", number_of_modes)
    vba.set_number("Accuracy", accuracy)
    vba.set_number("FrequencyMin", f_min)
    script = vba.build()

    result = client.execute_vba(script)
    result["solver"] = "Eigenmode"
    result["number_of_modes"] = number_of_modes
    result["accuracy"] = accuracy
    result["f_min_ghz"] = f_min
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _configure_integral_equation(arguments: dict, client: CSTClient) -> list[TextContent]:
    accuracy = float(arguments.get("accuracy", 1e-3))
    max_iterations = int(arguments.get("max_iterations", 1000))

    validate_positive(accuracy, "accuracy")
    validate_range(max_iterations, 1, 100000, "max_iterations")

    vba = VBABuilder("IESolver")
    vba.set_number("Accuracy", accuracy)
    vba.set_number("MaxIterations", max_iterations)
    script = vba.build()

    result = client.execute_vba(script)
    result["solver"] = "Integral Equation"
    result["accuracy"] = accuracy
    result["max_iterations"] = max_iterations
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _get_solver_info(arguments: dict, client: CSTClient) -> list[TextContent]:
    # Read-only query through output capture (never model history).
    fields = [
        ("solver_type", "GetSolverType()"),
        ("fmin", "Solver.GetFmin"),
        ("fmax", "Solver.GetFmax"),
        ("n_frequency_samples", "Solver.GetNFsamples"),
        ("number_of_ports", "Solver.GetNumberOfPorts"),
        ("stimulation_port", "Solver.GetStimulationPort"),
        ("last_solver_time_s", "Solver.GetLastSolverTime"),
    ]
    script = client.build_query_vba(fields) if hasattr(client, "build_query_vba") else ""

    if client.connected:
        query = client.query_values(fields)
        if query.get("status") != "ok":
            result = query
        else:
            result = {"status": "ok", "source": query.get("source")}
            for key, value in query["values"].items():
                if key == "solver_type":
                    result[key] = value
                    continue
                try:
                    result[key] = int(value)
                except ValueError:
                    try:
                        result[key] = float(value.replace(",", "."))
                    except ValueError:
                        result[key] = value
            if "fmin" in result or "fmax" in result:
                result["frequency_unit"] = "project frequency unit (as set by cst_set_units)"
            if query.get("errors"):
                result["unavailable"] = query["errors"]
    else:
        result = {
            "status": "offline",
            "vba": script,
            "description": (
                "In connected mode this returns the active solver type and its "
                "configuration. Available solver types: Time Domain, Frequency Domain, "
                "Eigenmode, Integral Equation, Multilayer, Asymptotic."
            ),
            "configurable_solvers": {
                "Time Domain": {
                    "vba_object": "Solver",
                    "key_settings": [
                        "accuracy (dB)",
                        "max_time_steps",
                        "stimulation_port",
                        "excitation_type",
                        "fixed_impedance",
                    ],
                },
                "Frequency Domain": {
                    "vba_object": "FDSolver",
                    "key_settings": [
                        "accuracy",
                        "f_min/f_max (GHz)",
                        "samples",
                        "sweep_type",
                    ],
                },
                "Eigenmode": {
                    "vba_object": "EigenmodeSolver",
                    "key_settings": [
                        "number_of_modes",
                        "accuracy",
                        "f_min (GHz)",
                    ],
                },
                "Integral Equation": {
                    "vba_object": "IESolver",
                    "key_settings": [
                        "accuracy",
                        "max_iterations",
                    ],
                },
            },
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _configure_eigenmode_advanced(arguments: dict, client: CSTClient) -> list[TextContent]:
    num_modes = int(arguments.get("num_modes", 5))
    frequency_estimate = arguments.get("frequency_estimate_ghz")
    accuracy = float(arguments.get("accuracy", 1e-6))
    solver_order = int(arguments.get("solver_order", 1))

    validate_range(num_modes, 1, 50, "num_modes")
    validate_positive(accuracy, "accuracy")
    validate_range(solver_order, 1, 3, "solver_order")

    vba = VBABuilder("EigenmodeSolver")
    vba.set_number("SetNumberOfModes", num_modes)
    if frequency_estimate is not None:
        freq_est = float(frequency_estimate)
        validate_positive(freq_est, "frequency_estimate_ghz")
        vba.set_number("SetFrequencyTarget", freq_est)
    vba.set_number("SetAccuracy", accuracy)
    vba.set_bool("SetMeshAdaption", False)
    vba.set_number("SetSolverOrder", solver_order)
    script = vba.build()

    result = client.execute_vba(script)
    result["solver"] = "Eigenmode (Advanced)"
    result["num_modes"] = num_modes
    result["accuracy"] = accuracy
    result["solver_order"] = solver_order
    if frequency_estimate is not None:
        result["frequency_estimate_ghz"] = float(frequency_estimate)
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _configure_ie_solver_advanced(arguments: dict, client: CSTClient) -> list[TextContent]:
    accuracy = float(arguments.get("accuracy", 1e-3))
    max_iterations = int(arguments.get("max_iterations", 1000))
    preconditioner = arguments.get("preconditioner", "ILU")
    low_freq_stab = arguments.get("low_frequency_stabilization", False)
    mlfmm = arguments.get("mlfmm", True)

    validate_positive(accuracy, "accuracy")
    validate_range(max_iterations, 1, 100000, "max_iterations")
    valid_preconditioners = ["ILU", "Multilevel"]
    if preconditioner not in valid_preconditioners:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Invalid preconditioner '{preconditioner}'. Valid: {valid_preconditioners}",
        }))]

    vba = VBABuilder("IESolver")
    vba.set_number("SetAccuracy", accuracy)
    vba.set_number("SetMaxIterations", max_iterations)
    vba.set("SetPreconditionerType", preconditioner)
    vba.set_bool("SetLowFrequencyStabilization", low_freq_stab)
    vba.set_bool("SetMLFMM", mlfmm)
    script = vba.build()

    result = client.execute_vba(script)
    result["solver"] = "Integral Equation (Advanced)"
    result["accuracy"] = accuracy
    result["max_iterations"] = max_iterations
    result["preconditioner"] = preconditioner
    result["low_frequency_stabilization"] = low_freq_stab
    result["mlfmm"] = mlfmm
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _configure_multilayer_solver(arguments: dict, client: CSTClient) -> list[TextContent]:
    f_min = float(arguments.get("f_min", 0))
    f_max = float(arguments.get("f_max", 0))
    num_samples = int(arguments.get("num_samples", 501))
    sweep_type = arguments.get("sweep_type", "Interpolated")

    validate_positive(f_max, "f_max")
    if f_min < 0:
        f_min = 0
    if f_min >= f_max:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"f_min ({f_min}) must be less than f_max ({f_max})",
        }))]
    validate_positive(num_samples, "num_samples")
    valid_sweeps = ["Interpolated", "Discrete"]
    if sweep_type not in valid_sweeps:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Invalid sweep_type '{sweep_type}'. Valid: {valid_sweeps}",
        }))]

    vba = VBABuilder("FDSolver")
    vba.set_number("FrequencyMin", f_min)
    vba.set_number("FrequencyMax", f_max)
    vba.set_number("Samples", num_samples)
    vba.set("SweepType", sweep_type)
    vba.set_bool("UseMultilayerSolver", True)
    script = vba.build()

    result = client.execute_vba(script)
    result["solver"] = "Multilayer (Frequency Domain)"
    result["f_min_ghz"] = f_min
    result["f_max_ghz"] = f_max
    result["num_samples"] = num_samples
    result["sweep_type"] = sweep_type
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
