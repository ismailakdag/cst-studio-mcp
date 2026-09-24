"""Diagnostic tools for CST Studio Suite.

Provides tools for managing simulation results, reading project
messages/logs, and handling CST dialog windows — essential for
preventing blocking popups during automation.

- ``cst_delete_results``: Delete simulation results (prevents stale-result dialogs)
- ``cst_read_project_log``: Read solver log and project messages
- ``cst_dismiss_dialogs``: Find and dismiss CST dialog windows (read their content)
- ``cst_start_dialog_watcher``: Auto-dismiss dialogs in background during long ops
- ``cst_stop_dialog_watcher``: Stop the background dialog watcher and get its log
- ``cst_check_power_balance``: Read-only P_acc = P_rad + P_loss check (PML leakage)
- ``cst_check_model_setup``: Read-only boundary/port/loss-monitor sanity checks
"""

from __future__ import annotations

import json

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="cst_delete_results",
        description=(
            "Delete simulation results from the current CST project. "
            "This prevents the 'Results May Get Incompatible With Model' "
            "dialog that blocks automation when modifying a model with "
            "existing results. Call before making parameter or geometry "
            "changes on a project that has been solved."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_read_project_log",
        description=(
            "Read solver log files and project status information from "
            "the current CST project. Returns solver running state and "
            "the contents of the most recent log file. Useful for "
            "diagnosing solver errors, checking simulation progress, "
            "and understanding what happened during a failed run."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_dismiss_dialogs",
        description=(
            "Find and dismiss any visible CST dialog windows (error popups, "
            "'Results Incompatible' dialogs, solver warnings). Returns the "
            "title and text content of each dialog before dismissing it. "
            "Use this to unblock CST when a modal dialog is preventing "
            "further automation. Uses Win32 API on Windows."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "read_only": {
                    "type": "boolean",
                    "description": (
                        "If true, only read dialog content without dismissing. "
                        "Default: false (read and dismiss)."
                    ),
                    "default": False,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_start_dialog_watcher",
        description=(
            "Start a background thread that automatically detects and "
            "dismisses CST dialog windows as they appear. Essential for "
            "long-running operations like optimization loops where dialogs "
            "would otherwise block execution. The watcher logs every dialog "
            "it dismisses — retrieve the log with cst_stop_dialog_watcher."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_stop_dialog_watcher",
        description=(
            "Stop the background dialog watcher and return its log of all "
            "dialogs that were auto-dismissed. Use after completing an "
            "operation that required the watcher."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_check_power_balance",
        description=(
            "Read-only power-balance diagnostic. From 1D Results\\Power\\Excitation [n]\\ "
            "(Power Stimulated/Accepted/Radiated, Loss in Dielectrics/Metals) of a saved project "
            "(or inline curves) and optional realized-gain farfield grids, computes per frequency: "
            "eta_farfield = P_rad/P_acc, eta_loss = 1 - P_loss/P_acc, eta_pattern = mean(realized "
            "gain)*P_stim/P_acc, unaccounted = (P_acc-P_rad-P_loss)/P_acc, and flags "
            "|unaccounted| > threshold (3 %). A non-closing balance usually means geometry touches "
            "an 'open' boundary and is extended into the PML (virtually infinite), absorbing power "
            "that is neither radiated nor counted as loss, so efficiency/gain are unreliable; fix: "
            "'expanded open' + internal port (PortOnBound False) on a closed coax/SMA feed. Loss "
            "curves exist only at field-monitor frequencies unless the solver's 1D power-loss "
            "monitor is enabled (cst_configure_time_domain_solver activate_power_loss_1d=true)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Saved .cst project to read (cst.results). Defaults to the connected "
                    "session's project.",
                },
                "frequencies_ghz": {
                    "type": "array",
                    "items": {"type": "number", "exclusiveMinimum": 0},
                    "maxItems": 64,
                    "description": "Frequencies to evaluate (project frequency unit, normally GHz). "
                    "Default: the loss-curve sample frequencies.",
                },
                "excitation": {
                    "type": "string",
                    "default": "Excitation [1]",
                    "description": "Excitation folder under 1D Results\\Power.",
                },
                "run_id": {"type": "integer", "minimum": 0, "default": 0},
                "threshold": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 0.5,
                    "default": 0.03,
                    "description": "Flag when |unaccounted| (or the pattern vs P_rad spread) exceeds this.",
                },
                "farfield_grids": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {
                        "type": "object",
                        "properties": {
                            "frequency_ghz": {"type": "number", "exclusiveMinimum": 0},
                            "data_file": {
                                "type": "string",
                                "description": "CST farfield ASCII export of realized gain (dBi) on a "
                                "full theta/phi grid.",
                            },
                        },
                        "required": ["frequency_ghz", "data_file"],
                    },
                    "description": "Optional realized-gain grids for the pattern-integral estimate.",
                },
                "power_curves": {
                    "type": "object",
                    "description": "Inline curves instead of a project: keys P_stim, P_acc, P_rad, "
                    "P_loss_diel, P_loss_metal, each {x: [...GHz], y: [...W]}.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_check_model_setup",
        description=(
            "Read-only sanity check of a described setup (nothing is sent to CST). Warns when a "
            "waveguide port sits on an 'open' (no added space) boundary face and the structure touches "
            "that face: CST extends geometry touching an open boundary into the PML (virtually "
            "infinite), so power is absorbed there, the balance P_acc = P_rad + P_loss does not close "
            "and efficiency/gain are unreliable. Also flags plain 'open' faces the structure reaches, "
            "PortOnBound True on faces with added space, and farfield frequencies without loss data "
            "(ActivatePowerLoss1DMonitor off)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "boundaries": {
                    "type": "object",
                    "description": "Face -> boundary type, e.g. {'y_min': 'open', 'x_min': 'expanded open'} "
                    "(keys x_min..z_max or xmin..zmax).",
                },
                "ports": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {
                        "type": "object",
                        "properties": {
                            "port_number": {"type": "integer", "minimum": 1},
                            "type": {"type": "string", "enum": ["waveguide", "discrete"], "default": "waveguide"},
                            "orientation": {
                                "type": "string",
                                "enum": ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"],
                            },
                            "port_on_bound": {"type": "boolean"},
                            "plane": {
                                "type": "number",
                                "description": "Port plane coordinate along its normal axis.",
                            },
                        },
                    },
                },
                "structure_bbox": {
                    "type": "object",
                    "description": "Structure bounding box {xmin, xmax, ymin, ymax, zmin, zmax} (model units).",
                },
                "power_loss_1d": {
                    "type": "boolean",
                    "description": "Whether Solver.ActivatePowerLoss1DMonitor is enabled.",
                },
                "farfield_frequencies_ghz": {"type": "array", "items": {"type": "number"}, "maxItems": 64},
                "field_monitor_frequencies_ghz": {"type": "array", "items": {"type": "number"}, "maxItems": 64},
            },
            "required": ["boundaries"],
        },
    ),
]

_TOOL_NAMES = {t.name for t in TOOLS}


def _check_power_balance(arguments: dict, client: CSTClient) -> dict:
    from cst_mcp.execution import power_balance as pb

    threshold = float(arguments.get("threshold", pb.DEFAULT_THRESHOLD))
    excitation = str(arguments.get("excitation") or "Excitation [1]")
    if any(c in excitation for c in "\\\r\n"):
        raise ValueError("excitation must be a folder name such as 'Excitation [1]'")
    sources: dict = {}
    inline = arguments.get("power_curves")
    if inline:
        curves = {}
        for key, c in inline.items():
            if key not in pb.POWER_ITEMS:
                raise ValueError(f"power_curves key '{key}' not in {list(pb.POWER_ITEMS)}")
            curves[key] = {"x": [float(v) for v in c["x"]], "y": [float(v) for v in c["y"]]}
        sources["kind"] = "inline"
    else:
        project_path = arguments.get("project_path") or getattr(client, "project_path", None)
        if not project_path:
            return {"status": "error",
                    "message": "Pass project_path (saved .cst) or power_curves, or connect with a saved project."}
        if not arguments.get("project_path"):
            running = getattr(client, "is_solver_running", None)
            if callable(running) and running(timeout_s=5) is not False:
                return {"status": "busy", "message": "Results are not read while the solver is active "
                        "or its state is unknown."}
        curves, items = pb.read_power_curves(str(project_path), excitation, int(arguments.get("run_id", 0)))
        sources = {"kind": "project", "project_path": str(project_path), "items": items}
        if not curves.get("P_acc"):
            return {"status": "no_results",
                    "message": f"No '1D Results\\Power\\{excitation}\\Power Accepted' curve found. Run the "
                    "solver and save the project, or check the excitation name.",
                    "sources": sources}
    freqs = arguments.get("frequencies_ghz")
    if not freqs:
        loss = curves.get("P_loss_diel") or curves.get("P_loss_metal")
        if loss and len(loss["x"]) <= 10:
            freqs = list(loss["x"])
        else:
            return {"status": "error", "message": "Pass frequencies_ghz (no sparse loss samples to default to).",
                    "sources": sources}
    means: dict[float, float] = {}
    grids = []
    for g in arguments.get("farfield_grids") or []:
        from cst_mcp.execution.figures_3d_data import parse_farfield_ascii
        from cst_mcp.execution.power_balance import sphere_mean_linear

        grid = parse_farfield_ascii(g["data_file"], quantity_hint="realized_gain")
        mean = sphere_mean_linear(grid.theta, grid.phi, grid.total_db)
        means[float(g["frequency_ghz"])] = mean
        entry = {"frequency_ghz": float(g["frequency_ghz"]), "data_file": g["data_file"],
                 "quantity": grid.quantity, "sphere_mean_linear": round(mean, 6)}
        if grid.quantity not in ("realized_gain", "unknown"):
            entry["note"] = "eta_pattern assumes realized gain (4*pi*U/P_stim); this grid is " + grid.quantity
        grids.append(entry)
    out = pb.compute_balance(curves, [float(f) for f in freqs], threshold=threshold, pattern_means=means)
    out["sources"] = sources
    if grids:
        out["farfield_grids"] = grids
    out["read_only"] = True
    return out


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _text(data: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a diagnostics tool call."""
    try:
        if name == "cst_delete_results":
            return _text(client.delete_results())

        if name == "cst_read_project_log":
            return _text(client.read_project_messages())

        if name == "cst_dismiss_dialogs":
            read_only = arguments.get("read_only", False)
            if read_only:
                return _text(client.read_dialogs())
            return _text(client.dismiss_dialogs())

        if name == "cst_start_dialog_watcher":
            return _text(client.start_dialog_watcher())

        if name == "cst_stop_dialog_watcher":
            return _text(client.stop_dialog_watcher())

        if name == "cst_check_power_balance":
            return _text(_check_power_balance(arguments, client))

        if name == "cst_check_model_setup":
            from cst_mcp.execution.model_checks import check_setup

            return _text(check_setup(
                arguments.get("boundaries") or {},
                arguments.get("ports") or [],
                structure_bbox=arguments.get("structure_bbox"),
                power_loss_1d=arguments.get("power_loss_1d"),
                farfield_frequencies=arguments.get("farfield_frequencies_ghz"),
                field_monitor_frequencies=arguments.get("field_monitor_frequencies_ghz"),
            ))

        return _text({"status": "error", "message": f"Unknown diagnostics tool: {name}"})
    except Exception as e:
        return _text({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


# Reject line breaks and non-numeric values in numeric slots before any VBA
# is generated from the arguments (generated VBA bypasses CST_ALLOW_RAW_VBA).
from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
