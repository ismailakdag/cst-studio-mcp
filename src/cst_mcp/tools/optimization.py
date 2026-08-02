"""Antenna optimization tools for CST Studio Suite.

Provides 3 MCP tools for evaluating antenna performance against band/VSWR
goals, analyzing impedance for design guidance, and running automated
Nelder-Mead refinement loops.

- ``cst_evaluate_antenna``: Read-only evaluation of S11 against VSWR targets
- ``cst_analyze_impedance``: Impedance analysis with Smith chart metrics and
  design recommendations for improving matching toward a target impedance
- ``cst_refine_antenna``: Iterative parameter optimization via Nelder-Mead
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from typing import TYPE_CHECKING, Any, Callable

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBABuilder, VBAScript

if TYPE_CHECKING:
    from mcp.server import Server

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="cst_evaluate_antenna",
        description=(
            "Evaluate current antenna simulation results against performance goals. "
            "Exports S-parameter data and checks VSWR (or return loss) against "
            "per-band targets. Read-only — does not modify the model. "
            "Returns pass/fail per band, worst VSWR, and detected resonances."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "bands": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Band label (e.g. '2.4 GHz WiFi').",
                            },
                            "f_low_ghz": {
                                "type": "number",
                                "description": "Lower band edge in GHz.",
                            },
                            "f_high_ghz": {
                                "type": "number",
                                "description": "Upper band edge in GHz.",
                            },
                            "vswr_target": {
                                "type": "number",
                                "description": "Maximum acceptable VSWR (e.g. 2.0 or 2.5).",
                                "default": 2.5,
                            },
                        },
                        "required": ["name", "f_low_ghz", "f_high_ghz"],
                    },
                    "minItems": 1,
                    "description": "Frequency bands to evaluate.",
                },
                "port": {
                    "type": "integer",
                    "description": "Port number for S-parameter (default: 1).",
                    "default": 1,
                },
            },
            "required": ["bands"],
        },
    ),
    Tool(
        name="cst_analyze_impedance",
        description=(
            "Analyze antenna impedance match quality across frequency bands using "
            "S-parameter data. Exports S11 from a completed simulation, computes "
            "VSWR and return loss per frequency point, detects resonances, and "
            "provides resonance-based design recommendations (e.g. shift resonance "
            "up/down, widen bandwidth). Returns per-band worst/best VSWR, match "
            "quality classification, nearest resonance info, and actionable "
            "design guidance. Read-only — does not modify the model."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "bands": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Band label (e.g. '2.4 GHz WiFi').",
                            },
                            "f_low_ghz": {
                                "type": "number",
                                "description": "Lower band edge in GHz.",
                            },
                            "f_high_ghz": {
                                "type": "number",
                                "description": "Upper band edge in GHz.",
                            },
                            "vswr_target": {
                                "type": "number",
                                "description": "Maximum acceptable VSWR (default: 2.5).",
                                "default": 2.5,
                            },
                        },
                        "required": ["name", "f_low_ghz", "f_high_ghz"],
                    },
                    "minItems": 1,
                    "description": "Frequency bands to analyze impedance for.",
                },
                "z0": {
                    "type": "number",
                    "description": "Reference impedance in ohms (default: 50).",
                    "default": 50,
                },
                "port": {
                    "type": "integer",
                    "description": "Port number (default: 1).",
                    "default": 1,
                },
                "sample_frequencies_ghz": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "Specific frequencies (GHz) to report detailed impedance. "
                        "If omitted, band edges and center are used."
                    ),
                },
            },
            "required": ["bands"],
        },
    ),
    Tool(
        name="cst_refine_antenna",
        description=(
            "Run an automated Nelder-Mead optimization loop to tune CST design "
            "parameters toward VSWR goals across specified frequency bands. "
            "Each iteration sets parameters, runs the solver, exports S11, and "
            "evaluates against targets. Uses silent VBA execution to avoid "
            "history bloat. Applies the best parameters permanently at the end. "
            "Connected mode only — requires a live CST session with a solvable project."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "CST parameter name.",
                            },
                            "initial": {
                                "type": "number",
                                "description": "Initial value.",
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
                        "required": ["name", "initial", "min", "max"],
                    },
                    "minItems": 1,
                    "description": "Parameters to optimize with initial values and bounds.",
                },
                "bands": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "f_low_ghz": {"type": "number"},
                            "f_high_ghz": {"type": "number"},
                            "vswr_target": {
                                "type": "number",
                                "default": 2.5,
                            },
                        },
                        "required": ["name", "f_low_ghz", "f_high_ghz"],
                    },
                    "minItems": 1,
                    "description": "Frequency bands with VSWR targets.",
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Maximum optimization iterations (default: 20).",
                    "default": 20,
                },
                "port": {
                    "type": "integer",
                    "description": "Port number (default: 1).",
                    "default": 1,
                },
            },
            "required": ["parameters", "bands"],
        },
    ),
]

_TOOL_NAMES = {t.name for t in TOOLS}

# ---------------------------------------------------------------------------
# S-parameter parsing and VSWR math
# ---------------------------------------------------------------------------


def _parse_s11_data(filepath: str) -> tuple[list[float], list[float]]:
    """Parse CST ASCIIExport space-separated S11 data.

    Expected format (2-line header, then space-separated freq + S11_dB):
        Frequency / GHz    S1,1/abs,dB
        -----------------------------------------
        1.0                -0.053
        1.035              -0.061
        ...

    Returns (frequencies_ghz, s11_db).
    """
    freqs: list[float] = []
    s11: list[float] = []

    with open(filepath, "r") as f:
        lines = f.readlines()

    # Skip header lines (non-numeric or separator lines)
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.startswith("F"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            try:
                freqs.append(float(parts[0]))
                s11.append(float(parts[1]))
            except ValueError:
                continue

    if not freqs:
        raise ValueError(f"No data found in {filepath}")

    return freqs, s11


def s11_to_vswr(s11_db: float) -> float:
    """Convert S11 in dB to VSWR.

    VSWR = (1 + |Γ|) / (1 - |Γ|)  where |Γ| = 10^(S11_dB/20)
    """
    if s11_db >= 0:
        return float("inf")
    gamma = 10 ** (s11_db / 20.0)
    if gamma >= 1.0:
        return float("inf")
    return (1.0 + gamma) / (1.0 - gamma)


def vswr_to_s11(vswr: float) -> float:
    """Convert VSWR to S11 in dB.

    |Γ| = (VSWR - 1) / (VSWR + 1)
    S11_dB = 20 * log10(|Γ|)
    """
    if vswr <= 1.0:
        return -float("inf")
    gamma = (vswr - 1.0) / (vswr + 1.0)
    if gamma <= 0:
        return -float("inf")
    return 20.0 * math.log10(gamma)


def _evaluate_bands(
    freqs: list[float],
    s11_db: list[float],
    bands: list[dict],
) -> list[dict]:
    """Evaluate VSWR performance per band.

    Returns a list of dicts with band name, worst VSWR, target, pass/fail.
    """
    results = []
    for band in bands:
        f_low = band["f_low_ghz"]
        f_high = band["f_high_ghz"]
        target = band.get("vswr_target", 2.5)

        # Filter points within band
        band_vswr = []
        band_s11 = []
        for f, s in zip(freqs, s11_db):
            if f_low <= f <= f_high:
                band_vswr.append(s11_to_vswr(s))
                band_s11.append(s)

        if not band_vswr:
            results.append({
                "name": band["name"],
                "status": "NO_DATA",
                "message": f"No data points in {f_low}-{f_high} GHz",
                "target_vswr": target,
            })
            continue

        worst_vswr = max(band_vswr)
        worst_s11 = max(band_s11)  # Least negative = worst match
        best_vswr = min(band_vswr)
        best_idx = band_vswr.index(best_vswr)
        best_s11 = band_s11[best_idx]

        # Find frequency of best match within band
        band_freqs = [f for f in freqs if f_low <= f <= f_high]
        best_freq = band_freqs[best_idx] if best_idx < len(band_freqs) else None

        passed = worst_vswr <= target
        target_s11 = vswr_to_s11(target)
        margin_db = target_s11 - worst_s11  # Negative = pass, positive = fail

        results.append({
            "name": band["name"],
            "status": "PASS" if passed else "FAIL",
            "worst_vswr": round(worst_vswr, 3),
            "worst_s11_db": round(worst_s11, 2),
            "best_vswr": round(best_vswr, 3),
            "best_s11_db": round(best_s11, 2),
            "best_freq_ghz": round(best_freq, 4) if best_freq else None,
            "target_vswr": target,
            "target_s11_db": round(target_s11, 2),
            "margin_db": round(margin_db, 2),
            "num_points": len(band_vswr),
        })

    return results


def _find_resonances(
    freqs: list[float],
    s11_db: list[float],
    threshold_db: float = -5.0,
) -> list[dict]:
    """Find resonant frequencies (local minima of S11 below threshold).

    Returns list of {freq_ghz, s11_db, vswr} for each detected resonance.
    """
    resonances: list[dict] = []
    n = len(s11_db)
    if n < 3:
        return resonances

    for i in range(1, n - 1):
        if s11_db[i] < threshold_db:
            if s11_db[i] <= s11_db[i - 1] and s11_db[i] <= s11_db[i + 1]:
                resonances.append({
                    "freq_ghz": round(freqs[i], 4),
                    "s11_db": round(s11_db[i], 2),
                    "vswr": round(s11_to_vswr(s11_db[i]), 3),
                })

    return resonances


def _compute_cost(
    freqs: list[float],
    s11_db: list[float],
    bands: list[dict],
) -> tuple[float, list[dict]]:
    """Compute optimization cost: sum of VSWR violations across bands.

    Cost = sum(max(0, worst_band_vswr - target) for each band)
    Returns (cost, band_results).
    """
    band_results = _evaluate_bands(freqs, s11_db, bands)
    cost = 0.0
    for br in band_results:
        if br["status"] == "NO_DATA":
            cost += 10.0  # Penalty for missing data
        elif br["status"] == "FAIL":
            cost += br["worst_vswr"] - br["target_vswr"]
    return cost, band_results


# ---------------------------------------------------------------------------
# Impedance analysis and Smith chart metrics
# ---------------------------------------------------------------------------


def _parse_z_data(filepath: str) -> tuple[list[float], list[float]]:
    """Parse CST ASCIIExport space-separated Z-parameter data.

    CST exports real and imaginary parts as separate tree items, each
    producing a 2-column file: ``frequency  value``.

    Returns (frequencies_ghz, values).
    """
    freqs: list[float] = []
    values: list[float] = []

    with open(filepath, "r") as f:
        lines = f.readlines()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.startswith("F"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            try:
                freqs.append(float(parts[0]))
                values.append(float(parts[1]))
            except ValueError:
                continue

    if not freqs:
        raise ValueError(f"No Z-parameter data found in {filepath}")

    return freqs, values


def z_to_gamma(r: float, x: float, z0: float = 50.0) -> tuple[float, float]:
    """Convert impedance Z = R + jX to reflection coefficient Γ.

    Γ = (Z - Z0) / (Z + Z0)

    Returns (gamma_real, gamma_imag).
    """
    zr = r - z0
    zi = x
    zd_r = r + z0
    zd_i = x
    denom = zd_r * zd_r + zd_i * zd_i
    if denom == 0:
        return 1.0, 0.0
    g_real = (zr * zd_r + zi * zd_i) / denom
    g_imag = (zi * zd_r - zr * zd_i) / denom
    return g_real, g_imag


def gamma_mag(g_real: float, g_imag: float) -> float:
    """Magnitude of reflection coefficient |Γ|."""
    return math.sqrt(g_real * g_real + g_imag * g_imag)


def gamma_to_vswr(g_mag: float) -> float:
    """Convert |Γ| to VSWR."""
    if g_mag >= 1.0:
        return float("inf")
    return (1.0 + g_mag) / (1.0 - g_mag)


def gamma_to_return_loss(g_mag: float) -> float:
    """Convert |Γ| to return loss in dB (always positive, higher = better)."""
    if g_mag <= 0:
        return float("inf")
    return -20.0 * math.log10(g_mag)


def _classify_mismatch(r: float, x: float, z0: float = 50.0) -> dict:
    """Classify impedance mismatch relative to Z0.

    Returns a dict with mismatch type classification and metrics.
    """
    r_ratio = r / z0 if z0 > 0 else float("inf")

    # Resistive classification
    if r_ratio > 1.5:
        r_class = "high"
        r_desc = f"R={r:.1f}Ω is {r_ratio:.1f}× target ({z0:.0f}Ω) — too high"
    elif r_ratio < 0.67:
        r_class = "low"
        r_desc = f"R={r:.1f}Ω is {r_ratio:.1f}× target ({z0:.0f}Ω) — too low"
    else:
        r_class = "ok"
        r_desc = f"R={r:.1f}Ω is close to target ({z0:.0f}Ω)"

    # Reactive classification
    if abs(x) < 10:
        x_class = "ok"
        x_desc = f"X={x:+.1f}Ω — near resonance"
    elif x > 0:
        x_class = "inductive"
        x_desc = f"X={x:+.1f}Ω — inductive (antenna electrically long)"
    else:
        x_class = "capacitive"
        x_desc = f"X={x:+.1f}Ω — capacitive (antenna electrically short)"

    # Overall severity
    g_r, g_i = z_to_gamma(r, x, z0)
    g_m = gamma_mag(g_r, g_i)
    vswr = gamma_to_vswr(g_m)
    rl = gamma_to_return_loss(g_m)

    return {
        "resistance_ohm": round(r, 2),
        "reactance_ohm": round(x, 2),
        "impedance_mag_ohm": round(math.sqrt(r * r + x * x), 2),
        "r_ratio": round(r_ratio, 3),
        "r_class": r_class,
        "r_description": r_desc,
        "x_class": x_class,
        "x_description": x_desc,
        "gamma_mag": round(g_m, 4),
        "vswr": round(vswr, 3),
        "return_loss_db": round(rl, 2),
    }


def _generate_recommendations(
    band_name: str,
    worst_vswr: float,
    target_vswr: float,
    avg_s11_db: float,
    nearest_resonance: dict | None,
    f_low: float,
    f_high: float,
) -> list[str]:
    """Generate design recommendations from S11 magnitude analysis.

    Uses resonance locations and VSWR trends to provide actionable
    antenna design guidance.  Works with S11 dB data (no complex
    impedance needed).

    Parameters
    ----------
    band_name : str
        Label for the band.
    worst_vswr : float
        Worst VSWR within the band.
    target_vswr : float
        VSWR target for the band.
    avg_s11_db : float
        Average S11 (dB) within the band.
    nearest_resonance : dict | None
        Nearest detected resonance ``{freq_ghz, s11_db, vswr}``.
    f_low, f_high : float
        Band edges in GHz.
    """
    recs: list[str] = []

    if worst_vswr <= target_vswr:
        recs.append(
            f"✓ {band_name} meets VSWR target "
            f"({worst_vswr:.2f} ≤ {target_vswr:.1f})"
        )
        return recs

    gap = worst_vswr - target_vswr
    recs.append(
        f"✗ {band_name} VSWR={worst_vswr:.2f} exceeds target {target_vswr:.1f} "
        f"(gap: {gap:.2f})"
    )

    (f_low + f_high) / 2.0

    # Resonance-based recommendations
    if nearest_resonance:
        res_freq = nearest_resonance["freq_ghz"]
        if res_freq < f_low:
            shift = f_low - res_freq
            recs.append(
                f"  Nearest resonance at {res_freq:.2f} GHz is {shift:.2f} GHz "
                "BELOW band. Shorten the resonant path to shift upward: "
                "reduce patch length, shorten slot, decrease meander/arm length, "
                "or trim ground slot dimensions."
            )
        elif res_freq > f_high:
            shift = res_freq - f_high
            recs.append(
                f"  Nearest resonance at {res_freq:.2f} GHz is {shift:.2f} GHz "
                "ABOVE band. Lengthen the resonant path to shift downward: "
                "increase patch length, extend slot, add meander/stub, "
                "or enlarge ground slot."
            )
        else:
            # Resonance is within band but match isn't good enough
            recs.append(
                f"  Resonance at {res_freq:.2f} GHz is within band but "
                "bandwidth is insufficient. Increase bandwidth: raise "
                "substrate height, widen conductors, use thicker ground "
                "plane coupling (wider slots), or add parasitic elements."
            )
    else:
        recs.append(
            "  No resonance detected near this band. Consider adding a "
            "dedicated resonant element (parasitic strip, additional slot, "
            "or coupled resonator) targeting this frequency range."
        )

    # Severity-based recommendations
    if worst_vswr > 5.0:
        recs.append(
            "  Severe mismatch (VSWR > 5). The antenna likely has no useful "
            "mode in this band. A topology change may be needed (stacked "
            "patch, additional radiating element, or matching network)."
        )
    elif worst_vswr > 3.0:
        recs.append(
            "  Moderate mismatch. Fine-tuning feed position, slot dimensions, "
            "or ground plane geometry may improve the match."
        )

    return recs


def _analyze_impedance_band(
    freqs: list[float],
    s11_db: list[float],
    band: dict,
    z0: float = 50.0,
    sample_freqs: list[float] | None = None,
    resonances: list[dict] | None = None,
) -> dict:
    """Analyze impedance match quality within a frequency band from S11 data.

    Computes VSWR, return loss, and match quality from S11 magnitude (dB).
    For full R+jX impedance, complex S-parameter data would be needed.

    Parameters
    ----------
    freqs : list[float]
        Frequency values in GHz.
    s11_db : list[float]
        S11 magnitude values in dB (negative = good match).
    band : dict
        Band specification with name, f_low_ghz, f_high_ghz, vswr_target.
    z0 : float
        Reference impedance in ohms (used for VSWR context, default 50).
    sample_freqs : list[float] | None
        Specific frequencies for detailed reporting.
    resonances : list[dict] | None
        Previously detected resonances for recommendation context.
    """
    f_low = band["f_low_ghz"]
    f_high = band["f_high_ghz"]
    target_vswr = band.get("vswr_target", 2.5)

    # Filter points within band
    band_data = []
    for f, s in zip(freqs, s11_db):
        if f_low <= f <= f_high:
            # Compute |Γ| from S11 dB
            if s >= 0:
                g_m = 1.0
            else:
                g_m = 10.0 ** (s / 20.0)
            vswr = gamma_to_vswr(g_m)
            rl = gamma_to_return_loss(g_m) if g_m > 0 else float("inf")
            band_data.append({
                "freq_ghz": f,
                "s11_db": s,
                "gamma_mag": g_m,
                "vswr": vswr,
                "return_loss_db": rl,
            })

    if not band_data:
        return {
            "name": band["name"],
            "status": "NO_DATA",
            "message": f"No data in {f_low}-{f_high} GHz",
        }

    # Aggregate metrics
    worst_pt = max(band_data, key=lambda d: d["vswr"])
    best_pt = min(band_data, key=lambda d: d["vswr"])
    avg_s11 = sum(d["s11_db"] for d in band_data) / len(band_data)

    passed = worst_pt["vswr"] <= target_vswr
    target_s11 = vswr_to_s11(target_vswr)

    # Find nearest resonance to this band
    nearest_res = None
    if resonances:
        band_center = (f_low + f_high) / 2.0
        nearest_res = min(
            resonances, key=lambda r: abs(r["freq_ghz"] - band_center)
        )

    # Recommendations
    recommendations = _generate_recommendations(
        band["name"], worst_pt["vswr"], target_vswr,
        avg_s11, nearest_res, f_low, f_high,
    )

    # Sample points for detailed report
    detail_points = []
    if sample_freqs:
        targets = sample_freqs
    else:
        # Default: band edges + center + worst + best
        targets = sorted(set([
            f_low,
            (f_low + f_high) / 2,
            f_high,
            worst_pt["freq_ghz"],
            best_pt["freq_ghz"],
        ]))

    for f_target in targets:
        if f_low <= f_target <= f_high:
            closest = min(
                band_data, key=lambda d: abs(d["freq_ghz"] - f_target)
            )
            # Classify match quality by return loss
            rl = closest["return_loss_db"]
            if rl > 15:
                match_quality = "excellent"
            elif rl > 10:
                match_quality = "good"
            elif rl > 7:
                match_quality = "marginal"
            elif rl > 3:
                match_quality = "poor"
            else:
                match_quality = "very_poor"

            detail_points.append({
                "freq_ghz": round(closest["freq_ghz"], 4),
                "s11_db": round(closest["s11_db"], 2),
                "vswr": round(closest["vswr"], 3),
                "return_loss_db": round(rl, 2),
                "match_quality": match_quality,
            })

    return {
        "name": band["name"],
        "status": "PASS" if passed else "FAIL",
        "target_vswr": target_vswr,
        "target_s11_db": round(target_s11, 2),
        "worst_vswr": round(worst_pt["vswr"], 3),
        "worst_s11_db": round(worst_pt["s11_db"], 2),
        "worst_freq_ghz": round(worst_pt["freq_ghz"], 4),
        "best_vswr": round(best_pt["vswr"], 3),
        "best_s11_db": round(best_pt["s11_db"], 2),
        "best_freq_ghz": round(best_pt["freq_ghz"], 4),
        "average_s11_db": round(avg_s11, 2),
        "nearest_resonance": nearest_res,
        "num_points": len(band_data),
        "recommendations": recommendations,
        "detail_points": detail_points,
    }


# ---------------------------------------------------------------------------
# VBA generation helpers
# ---------------------------------------------------------------------------


def _set_params_and_solve_vba(params: dict[str, float], export_path: str | None = None, port: int = 1) -> str:
    """Build raw VBA that sets parameters, solves, and optionally exports.

    Combines everything in a single ``add_to_history`` call.  This is
    necessary because:
    - ``RebuildOnParametricChange`` is rejected inside a structure macro
    - ``StoreParameter`` alone doesn't trigger a rebuild
    - ``Solver.Start`` triggers the rebuild automatically before solving

    The "Results May Get Incompatible" dialog is handled by the
    background DialogWatcher.
    """
    lines = []
    for name, value in params.items():
        lines.append(f'StoreParameter "{name}", "{value}"')
    lines.append("Solver.Start")
    if export_path:
        safe_path = export_path.replace("\\", "/")
        tree_path = f"1D Results\\S-Parameters\\S{port},{port}"
        lines.append("")
        lines.append(f'SelectTreeItem "{tree_path}"')
        lines.append("With ASCIIExport")
        lines.append("  .Reset")
        lines.append(f'  .FileName "{safe_path}"')
        lines.append('  .SetfileType "csv"')
        lines.append("  .Execute")
        lines.append("End With")
    return "\n".join(lines)


def _set_params_vba(params: dict[str, float]) -> str:
    """Build raw VBA for just StoreParameter calls (for final application)."""
    lines = []
    for name, value in params.items():
        lines.append(f'StoreParameter "{name}", "{value}"')
    return "\n".join(lines)


def _run_solver_vba() -> str:
    """Build raw VBA to start the time-domain solver.

    Note: Solver.Start cannot run inside schematic.execute_vba_code()
    (structure macro context). Must use model3d.add_to_history() instead.
    """
    return "Solver.Start"


def _export_s11_vba(filepath: str, port: int = 1) -> str:
    """Build raw VBA to export S11 via ASCIIExport.

    Note: ASCIIExport doesn't work in schematic.execute_vba_code() context.
    Must use model3d.add_to_history() instead.
    """
    safe_path = filepath.replace("\\", "/")
    tree_path = f"1D Results\\S-Parameters\\S{port},{port}"
    return (
        f'SelectTreeItem "{tree_path}"\n'
        "With ASCIIExport\n"
        "  .Reset\n"
        f'  .FileName "{safe_path}"\n'
        '  .SetfileType "csv"\n'
        "  .Execute\n"
        "End With"
    )


def _solve_and_export_vba(filepath: str, port: int = 1) -> str:
    """Build raw VBA that runs solver then exports S11.

    Combines both operations in a single add_to_history call to minimize
    history bloat during optimization.
    """
    safe_path = filepath.replace("\\", "/")
    tree_path = f"1D Results\\S-Parameters\\S{port},{port}"
    return (
        "Solver.Start\n"
        "\n"
        f'SelectTreeItem "{tree_path}"\n'
        "With ASCIIExport\n"
        "  .Reset\n"
        f'  .FileName "{safe_path}"\n'
        '  .SetfileType "csv"\n'
        "  .Execute\n"
        "End With"
    )


# ---------------------------------------------------------------------------
# Nelder-Mead simplex optimizer (no scipy dependency)
# ---------------------------------------------------------------------------


def _build_initial_simplex(
    x0: list[float],
    bounds: list[tuple[float, float]],
) -> list[list[float]]:
    """Build initial Nelder-Mead simplex (N+1 vertices for N parameters).

    Each vertex perturbs one parameter by ~10% of its range from x0,
    clamped to bounds.
    """
    n = len(x0)
    simplex = [list(x0)]  # First vertex is the initial point

    for i in range(n):
        vertex = list(x0)
        span = bounds[i][1] - bounds[i][0]
        delta = 0.25 * span  # 25% of range for meaningful exploration
        # Perturb away from nearest bound to maximise exploration
        mid = (bounds[i][0] + bounds[i][1]) / 2.0
        if x0[i] >= mid:
            vertex[i] = x0[i] - delta
        else:
            vertex[i] = x0[i] + delta
        # Clamp to bounds
        vertex[i] = max(bounds[i][0], min(bounds[i][1], vertex[i]))
        simplex.append(vertex)

    return simplex


def _clamp_to_bounds(
    point: list[float],
    bounds: list[tuple[float, float]],
) -> list[float]:
    """Clamp each coordinate to its bounds."""
    return [max(lo, min(hi, v)) for v, (lo, hi) in zip(point, bounds)]


def _centroid(simplex: list[list[float]], exclude_idx: int) -> list[float]:
    """Compute centroid of all simplex vertices except exclude_idx."""
    n = len(simplex[0])
    m = len(simplex) - 1  # Number of points to average
    c = [0.0] * n
    for i, vertex in enumerate(simplex):
        if i == exclude_idx:
            continue
        for j in range(n):
            c[j] += vertex[j]
    return [v / m for v in c]


def _reflect(centroid: list[float], worst: list[float], alpha: float = 1.0) -> list[float]:
    """Reflect worst point through centroid."""
    return [centroid[j] + alpha * (centroid[j] - worst[j]) for j in range(len(centroid))]


def _expand(centroid: list[float], reflected: list[float], gamma: float = 2.0) -> list[float]:
    """Expand reflected point further from centroid."""
    return [centroid[j] + gamma * (reflected[j] - centroid[j]) for j in range(len(centroid))]


def _contract(centroid: list[float], point: list[float], rho: float = 0.5) -> list[float]:
    """Contract point toward centroid."""
    return [centroid[j] + rho * (point[j] - centroid[j]) for j in range(len(centroid))]


def _shrink(simplex: list[list[float]], best_idx: int, sigma: float = 0.5) -> list[list[float]]:
    """Shrink all vertices toward the best vertex."""
    best = simplex[best_idx]
    new_simplex = []
    for i, vertex in enumerate(simplex):
        if i == best_idx:
            new_simplex.append(list(vertex))
        else:
            new_simplex.append([
                best[j] + sigma * (vertex[j] - best[j])
                for j in range(len(vertex))
            ])
    return new_simplex


async def _optimization_loop(
    client: CSTClient,
    params_spec: list[dict],
    bands: list[dict],
    max_iterations: int,
    port: int,
) -> dict:
    """Run the Nelder-Mead optimization loop in connected mode.

    For each simplex vertex evaluation:
    1. Set parameters via execute_vba_silent (no history entry)
    2. Run solver via Python API run_solver() (no history entry)
    3. Export S11 via Python API export_result() (no history entry)
    4. Parse S11 and compute cost

    Only the final best-parameter application uses add_to_history.
    """
    len(params_spec)
    param_names = [p["name"] for p in params_spec]
    x0 = [p["initial"] for p in params_spec]
    bounds = [(p["min"], p["max"]) for p in params_spec]

    # Build initial simplex
    simplex = _build_initial_simplex(x0, bounds)
    costs: list[float] = []
    history: list[dict] = []

    # Delete any stale results up front to prevent dialog popups
    client.delete_results()

    # Start dialog watcher to auto-dismiss any popups during the loop
    client.start_dialog_watcher()

    # Temp file for S11 export
    work_dir = client._config.work_dir or tempfile.gettempdir()
    s11_file = os.path.join(work_dir, "_optim_s11_temp.csv").replace("\\", "/")

    # Helper: evaluate a parameter set
    eval_count = 0

    async def evaluate(x: list[float]) -> tuple[float, list[dict]]:
        nonlocal eval_count
        eval_count += 1

        # Clamp to bounds
        x = _clamp_to_bounds(x, bounds)
        params = dict(zip(param_names, x))

        # Use Python API: StoreParameter → DeleteResults → Rebuild → solve → export
        # This avoids history bloat and ensures the geometry actually rebuilds.
        result = client.set_params_rebuild_solve(params, export_path=s11_file, port=port)
        if result.get("status") == "error":
            logger.error("Solve iteration failed: %s", result.get("message"))
            return 100.0, []

        # Parse and evaluate
        try:
            freqs, s11_db = _parse_s11_data(s11_file)
            cost, band_results = _compute_cost(freqs, s11_db, bands)
            return cost, band_results
        except Exception as e:
            logger.error("Parse/eval error: %s", e)
            return 100.0, []

    # Evaluate initial simplex
    for vertex in simplex:
        cost, _ = await evaluate(vertex)
        costs.append(cost)

    # Track best
    best_idx = costs.index(min(costs))
    best_cost = costs[best_idx]
    best_params = dict(zip(param_names, simplex[best_idx]))

    history.append({
        "iteration": 0,
        "eval_count": eval_count,
        "best_cost": round(best_cost, 4),
        "best_params": {k: round(v, 4) for k, v in best_params.items()},
    })

    logger.info("Optimization start: cost=%.4f params=%s", best_cost, best_params)

    # Nelder-Mead iterations
    for iteration in range(1, max_iterations + 1):
        # Sort simplex by cost
        order = sorted(range(len(costs)), key=lambda i: costs[i])
        simplex = [simplex[i] for i in order]
        costs = [costs[i] for i in order]

        best_idx_local = 0
        worst_idx = len(simplex) - 1
        second_worst_idx = worst_idx - 1

        f_best = costs[best_idx_local]
        f_worst = costs[worst_idx]
        f_second_worst = costs[second_worst_idx]

        # Centroid of all except worst
        c = _centroid(simplex, worst_idx)

        # Reflect
        xr = _clamp_to_bounds(_reflect(c, simplex[worst_idx]), bounds)
        fr, _ = await evaluate(xr)

        if f_best <= fr < f_second_worst:
            # Accept reflection
            simplex[worst_idx] = xr
            costs[worst_idx] = fr
        elif fr < f_best:
            # Try expansion
            xe = _clamp_to_bounds(_expand(c, xr), bounds)
            fe, _ = await evaluate(xe)
            if fe < fr:
                simplex[worst_idx] = xe
                costs[worst_idx] = fe
            else:
                simplex[worst_idx] = xr
                costs[worst_idx] = fr
        else:
            # Contraction
            if fr < f_worst:
                # Outside contraction
                xc = _clamp_to_bounds(_contract(c, xr), bounds)
            else:
                # Inside contraction
                xc = _clamp_to_bounds(_contract(c, simplex[worst_idx]), bounds)
            fc, _ = await evaluate(xc)
            if fc < min(fr, f_worst):
                simplex[worst_idx] = xc
                costs[worst_idx] = fc
            else:
                # Shrink
                simplex = _shrink(simplex, best_idx_local)
                costs = []
                for vertex in simplex:
                    cost, _ = await evaluate(vertex)
                    costs.append(cost)

        # Update best
        current_best_idx = costs.index(min(costs))
        current_best_cost = costs[current_best_idx]
        if current_best_cost < best_cost:
            best_cost = current_best_cost
            best_params = dict(zip(param_names, simplex[current_best_idx]))

        history.append({
            "iteration": iteration,
            "eval_count": eval_count,
            "best_cost": round(best_cost, 4),
            "best_params": {k: round(v, 4) for k, v in best_params.items()},
        })

        logger.info(
            "Iter %d: cost=%.4f evals=%d params=%s",
            iteration, best_cost, eval_count, best_params,
        )

        # Convergence check: cost is 0 (all bands pass)
        if best_cost == 0.0:
            logger.info("All bands pass — converged at iteration %d", iteration)
            break

    # Apply best parameters + final solve + export
    # Use add_to_history for the final application so it's visible in the project
    final_params_vba = _set_params_vba(best_params)
    client.execute_vba(final_params_vba, history_label="optimization_best_params")

    # Then do a proper rebuild + solve + export via Python API
    client.set_params_rebuild_solve(best_params, export_path=s11_file, port=port)

    # Final evaluation
    try:
        freqs, s11_db = _parse_s11_data(s11_file)
        final_cost, final_bands = _compute_cost(freqs, s11_db, bands)
        resonances = _find_resonances(freqs, s11_db)
    except Exception:
        final_cost = best_cost
        final_bands = []
        resonances = []

    # Clean up temp file
    try:
        os.remove(s11_file)
    except OSError:
        pass

    # Stop dialog watcher and collect its log
    watcher_result = client.stop_dialog_watcher()
    dialog_log = watcher_result.get("log", [])

    overall = "PASS" if final_cost == 0.0 else "FAIL"

    result: dict = {
        "status": "optimized",
        "overall": overall,
        "best_cost": round(best_cost, 4),
        "best_params": {k: round(v, 4) for k, v in best_params.items()},
        "total_evaluations": eval_count,
        "iterations": len(history) - 1,
        "bands": final_bands,
        "resonances": resonances,
        "history": history,
    }
    if dialog_log:
        result["dismissed_dialogs"] = len(dialog_log)
        result["dialog_log"] = dialog_log

    return result


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def _handle_evaluate(args: dict, client: CSTClient) -> dict:
    """Handle cst_evaluate_antenna."""
    bands = args["bands"]
    port = int(args.get("port", 1))

    if not client.connected or not client.has_project:
        # Offline mode: return VBA for manual evaluation
        script = VBAScript()
        script.add_comment("Export S-parameters for antenna evaluation")
        export_vba = _export_s11_vba("C:/cst_projects/s11_eval.csv", port)
        script.add_raw(export_vba)
        return {
            "status": "offline",
            "vba": script.build(),
            "message": (
                "Run this VBA in CST to export S11 data, then use the exported "
                "CSV to evaluate VSWR against your band targets manually."
            ),
            "bands": [
                {
                    "name": b["name"],
                    "f_low_ghz": b["f_low_ghz"],
                    "f_high_ghz": b["f_high_ghz"],
                    "vswr_target": b.get("vswr_target", 2.5),
                    "s11_threshold_db": round(vswr_to_s11(b.get("vswr_target", 2.5)), 2),
                }
                for b in bands
            ],
        }

    # Connected mode: export, parse, evaluate
    work_dir = client._config.work_dir or tempfile.gettempdir()
    s11_file = os.path.join(work_dir, "_eval_s11_temp.csv").replace("\\", "/")

    # Export S11 via Python API (no history entry, view-independent)
    tree_path = f"1D Results\\S-Parameters\\S{port},{port}"
    result = client.export_result(tree_path, s11_file)
    if result.get("status") == "error":
        return {"status": "error", "message": f"Export failed: {result.get('message')}"}

    # Parse
    try:
        freqs, s11_db = _parse_s11_data(s11_file)
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse S11 data: {e}"}

    # Evaluate
    band_results = _evaluate_bands(freqs, s11_db, bands)
    resonances = _find_resonances(freqs, s11_db)

    overall = "PASS" if all(b["status"] == "PASS" for b in band_results) else "FAIL"

    # Clean up
    try:
        os.remove(s11_file)
    except OSError:
        pass

    return {
        "status": "evaluated",
        "overall": overall,
        "bands": band_results,
        "resonances": resonances,
        "frequency_range_ghz": [round(freqs[0], 4), round(freqs[-1], 4)],
        "num_points": len(freqs),
    }


async def _handle_refine(args: dict, client: CSTClient) -> dict:
    """Handle cst_refine_antenna."""
    params_spec = args["parameters"]
    bands = args["bands"]
    max_iterations = int(args.get("max_iterations", 20))
    port = int(args.get("port", 1))

    # Validate
    for p in params_spec:
        if p["min"] >= p["max"]:
            return {
                "status": "error",
                "message": f"Parameter '{p['name']}' min ({p['min']}) must be < max ({p['max']})",
            }
        if not (p["min"] <= p["initial"] <= p["max"]):
            return {
                "status": "error",
                "message": (
                    f"Parameter '{p['name']}' initial ({p['initial']}) "
                    f"must be within [{p['min']}, {p['max']}]"
                ),
            }

    if max_iterations < 1:
        return {"status": "error", "message": "max_iterations must be >= 1"}

    if not client.connected or not client.has_project:
        # Offline: fall back to CST built-in optimizer VBA
        script = VBAScript()
        script.add_comment("Antenna optimization via CST built-in optimizer")

        vba = VBABuilder("Optimizer").call("Reset")
        vba.set("SetOptimizerType", "Nelder Mead")
        vba.set_number("SetMaxEvaluations", max_iterations * (len(params_spec) + 1))

        # Use first band's target for the goal
        first_band = bands[0]
        vswr_to_s11(first_band.get("vswr_target", 2.5))
        tree_path = f"1D Results\\S-Parameters\\S{port},{port}"
        vba.set("SetGoalType", "Min")
        vba.set("SetGoalResult", tree_path)
        vba.call("InitGoal")

        for p in params_spec:
            vba.call_with_args("AddParameter", p["name"], str(p["min"]), str(p["max"]))

        vba.call("Start")
        script.add_block(vba)

        return {
            "status": "offline",
            "vba": script.build(),
            "message": (
                "Run this VBA in CST to optimize using the built-in optimizer. "
                "In connected mode, the MCP server runs a custom Nelder-Mead loop "
                "with per-band VSWR cost evaluation."
            ),
        }

    # Connected mode: run optimization loop
    return await _optimization_loop(client, params_spec, bands, max_iterations, port)


async def _handle_analyze_impedance(args: dict, client: CSTClient) -> dict:
    """Handle cst_analyze_impedance.

    Exports S11 data and analyzes impedance match quality per band.
    Uses S-parameter magnitude (dB) to compute VSWR, return loss,
    detect resonances, and provide design recommendations.

    Note: CST's Z-parameter tree items exported via ASCIIExport return
    dB-like values rather than actual impedance in Ohms.  We therefore
    use the reliable S-parameter export path and derive all metrics from
    S11 magnitude.  Full R+jX analysis requires complex S-parameter data
    (future enhancement via ProjectFile API).
    """
    bands = args["bands"]
    z0 = float(args.get("z0", 50))
    port = int(args.get("port", 1))
    sample_freqs = args.get("sample_frequencies_ghz")

    if not client.connected or not client.has_project:
        # Offline mode: return VBA for S-parameter extraction
        vba = _build_impedance_vba(port)
        return {
            "status": "offline",
            "vba": vba,
            "z0_ohm": z0,
            "message": (
                "Run this VBA in CST to export S11 data from "
                "'1D Results\\S-Parameters\\S{p},{p}'. After export, "
                "compute |Γ| = 10^(S11_dB/20), VSWR = (1+|Γ|)/(1-|Γ|). "
                "VSWR should be ≤ target across each band."
            ).format(p=port),
            "analysis_guidance": {
                "resonance_below": (
                    "Resonance below band: shorten the resonant path, "
                    "reduce patch/slot dimensions."
                ),
                "resonance_above": (
                    "Resonance above band: lengthen the resonant path, "
                    "increase patch/slot dimensions."
                ),
                "narrow_bandwidth": (
                    "Resonance in band but too narrow: increase substrate "
                    "height, widen conductors, add parasitic elements."
                ),
                "no_resonance": (
                    "No resonance near band: add a dedicated resonant "
                    "element or coupled resonator for this frequency."
                ),
            },
            "bands": [
                {
                    "name": b["name"],
                    "f_low_ghz": b["f_low_ghz"],
                    "f_high_ghz": b["f_high_ghz"],
                    "vswr_target": b.get("vswr_target", 2.5),
                    "s11_threshold_db": round(
                        vswr_to_s11(b.get("vswr_target", 2.5)), 2
                    ),
                }
                for b in bands
            ],
        }

    # Connected mode: export S11 via Python API
    work_dir = client._config.work_dir or tempfile.gettempdir()
    s11_file = os.path.join(work_dir, "_impedance_s11_temp.csv").replace(
        "\\", "/"
    )

    tree_path = f"1D Results\\S-Parameters\\S{port},{port}"
    result = client.export_result(tree_path, s11_file)
    if result.get("status") == "error":
        return {
            "status": "error",
            "message": (
                f"Export S11 failed: {result.get('message')}. "
                "Ensure a simulation has been completed."
            ),
        }

    # Parse S11 data
    try:
        freqs, s11_db = _parse_s11_data(s11_file)
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse S11 data: {e}"}
    finally:
        try:
            os.remove(s11_file)
        except OSError:
            pass

    # Detect resonances across full frequency range
    resonances = _find_resonances(freqs, s11_db)

    # Analyze each band
    band_results = []
    all_recommendations = []
    for band in bands:
        br = _analyze_impedance_band(
            freqs, s11_db, band, z0, sample_freqs, resonances
        )
        band_results.append(br)
        if "recommendations" in br:
            all_recommendations.extend(br["recommendations"])

    overall = "PASS" if all(
        b.get("status") == "PASS" for b in band_results
    ) else "FAIL"

    return {
        "status": "analyzed",
        "overall": overall,
        "z0_ohm": z0,
        "port": port,
        "frequency_range_ghz": [round(freqs[0], 4), round(freqs[-1], 4)],
        "num_points": len(freqs),
        "resonances": resonances,
        "bands": band_results,
        "summary_recommendations": all_recommendations,
        "note": (
            "Analysis is based on S11 magnitude (dB). VSWR and return loss "
            "are accurate. Full R+jX impedance requires complex S-parameter "
            "data (future enhancement)."
        ),
    }


def _build_impedance_vba(port: int) -> str:
    """Build VBA to export S-parameter data for offline impedance analysis.

    Exports S11 magnitude (dB) which can be used to compute |Γ|, VSWR,
    and return loss.  CST's Z-parameter tree items return dB-like values
    via ASCIIExport rather than actual impedance in Ohms, so we use the
    reliable S-parameter export path instead.
    """
    script = VBAScript()
    script.add_comment(f"Export S{port},{port} for impedance match analysis")
    script.add_comment("Compute: |Gamma| = 10^(S11_dB/20)")
    script.add_comment("         VSWR = (1 + |Gamma|) / (1 - |Gamma|)")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "1D Results\\S-Parameters\\S{port},{port}"',
        "  With ASCIIExport",
        "    .Reset",
        f'    .FileName "C:/cst_projects/s{port}{port}_impedance.csv"',
        '    .SetfileType "csv"',
        "    .Execute",
        "  End With",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[..., Any]] = {
    "cst_evaluate_antenna": _handle_evaluate,
    "cst_analyze_impedance": _handle_analyze_impedance,
    "cst_refine_antenna": _handle_refine,
}


def _text(data: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


async def handle(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle an optimization tool call."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return _text({"status": "error", "message": f"Unknown optimization tool: {name}"})

    try:
        result = await handler(arguments, client)
        return _text(result)
    except Exception as e:
        return _text({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_optimization_tools(server: Server, client: CSTClient) -> None:
    """Register optimization tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
