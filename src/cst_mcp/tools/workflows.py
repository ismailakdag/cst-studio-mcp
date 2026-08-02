"""High-level workflow tools — safe composites over the full surface."""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from cst_mcp.domain.antennas.patch import design_patch
from cst_mcp.execution.port_helpers import feed_line_y_range, microstrip_waveguide_port_vba
from cst_mcp.execution.vba_builder import fmt_num, vba_str
from cst_mcp.tools.registry import as_json, err
from cst_mcp.vba_builder import VBABuilder, VBAScript

TOOLS: list[Tool] = [
    Tool(
        name="cst_workflow_patch_antenna",
        description=(
            "END-TO-END / Uçtan uca: size a rectangular microstrip patch, build "
            "substrate/ground/patch/feed, frequency, open BCs, waveguide port, farfield "
            "monitor. Does NOT run the solver. "
            "Simülasyon çalıştırmaz — next: cst_workflow_run_and_s11 or cst_run_simulation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {"type": "number", "description": "Center frequency (GHz) / Merkez frekans"},
                "epsilon_r": {"type": "number", "default": 4.4, "description": "Substrate εr"},
                "height_mm": {"type": "number", "default": 1.6, "description": "Substrate height (mm)"},
                "tan_delta": {"type": "number", "default": 0.02, "description": "Loss tangent"},
                "feed_type": {
                    "type": "string",
                    "enum": ["inset", "microstrip", "probe"],
                    "default": "inset",
                },
                "project_path": {
                    "type": "string",
                    "description": "Optional .cst path when creating a new project",
                },
                "create_project": {"type": "boolean", "default": True},
            },
            "required": ["frequency_ghz"],
        },
    ),
    Tool(
        name="cst_workflow_run_and_s11",
        description=(
            "Run solver and return structured S11/Sij with metrics (min dB, bandwidth). "
            "Solver çalıştırır ve S parametrelerini metriklerle döner."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port_out": {"type": "integer", "default": 1},
                "port_in": {"type": "integer", "default": 1},
                "timeout_s": {"type": "number", "default": 3600},
                "max_points": {"type": "integer", "default": 200},
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_design_patch_only",
        description=(
            "Calculate microstrip patch dimensions only (offline, no CST). "
            "Sadece boyut hesabı — CST gerekmez."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {"type": "number"},
                "epsilon_r": {"type": "number", "default": 4.4},
                "height_mm": {"type": "number", "default": 1.6},
                "tan_delta": {"type": "number", "default": 0.02},
                "feed_type": {
                    "type": "string",
                    "enum": ["inset", "microstrip", "probe"],
                    "default": "inset",
                },
            },
            "required": ["frequency_ghz"],
        },
    ),
    Tool(
        name="cst_export_structure_views",
        description=(
            "Export structure screenshots (perspective/xy/xz/yz) via Plot.ExportImage. "
            "Yapı görünüm görsellerini dışa aktarır. Connected mode required."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "out_dir": {
                    "type": "string",
                    "description": "Output folder (default: work_dir/exports/views)",
                },
                "width": {"type": "integer", "default": 1280},
                "height": {"type": "integer", "default": 720},
                "views": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Subset of: perspective, xy, xz, yz",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_workflow_design_report",
        description=(
            "ONE-SHOT design package after modeling/simulation: project status, "
            "parameters/dimensions, S-parameters (+metrics), best-effort farfield export, "
            "and structure view images. Each section fails soft — you still get partial results. "
            "Tasarım bittikten sonra boyutlar, S11, uzak alan ve görselleri tek çağrıda toplar."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "default": 1},
                "frequency_ghz": {
                    "type": "number",
                    "description": "Optional farfield monitor frequency hint",
                },
                "include_images": {"type": "boolean", "default": True},
                "include_sparams": {"type": "boolean", "default": True},
                "include_farfield": {"type": "boolean", "default": True},
                "include_parameters": {"type": "boolean", "default": True},
                "max_points": {"type": "integer", "default": 200},
                "out_dir": {
                    "type": "string",
                    "description": "Report folder (default under CST_WORK_DIR/exports/report_*)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_workflow_simulate_and_report",
        description=(
            "Run the solver, then immediately build a design report (S-params + views + "
            "optional farfield). Simülasyonu çalıştırıp rapor paketini üretir."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {"type": "integer", "default": 1},
                "frequency_ghz": {"type": "number"},
                "timeout_s": {"type": "number", "default": 3600},
                "include_images": {"type": "boolean", "default": True},
                "include_farfield": {"type": "boolean", "default": True},
                "max_points": {"type": "integer", "default": 200},
                "out_dir": {"type": "string"},
            },
            "required": [],
        },
    ),
    Tool(
        name="cst_discover_farfield_monitors",
        description=(
            "Discover farfield monitors from the project Result folder and tree-path "
            "heuristics. Uzak alan monitörlerini disk + path sezgisiyle listeler."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="cst_get_farfield_metrics",
        description=(
            "Read antenna metrics after a solve: S11 + radiation/total efficiency "
            "from 1D Results, plus max realized gain via official FarfieldPlot.GetMax "
            "(SelectTreeItem Farfields\\farfield (f=X) [1] → Plot → GetMax). "
            "Does NOT use ASCIIExportSummary (that API spams Message on CST 2026). "
            "Solve sonrası S11, verimlilik ve max gain; GUI farfield ile uyumlu."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design frequency in GHz (for nearest efficiency sample)",
                },
                "monitor_name": {
                    "type": "string",
                    "description": "Optional exact monitor label, e.g. farfield (f=2.4) [1]",
                },
                "try_farfield_plot": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "If true (default), also run FarfieldPlot.GetMax for peak "
                        "realized gain. Set false for 1D-only metrics."
                    ),
                },
            },
            "required": [],
        },
    ),
]


def _brick_expr(
    component: str,
    name: str,
    material: str,
    x0: str,
    x1: str,
    y0: str,
    y1: str,
    z0: str,
    z1: str,
) -> str:
    """Brick with CST parameter expressions (so Parameter List drives geometry)."""
    return "\n".join(
        [
            "With Brick",
            "  .Reset",
            f'  .Name "{name}"',
            f'  .Component "{component}"',
            f'  .Material "{material}"',
            f'  .Xrange "{x0}", "{x1}"',
            f'  .Yrange "{y0}", "{y1}"',
            f'  .Zrange "{z0}", "{z1}"',
            "  .Create",
            "End With",
        ]
    )


def _store_params_vba(params: dict[str, float]) -> str:
    lines = []
    for name, value in params.items():
        if isinstance(value, float):
            val = f"{value:.8g}"
        else:
            val = str(value)
        lines.append(f'StoreParameter "{name}", "{val}"')
    return "\n".join(lines)


def _patch_vba_steps(design) -> list[tuple[str, str]]:
    """Return ordered (history_label, vba) steps for a parametric patch antenna.

    Dimensions are stored in the CST Parameter List and geometry uses those
    names as expressions so the user can edit parameters + Rebuild later.
    """
    d = design
    w, l, h = d.width_mm, d.length_mm, d.height_mm
    gx, gy = d.ground_x_mm, d.ground_y_mm
    fw = d.feed_width_mm
    inset = d.inset_mm
    f0 = d.frequency_ghz
    fmin, fmax = f0 * 0.7, f0 * 1.3
    feed_y0, feed_y1 = feed_line_y_range(
        ground_y=gy, patch_length=l, inset=inset, feed_type=d.feed_type
    )
    mon = f"farfield (f={f0})"
    metal_t = 0.035

    # Numeric values go into Parameter List (what user edits in CST)
    design_params: dict[str, float] = {
        "freq_GHz": f0,
        "eps_r": d.epsilon_r,
        "tan_d": d.tan_delta,
        "sub_h": h,
        "patch_W": w,
        "patch_L": l,
        "gnd_x": gx,
        "gnd_y": gy,
        "feed_w": fw,
        "inset": inset if d.feed_type == "inset" else 0.0,
        "metal_t": metal_t,
        "fmin_GHz": fmin,
        "fmax_GHz": fmax,
    }

    steps: list[tuple[str, str]] = []

    steps.append(
        (
            "units",
            "\n".join(
                [
                    "With Units",
                    '  .SetUnit "Length", "mm"',
                    '  .SetUnit "Frequency", "GHz"',
                    '  .SetUnit "Time", "ns"',
                    "End With",
                ]
            ),
        )
    )

    # Parameter List first — visible in CST and usable in expressions
    steps.append(("store_parameters", _store_params_vba(design_params)))

    steps.append(
        (
            "material_substrate",
            (
                VBABuilder("Material")
                .call("Reset")
                .set("Name", "Substrate")
                .set("Type", "Normal")
                .set_triple("Colour", 0.2, 0.5, 0.2)
                .set("Wireframe", "False")
                .set_number("Transparency", 0.3)
                # Use parameter expressions where CST accepts them
                .set("Epsilon", "eps_r")
                .set_number("Mu", 1.0)
                .set_number("Rho", 0.0)
                .set_number("Sigma", 0.0)
                .set("TanD", "tan_d")
                .set_number("TanDFreq", 0.0)
                .set("TanDGiven", "True" if d.tan_delta > 0 else "False")
                .set("TanDModel", "ConstTanD")
                .call("Create")
                .build()
            ),
        )
    )

    # Parametric solids (edit Parameter List → Rebuild)
    steps.append(
        (
            "brick_ground",
            _brick_expr(
                "Antenna",
                "Ground",
                "PEC",
                "-gnd_x/2",
                "gnd_x/2",
                "-gnd_y/2",
                "gnd_y/2",
                "-metal_t",
                "0",
            ),
        )
    )
    steps.append(
        (
            "brick_substrate",
            _brick_expr(
                "Antenna",
                "Substrate",
                "Substrate",
                "-gnd_x/2",
                "gnd_x/2",
                "-gnd_y/2",
                "gnd_y/2",
                "0",
                "sub_h",
            ),
        )
    )
    steps.append(
        (
            "brick_patch",
            _brick_expr(
                "Antenna",
                "Patch",
                "PEC",
                "-patch_W/2",
                "patch_W/2",
                "-patch_L/2",
                "patch_L/2",
                "sub_h",
                "sub_h+metal_t",
            ),
        )
    )
    if d.feed_type in ("inset", "microstrip"):
        # Outer end = -gnd_y/2 (port plane); inner toward patch
        y_inner = (
            "-patch_L/2+inset" if d.feed_type == "inset" else "-patch_L/2"
        )
        steps.append(
            (
                "brick_feed",
                _brick_expr(
                    "Antenna",
                    "Feed",
                    "PEC",
                    "-feed_w/2",
                    "feed_w/2",
                    "-gnd_y/2",
                    y_inner,
                    "sub_h",
                    "sub_h+metal_t",
                ),
            )
        )

    # Use numeric frequency bounds in Solver/Monitor — NOT parameter names.
    # Result Navigator fails with: Unable to resolve "freq_GHz = 2.4" when
    # secondary results are tied to unresolved parametric expressions.
    steps.append(
        (
            "freq_range",
            "\n".join(
                [
                    "With Solver",
                    f'  .FrequencyRange "{fmt_num(fmin)}", "{fmt_num(fmax)}"',
                    "End With",
                ]
            ),
        )
    )
    steps.append(
        (
            "boundaries",
            "\n".join(
                [
                    'Boundary.Xmin "expanded open"',
                    'Boundary.Xmax "expanded open"',
                    'Boundary.Ymin "expanded open"',
                    'Boundary.Ymax "expanded open"',
                    'Boundary.Zmin "expanded open"',
                    'Boundary.Zmax "expanded open"',
                ]
            ),
        )
    )
    # Port still needs numeric edge for Free port plane (expressions less reliable)
    steps.append(
        (
            "port_wg_1",
            microstrip_waveguide_port_vba(
                port_number=1,
                y_edge=feed_y0,
                feed_width=fw,
                substrate_height=h,
                ground_bottom=-metal_t,
                metal_thickness=metal_t,
                x_center=0.0,
            ),
        )
    )
    steps.append(
        (
            "monitor_farfield",
            "\n".join(
                [
                    "With Monitor",
                    "  .Reset",
                    f'  .Name "{vba_str(mon)}"',
                    '  .Domain "Frequency"',
                    '  .FieldType "Farfield"',
                    # Numeric frequency (not "freq_GHz") avoids Result Navigator warnings
                    f'  .Frequency "{fmt_num(f0)}"',
                    '  .ExportFarfieldSource "False"',
                    # Keep nearfield so FarfieldPlot.GetMax works after mesh is freed
                    '  .EnableNearfieldCalculation "True"',
                    '  .UseSubvolume "False"',
                    "  .Create",
                    "End With",
                ]
            ),
        )
    )
    steps.append(("solver_type", 'ChangeSolverType "HF Time Domain"'))
    return steps


def _build_patch_model(design) -> str:
    """Full VBA as a single script (offline / debugging)."""
    return "\n\n".join(vba for _, vba in _patch_vba_steps(design))
async def handle(name: str, args: dict[str, Any], client: Any) -> list[TextContent]:
    try:
        if name == "cst_design_patch_only":
            d = design_patch(
                float(args["frequency_ghz"]),
                epsilon_r=float(args.get("epsilon_r") or 4.4),
                height_mm=float(args.get("height_mm") or 1.6),
                tan_delta=float(args.get("tan_delta") or 0.02),
                feed_type=str(args.get("feed_type") or "inset"),
            )
            return as_json({"design": d.to_dict()})

        if name == "cst_workflow_patch_antenna":
            d = design_patch(
                float(args["frequency_ghz"]),
                epsilon_r=float(args.get("epsilon_r") or 4.4),
                height_mm=float(args.get("height_mm") or 1.6),
                tan_delta=float(args.get("tan_delta") or 0.02),
                feed_type=str(args.get("feed_type") or "inset"),
            )
            steps: list[dict[str, Any]] = []
            if args.get("create_project", True):
                if not client.connected:
                    steps.append(client.connect())
                # Always start a fresh project when building a full antenna so
                # leftover solids from a previous run do not collide.
                if client.has_project:
                    steps.append(client.close_project())
                path = args.get("project_path") or str(
                    client.config.work_dir / f"patch_{d.frequency_ghz}GHz.cst"
                )
                steps.append(client.new_project(str(path), "MWS"))

            # Execute step-by-step so one bad Units line cannot kill geometry
            vba_steps = _patch_vba_steps(d)
            step_results: list[dict[str, Any]] = []
            fatal = False
            for label, vba in vba_steps:
                run = client.execute_vba(vba, history_label=label)
                entry = {"label": label, **run}
                # Drop huge vba from response except on error
                if entry.get("status") != "error":
                    entry.pop("vba", None)
                step_results.append(entry)
                # Geometry/material failures are fatal; units/params optional
                if run.get("status") == "error":
                    if label in {"units", "store_parameters"}:
                        entry["note"] = f"{label} failed (non-fatal); continuing."
                        continue
                    if label.startswith("brick_") or label.startswith("material_"):
                        fatal = True
                        break

            steps.extend(step_results)
            ok_geom = any(
                s.get("label", "").startswith("brick_") and s.get("status") == "executed"
                for s in step_results
            )
            status = "error" if fatal else (
                "executed" if ok_geom or any(s.get("status") == "executed" for s in step_results)
                else step_results[-1].get("status", "error") if step_results else "error"
            )
            params_now = client.list_parameters() if hasattr(client, "list_parameters") else {}
            return as_json(
                {
                    "status": status,
                    "design": d.to_dict(),
                    "parameters_in_project": params_now,
                    "parameter_hint": (
                        "Edit patch_W, patch_L, sub_h, feed_w, inset, gnd_x, gnd_y in "
                        "CST Parameter List, then Rebuild (or cst_param_sweep_solve)."
                    ),
                    "steps": steps,
                    "vba": _build_patch_model(d) if status == "offline" else None,
                    "next": "Call cst_workflow_simulate_and_report or cst_run_simulation.",
                }
            )

        if name == "cst_workflow_run_and_s11":
            solve = client.run_solver(timeout_s=float(args.get("timeout_s") or 3600))
            if solve.get("status") not in {"executed", "ok"}:
                return as_json(solve)
            sparams = client.get_s_parameters(
                port_out=int(args.get("port_out") or 1),
                port_in=int(args.get("port_in") or 1),
                max_points=int(args.get("max_points") or 200),
            )
            return as_json({"status": "ok", "solver": solve, "s_parameters": sparams})

        if name == "cst_export_structure_views":
            return as_json(
                client.export_plot_images(
                    args.get("out_dir"),
                    width=int(args.get("width") or 1280),
                    height=int(args.get("height") or 720),
                    views=args.get("views"),
                )
            )

        if name == "cst_workflow_design_report":
            return as_json(
                client.design_report(
                    port=int(args.get("port") or 1),
                    frequency_ghz=(
                        float(args["frequency_ghz"])
                        if args.get("frequency_ghz") is not None
                        else None
                    ),
                    include_images=bool(args.get("include_images", True)),
                    include_sparams=bool(args.get("include_sparams", True)),
                    include_farfield=bool(args.get("include_farfield", True)),
                    include_parameters=bool(args.get("include_parameters", True)),
                    max_points=int(args.get("max_points") or 200),
                    out_dir=args.get("out_dir"),
                )
            )

        if name == "cst_workflow_simulate_and_report":
            solve = client.run_solver(timeout_s=float(args.get("timeout_s") or 3600))
            report = client.design_report(
                port=int(args.get("port") or 1),
                frequency_ghz=(
                    float(args["frequency_ghz"])
                    if args.get("frequency_ghz") is not None
                    else None
                ),
                include_images=bool(args.get("include_images", True)),
                include_sparams=True,
                include_farfield=bool(args.get("include_farfield", True)),
                include_parameters=True,
                max_points=int(args.get("max_points") or 200),
                out_dir=args.get("out_dir"),
            )
            return as_json({"status": "ok", "solver": solve, "report": report})

        if name == "cst_discover_farfield_monitors":
            return as_json(client.discover_farfield_monitors())

        if name == "cst_get_farfield_metrics":
            return as_json(
                client.get_farfield_metrics(
                    frequency_ghz=(
                        float(args["frequency_ghz"])
                        if args.get("frequency_ghz") is not None
                        else None
                    ),
                    monitor_name=args.get("monitor_name"),
                    try_farfield_plot=bool(
                        True if args.get("try_farfield_plot") is None else args.get("try_farfield_plot")
                    ),
                )
            )

        return err(f"Unknown workflow tool: {name}")
    except Exception as exc:  # noqa: BLE001
        return err(str(exc))
