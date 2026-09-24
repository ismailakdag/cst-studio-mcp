"""Power-balance diagnostics from CST 1D power curves (read-only).

CST writes, per excitation, ``1D Results\\Power\\Excitation [1]\\``:
``Power Stimulated``, ``Power Accepted``, ``Power Radiated`` and (when loss
monitors exist) ``Loss in Dielectrics`` / ``Loss in Metals``.  For a closed
energy balance ``P_acc = P_rad + P_loss``; three independent radiation
efficiency estimates then agree:

* ``eta_farfield = P_rad / P_acc``
* ``eta_loss     = 1 - P_loss / P_acc``
* ``eta_pattern  = mean(realized gain over the sphere) * P_stim / P_acc``
  (realized gain = 4 pi U / P_stim, so its sphere mean is P_rad,pattern / P_stim)

``unaccounted = (P_acc - P_rad - P_loss) / P_acc`` is the power that is
neither radiated nor dissipated.  A two-day CST 2026 campaign traced a 16-24 %
unaccounted fraction to a waveguide port on an ``open`` (no added space)
boundary with the board touching that face: CST extends geometry touching an
open boundary into the PML ("virtually infinite"), so the board/grounds act as
an infinite line whose current is absorbed in the PML.  Efficiency and gain are
then unreliable (and S11 looks artificially broadband).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from typing import Any

POWER_ITEMS: dict[str, str] = {
    "P_stim": "Power Stimulated",
    "P_acc": "Power Accepted",
    "P_rad": "Power Radiated",
    "P_loss_diel": "Loss in Dielectrics",
    "P_loss_metal": "Loss in Metals",
}

DEFAULT_THRESHOLD = 0.03

PML_EXPLANATION = (
    "The power balance does not close: part of the accepted power is neither radiated "
    "(P_rad) nor counted as loss. The usual cause is geometry touching an 'open' boundary "
    "(open without added space), typically a waveguide port on that face with the "
    "substrate/grounds ending there. CST's TD solver extends geometry and materials that "
    "touch an open boundary into the PML (virtually infinite), so the structure behaves "
    "like an infinite line and the PML absorbs power that appears nowhere in the balance. "
    "Radiation/total efficiency and (realized) gain are then unreliable, and S11 can look "
    "artificially broadband because the PML acts as a resistive load."
)

RECOMMENDATION = (
    "Use 'expanded open' on all faces and feed through a closed structure (coax / SMA, e.g. "
    "cst_add_sma_edge_connector) with an internal waveguide port on the coax back face "
    "(PortOnBound False), so no structure touches the boundary. Then re-check with "
    "cst_check_power_balance (target |unaccounted| <= 2-3 %)."
)

LOSS_MONITOR_NOTE = (
    "Loss curves exist only at 3D field-monitor frequencies unless the 1D power-loss monitor "
    "is enabled: Solver.ActivatePowerLoss1DMonitor True (+ UseFarFieldMonitorForPowerLoss1DMonitor "
    "True for farfield frequencies, or UseExtraFreqForPowerLoss1DMonitor True with "
    "AddPowerLoss1DMonitorExtraFreq). Use cst_configure_time_domain_solver "
    "activate_power_loss_1d=true and re-solve."
)


def power_tree_path(excitation: str, item: str) -> str:
    return f"1D Results\\Power\\{excitation}\\{item}"


def value_at(x: list[float], y: list[float], f: float, *, tol: float = 1e-3) -> tuple[float | None, str]:
    """Value of curve (x, y) at ``f``.

    Dense curves (> 10 samples) are linearly interpolated inside their range;
    sparse curves (loss values stored only at monitor frequencies) return the
    nearest sample within ``tol`` and ``None`` otherwise.
    """
    if not x or len(x) != len(y):
        return None, "empty"
    pairs = sorted(zip(x, y))
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    k = min(range(len(xs)), key=lambda i: abs(xs[i] - f))
    if abs(xs[k] - f) <= tol:
        return float(ys[k]), "sample"
    if len(xs) <= 10:
        return None, "no_sample"
    if not xs[0] <= f <= xs[-1]:
        return None, "out_of_range"
    for i in range(len(xs) - 1):
        if xs[i] <= f <= xs[i + 1]:
            t = (f - xs[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] != xs[i] else 0.0
            return float(ys[i] + t * (ys[i + 1] - ys[i])), "interpolated"
    return None, "out_of_range"  # pragma: no cover


def sphere_mean_linear(theta_deg: Iterable[float], phi_deg: Iterable[float], gain_db) -> float:
    """Mean over the sphere of a dB pattern on a regular theta/phi grid.

    ``gain_db`` is indexed ``[phi][theta]``; phi must not repeat 0/360.
    Uses sin(theta) weights with exact polar-cap areas at theta 0/180.
    """
    th = [float(t) for t in theta_deg]
    ph = [float(p) for p in phi_deg]
    if len(th) < 3 or len(ph) < 2:
        raise ValueError("farfield grid too small for a sphere integral")
    n_t = len(th)
    weights = []
    for i, t in enumerate(th):
        lo = th[i - 1] if i > 0 else t
        hi = th[i + 1] if i < n_t - 1 else t
        a = math.radians((lo + t) / 2 if i > 0 else t)
        b = math.radians((t + hi) / 2 if i < n_t - 1 else t)
        weights.append(math.cos(a) - math.cos(b))  # integral of sin over the theta cell
    total_w = sum(weights)
    acc = 0.0
    for row in gain_db:
        vals = [10 ** (float(v) / 10) for v in row]
        acc += sum(w * v for w, v in zip(weights, vals))
    return acc / (total_w * len(ph))


def compute_balance(
    curves: dict[str, dict[str, list[float]]],
    frequencies: Iterable[float],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    pattern_means: dict[float, float] | None = None,
) -> dict[str, Any]:
    """Evaluate the balance at each frequency from ``{key: {"x": [...], "y": [...]}}``.

    ``key`` is one of :data:`POWER_ITEMS`.  ``pattern_means`` maps frequency to
    the linear sphere mean of the realized gain.
    """
    threshold = float(threshold)
    pattern_means = pattern_means or {}
    per_freq: dict[str, Any] = {}
    flagged: list[float] = []
    loss_missing: list[float] = []
    loss_zero: list[float] = []
    for f in frequencies:
        f = float(f)
        row: dict[str, Any] = {"frequency_ghz": f}
        how: dict[str, str] = {}
        for key in POWER_ITEMS:
            c = curves.get(key)
            if not c:
                row[key] = None
                how[key] = "missing_curve"
                continue
            v, h = value_at(list(c.get("x") or []), list(c.get("y") or []), f)
            row[key] = v
            how[key] = h
        row["sampling"] = how
        pa, pr, ps = row["P_acc"], row["P_rad"], row["P_stim"]
        ld, lm = row["P_loss_diel"], row["P_loss_metal"]
        loss = None
        if ld is not None or lm is not None:
            loss = (ld or 0.0) + (lm or 0.0)
        row["P_loss"] = loss
        if loss is None:
            loss_missing.append(f)
        elif loss == 0.0:
            loss_zero.append(f)
        mean = pattern_means.get(f)
        if mean is None:
            for fk, mv in pattern_means.items():
                if abs(float(fk) - f) <= 1e-6:
                    mean = mv
        estimates: dict[str, float] = {}
        if pa:
            if pr is not None:
                estimates["eta_farfield"] = pr / pa
            if loss is not None:
                estimates["eta_loss"] = 1.0 - loss / pa
            if mean is not None and ps:
                estimates["eta_pattern"] = mean * ps / pa
            if pr is not None and loss is not None:
                row["unaccounted_fraction"] = (pa - pr - loss) / pa
            if ps:
                row["mismatch_efficiency"] = pa / ps
                if pr is not None:
                    row["eta_total"] = pr / ps
        row.update(estimates)
        vals = list(estimates.values())
        row["spread"] = (max(vals) - min(vals)) if len(vals) >= 2 else None
        un = row.get("unaccounted_fraction")
        reasons = []
        if un is not None and abs(un) > threshold:
            reasons.append(f"|unaccounted| {abs(un):.1%} > {threshold:.0%}")
        if "eta_pattern" in estimates and "eta_farfield" in estimates and abs(
            estimates["eta_pattern"] - estimates["eta_farfield"]
        ) > threshold:
            reasons.append("pattern integral disagrees with P_rad/P_acc")
        row["flag"] = bool(reasons)
        row["flag_reasons"] = reasons
        if un is None:
            row["closes"] = None
        else:
            row["closes"] = not reasons
        if reasons:
            flagged.append(f)
        per_freq[f"{f:g}"] = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}

    out: dict[str, Any] = {
        "status": "ok",
        "threshold": threshold,
        "frequencies": per_freq,
        "flagged_frequencies_ghz": flagged,
        "balance_closes": (not flagged) if any(
            r.get("closes") is not None for r in per_freq.values()) else None,
        "definitions": {
            "eta_farfield": "P_rad / P_acc",
            "eta_loss": "1 - (Loss in Dielectrics + Loss in Metals) / P_acc",
            "eta_pattern": "mean(realized gain over sphere) * P_stim / P_acc",
            "unaccounted_fraction": "(P_acc - P_rad - P_loss) / P_acc",
        },
    }
    if flagged:
        out["warning"] = PML_EXPLANATION
        out["recommendation"] = RECOMMENDATION
    if loss_zero:
        # Live CST 2026: with only an Hfield monitor and the 1D power-loss monitor
        # off, 'Loss in Dielectrics' exists at that frequency but is exactly 0 even
        # for FR-4 (tan d 0.025); the 1D monitor then gave 3.3 % of P_acc.
        out["zero_loss_note"] = (
            f"Loss is exactly 0 at {loss_zero} GHz. Unless the model is lossless, the loss was not "
            "computed there (e.g. only an H-field monitor and no 1D power-loss monitor), so "
            "unaccounted_fraction is overestimated. " + LOSS_MONITOR_NOTE
        )
    if loss_missing:
        out["loss_note"] = (
            f"No loss value at {loss_missing} GHz, so eta_loss/unaccounted are not available there. "
            + LOSS_MONITOR_NOTE
        )
    return out


CurveReader = Callable[..., dict[str, Any]]


def read_power_curves(
    project_path: str, excitation: str = "Excitation [1]", run_id: int = 0,
    reader: CurveReader | None = None,
) -> tuple[dict[str, dict[str, list[float]]], dict[str, Any]]:
    """Read the power curves of one excitation from a saved project (cst.results)."""
    if reader is None:
        from cst_mcp.execution.curves import read_curve as reader  # type: ignore[no-redef]
    curves: dict[str, dict[str, list[float]]] = {}
    sources: dict[str, Any] = {}
    for key, item in POWER_ITEMS.items():
        path = power_tree_path(excitation, item)
        data = reader(project_path, path, run_id, allow_interactive=True)
        if data.get("status") == "ok":
            y = data.get("real") if data.get("real") is not None else data.get("y")
            curves[key] = {"x": [float(v) for v in data["x"]], "y": [float(v) for v in y]}
            sources[key] = {"tree_path": path, "n": len(data["x"])}
        else:
            sources[key] = {"tree_path": path, "status": data.get("status"),
                            "message": str(data.get("message", ""))[:200]}
    return curves, sources


def farfield_warning(
    project_path: str | None, frequency_ghz: float | None, *,
    excitation: str = "Excitation [1]", threshold: float = DEFAULT_THRESHOLD,
    reader: CurveReader | None = None,
) -> dict[str, Any] | None:
    """Compact power-balance warning for farfield/efficiency tools.

    Returns ``None`` when the project, frequency or loss curves are not
    available, or when the balance closes within ``threshold``.
    """
    if not project_path or frequency_ghz is None:
        return None
    try:
        curves, _ = read_power_curves(project_path, excitation, 0, reader)
    except Exception:  # noqa: BLE001
        return None
    if not curves.get("P_acc") or not (curves.get("P_loss_diel") or curves.get("P_loss_metal")):
        return None
    bal = compute_balance(curves, [float(frequency_ghz)], threshold=threshold)
    row = next(iter(bal["frequencies"].values()))
    if not row.get("flag"):
        return None
    return {
        "frequency_ghz": float(frequency_ghz),
        "unaccounted_fraction": row.get("unaccounted_fraction"),
        "eta_farfield": row.get("eta_farfield"),
        "eta_loss": row.get("eta_loss"),
        "message": PML_EXPLANATION,
        "recommendation": RECOMMENDATION,
        "details": "cst_check_power_balance",
    }
