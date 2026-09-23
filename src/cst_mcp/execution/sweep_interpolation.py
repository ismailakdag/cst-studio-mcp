"""Interpolate a saved 1D result between parameter-sweep runs (read-only).

Works on any reader exposing ``run_ids(tree)``, ``parameter_combination(run)``
and ``read(tree, run)`` (see :class:`~cst_mcp.execution.figures_1d_source.SavedResults`),
so it is testable with fakes.  Values are interpolated linearly in the swept
parameter on the complex samples; no extrapolation is performed.
"""

from __future__ import annotations

import bisect
import math
from typing import Any

from cst_mcp.execution.curves import frequency_scale


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _resample(x_src: list[float], y_src: list[complex], x_dst: list[float]) -> list[complex]:
    """Linear resampling of a complex curve onto another (increasing) grid."""
    if x_src == x_dst:
        return list(y_src)
    out = []
    for x in x_dst:
        if x < x_src[0] or x > x_src[-1]:
            raise ValueError("Sweep runs do not cover the same x range; cannot interpolate")
        j = min(max(bisect.bisect_left(x_src, x), 1), len(x_src) - 1)
        x0, x1 = x_src[j - 1], x_src[j]
        t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
        out.append(y_src[j - 1] + t * (y_src[j] - y_src[j - 1]))
    return out


def interpolate_runs(
    reader: Any, tree_path: str, parameter: str, target: float, *, max_points: int = 200
) -> dict[str, Any]:
    try:
        run_ids = list(reader.run_ids(tree_path))
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"Result {tree_path!r} not found: {exc}"}
    # Run 0 mirrors the current model state (duplicate of one sweep run); prefer real runs.
    candidates = [r for r in run_ids if r != 0] or run_ids
    samples: dict[float, tuple[int, dict]] = {}
    for run_id in candidates:
        combo = reader.parameter_combination(run_id) or {}
        value = _as_float(combo.get(parameter))
        if value is not None and value not in samples:
            samples[value] = (run_id, combo)
    if len(samples) < 1:
        return {"status": "error", "code": "no_sweep_runs",
                "message": f"No saved runs of {tree_path!r} carry parameter {parameter!r}; "
                           "run cst_parameter_sweep (run=true) first.",
                "run_ids": run_ids}
    values = sorted(samples)
    tolerance = 1e-9 * max(1.0, abs(target))
    exact = next((v for v in values if abs(v - target) <= tolerance), None)
    if exact is None and not values[0] < target < values[-1]:
        return {"status": "error", "code": "out_of_range",
                "message": f"target_value {target} is outside the swept range "
                           f"[{values[0]}, {values[-1]}]; no extrapolation is performed.",
                "swept_values": values}
    if exact is not None:
        low = high = exact
        weight = 0.0
    else:
        k = bisect.bisect_left(values, target)
        low, high = values[k - 1], values[k]
        weight = (target - low) / (high - low)
    run_low, combo_low = samples[low]
    run_high, combo_high = samples[high]
    raw_low = reader.read(tree_path, run_low)
    x = [float(v) for v in raw_low["x"]]
    y_low = [complex(v) for v in raw_low["values"]]
    if run_high == run_low:
        y = y_low
    else:
        raw_high = reader.read(tree_path, run_high)
        y_high = _resample([float(v) for v in raw_high["x"]], [complex(v) for v in raw_high["values"]], x)
        y = [a + weight * (b - a) for a, b in zip(y_low, y_high)]
    warnings = []
    others_low = {k: v for k, v in combo_low.items() if k != parameter}
    others_high = {k: v for k, v in combo_high.items() if k != parameter}
    if others_low != others_high:
        changed = sorted(k for k in set(others_low) | set(others_high)
                         if others_low.get(k) != others_high.get(k))
        warnings.append(f"Bracketing runs also differ in {changed}; the interpolation mixes those changes.")
    try:
        scale = frequency_scale(raw_low.get("xlabel", "")) / 1e9
        x_out, x_unit = [v * scale for v in x], "GHz"
    except ValueError:
        x_out, x_unit = x, raw_low.get("xlabel", "")
    complex_result = any(v.imag for v in y)
    if complex_result:
        y_out = [20 * math.log10(abs(v)) if v else None for v in y]
        y_kind = "magnitude_db"
    else:
        y_out = [v.real for v in y]
        y_kind = "value"
    finite = [(xv, yv) for xv, yv in zip(x_out, y_out) if yv is not None]
    metrics = {}
    if finite:
        x_min, y_min = min(finite, key=lambda p: p[1])
        metrics = {"min": y_min, "x_at_min": x_min}
    n = len(x_out)
    if max_points and max_points < n:
        idx = sorted({round(j * (n - 1) / (max_points - 1)) for j in range(max_points)}) if max_points > 1 else [0]
        x_out = [x_out[j] for j in idx]
        y_out = [y_out[j] for j in idx]
    return {
        "status": "ok",
        "source": "cst.results (saved sweep runs)",
        "tree_path": tree_path,
        "method": "exact run" if exact is not None else "linear in parameter (complex samples)",
        "bracket": {"low": {"value": low, "run_id": run_low},
                    "high": {"value": high, "run_id": run_high}, "weight": round(weight, 6)},
        "swept_values": values,
        "x_unit": x_unit,
        "y_kind": y_kind,
        "metrics": metrics,
        "x": x_out,
        "y": y_out,
        "total_points": n,
        "warnings": warnings,
        "note": "Estimate only; verify a chosen value with a real solve.",
    }
