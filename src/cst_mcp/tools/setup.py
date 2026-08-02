"""Frequency, boundaries, mesh, and solver configuration."""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from cst_mcp.execution.vba_builder import VBABuilder, VBAScript
from cst_mcp.session import CSTSession
from cst_mcp.tools.registry import as_json, err

TOOLS: list[Tool] = [
    Tool(
        name="cst_set_frequency",
        description="Set simulation frequency range in GHz (fmin, fmax).",
        inputSchema={
            "type": "object",
            "properties": {
                "fmin_ghz": {"type": "number"},
                "fmax_ghz": {"type": "number"},
            },
            "required": ["fmin_ghz", "fmax_ghz"],
        },
    ),
    Tool(
        name="cst_set_boundaries",
        description=(
            "Set open/electric/magnetic/conducting wall boundaries on each side. "
            "Values: expanded open | open | electric | magnetic | conducting wall | periodic"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "xmin": {"type": "string", "default": "expanded open"},
                "xmax": {"type": "string", "default": "expanded open"},
                "ymin": {"type": "string", "default": "expanded open"},
                "ymax": {"type": "string", "default": "expanded open"},
                "zmin": {"type": "string", "default": "expanded open"},
                "zmax": {"type": "string", "default": "expanded open"},
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_set_units",
        description="Set geometry and frequency units (Units block; no Apply — CST 2026).",
        inputSchema={
            "type": "object",
            "properties": {
                "geometry": {
                    "type": "string",
                    "enum": ["mm", "cm", "m", "um", "nm", "mil", "in"],
                    "default": "mm",
                },
                "frequency": {
                    "type": "string",
                    "enum": ["Hz", "kHz", "MHz", "GHz", "THz"],
                    "default": "GHz",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_configure_solver",
        description=(
            "Configure the time-domain (default) or frequency-domain solver accuracy / samples."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "solver": {
                    "type": "string",
                    "enum": ["time_domain", "frequency_domain"],
                    "default": "time_domain",
                },
                "accuracy_db": {
                    "type": "number",
                    "description": "TD energy decay accuracy, e.g. -40",
                    "default": -40,
                },
                "samples": {
                    "type": "integer",
                    "description": "FD frequency samples",
                    "default": 1001,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_add_farfield_monitor",
        description="Add a far-field broadband/frequency monitor at a given GHz frequency.",
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {"type": "number"},
                "name": {"type": "string", "description": "Optional monitor name"},
            },
            "required": ["frequency_ghz"],
        },
    ),
    Tool(
        name="cst_set_background",
        description="Set background material (usually Vacuum) and optional frequency-dependent options.",
        inputSchema={
            "type": "object",
            "properties": {
                "material": {"type": "string", "default": "Vacuum"},
                "x_min": {"type": "number", "default": 0},
                "x_max": {"type": "number", "default": 0},
                "y_min": {"type": "number", "default": 0},
                "y_max": {"type": "number", "default": 0},
                "z_min": {"type": "number", "default": 0},
                "z_max": {"type": "number", "default": 0},
            },
            "required": [],
        },
    ),
]


async def handle(name: str, args: dict[str, Any], session: CSTSession) -> list[TextContent] | None:
    try:
        if name == "cst_set_frequency":
            from cst_mcp.execution.vba_builder import fmt_num

            vba = (
                "With Solver\n"
                f'     .FrequencyRange "{fmt_num(float(args["fmin_ghz"]))}", '
                f'"{fmt_num(float(args["fmax_ghz"]))}"\n'
                "End With"
            )
            return as_json({**session.run_history(vba, label="freq_range"), "vba": vba})

        if name == "cst_set_boundaries":
            from cst_mcp.execution.vba_builder import vba_str

            sides = {
                "Xmin": args.get("xmin") or "expanded open",
                "Xmax": args.get("xmax") or "expanded open",
                "Ymin": args.get("ymin") or "expanded open",
                "Ymax": args.get("ymax") or "expanded open",
                "Zmin": args.get("zmin") or "expanded open",
                "Zmax": args.get("zmax") or "expanded open",
            }
            lines = ["With Boundary"]
            for prop, val in sides.items():
                lines.append(f'     .{prop} "{vba_str(str(val))}"')
            lines.append("End With")
            vba = "\n".join(lines)
            return as_json({**session.run_history(vba, label="boundaries"), "vba": vba})

        if name == "cst_set_units":
            from cst_mcp.execution.vba_builder import vba_str

            geo = str(args.get("geometry") or "mm")
            freq = str(args.get("frequency") or "GHz")
            # CST 2024+ official API: SetUnit(dimension, unit) — no .Geometry/.Apply
            vba = "\n".join(
                [
                    "With Units",
                    f'     .SetUnit "Length", "{vba_str(geo)}"',
                    f'     .SetUnit "Frequency", "{vba_str(freq)}"',
                    '     .SetUnit "Time", "ns"',
                    "End With",
                ]
            )
            return as_json({**session.run_history(vba, label="units"), "vba": vba})

        if name == "cst_configure_solver":
            from cst_mcp.execution.vba_builder import fmt_num

            solver = str(args.get("solver") or "time_domain")
            if solver == "frequency_domain":
                samples = int(args.get("samples") or 1001)
                vba = "\n".join(
                    [
                        "ChangeSolverType \"HF Frequency Domain\"",
                        "With FDSolver",
                        f'     .Samples "{samples}"',
                        "End With",
                    ]
                )
            else:
                acc = float(args.get("accuracy_db") or -40)
                vba = "\n".join(
                    [
                        "ChangeSolverType \"HF Time Domain\"",
                        "With Solver",
                        f'     .StimulationPort "All"',
                        f'     .StimulationMode "All"',
                        f'     .SteadyStateLimit "{fmt_num(acc)}"',
                        "End With",
                    ]
                )
            return as_json({**session.run_history(vba, label="solver_cfg"), "vba": vba})

        if name == "cst_add_farfield_monitor":
            from cst_mcp.execution.farfield import farfield_monitor_vba
            from cst_mcp.execution.vba_builder import fmt_num

            f = float(args["frequency_ghz"])
            mon_name = str(args.get("name") or f"farfield (f={fmt_num(f)})")
            # Official Monitor API: .Frequency + EnableNearfieldCalculation
            vba = farfield_monitor_vba(mon_name, f)
            return as_json({**session.run_history(vba, label="farfield_mon"), "vba": vba})

        if name == "cst_set_background":
            from cst_mcp.execution.vba_builder import fmt_num, vba_str

            mat = str(args.get("material") or "Vacuum")
            vba = "\n".join(
                [
                    "With Background",
                    f'     .Type "Normal"',
                    f'     .Epsilon "1.0"',
                    f'     .Mu "1.0"',
                    f'     .XminSpace "{fmt_num(float(args.get("x_min") or 0))}"',
                    f'     .XmaxSpace "{fmt_num(float(args.get("x_max") or 0))}"',
                    f'     .YminSpace "{fmt_num(float(args.get("y_min") or 0))}"',
                    f'     .YmaxSpace "{fmt_num(float(args.get("y_max") or 0))}"',
                    f'     .ZminSpace "{fmt_num(float(args.get("z_min") or 0))}"',
                    f'     .ZmaxSpace "{fmt_num(float(args.get("z_max") or 0))}"',
                    "End With",
                ]
            )
            return as_json({**session.run_history(vba, label="background"), "vba": vba})
    except Exception as exc:  # noqa: BLE001
        return err(str(exc))
    return None
