"""Pure numeric helpers for 1D publication figures (no matplotlib, no CST).

All functions take plain Python sequences so they are trivially testable.
Frequencies are in GHz throughout this module.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DB_FLOOR = -300.0  # finite stand-in for |S| == 0 (never reported as a metric)


def to_db(values: Sequence[complex]) -> list[float]:
    return [20 * math.log10(abs(v)) if abs(v) > 0 else DB_FLOOR for v in values]


def vswr(values: Sequence[complex]) -> list[float]:
    """VSWR from reflection; NaN where |Gamma| >= 1 (undefined)."""
    out = []
    for v in values:
        m = abs(v)
        out.append((1 + m) / (1 - m) if m < 1 else math.nan)
    return out


def impedance(values: Sequence[complex], z0: float | Sequence[complex] = 50.0) -> list[complex]:
    """Input impedance Z = Z0 (1 + G) / (1 - G); NaN where G == 1."""
    n = len(values)
    z0s = [complex(z0)] * n if isinstance(z0, (int, float, complex)) else [complex(z) for z in z0]
    if len(z0s) != n:
        raise ValueError("z0 length must match the reflection curve")
    out = []
    for g, z in zip(values, z0s):
        den = 1 - g
        out.append(z * (1 + g) / den if abs(den) > 1e-15 else complex(math.nan, math.nan))
    return out


def phase_deg(values: Sequence[complex], unwrap: bool = False) -> list[float]:
    ph = [math.atan2(v.imag, v.real) for v in values]
    if unwrap:
        for j in range(1, len(ph)):
            ph[j] = ph[j - 1] + (ph[j] - ph[j - 1] + math.pi) % (2 * math.pi) - math.pi
    return [math.degrees(p) for p in ph]


def crop(
    f: Sequence[float], *series: Sequence[Any], freq_range: Sequence[float] | None = None
) -> tuple[list[float], ...]:
    """Keep samples with fmin <= f <= fmax (GHz); returns (f, *series)."""
    if not freq_range:
        return (list(f), *[list(s) for s in series])
    lo, hi = float(freq_range[0]), float(freq_range[1])
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        raise ValueError("freq_range_ghz must be [fmin, fmax] with fmax > fmin")
    idx = [j for j, x in enumerate(f) if lo <= x <= hi]
    return ([f[j] for j in idx], *[[s[j] for j in idx] for s in series])


def _crossing(f0: float, f1: float, y0: float, y1: float, level: float) -> float:
    if y1 == y0:
        return f0
    return f0 + (f1 - f0) * (level - y0) / (y1 - y0)


def bandwidth_metrics(
    f_ghz: Sequence[float], s_db: Sequence[float], threshold_db: float = -10.0
) -> dict[str, Any]:
    """Resonance and every contiguous band with s_db <= threshold_db.

    Band edges are linearly interpolated in dB between neighbouring samples.
    Fractional bandwidth uses the arithmetic band centre:
    FBW = 100 * (f_high - f_low) / ((f_high + f_low) / 2).
    Edges that touch the first/last sample are flagged as truncated (the true
    band may extend beyond the simulated range).
    """
    f = [float(x) for x in f_ghz]
    y = [float(v) for v in s_db]
    if len(f) != len(y):
        raise ValueError("Frequency and dB arrays differ in length")
    if len(f) < 2:
        raise ValueError("Need at least two samples")
    if any(b <= a for a, b in zip(f, f[1:])):
        raise ValueError("Frequency samples must be strictly increasing")
    if not math.isfinite(threshold_db):
        raise ValueError("threshold_db must be finite")
    j_min = min(range(len(y)), key=y.__getitem__)
    # Parabolic refinement of the minimum on a uniform-enough local grid.
    f_res, y_res = f[j_min], y[j_min]
    if 0 < j_min < len(y) - 1:
        x0, x1, x2 = f[j_min - 1], f[j_min], f[j_min + 1]
        a, b, c = y[j_min - 1], y[j_min], y[j_min + 1]
        den = (x0 - x1) * (x0 - x2) * (x1 - x2)
        if den:
            A = (x2 * (b - a) + x1 * (a - c) + x0 * (c - b)) / den
            B = (x2 * x2 * (a - b) + x1 * x1 * (c - a) + x0 * x0 * (b - c)) / den
            if A > 0:
                xv = -B / (2 * A)
                if x0 <= xv <= x2:
                    C = a - A * x0 * x0 - B * x0
                    f_res, y_res = xv, min(y[j_min], A * xv * xv + B * xv + C)
    bands: list[dict[str, Any]] = []
    inside = y[0] <= threshold_db
    start = f[0] if inside else None
    start_j = 0
    for j in range(1, len(f)):
        now = y[j] <= threshold_db
        if now != inside:
            edge = _crossing(f[j - 1], f[j], y[j - 1], y[j], threshold_db)
            if now:
                start, start_j = edge, j
            else:
                bands.append(_band(start, edge, f, y, start_j, j - 1))
                start = None
            inside = now
    if start is not None:
        bands.append(_band(start, f[-1], f, y, start_j, len(f) - 1, upper_truncated=True))
    for band in bands:
        if band["f_low"] == f[0] and y[0] <= threshold_db:
            band["lower_truncated"] = True
    return {
        "f_res_ghz": f_res,
        "s11_min_db": y_res,
        "sample_min": {"f_ghz": f[j_min], "db": y[j_min]},
        "threshold_db": threshold_db,
        "matched": y[j_min] <= threshold_db,
        "bands": bands,
        "total_bw_mhz": sum(b["bw_mhz"] for b in bands),
        "fbw_definition": "100*(f_high-f_low)/((f_high+f_low)/2); edges linearly interpolated in dB",
    }


def _band(lo, hi, f, y, j0, j1, upper_truncated=False) -> dict[str, Any]:
    j_min = min(range(j0, j1 + 1), key=y.__getitem__) if j1 >= j0 else j0
    fc = (lo + hi) / 2
    return {
        "f_low": lo,
        "f_high": hi,
        "f_center": fc,
        "bw_mhz": (hi - lo) * 1e3,
        "fbw_pct": 100 * (hi - lo) / fc if fc > 0 else math.nan,
        "f_min_ghz": f[j_min],
        "s11_min_db": y[j_min],
        "lower_truncated": False,
        "upper_truncated": upper_truncated,
    }


_UNIT_SCALE_TO_GHZ = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0, "thz": 1e3}


def parse_overlay_csv(path: str | Path, freq_unit: str | None = None) -> dict[str, Any]:
    """Read measured ``freq, dB`` data (first two numeric columns).

    Delimiters: comma, semicolon, tab or whitespace. Comment lines starting
    with ``#``/``!``/``%`` and non-numeric header lines are skipped. The
    frequency unit comes from ``freq_unit``, else from a header token such as
    ``GHz``/``MHz``/``Hz``, else it is inferred from magnitude (reported).
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Overlay CSV not found: {p}")
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    headers: list[str] = []
    f: list[float] = []
    y: list[float] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line[0] in "#!%":
            headers.append(line)
            continue
        parts = [v.strip("\"'") for v in re.split(r"[,;\t ]+", line) if v]
        try:
            fx, fy = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            headers.append(line)
            continue
        if math.isfinite(fx) and math.isfinite(fy):
            f.append(fx)
            y.append(fy)
    if len(f) < 2:
        raise ValueError(f"{p.name}: fewer than two numeric freq,dB rows")
    unit_source = "argument"
    unit = (freq_unit or "").strip().lower()
    if not unit:
        m = re.search(r"(?<![a-z])([kmgt]?hz)(?![a-z])", " ".join(headers).lower())
        if m:
            unit, unit_source = m.group(1), "header"
    if not unit:
        top = max(abs(v) for v in f)
        unit = "hz" if top >= 1e6 else "mhz" if top >= 1e3 else "ghz"
        unit_source = "inferred_from_magnitude"
    if unit not in _UNIT_SCALE_TO_GHZ:
        raise ValueError(f"Unsupported freq_unit {freq_unit!r}")
    scale = _UNIT_SCALE_TO_GHZ[unit]
    pairs = sorted(zip((v * scale for v in f), y))
    return {
        "path": str(p),
        "f_ghz": [a for a, _ in pairs],
        "db": [b for _, b in pairs],
        "n": len(pairs),
        "freq_unit": unit,
        "freq_unit_source": unit_source,
    }


def run_labels(combos: dict[int, dict[str, Any]]) -> dict[int, str]:
    """Legend labels from the parameters that differ between runs."""
    if not combos:
        return {}
    keys = sorted({k for c in combos.values() for k in (c or {})})
    varying = [k for k in keys if len({repr((c or {}).get(k)) for c in combos.values()}) > 1]
    labels = {}
    for rid, combo in combos.items():
        if varying and combo:
            parts = [f"{k} = {_fmt(combo.get(k))}" for k in varying[:2]]
            labels[rid] = ", ".join(parts)
        else:
            labels[rid] = f"Run {rid}"
    return labels


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)
