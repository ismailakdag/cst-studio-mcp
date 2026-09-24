"""Publication-quality figures for 3D/farfield CST results (patterns, cuts, gain)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp.types import Tool

from cst_mcp.tools.registry import as_json, err, ok

_PLOTS = ("polar", "rect", "heatmap", "3d")
_QUANTITIES = ("realized_gain", "gain", "directivity")

TOOLS: list[Tool] = [
    Tool(
        name="cst_plot_farfield",
        description=(
            "Publication-quality farfield figures (IEEE sizes, serif, grayscale-safe): polar dB cuts "
            "(E/H-plane, co/cross-pol when Ludwig-3/spherical components exist, -3 dB beamwidth marks), "
            "rectangular cuts, theta-phi or u-v heatmap, optional 3D gain surface; plus metrics (max "
            "gain + direction, HPBW per cut, front-to-back, side-lobe level). Data source: data_file "
            "(a CST farfield ASCII export, works offline) or, when connected, the open project's "
            "Farfields\\farfield (f=X) [1] item exported via FarfieldPlot + ASCIIExport. Never solves: "
            "returns status no_results with monitor info and next steps when no farfield exists."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "data_file": {
                    "type": "string",
                    "description": "Existing CST farfield ASCII export (.txt/.csv: Theta Phi Abs(...) ...). "
                    "Preferred source; no CST connection needed.",
                },
                "project_path": {
                    "type": "string",
                    "description": "Project (.cst) to use in connected mode; opened if it is not the current one.",
                },
                "farfield_name": {
                    "type": "string",
                    "description": "Farfield result/monitor name, e.g. 'farfield (f=2.4)' or "
                    "'Farfields\\farfield (f=2.4) [1]'.",
                },
                "frequency_ghz": {"type": "number", "exclusiveMinimum": 0,
                                  "description": "Selects farfield (f=X) when farfield_name is omitted."},
                "quantity": {"type": "string", "enum": list(_QUANTITIES), "default": "realized_gain",
                             "description": "Plotted quantity for CST export (dBi)."},
                "polarization_basis": {"type": "string", "enum": ["ludwig3", "spherical"], "default": "ludwig3",
                                       "description": "Component basis requested from CST for co/cross-pol."},
                "step_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 30, "default": 5,
                             "description": "Spherical grid step for CST export (divisor of 180)."},
                "cuts": {
                    "type": "array",
                    "items": {"type": ["number", "string"]},
                    "maxItems": 8,
                    "default": [0, 90],
                    "description": "Cuts: numbers = constant phi (deg), or strings 'phi=45', 'theta=90', "
                    "'E-plane' (phi=0), 'H-plane' (phi=90).",
                },
                "plots": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_PLOTS)},
                    "uniqueItems": True,
                    "default": ["polar", "rect", "heatmap"],
                },
                "heatmap_projection": {"type": "string", "enum": ["theta_phi", "uv"], "default": "theta_phi"},
                "dynamic_range_db": {"type": "number", "minimum": 5, "maximum": 120, "default": 30,
                                     "description": "Plot range below the maximum (dB)."},
                "formats": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["pdf", "svg", "png", "eps"]},
                    "uniqueItems": True,
                    "default": ["pdf", "png"],
                },
                "width": {
                    "type": ["string", "number"],
                    "description": "'single' (3.5 in, default), 'double' (7.16 in) or inches.",
                },
                "out_dir": {"type": "string", "description": "Output folder (default <CST_WORK_DIR>/figures/farfield)."},
                "file_stem": {"type": "string", "description": "Base name for output files."},
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="cst_plot_surface_current",
        description=(
            "Top-view surface-current |J| map(s) in dB with matplotlib (shared scale across panels "
            "optional, maximum marked) plus metrics (max A/m and location, integral of |J| dA). Data: "
            "data_files (CST ASCIIExport of '2D/3D Results\\Surface Current\\surface current (f=X) [1]': "
            "x y z KxRe KxIm KyRe KyIm KzRe KzIm Area), or, when connected, the open project's item is "
            "exported via ASCIIExport. Needed because Plot.ExportImage in a quiet Design Environment "
            "returns only the geometry. Surface current requires an Hfield monitor (CST 2026 has no "
            "'Surfacecurrent' type). Top/bottom faces of a copper sheet are summed as complex vectors "
            "per cell (total sheet current). Never solves."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "data_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 8,
                    "description": "Existing surface-current ASCIIExport files (one panel each; offline).",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 8,
                    "description": "Panel labels (default: file stems / tree item).",
                },
                "project_path": {
                    "type": "string",
                    "description": "Connected mode: project to open if it is not the current one.",
                },
                "frequency_ghz": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "Connected mode: selects 'surface current (f=X) [1]'.",
                },
                "tree_path": {"type": "string", "description": "Connected mode: exact surface-current tree item."},
                "export_step": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": 0.25,
                    "description": "ASCIIExport FixedWidth step (model units).",
                },
                "subvolume": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 6,
                    "maxItems": 6,
                    "description": "Optional ASCIIExport subvolume [xmin, xmax, ymin, ymax, zmin, zmax].",
                },
                "cell": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": 0.4,
                    "description": "Top-view binning cell size (model units).",
                },
                "z_range": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Keep samples with z in [zmin, zmax] (e.g. the copper layer).",
                },
                "extent": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "[xmin, xmax, ymin, ymax] of the map (default: data bounds).",
                },
                "layer_split_z": {
                    "type": "number",
                    "description": "z separating the two face layers summed per cell (default: midpoint "
                    "of the selected z span).",
                },
                "include_kz": {"type": "boolean", "default": False},
                "shared_scale": {
                    "type": "boolean",
                    "default": True,
                    "description": "One dB reference (largest cell over all panels).",
                },
                "dynamic_range_db": {"type": "number", "minimum": 5, "maximum": 120, "default": 40},
                "formats": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["pdf", "svg", "png", "eps"]},
                    "uniqueItems": True,
                    "default": ["png"],
                },
                "title": {"type": "string"},
                "out_dir": {
                    "type": "string",
                    "description": "Output folder (default <CST_WORK_DIR>/figures/surface_current).",
                },
                "file_stem": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
    ),
]


def _schema(tool: Tool) -> dict[str, Any]:
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema")


def _stem(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._=-]+", "_", text).strip("_")[:80] or "farfield"


def render(
    data_path: str | Path,
    *,
    out_dir: Path,
    cuts: list[Any] | None = None,
    plots: list[str] | None = None,
    dynamic_range_db: float = 30.0,
    formats: list[str] | None = None,
    width: Any = None,
    heatmap_projection: str = "theta_phi",
    stem: str | None = None,
    quantity_hint: str | None = None,
) -> dict[str, Any]:
    """Parse a farfield ASCII file and write figures; returns files + metrics."""
    from cst_mcp.execution import figures_3d_plot as fp
    from cst_mcp.execution.figures_3d_data import extract_cut, parse_cut_spec, parse_farfield_ascii, pattern_metrics

    grid = parse_farfield_ascii(data_path, quantity_hint=quantity_hint)
    specs = [parse_cut_spec(c) for c in (cuts if cuts else [0, 90])]
    cut_objs = [extract_cut(grid, k, v) for k, v in specs]
    metrics = pattern_metrics(grid, cut_objs)
    w = fp.figure_width(width)
    fmts = list(formats or ["pdf", "png"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _stem(stem or Path(data_path).stem)
    files: list[str] = []
    for plot in plots or ["polar", "rect", "heatmap"]:
        if plot == "polar":
            files += fp.plot_polar(grid, cut_objs, out_dir, stem, dynamic_range_db=dynamic_range_db,
                                   width=fp.figure_width("double") if width is None and len(cut_objs) > 1 else w,
                                   formats=fmts)
        elif plot == "rect":
            files += fp.plot_rect(grid, cut_objs, out_dir, stem, dynamic_range_db=dynamic_range_db, width=w,
                                  formats=fmts)
        elif plot == "heatmap":
            files += fp.plot_heatmap(grid, out_dir, stem, dynamic_range_db=dynamic_range_db, width=w,
                                     formats=fmts, projection=heatmap_projection)
        elif plot == "3d":
            files += fp.plot_3d(grid, out_dir, stem, dynamic_range_db=dynamic_range_db, width=w, formats=fmts)
        else:
            raise ValueError(f"Unknown plot type {plot!r}; use {list(_PLOTS)}")
    parse_info = {
        "column": grid.column,
        "columns": grid.columns,
        "rows": grid.n_rows,
        "input_scale": grid.scale_input,
        "header_found": grid.header_found,
        "components": sorted(grid.components_db),
    }
    return {"files": files, "metrics": metrics, "parse": parse_info}


def _validate(args: dict[str, Any]) -> str | None:
    allowed = set(_schema(TOOLS[0])["properties"])
    extra = sorted(set(args) - allowed)
    if extra:
        return f"Unknown argument(s): {', '.join(extra)}"
    q = args.get("quantity", "realized_gain")
    if q not in _QUANTITIES:
        return f"quantity must be one of {list(_QUANTITIES)}"
    for p in args.get("plots") or []:
        if p not in _PLOTS:
            return f"plots entries must be in {list(_PLOTS)}"
    for f in args.get("formats") or []:
        if f not in ("pdf", "svg", "png", "eps"):
            return "formats entries must be pdf, svg, png or eps"
    dr = float(args.get("dynamic_range_db", 30))
    if not 5 <= dr <= 120:
        return "dynamic_range_db must be in [5, 120]"
    step = float(args.get("step_deg", 5))
    if not 0 < step <= 30 or abs(180 / step - round(180 / step)) > 1e-6:
        return "step_deg must divide 180 and be in (0, 30]"
    return None


async def _handle_surface_current(args: dict[str, Any], client: Any):
    allowed = set(_schema(TOOLS[1])["properties"])
    extra = sorted(set(args) - allowed)
    if extra:
        return err(f"Unknown argument(s): {', '.join(extra)}")
    for f in args.get("formats") or []:
        if f not in ("pdf", "svg", "png", "eps"):
            return err("formats entries must be pdf, svg, png or eps")
    try:
        from cst_mcp.execution.academic_style import require_matplotlib

        require_matplotlib()
    except ImportError as exc:
        return err(str(exc))
    from cst_mcp.execution.surface_current import grid_top_view, parse_surface_current_ascii, render_maps

    work_dir = Path(getattr(getattr(client, "config", None), "work_dir", None) or Path.cwd())
    out_dir = (Path(args["out_dir"]).expanduser() if args.get("out_dir")
               else work_dir / "figures" / "surface_current")
    sources: list[dict[str, Any]] = []
    files = [Path(f).expanduser() for f in args.get("data_files") or []]
    if files:
        missing = [str(f) for f in files if not f.is_file()]
        if missing:
            return err(f"data_files not found: {missing}")
        sources = [{"kind": "data_file", "path": str(f)} for f in files]
    else:
        if not getattr(client, "is_connected", False):
            return err("Not connected to CST. Pass data_files (surface-current ASCIIExport files) to render "
                       "offline, or connect (cst_connect) and open the solved project.")
        project_path = args.get("project_path")
        if project_path:
            current = getattr(client, "project_path", None)
            same = current and Path(current).resolve() == Path(project_path).expanduser().resolve()
            if not same or not client.has_project:
                opened = client.open_project(project_path)
                if opened.get("status") not in ("opened", "ok"):
                    return err(f"Could not open project: {opened.get('message')}", open_result=opened)
        if not client.has_project:
            return err("No project open. Pass project_path or data_files.")
        from cst_mcp.execution.surface_current import acquire as _sc_acquire

        acq = _sc_acquire(client, args, work_dir)
        if acq.get("status") != "ok":
            if acq.get("status") == "error":
                return err(acq.get("message", "export failed"),
                           **{k: v for k, v in acq.items() if k not in ("status", "message")})
            return as_json(acq)
        files = [Path(acq["path"])]
        sources = [{"kind": "cst_export", "path": acq["path"], "tree_path": acq["tree_path"],
                    "method": "ASCIIExport"}]
    labels = list(args.get("labels") or [])
    grids = []
    unit = "mm"
    for i, f in enumerate(files):
        samples = parse_surface_current_ascii(f)
        unit = samples.length_unit or unit
        g = grid_top_view(
            samples,
            cell=float(args.get("cell", 0.4)),
            extent=tuple(args["extent"]) if args.get("extent") else None,
            z_range=tuple(args["z_range"]) if args.get("z_range") else None,
            layer_split_z=args.get("layer_split_z"),
            include_kz=bool(args.get("include_kz", False)),
        )
        label = labels[i] if i < len(labels) else (
            sources[i].get("tree_path", "").split(chr(92))[-1] or f.stem)
        grids.append((label, g))
    stem = _stem(args.get("file_stem") or ("surface_current_" + "_".join(_stem(lb) for lb, _ in grids))[:80])
    out = render_maps(grids, out_dir, stem=stem, shared_scale=bool(args.get("shared_scale", True)),
                      dynamic_range_db=float(args.get("dynamic_range_db", 40)), formats=args.get("formats"),
                      title=args.get("title"), length_unit=unit)
    return ok(**out, sources=sources, note=(
        "|J| per cell = |sum over face layers of the area-weighted mean K phasor| (peak phasor A/m for the "
        "solver's excitation). 0 dB = scale_ref_A_per_m."))


async def handle(name, arguments, client):
    if name == "cst_plot_surface_current":
        try:
            return await _handle_surface_current(dict(arguments or {}), client)
        except ValueError as exc:
            return err(str(exc))
        except Exception as exc:  # noqa: BLE001
            return err(f"cst_plot_surface_current failed: {exc}")
    if name != "cst_plot_farfield":
        return err(f"Unknown tool: {name}")
    args = dict(arguments or {})
    problem = _validate(args)
    if problem:
        return err(problem)
    try:
        from cst_mcp.execution.academic_style import require_matplotlib

        require_matplotlib()
    except ImportError as exc:
        return err(str(exc))

    quantity = args.get("quantity", "realized_gain")
    work_dir = Path(getattr(getattr(client, "config", None), "work_dir", None) or Path.cwd())
    out_dir = Path(args["out_dir"]).expanduser() if args.get("out_dir") else work_dir / "figures" / "farfield"
    render_kw = dict(
        out_dir=out_dir,
        cuts=args.get("cuts"),
        plots=args.get("plots"),
        dynamic_range_db=float(args.get("dynamic_range_db", 30)),
        formats=args.get("formats"),
        width=args.get("width"),
        heatmap_projection=args.get("heatmap_projection", "theta_phi"),
        stem=args.get("file_stem"),
    )

    try:
        if args.get("data_file"):
            data = Path(args["data_file"]).expanduser()
            if not data.is_file():
                return err(f"data_file not found: {data}")
            out = render(data, **render_kw)
            return ok(**out, source={"kind": "data_file", "path": str(data)})

        from cst_mcp.execution import figures_3d_cst as fc

        project_path = args.get("project_path")
        connected = bool(getattr(client, "is_connected", False))
        if not connected:
            from cst_mcp.execution.farfield import discover_farfield_from_project_dir

            disk = discover_farfield_from_project_dir(project_path) if project_path else []
            if project_path and not disk:
                return as_json({
                    "status": "no_results",
                    "message": "No farfield results on disk for this project. Add a farfield monitor "
                    "(cst_add_farfield_monitor), run cst_run_simulation_async + cst_wait_for_simulation, then "
                    "retry connected; or pass data_file.",
                    "disk_results": [],
                })
            return err(
                "Not connected to CST. Pass data_file (a CST farfield ASCII export) to render offline, "
                "or connect (cst_connect) and open the project.",
                disk_results=disk,
            )
        if project_path:
            current = getattr(client, "project_path", None)
            same = current and Path(current).resolve() == Path(project_path).expanduser().resolve()
            if not same or not client.has_project:
                opened = client.open_project(project_path)
                if opened.get("status") not in ("opened", "ok"):
                    return err(f"Could not open project: {opened.get('message')}", open_result=opened)
        if not client.has_project:
            return err("No project open. Pass project_path or data_file.")

        freq = float(args["frequency_ghz"]) if args.get("frequency_ghz") is not None else None
        acq = fc.acquire(
            client,
            farfield_name=args.get("farfield_name"),
            frequency_ghz=freq,
            quantity=quantity,
            step_deg=float(args.get("step_deg", 5)),
            basis=args.get("polarization_basis", "ludwig3"),
            export_dir=work_dir / "exports" / "farfield",
        )
        if acq.get("status") != "ok":
            if acq.get("status") == "error":
                return err(acq.get("message", "farfield export failed"), **{k: v for k, v in acq.items()
                                                                             if k not in ("status", "message")})
            return as_json(acq)
        if not render_kw["stem"]:
            render_kw["stem"] = _stem(f"{acq['tree_path'].split(chr(92))[-1]}_{quantity}")
        out = render(acq["path"], quantity_hint=quantity, **render_kw)
        return ok(**out, source={
            "kind": "cst_export",
            "path": acq["path"],
            "tree_path": acq["tree_path"],
            "method": acq["method"],
            "project_path": getattr(client, "project_path", None),
        })
    except ValueError as exc:
        return err(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err(f"cst_plot_farfield failed: {exc}")


from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
