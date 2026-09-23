"""Publication-quality figures for 1D CST results (S-parameters, VSWR, impedance, efficiency)."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from mcp.types import Tool

from cst_mcp.execution import figures_1d_source as source
from cst_mcp.execution.academic_style import SUPPORTED_FORMATS
from cst_mcp.execution.figures_1d_metrics import (
    bandwidth_metrics,
    crop,
    parse_overlay_csv,
    run_labels,
    to_db,
)
from cst_mcp.tools.registry import as_json, err

QUANTITIES = ("s11_db", "s_params_db", "vswr", "smith", "impedance", "phase", "efficiency")
REFLECTION_QUANTITIES = {"s11_db", "vswr", "smith", "impedance", "phase"}
MAX_CURVES = 12

_BAND = {
    "type": "object",
    "properties": {
        "f_low": {"type": "number"},
        "f_high": {"type": "number"},
        "bw_mhz": {"type": "number"},
        "fbw_pct": {"type": ["number", "null"]},
    },
    "required": ["f_low", "f_high", "bw_mhz", "fbw_pct"],
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok", "no_results", "busy"]},
        "message": {"type": "string"},
        "files": {"type": "array", "items": {"type": "string"}},
        "figures": {"type": "array", "items": {"type": "object"}},
        "metrics": {
            "type": ["object", "null"],
            "properties": {
                "f_res_ghz": {"type": ["number", "null"]},
                "s11_min_db": {"type": ["number", "null"]},
                "bands": {"type": "array", "items": _BAND},
            },
        },
        "source": {"type": "object"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "available_tree_items": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status"],
}

TOOLS: list[Tool] = [
    Tool(
        name="cst_plot_1d_results",
        description=(
            "Publication-quality (IEEE column, serif, PDF/SVG/PNG) figures of 1D results read "
            "offline from a saved .cst via cst.results (no GUI, no solving): |S11| dB with "
            "threshold line, resonance marker and every -10 dB band (BW, fractional BW), all "
            "S-parameters, VSWR, Smith chart, input impedance (Z0 from port reference impedance, "
            "else 50 ohm), S11 phase, efficiencies; parameter-sweep runs overlaid; optional "
            "measured CSV overlays. Returns status 'no_results' plus the available tree items "
            "when the project has not been simulated; it never starts the solver."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Saved .cst file. Omit to use the currently open project (connected mode).",
                },
                "quantities": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(QUANTITIES)},
                    "minItems": 1,
                    "uniqueItems": True,
                    "default": ["s11_db"],
                },
                "tree_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "maxItems": 12,
                    "description": "Extra exact 1D tree paths plotted as custom figures (see cst_list_saved_results).",
                },
                "run_ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "maxItems": MAX_CURVES,
                    "description": "Runs to compare. Default: newest max_runs parametric runs (run 0 only if it is the sole run).",
                },
                "max_runs": {"type": "integer", "minimum": 1, "maximum": MAX_CURVES, "default": 6},
                "freq_range_ghz": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "threshold_db": {"type": "number", "exclusiveMaximum": 0, "default": -10},
                "mark_resonance": {"type": "boolean", "default": True},
                "formats": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(SUPPORTED_FORMATS)},
                    "minItems": 1,
                    "uniqueItems": True,
                    "default": ["pdf", "png"],
                },
                "width": {"type": "string", "enum": ["single", "double"], "default": "single"},
                "out_dir": {
                    "type": "string",
                    "description": "Output directory. Default: <project folder>/<project name>_figures.",
                },
                "title": {"type": "string"},
                "legend_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "One legend label per plotted run, in run order.",
                },
                "csv_overlays": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {
                        "anyOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "label": {"type": "string"},
                                    "freq_unit": {
                                        "type": "string",
                                        "enum": ["Hz", "kHz", "MHz", "GHz", "THz"],
                                    },
                                },
                                "required": ["path"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                    "description": "Measured freq,dB CSV files overlaid on the |S11| figure (label default 'Measured').",
                },
                "simulate_if_missing": {
                    "type": "boolean",
                    "default": False,
                    "description": "When no results exist, return next_steps for cst_run_simulation_async + cst_wait_for_simulation (connected mode). Never solves here.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        outputSchema=OUTPUT_SCHEMA,
    )
]


def _clean(obj: Any) -> Any:
    """Strict JSON: NaN/inf -> None."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:60] or "curve"


def _crop_series(s: dict, freq_range) -> dict:
    if not freq_range:
        return s
    z0 = s.get("z0")
    if isinstance(z0, list):
        f, v, z = crop(s["f"], s["values"], z0, freq_range=freq_range)
    else:
        f, v = crop(s["f"], s["values"], freq_range=freq_range)
        z = z0
    out = dict(s, f=f, values=v, z0=z)
    if len(f) < 2:
        raise ValueError(
            f"freq_range_ghz {list(freq_range)} leaves fewer than two samples of {s['tree_path']}"
        )
    return out


def _resolve_project(arguments: dict, client) -> tuple[Path | None, bool, str | None]:
    raw = arguments.get("project_path")
    connected = bool(getattr(client, "connected", False))
    current = getattr(client, "project_path", None)
    if not raw:
        if connected and current:
            raw = current
        else:
            return None, False, "project_path is required unless a project is open in connected mode"
    path = Path(raw).expanduser().resolve()
    if path.suffix.lower() != ".cst":
        return None, False, f"project_path must be a .cst file: {path}"
    if not path.is_file():
        return None, False, f"Project file not found: {path}"
    same = bool(connected and current and Path(current).resolve() == path)
    return path, same, None


def _no_results(path: Path, items: list[str], message: str, arguments: dict, client) -> list:
    payload: dict[str, Any] = {
        "status": "no_results",
        "message": message,
        "source": {"project": str(path), "reader": "cst.results"},
        "available_tree_items": items[:200],
        "files": [],
    }
    if arguments.get("simulate_if_missing"):
        if getattr(client, "connected", False):
            payload["next_steps"] = [
                "cst_run_simulation_async (starts the solver without blocking)",
                "cst_wait_for_simulation (repeat until finished; then save the project)",
                "cst_plot_1d_results again with the same arguments",
            ]
        else:
            payload["next_steps"] = [
                "cst_connect and cst_open_project for this file (connected mode is required to solve)",
                "cst_run_simulation_async, then cst_wait_for_simulation until finished",
                "cst_plot_1d_results again with the same arguments",
            ]
    return as_json(payload)


async def handle(name, arguments, client):
    if name != "cst_plot_1d_results":
        return err(f"Unknown tool: {name}")
    try:
        return _plot(arguments or {}, client)
    except ImportError as exc:
        return err(str(exc))


def _plot(arguments: dict, client):
    from cst_mcp.execution import figures_1d_plot as fp

    config = getattr(client, "config", None)
    if config is not None and getattr(config, "connect_mode", None) == "disabled":
        return err("CST access is disabled; use manual mode for saved-result reading")
    path, same_as_open, problem = _resolve_project(arguments, client)
    if problem:
        return err(problem)
    if same_as_open:
        running = client.is_solver_running(timeout_s=5)
        if running is not False:
            return as_json({
                "status": "busy",
                "message": "Solver is running or its state is unknown; wait with cst_wait_for_simulation",
                "running": running,
            })

    quantities = list(dict.fromkeys(arguments.get("quantities") or ["s11_db"]))
    bad = [q for q in quantities if q not in QUANTITIES]
    if bad:
        return err(f"Unknown quantities {bad}; choose from {list(QUANTITIES)}")
    formats = [f.lower() for f in (arguments.get("formats") or ["pdf", "png"])]
    bad = [f for f in formats if f not in SUPPORTED_FORMATS]
    if bad:
        return err(f"Unsupported formats {bad}; choose from {list(SUPPORTED_FORMATS)}")
    width = arguments.get("width", "single")
    if width not in {"single", "double"}:
        return err("width must be 'single' or 'double'")
    threshold = float(arguments.get("threshold_db", -10))
    if not math.isfinite(threshold) or threshold >= 0:
        return err("threshold_db must be finite and negative")
    freq_range = arguments.get("freq_range_ghz")
    if freq_range is not None:
        if len(freq_range) != 2 or not float(freq_range[1]) > float(freq_range[0]):
            return err("freq_range_ghz must be [fmin, fmax] with fmax > fmin")
    mark = bool(arguments.get("mark_resonance", True))
    title = arguments.get("title") or None
    max_runs = int(arguments.get("max_runs", 6))

    overlays = []
    for entry in arguments.get("csv_overlays") or []:
        spec = {"path": entry} if isinstance(entry, str) else dict(entry)
        try:
            ov = parse_overlay_csv(spec["path"], spec.get("freq_unit"))
        except (OSError, ValueError) as exc:
            return err(f"csv_overlays: {exc}")
        ov["label"] = spec.get("label") or ("Measured" if len(arguments["csv_overlays"]) == 1
                                             else f"Measured ({Path(spec['path']).stem})")
        if freq_range:
            ov["f_ghz"], ov["db"] = crop(ov["f_ghz"], ov["db"], freq_range=freq_range)
        overlays.append(ov)

    try:
        reader = source.open_reader(str(path), allow_interactive=same_as_open)
        items = reader.tree_items()
    except Exception as exc:
        return err(
            f"Cannot read saved results from {path}: {exc}",
            hint="Use a saved, unpacked project (.cst plus its same-name folder) that is not being solved.",
        )

    one_d = [p for p in items if p.startswith("1D Results\\")]
    refl = source.reflection_path(items)
    needed: dict[str, list[str]] = {}
    warnings: list[str] = []
    for q in quantities:
        if q in REFLECTION_QUANTITIES:
            if refl:
                needed[q] = [refl]
            else:
                warnings.append(f"{q}: no reflection S-parameter (Sii) in saved results")
        elif q == "s_params_db":
            sp = source.s_param_paths(items)
            if sp:
                needed[q] = sp
            else:
                warnings.append("s_params_db: no S-parameter results")
        elif q == "efficiency":
            eff = source.efficiency_paths(items)
            if eff:
                needed[q] = eff
            else:
                warnings.append("efficiency: no efficiency results (needs a farfield monitor)")
    custom = list(dict.fromkeys(arguments.get("tree_paths") or []))
    missing_custom = [p for p in custom if p not in items]
    if missing_custom:
        return err(
            f"tree_paths not found in saved results: {missing_custom}",
            available_tree_items=one_d[:200],
        )
    if not needed and not custom:
        msg = ("Project has no saved 1D results for the requested quantities; it has not been "
               "simulated (or results were deleted/not saved).") if not one_d else (
               "Saved results exist but none match the requested quantities: " + "; ".join(warnings))
        return _no_results(path, items, msg, arguments, client)

    # Run selection is driven by the primary curve (reflection if present).
    primary_path = refl or next(iter(needed.values()), custom)[0]
    try:
        runs = source.select_runs(reader.run_ids(primary_path), arguments.get("run_ids"), max_runs)
    except ValueError as exc:
        return err(str(exc))
    if not runs:
        return _no_results(path, items, f"No result runs stored for {primary_path}", arguments, client)
    labels = run_labels({r: reader.parameter_combination(r) for r in runs}) if len(runs) > 1 else {}
    custom_labels = arguments.get("legend_labels") or []
    if custom_labels and len(custom_labels) != len(runs):
        return err(f"legend_labels has {len(custom_labels)} entries but {len(runs)} runs are plotted: {runs}")
    for j, r in enumerate(runs):
        if custom_labels:
            labels[r] = custom_labels[j]
        elif len(runs) == 1:
            labels[r] = "Simulated" if overlays else ""

    cache: dict[tuple[str, int], dict] = {}
    z0_sources: set[str] = set()

    def series(tree: str, run: int, label: str) -> dict:
        key = (tree, run)
        if key not in cache:
            raw = reader.read(tree, run)
            s = source.to_series(raw, label, run, tree)
            if tree == refl:
                if s["z0"] is None:
                    zpath = source.ref_impedance_path(items)
                    if zpath:
                        try:
                            zr = reader.read(zpath, run)
                            if len(zr["values"]) == len(s["values"]):
                                s["z0"] = list(zr["values"])
                                z0_sources.add(zpath)
                        except Exception:
                            pass
                else:
                    z0_sources.add("port reference impedance (get_ref_imp_data)")
                if s["z0"] is None:
                    s["z0"] = 50.0
                    z0_sources.add("assumed 50 ohm")
            cache[key] = _crop_series(s, freq_range) if s["is_frequency"] else s
        return dict(cache[key], label=label)

    stem = _slug(path.stem)
    out_dir = Path(arguments.get("out_dir") or path.parent / f"{path.stem}_figures").expanduser()
    files: list[str] = []
    figures: list[dict] = []
    metrics: dict[str, Any] | None = None

    def emit(q: str, fig, trees: list[str]):
        paths = fp.save_figure(fig, out_dir, f"{stem}_{q}", formats)
        files.extend(paths)
        figures.append({"quantity": q, "files": paths, "tree_paths": trees})

    try:
        refl_series = []
        if refl and any(q in needed for q in REFLECTION_QUANTITIES):
            refl_series = [series(refl, r, labels.get(r, f"Run {r}")) for r in runs]
            per_run = []
            for s in refl_series:
                m = bandwidth_metrics(s["f"], to_db(s["values"]), threshold)
                m.update(run_id=s["run_id"], label=s["label"])
                per_run.append(m)
            primary = per_run[-1]
            metrics = {
                "f_res_ghz": primary["f_res_ghz"],
                "s11_min_db": primary["s11_min_db"],
                "bands": primary["bands"],
                "matched": primary["matched"],
                "threshold_db": threshold,
                "total_bw_mhz": primary["total_bw_mhz"],
                "primary_run_id": primary["run_id"],
                "fbw_definition": primary["fbw_definition"],
                "per_run": [
                    {k: m[k] for k in ("run_id", "label", "f_res_ghz", "s11_min_db", "bands", "matched")}
                    for m in per_run
                ] if len(per_run) > 1 else [],
                "z0_ohm_source": sorted(z0_sources),
            }
            z0 = refl_series[-1]["z0"]
            zs = [complex(v).real for v in z0] if isinstance(z0, list) else [float(z0)]
            metrics["z0_ohm"] = sum(zs) / len(zs)
        refl_label = source.s_param_latex(refl) if refl else ""
        for q in quantities:
            if q not in needed:
                continue
            if q == "s11_db":
                fig = fp.plot_s11_db(
                    refl_series, overlays=overlays, metrics=metrics, threshold_db=threshold,
                    mark_resonance=mark, width=width, title=title,
                    ylabel=f"{refl_label} (dB)",
                )
            elif q == "vswr":
                fig = fp.plot_vswr(refl_series, threshold_db=threshold, width=width, title=title)
            elif q == "smith":
                fig = fp.plot_smith(refl_series, width=width, title=title, metrics=metrics,
                                    mark_resonance=mark)
            elif q == "impedance":
                fig = fp.plot_impedance(refl_series, width=width, title=title, metrics=metrics,
                                        mark_resonance=mark)
            elif q == "phase":
                fig = fp.plot_phase(refl_series, width=width, title=title,
                                    ylabel=refl_label.replace("|", "").replace("$S", r"$\angle S")
                                    + " (deg)")
            elif q == "s_params_db":
                curves = []
                for tree in needed[q]:
                    for r in runs:
                        lab = source.s_param_latex(tree)
                        if len(runs) > 1:
                            lab = f"{lab}, {labels.get(r, f'Run {r}')}"
                        curves.append(series(tree, r, lab))
                if len(curves) > MAX_CURVES:
                    warnings.append(f"s_params_db: plotted first {MAX_CURVES} of {len(curves)} curves")
                    curves = curves[:MAX_CURVES]
                fig = fp.plot_db_family(curves, width=width, title=title,
                                        ylabel="S-parameters (dB)", threshold_db=threshold)
            elif q == "efficiency":
                curves = []
                for tree in needed[q]:
                    for r in runs:
                        lab = tree.rsplit("\\", 1)[-1].replace(" [1]", "")
                        lab = lab.replace("Rad.", "Radiation").replace("Tot.", "Total")
                        if len(runs) > 1:
                            lab = f"{lab}, {labels.get(r, f'Run {r}')}"
                        curves.append(series(tree, r, lab))
                fig = fp.plot_efficiency(curves[:MAX_CURVES], width=width, title=title)
                metrics = metrics if metrics is not None else {}
                metrics["efficiency"] = [
                    {"tree_path": c["tree_path"], "run_id": c["run_id"],
                     "f_ghz": c["f"], "pct": [100 * complex(v).real for v in c["values"]]}
                    for c in curves if len(c["f"]) <= 5
                ]
            else:  # pragma: no cover - guarded above
                continue
            emit(q, fig, needed[q])
        for tree in custom:
            curves = [series(tree, r, labels.get(r, f"Run {r}")) for r in runs
                      if r in reader.run_ids(tree)]
            if not curves:
                warnings.append(f"{tree}: none of runs {runs} stored")
                continue
            name = tree.rsplit("\\", 1)[-1]
            if tree.startswith(source.S_PARAM_PREFIX):
                fig = fp.plot_db_family(curves, width=width, title=title,
                                        ylabel=f"{source.s_param_latex(tree)} (dB)")
            else:
                ylabel = curves[0]["ylabel"] or name
                fig = fp.plot_real(curves, width=width, title=title, ylabel=ylabel)
                if any(abs(complex(v).imag) > 1e-12 for c in curves for v in c["values"]):
                    warnings.append(f"{tree}: complex data; real part plotted")
            emit(f"custom_{_slug(name)}", fig, [tree])
    except ValueError as exc:
        return err(str(exc))
    except OSError as exc:
        return err(f"Cannot write figures to {out_dir}: {exc}")

    trees = sorted({t for f in figures for t in f["tree_paths"]})
    payload = {
        "status": "ok",
        "files": files,
        "figures": figures,
        "metrics": metrics,
        "source": {
            "project": str(path),
            "tree_paths": trees,
            "run_ids": runs,
            "run_labels": {str(r): labels.get(r, "") for r in runs},
            "reader": "cst.results",
            "snapshot": "Last saved project results; unsaved GUI changes are not included",
            "overlays": [{k: o[k] for k in ("path", "label", "n", "freq_unit", "freq_unit_source")}
                         for o in overlays],
        },
        "out_dir": str(out_dir),
        "warnings": warnings,
    }
    return as_json(_clean(payload))


from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
