"""Farfield discovery, summary export, and metric parsing."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any


_FREQ_RE = re.compile(
    r"farfield\s*\(\s*f\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*\)",
    re.IGNORECASE,
)

# Labels commonly written by FarfieldPlot.ASCIIExportSummary / log dumps.
# Prefer longer / more specific patterns first.
_METRIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "max_realized_gain_dbi",
        re.compile(
            r"maximum\s+realized\s+gain(?:\s*\[dB(?:i)?\])?\s*[:=]\s*([-+]?[0-9]*\.?[0-9]+)",
            re.I,
        ),
    ),
    (
        "max_gain_dbi",
        re.compile(
            r"maximum\s+gain(?:\s*\[dB(?:i)?\])?\s*[:=]\s*([-+]?[0-9]*\.?[0-9]+)",
            re.I,
        ),
    ),
    (
        "directivity_dbi",
        re.compile(
            r"maximum\s+directivity(?:\s*\[dB(?:i)?\])?\s*[:=]\s*([-+]?[0-9]*\.?[0-9]+)",
            re.I,
        ),
    ),
    (
        "radiation_efficiency_db",
        re.compile(
            r"radiation\s+efficiency\s*[:=]\s*([-+]?[0-9]*\.?[0-9]+)\s*dB",
            re.I,
        ),
    ),
    (
        "total_efficiency_db",
        re.compile(
            r"total\s+efficiency\s*[:=]\s*([-+]?[0-9]*\.?[0-9]+)\s*dB",
            re.I,
        ),
    ),
    (
        "radiation_efficiency_percent",
        re.compile(
            r"radiation\s+efficiency\s*[:=]\s*([-+]?[0-9]*\.?[0-9]+)\s*%",
            re.I,
        ),
    ),
    (
        "frequency_label",
        re.compile(r"frequency\s*:\s*([-+]?[0-9]*\.?[0-9]+)\s*(MHz|GHz|Hz)?", re.I),
    ),
    (
        "step_theta_deg",
        re.compile(r"step\s+angle\s+theta\s*:\s*([-+]?[0-9]*\.?[0-9]+)", re.I),
    ),
    (
        "step_phi_deg",
        re.compile(r"step\s+angle\s+phi\s*:\s*([-+]?[0-9]*\.?[0-9]+)", re.I),
    ),
    # Loose fallbacks (after specific ones)
    (
        "max_gain_dbi",
        re.compile(r"(?<!realized\s)(?<!maximum\s)gain\s*[:=]\s*([-+]?[0-9]*\.?[0-9]+)", re.I),
    ),
    (
        "directivity_dbi",
        re.compile(r"(?<!maximum\s)directivity\s*[:=]\s*([-+]?[0-9]*\.?[0-9]+)", re.I),
    ),
]


def extract_frequency_ghz(name: str) -> float | None:
    m = _FREQ_RE.search(name.replace(",", "."))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def farfield_tree_candidates(
    frequency_ghz: float | None = None,
    monitor_name: str | None = None,
) -> list[str]:
    """Ordered tree paths CST uses for farfield result items.

    Prefer ``Farfields\\farfield (f=X) [1]`` — the ``[1]`` suffix is the
    excitation-port tag CST adds after a TD solve. Bare names without
    ``Farfields\\`` fail SelectTreeItem; parent-only ``Farfields`` is not
    a result item.
    """
    paths: list[str] = []

    def _add_monitor_label(label: str) -> None:
        label = label.strip()
        if not label:
            return
        # strip accidental Farfields\ prefix for uniform handling
        low = label.replace("/", "\\")
        if low.lower().startswith("farfields\\"):
            label = label.split("\\", 1)[-1]
        # Prefer [1] excitation suffix first (SelectTreeItem succeeds here)
        variants: list[str] = []
        if "[" in label:
            variants.append(label)
        else:
            variants.extend([f"{label} [1]", f"{label}[1]", label])
        for v in variants:
            paths.append(rf"Farfields\{v}")
            paths.append(rf"2D/3D Results\Farfields\{v}")

    if monitor_name:
        _add_monitor_label(monitor_name)

    if frequency_ghz is not None:
        # Format variants: 2.4, 2.40, 2.400...
        freqs = {f"{frequency_ghz:g}", f"{frequency_ghz:.3f}".rstrip("0").rstrip(".")}
        for f in freqs:
            _add_monitor_label(f"farfield (f={f})")

    # Do NOT add bare parent folders "Farfields" / "2D/3D Results\Farfields"
    # — selecting those and calling export APIs spams Message with
    # "No data available for export".

    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def discover_farfield_from_project_dir(project_path: str | None) -> list[dict[str, Any]]:
    """Scan on-disk Result folder next to a .cst project for farfield files."""
    if not project_path:
        return []
    p = Path(project_path)
    bases = []
    if p.suffix.lower() == ".cst":
        bases.append(p.with_suffix(""))  # ProjectName/
        bases.append(p.parent / p.stem)
    bases.append(p.parent / "Result")

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for base in bases:
        result_dir = base / "Result" if base.name != "Result" else base
        if not result_dir.is_dir():
            # also try base itself
            result_dir = base if base.is_dir() else None
        if result_dir is None or not result_dir.is_dir():
            continue
        try:
            # Prefer .ffm (native monitor) over .ffp/.ffs (exports)
            files = sorted(
                result_dir.iterdir(),
                key=lambda p: (
                    0 if p.suffix.lower() == ".ffm" else 1 if p.suffix.lower() == ".fme" else 2,
                    p.name.lower(),
                ),
            )
            for fp in files:
                name = fp.name
                if "farfield" not in name.lower():
                    continue
                # strip extensions like _1.ffm, 2D_1.ffp
                mon = re.sub(r"(_?\d+)?\.(ffm|fme|ffp|ffs|txt|csv)$", "", name, flags=re.I)
                mon = re.sub(r"2D$", "", mon, flags=re.I).strip()
                if mon in seen:
                    continue
                seen.add(mon)
                freq = extract_frequency_ghz(mon)
                found.append(
                    {
                        "monitor_name": mon,
                        "frequency_ghz": freq,
                        "file": str(fp),
                        "tree_candidates": farfield_tree_candidates(freq, mon),
                    }
                )
        except OSError:
            continue
    return found


def parse_farfield_summary_text(text: str) -> dict[str, Any]:
    """Parse FarfieldPlot.ASCIIExportSummary (or similar) text into metrics."""
    metrics: dict[str, Any] = {}
    if not text or not text.strip():
        return metrics

    for key, pattern in _METRIC_PATTERNS:
        if key in metrics and key != "frequency_label":
            continue
        m = pattern.search(text)
        if not m:
            continue
        try:
            if key == "frequency_label":
                val = float(m.group(1))
                unit = (m.group(2) or "").lower()
                metrics["frequency_value"] = val
                metrics["frequency_unit"] = unit or None
                if unit == "mhz":
                    metrics["frequency_ghz"] = val / 1000.0
                elif unit == "hz":
                    metrics["frequency_ghz"] = val / 1e9
                elif unit == "ghz" or not unit:
                    metrics["frequency_ghz"] = val if unit == "ghz" or val < 500 else val / 1000.0
            else:
                metrics[key] = float(m.group(1))
        except ValueError:
            continue

    # Linear efficiency if only percent available
    if "radiation_efficiency_percent" in metrics and "radiation_efficiency" not in metrics:
        metrics["radiation_efficiency"] = metrics["radiation_efficiency_percent"] / 100.0

    # dB efficiency → linear (η = 10^(dB/10))
    if "radiation_efficiency_db" in metrics and "radiation_efficiency" not in metrics:
        metrics["radiation_efficiency"] = 10 ** (metrics["radiation_efficiency_db"] / 10.0)
    if "total_efficiency_db" in metrics and "total_efficiency" not in metrics:
        metrics["total_efficiency"] = 10 ** (metrics["total_efficiency_db"] / 10.0)

    return metrics

def parse_farfield_pattern_csv(path: str | Path, max_points: int = 500) -> dict[str, Any]:
    """Best-effort parse of a farfield cut/pattern CSV into peak gain."""
    path = Path(path)
    if not path.is_file():
        return {"status": "error", "message": f"File not found: {path}"}

    text = path.read_text(encoding="utf-8", errors="replace")
    rows: list[list[float]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!", "Theta", "Phi", "Frequency")):
            # keep header scan soft
            parts_try = line.replace(";", ",").replace("\t", ",").split(",")
            if parts_try and re.match(r"^[-+]?[0-9]", parts_try[0].strip() or "x"):
                pass
            else:
                continue
        line = line.replace(";", ",").replace("\t", ",")
        parts = [p.strip() for p in line.split(",") if p.strip() != ""]
        if len(parts) < 2:
            continue
        try:
            nums = [float(p) for p in parts[:4]]
        except ValueError:
            continue
        rows.append(nums)

    if not rows:
        # also try summary-style
        metrics = parse_farfield_summary_text(text)
        if metrics:
            return {"status": "ok", "source": "summary_text", "metrics": metrics, "path": str(path)}
        return {"status": "error", "message": f"No numeric farfield rows in {path}"}

    # Assume last numeric column is the quantity (dB gain-like)
    values = [r[-1] for r in rows]
    peak_i = max(range(len(values)), key=lambda i: values[i] if math.isfinite(values[i]) else -1e300)
    peak_row = rows[peak_i]
    metrics: dict[str, Any] = {"peak_value": values[peak_i]}
    if len(peak_row) >= 2:
        metrics["theta_or_col0"] = peak_row[0]
        metrics["phi_or_col1"] = peak_row[1] if len(peak_row) > 2 else None

    step = max(1, len(rows) // max_points)
    sample = rows[::step]
    return {
        "status": "ok",
        "source": "pattern_csv",
        "n_points": len(rows),
        "metrics": metrics,
        "sample": sample[: max_points],
        "path": str(path),
    }


def build_farfield_summary_vba(tree_path: str, summary_path: str) -> str:
    """Legacy VBA using ASCIIExportSummary (often fails on CST 2026).

    Prefer :func:`build_farfield_metrics_vba` (official GetMax path).
    Returns **body only** (no ``Sub Main``).
    """
    safe_tree = tree_path.replace('"', '""')
    safe_file = summary_path.replace("\\", "/").replace('"', '""')
    return "\n".join(
        [
            f'SelectTreeItem "{safe_tree}"',
            "With FarfieldPlot",
            "  .Reset",
            '  .Plottype "3d"',
            '  .SetPlotMode "realized gain"',
            "  .Plot",
            f'  .ASCIIExportSummary "{safe_file}"',
            "End With",
        ]
    )


def build_farfield_metrics_vba(tree_path: str, metrics_path: str) -> str:
    """VBA body: configure plot, select tree item, Plot, dump Get* metrics.

    Official CST 2026 FarfieldPlot API (no ASCIIExportSummary). After a
    successful TD solve with a frequency-domain farfield monitor, this is the
    reliable path for max gain / efficiencies without Message spam.

    Returns **body only** (no ``Sub Main``).
    """
    safe_tree = tree_path.replace('"', '""')
    safe_file = metrics_path.replace("\\", "/").replace('"', '""')
    # Settings first, then SelectTreeItem, then Plot — matches official help example.
    return "\n".join(
        [
            "Dim ok As Boolean",
            "With FarfieldPlot",
            "  .Reset",
            '  .Plottype ("3d")',
            "  .Step (5)",
            "  .Step2 (5)",
            '  .SetLockSteps (True)',
            '  .SetPlotMode ("realized gain")',
            "  .SetScaleLinear (False)",
            "  .UseFarfieldApproximation (True)",
            '  .Origin ("bbox")',
            "End With",
            f'ok = SelectTreeItem("{safe_tree}")',
            f'Open "{safe_file}" For Output As #1',
            'Print #1, "select=" & CStr(ok)',
            "On Error Resume Next",
            "If ok Then",
            "  FarfieldPlot.Plot",
            '  Print #1, "GetMax=" & CStr(FarfieldPlot.GetMax)',
            '  Print #1, "GetMin=" & CStr(FarfieldPlot.GetMin)',
            '  Print #1, "GetMean=" & CStr(FarfieldPlot.GetMean)',
            '  Print #1, "GetRadiationEfficiency=" & CStr(FarfieldPlot.GetRadiationEfficiency)',
            '  Print #1, "GetTotalEfficiency=" & CStr(FarfieldPlot.GetTotalEfficiency)',
            '  Print #1, "GetTRP=" & CStr(FarfieldPlot.GetTRP)',
            '  Print #1, "GetPlotMode=" & CStr(FarfieldPlot.GetPlotMode)',
            '  Print #1, "err=" & Err.Description',
            "Else",
            f'  Print #1, "error=SelectTreeItem failed: {safe_tree}"',
            "End If",
            "Close #1",
        ]
    )


def parse_farfield_metrics_kv(text: str) -> dict[str, Any]:
    """Parse key=value dump from :func:`build_farfield_metrics_vba`."""
    metrics: dict[str, Any] = {}
    if not text or not text.strip():
        return metrics

    kv: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, _, v = line.partition("=")
        kv[k.strip()] = v.strip()

    if kv.get("select") in {"0", "False", "false"}:
        metrics["select_ok"] = False
    elif kv.get("select") in {"-1", "True", "true", "1"}:
        metrics["select_ok"] = True

    def _f(key: str) -> float | None:
        raw = kv.get(key)
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    # GetMax in realized-gain / gain / directivity mode is dB when scale is log
    gmax = _f("GetMax")
    gmin = _f("GetMin")
    gmean = _f("GetMean")
    if gmax is not None:
        # -200 is CST's empty-marker for efficiency; for gain 0 can be valid
        metrics["max_realized_gain_dbi"] = gmax
        metrics["max_gain_dbi"] = gmax  # plot mode dependent; documented by caller
    if gmin is not None:
        metrics["min_plot_value"] = gmin
    if gmean is not None:
        metrics["mean_plot_value"] = gmean

    rad = _f("GetRadiationEfficiency")
    tot = _f("GetTotalEfficiency")
    # CST returns -200 when no data
    if rad is not None and rad > -199:
        metrics["radiation_efficiency_db"] = rad
        metrics["radiation_efficiency"] = 10 ** (rad / 10.0)
    if tot is not None and tot > -199:
        metrics["total_efficiency_db"] = tot
        metrics["total_efficiency"] = 10 ** (tot / 10.0)

    trp = _f("GetTRP")
    if trp is not None and trp >= 0:
        metrics["trp_w"] = trp

    if kv.get("GetPlotMode"):
        metrics["plot_mode"] = kv["GetPlotMode"]
    if kv.get("err"):
        metrics["vba_err"] = kv["err"]
    if kv.get("error"):
        metrics["error"] = kv["error"]

    return metrics


def build_farfield_list_eval_hint() -> str:
    return (
        "Use FarfieldPlot.Plot + GetMax / GetRadiationEfficiency after "
        "SelectTreeItem('Farfields\\farfield (f=X) [1]'). "
        "Avoid ASCIIExportSummary (not reliable on CST 2026)."
    )


def farfield_monitor_vba(name: str, frequency_ghz: float) -> str:
    """Official single-frequency farfield monitor VBA body.

    ``EnableNearfieldCalculation True`` keeps nearfield data for robust
    post-processing when the hex mesh is discarded after solve.
    """
    from cst_mcp.execution.vba_builder import fmt_num, vba_str

    return "\n".join(
        [
            "With Monitor",
            "  .Reset",
            f'  .Name "{vba_str(name)}"',
            '  .Domain "Frequency"',
            '  .FieldType "Farfield"',
            f'  .Frequency "{fmt_num(frequency_ghz)}"',
            '  .ExportFarfieldSource "False"',
            '  .EnableNearfieldCalculation "True"',
            '  .UseSubvolume "False"',
            "  .Create",
            "End With",
        ]
    )
