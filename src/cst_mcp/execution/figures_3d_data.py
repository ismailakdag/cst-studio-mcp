"""Farfield ASCII parsing and pattern metrics for ``cst_plot_farfield``.

Parses the text written by CST's ``ASCIIExport`` for a selected farfield
plot (``Theta [deg.]  Phi [deg.]  Abs(Realized Gain)[dBi ] ...`` followed by a
dashed rule and whitespace-separated rows), CSV variants of it, and bare
numeric ``theta phi value`` tables. The result is a regular theta/phi grid in
dB plus optional polarization components, from which cuts and metrics
(peak, HPBW, F/B, SLL) are derived. Only numpy is required.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

_HEADER_TOKEN = re.compile(r"\s*([^\[\],;\t]+?)\s*\[([^\]]*)\]")
_NUM = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")

# Component name patterns -> canonical key.
_COMPONENTS: list[tuple[str, re.Pattern[str]]] = [
    ("theta", re.compile(r"^abs\s*\(\s*theta\s*\)$", re.I)),
    ("phi", re.compile(r"^abs\s*\(\s*phi\s*\)$", re.I)),
    ("horizontal", re.compile(r"^abs\s*\(\s*(hor|horiz|horizontal|comp1|azimuth|alpha)\s*\)$", re.I)),
    ("vertical", re.compile(r"^abs\s*\(\s*(ver|vert|verti|vertical|comp2|elevation|epsilon)\s*\)$", re.I)),
    ("copolar", re.compile(r"^abs\s*\(\s*(co|copol|copolar|co-pol)\s*\)$", re.I)),
    ("crosspolar", re.compile(r"^abs\s*\(\s*(cross|crosspol|crosspolar|cx|x-pol)\s*\)$", re.I)),
    ("left", re.compile(r"^abs\s*\(\s*left\s*\)$", re.I)),
    ("right", re.compile(r"^abs\s*\(\s*right\s*\)$", re.I)),
]

_QUANTITY_HINTS = [
    ("realized_gain", re.compile(r"realized\s*gain|realised\s*gain|r\.?\s*gain|grlz|g_?rlz", re.I)),
    ("gain", re.compile(r"gain", re.I)),
    ("directivity", re.compile(r"dir", re.I)),
    ("efield", re.compile(r"\be\b|e-?field|abs\s*\(\s*e\s*\)", re.I)),
]

QUANTITY_LABEL = {
    "realized_gain": "Realized gain",
    "gain": "Gain",
    "directivity": "Directivity",
    "efield": "|E|",
    "unknown": "Pattern",
}


@dataclass
class FarfieldGrid:
    """Farfield on a regular grid: arrays indexed ``[phi, theta]`` in dB."""

    theta: np.ndarray  # deg, 0..180 ascending
    phi: np.ndarray  # deg, 0..360 (exclusive) ascending
    total_db: np.ndarray
    components_db: dict[str, np.ndarray] = field(default_factory=dict)
    quantity: str = "unknown"
    unit: str = "dBi"
    column: str = ""
    columns: list[str] = field(default_factory=list)
    n_rows: int = 0
    scale_input: str = "db"
    header_found: bool = False
    frequency_ghz: float | None = None

    @property
    def label(self) -> str:
        return QUANTITY_LABEL.get(self.quantity, "Pattern")


def _split(line: str) -> list[str]:
    if ";" in line:
        parts = line.split(";")
    elif "," in line:
        parts = line.split(",")
    else:
        parts = line.split()
    return [p.strip().strip('"').strip() for p in parts if p.strip().strip('"').strip()]


def _is_numeric_row(parts: list[str]) -> bool:
    return len(parts) >= 3 and all(_NUM.match(p) for p in parts[:3])


def _parse_header(line: str) -> list[tuple[str, str]]:
    stripped = line.strip().lstrip("#!%").strip()
    tokens = [(m.group(1).strip().strip('"').strip(), m.group(2).strip()) for m in _HEADER_TOKEN.finditer(stripped)]
    if len(tokens) >= 3:
        return tokens
    # Unit-less header: "theta phi gain" / "Theta,Phi,Abs(Gain) dBi"
    parts = _split(stripped)
    if len(parts) >= 3 and not _is_numeric_row(parts) and re.match(r"(?i)^theta", parts[0]):
        out = []
        for p in parts:
            m = re.match(r"^(.*?)\s*[\(\[]\s*(dBi|dBV/m|dB|V/m|W/sr)\s*[\)\]]$", p, re.I) or re.match(
                r"^(.*?)[\s_]+(dBi|dBV/m|dB|V/m|W/sr)$", p, re.I
            )
            out.append((m.group(1).strip(), m.group(2)) if m else (p, ""))
        return out
    return []


def _unit_is_db(unit: str) -> bool:
    return unit.strip().lower().startswith("db")


def _is_field_unit(unit: str) -> bool:
    u = unit.strip().lower()
    return "v/m" in u or u in {"v", "dbv", "dbuv/m"}


def _to_db(values: np.ndarray, unit: str) -> np.ndarray:
    if _unit_is_db(unit):
        return values.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        factor = 20.0 if _is_field_unit(unit) else 10.0
        out = factor * np.log10(np.abs(values.astype(float)))
    out[~np.isfinite(out)] = -300.0
    return out


def _quantity_from(name: str, unit: str) -> str:
    for key, rx in _QUANTITY_HINTS:
        if rx.search(name):
            if key == "efield" or _is_field_unit(unit):
                return "efield"
            return key
    return "efield" if _is_field_unit(unit) else "unknown"


def parse_farfield_ascii(
    path: str | Path | None = None,
    *,
    text: str | None = None,
    quantity_hint: str | None = None,
    assume_linear: bool | None = None,
) -> FarfieldGrid:
    """Parse a CST farfield ASCII export into a :class:`FarfieldGrid`.

    Header variants handled: CST ``Name [unit]`` columns with dashed rule,
    ``#``-commented headers, CSV/semicolon separated, unit-less
    ``theta phi value`` headers, and headerless numeric tables (columns taken
    as theta, phi, value[, ...]). Values in ``[dBi]``/``[dB]`` stay in dB;
    linear directivity/gain (empty unit) is converted with 10·log10 and
    field magnitudes (``V/m``) with 20·log10. Rows with theta > 180° (Theta360
    exports) or negative phi are folded onto theta ∈ [0, 180], phi ∈ [0, 360).
    Raises ValueError with a human-readable reason on unusable input.
    """
    if text is None:
        if path is None:
            raise ValueError("path or text is required")
        p = Path(path)
        if not p.is_file():
            raise ValueError(f"Farfield data file not found: {p}")
        raw = p.read_bytes()
        text = raw.decode("utf-8", errors="replace") if not raw.startswith(b"\xff\xfe") else raw.decode("utf-16")
    header: list[tuple[str, str]] = []
    rows: list[list[float]] = []
    frequency_ghz: float | None = None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.fullmatch(r"[-=_\s]+", s):
            continue
        fm = re.search(r"(?i)(?:frequency|f)\s*[=:]\s*([-+]?\d*\.?\d+)\s*(ghz|mhz|hz)?", s)
        parts = _split(s.lstrip("#!%"))
        if _is_numeric_row(parts) and not s.startswith(("#", "!", "%")):
            nums: list[float] = []
            for tok in parts:
                if _NUM.match(tok):
                    nums.append(float(tok))
                else:
                    break
            rows.append(nums)
            continue
        if fm and frequency_ghz is None:
            try:
                val = float(fm.group(1))
                unit = (fm.group(2) or "ghz").lower()
                frequency_ghz = val / 1e3 if unit == "mhz" else val / 1e9 if unit == "hz" else val
            except ValueError:
                pass
        if not header and not rows:
            header = _parse_header(s)
    if not rows:
        raise ValueError("No numeric farfield rows found (expected columns Theta Phi Value ...)")
    width = min(len(r) for r in rows)
    if width < 3:
        raise ValueError("Farfield rows need at least 3 numeric columns (theta, phi, value)")
    data = np.array([r[:width] for r in rows], dtype=float)

    names = [h[0] for h in header][:width] if header else []
    units = [h[1] for h in header][:width] if header else []
    if len(names) < width:
        names += [f"col{i}" for i in range(len(names), width)]
        units += [""] * (width - len(units))
    if not header:
        names[0], names[1], names[2] = "Theta", "Phi", "Value"
        units[0], units[1] = "deg.", "deg."
        units[2] = "" if assume_linear else "dB"

    # Locate theta/phi columns (CST writes theta first) and the main value.
    ti = next((i for i, n in enumerate(names) if re.fullmatch(r"(?i)theta", n.strip())), 0)
    pi = next((i for i, n in enumerate(names) if re.fullmatch(r"(?i)phi", n.strip())), 1)
    value_cols = [i for i in range(width) if i not in (ti, pi)]
    abs_cols = [i for i in value_cols if re.match(r"(?i)^abs", names[i]) or names[i] == "Value"]
    comp_idx: dict[str, int] = {}
    for i in value_cols:
        for key, rx in _COMPONENTS:
            if rx.match(names[i].strip()) and key not in comp_idx:
                comp_idx[key] = i
    main_candidates = [i for i in abs_cols if i not in comp_idx.values()] or abs_cols or value_cols
    mi = main_candidates[0]

    unit_main = units[mi]
    if assume_linear is True:
        unit_main = unit_main if not _unit_is_db(unit_main) else ""
    elif assume_linear is False and not _unit_is_db(unit_main):
        unit_main = "dB"
    quantity = quantity_hint or _quantity_from(names[mi], unit_main)

    theta = data[:, ti].copy()
    phi = data[:, pi].copy()
    over = theta > 180.0 + 1e-9
    theta[over] = 360.0 - theta[over]
    phi[over] = phi[over] + 180.0
    neg = theta < -1e-9
    theta[neg] = -theta[neg]
    phi[neg] = phi[neg] + 180.0
    phi = np.mod(phi, 360.0)
    phi[np.isclose(phi, 360.0)] = 0.0

    th_u = np.unique(np.round(theta, 6))
    ph_u = np.unique(np.round(phi, 6))
    t_index = {v: k for k, v in enumerate(th_u)}
    p_index = {v: k for k, v in enumerate(ph_u)}
    ti_arr = np.array([t_index[v] for v in np.round(theta, 6)])
    pi_arr = np.array([p_index[v] for v in np.round(phi, 6)])

    def _grid(col: int, unit: str) -> np.ndarray:
        g = np.full((len(ph_u), len(th_u)), np.nan)
        g[pi_arr, ti_arr] = _to_db(data[:, col], unit)
        # Poles are phi-independent: fill missing pole samples from any phi.
        for k in (0, len(th_u) - 1):
            if th_u[k] in (0.0, 180.0):
                col_vals = g[:, k]
                if np.isnan(col_vals).any() and np.isfinite(col_vals).any():
                    col_vals[np.isnan(col_vals)] = np.nanmax(col_vals)
        return g

    total = _grid(mi, unit_main)
    comps = {}
    for key, i in comp_idx.items():
        u = units[i]
        if assume_linear is True and _unit_is_db(u):
            u = ""
        comps[key] = _grid(i, u if (u or not _unit_is_db(unit_main)) else unit_main)

    unit_label = unit_main if _unit_is_db(unit_main) else ("dBV/m" if _is_field_unit(unit_main) else "dBi")
    if quantity == "efield" and not _unit_is_db(unit_main):
        unit_label = "dBV/m"
    return FarfieldGrid(
        theta=th_u,
        phi=ph_u,
        total_db=total,
        components_db=comps,
        quantity=quantity,
        unit=unit_label or "dB",
        column=names[mi],
        columns=[f"{n} [{u}]" if u else n for n, u in zip(names, units)],
        n_rows=len(rows),
        scale_input="db" if _unit_is_db(unit_main) else "linear",
        header_found=bool(header),
        frequency_ghz=frequency_ghz,
    )


# ---------------------------------------------------------------------------
# Cuts and metrics
# ---------------------------------------------------------------------------


def _nearest(arr: np.ndarray, value: float, period: float | None = None) -> int:
    if period:
        d = np.abs((arr - value + period / 2) % period - period / 2)
    else:
        d = np.abs(arr - value)
    return int(np.argmin(d))


def value_at(grid: FarfieldGrid, theta: float, phi: float, arr: np.ndarray | None = None) -> float:
    arr = grid.total_db if arr is None else arr
    th = theta
    ph = phi
    if th > 180:
        th, ph = 360 - th, ph + 180
    if th < 0:
        th, ph = -th, ph + 180
    return float(arr[_nearest(grid.phi, ph % 360, 360.0), _nearest(grid.theta, th)])


@dataclass
class Cut:
    kind: str  # "phi" (constant phi, theta varies) or "theta" (constant theta)
    value: float
    angle: np.ndarray  # deg; -180..180 for phi cuts (signed theta), 0..360 for theta cuts
    total: np.ndarray
    components: dict[str, np.ndarray]
    label: str = ""


def parse_cut_spec(spec: Any) -> tuple[str, float]:
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return "phi", float(spec)
    if isinstance(spec, str):
        m = re.fullmatch(r"\s*(phi|theta)?\s*=?\s*([-+]?\d*\.?\d+)\s*(?:deg|°)?\s*", spec, re.I)
        if m:
            return (m.group(1) or "phi").lower(), float(m.group(2))
        low = spec.strip().lower()
        if low in {"e", "e-plane", "eplane"}:
            return "phi", 0.0
        if low in {"h", "h-plane", "hplane"}:
            return "phi", 90.0
        if low in {"azimuth", "horizon", "xy"}:
            return "theta", 90.0
    raise ValueError(f"Invalid cut {spec!r}: use a phi angle (number), 'phi=45' or 'theta=90'")


def extract_cut(grid: FarfieldGrid, kind: str, value: float) -> Cut:
    arrays = {"total": grid.total_db, **grid.components_db}
    if kind == "phi":
        i0 = _nearest(grid.phi, value % 360, 360.0)
        i1 = _nearest(grid.phi, (value + 180) % 360, 360.0)
        have_back = abs(((grid.phi[i1] - value - 180) + 180) % 360 - 180) < 1e-6 + (
            np.min(np.diff(grid.phi)) / 2 if len(grid.phi) > 1 else 0
        )
        th = grid.theta
        if have_back and len(grid.phi) > 1:
            angle = np.concatenate([-th[::-1], th[1:] if th[0] == 0 else th])
            out = {}
            for k, a in arrays.items():
                back = a[i1, ::-1]
                front = a[i0, 1:] if th[0] == 0 else a[i0, :]
                out[k] = np.concatenate([back, front])
            # drop duplicated ±180 endpoint
            if len(angle) > 1 and np.isclose(angle[0], -180) and np.isclose(angle[-1], 180):
                angle = angle[1:]
                out = {k: v[1:] for k, v in out.items()}
        else:
            angle = th.copy()
            out = {k: a[i0, :].copy() for k, a in arrays.items()}
        return Cut("phi", float(grid.phi[i0]), angle, out.pop("total"), out,
                   label=f"φ = {grid.phi[i0]:g}°")
    j = _nearest(grid.theta, value)
    out = {k: a[:, j].copy() for k, a in arrays.items()}
    return Cut("theta", float(grid.theta[j]), grid.phi.copy(), out.pop("total"), out,
               label=f"θ = {grid.theta[j]:g}°")


def _crossing(angle: np.ndarray, vals: np.ndarray, i_peak: int, level: float, step: int, circular: bool):
    n = len(vals)
    i = i_peak
    for _ in range(n - 1):
        j = i + step
        if circular:
            j %= n
        elif j < 0 or j >= n:
            return None
        if vals[j] < level:
            a0, a1 = angle[i], angle[j]
            if circular and step > 0 and a1 < a0:
                a1 += 360.0
            if circular and step < 0 and a1 > a0:
                a1 -= 360.0
            v0, v1 = vals[i], vals[j]
            f = 0.0 if v0 == v1 else (v0 - level) / (v0 - v1)
            return float(a0 + f * (a1 - a0))
        i = j
    return None


def beam_metrics(cut: Cut, threshold_db: float = 3.0) -> dict[str, Any]:
    vals = np.where(np.isfinite(cut.total), cut.total, -300.0)
    angle = cut.angle
    circular = cut.kind == "theta" or (len(angle) > 2 and angle[0] <= -180 + 1e-6 + (angle[1] - angle[0])
                                       and angle[-1] >= 180 - (angle[1] - angle[0]) - 1e-6)
    ip = int(np.argmax(vals))
    peak = float(vals[ip])
    level = peak - threshold_db
    left = _crossing(angle, vals, ip, level, -1, circular)
    right = _crossing(angle, vals, ip, level, +1, circular)
    hpbw = None if left is None or right is None else float(right - left)
    if hpbw is not None and hpbw <= 0:
        hpbw = None
    # Side-lobe level: walk down the main lobe to the first minimum each side.
    n = len(vals)

    def _step(i: int, step: int) -> int | None:
        j = i + step
        if circular:
            return j % n
        return j if 0 <= j < n else None

    # Main lobe = indices walked from the peak down to the first minimum each side.
    main = {ip}
    for step in (-1, 1):
        i = ip
        for _ in range(n // 2 if circular else n):
            j = _step(i, step)
            if j is None or vals[j] >= vals[i]:
                break
            main.add(j)
            i = j
    peaks = []
    for k in range(n):
        if k in main:
            continue
        a, b = _step(k, -1), _step(k, 1)
        pv = vals[a] if a is not None else -np.inf
        nv = vals[b] if b is not None else -np.inf
        if vals[k] > pv and vals[k] >= nv and vals[k] > -299:
            peaks.append(vals[k])
    sll = float(max(peaks) - peak) if peaks else None
    return {
        "cut": cut.label,
        "peak": round(peak, 3),
        "peak_angle_deg": round(float(angle[ip]), 3) + 0.0,
        "hpbw_deg": None if hpbw is None else round(hpbw, 2),
        "hpbw_edges_deg": None if hpbw is None else [round(left, 2), round(right, 2)],
        "sll_db": None if sll is None else round(sll, 2),
    }


def pattern_metrics(grid: FarfieldGrid, cuts: list[Cut]) -> dict[str, Any]:
    g = np.where(np.isfinite(grid.total_db), grid.total_db, -np.inf)
    ip, it = np.unravel_index(int(np.argmax(g)), g.shape)
    gmax = float(g[ip, it])
    th0, ph0 = float(grid.theta[it]), float(grid.phi[ip])
    back = value_at(grid, 180.0 - th0, ph0 + 180.0)
    metrics: dict[str, Any] = {
        "quantity": grid.quantity,
        "unit": grid.unit,
        "max_value": round(gmax, 3),
        "max_direction_deg": {"theta": th0, "phi": ph0},
        "front_to_back_db": round(gmax - back, 2) if math.isfinite(back) else None,
        "grid": {
            "n_theta": int(len(grid.theta)),
            "n_phi": int(len(grid.phi)),
            "theta_step_deg": float(np.min(np.diff(grid.theta))) if len(grid.theta) > 1 else None,
            "phi_step_deg": float(np.min(np.diff(grid.phi))) if len(grid.phi) > 1 else None,
        },
        "cuts": [beam_metrics(c) for c in cuts],
    }
    if grid.quantity in {"realized_gain", "gain", "directivity"}:
        metrics[f"max_{grid.quantity}_{grid.unit.lower()}"] = round(gmax, 3)
    if grid.frequency_ghz is not None:
        metrics["frequency_ghz"] = grid.frequency_ghz
    co, cx = co_cross_keys(grid)
    if co and cx:
        a = grid.components_db[co]
        b = grid.components_db[cx]
        metrics["polarization"] = {
            "co": co,
            "cross": cx,
            "xpd_at_peak_db": round(value_at(grid, th0, ph0, a) - value_at(grid, th0, ph0, b), 2),
        }
    return metrics


def co_cross_keys(grid: FarfieldGrid) -> tuple[str | None, str | None]:
    """Choose co/cross-pol component keys (Ludwig-3 preferred)."""
    comps = grid.components_db
    for pair in (("copolar", "crosspolar"),):
        if all(k in comps for k in pair):
            return pair
    for a, b in (("vertical", "horizontal"), ("left", "right"), ("theta", "phi")):
        if a in comps and b in comps:
            # Decide at the main-beam direction (global maxima of Etheta/Ephi
            # can be equal for a linearly polarized antenna on different planes).
            ip, it = np.unravel_index(int(np.nanargmax(grid.total_db)), grid.total_db.shape)
            ma, mb = comps[a][ip, it], comps[b][ip, it]
            return (a, b) if ma >= mb else (b, a)
    return None, None


def cut_co_cross(grid: FarfieldGrid, cut: Cut) -> tuple[str | None, str | None]:
    """Per-cut co/cross for spherical components (Eθ/Eφ swap between planes)."""
    co, cx = co_cross_keys(grid)
    if co in ("theta", "phi") and co in cut.components and cx in cut.components:
        if np.nanmax(cut.components[cx]) > np.nanmax(cut.components[co]):
            co, cx = cx, co
    return co, cx


def plane_label(grid: FarfieldGrid, cut: Cut) -> str:
    """Return 'E-plane'/'H-plane' for principal phi cuts when polarization is known."""
    if cut.kind != "phi" or "theta" not in grid.components_db or "phi" not in grid.components_db:
        return ""
    base = cut.value % 180
    if not (np.isclose(base, 0) or np.isclose(base, 90)):
        return ""
    ip, it = np.unravel_index(int(np.nanargmax(grid.total_db)), grid.total_db.shape)
    th0 = float(grid.theta[it])
    et = value_at(grid, th0, cut.value, grid.components_db["theta"])
    ep = value_at(grid, th0, cut.value, grid.components_db["phi"])
    return "E-plane" if et >= ep else "H-plane"


def write_cst_ascii(
    path: str | Path,
    theta: np.ndarray,
    phi: np.ndarray,
    total_db: np.ndarray,
    *,
    name: str = "Realized Gain",
    unit: str = "dBi",
    components: dict[str, np.ndarray] | None = None,
) -> Path:
    """Write a grid (``[phi, theta]``) in CST's farfield ASCII layout (tests/fallback)."""
    p = Path(path)
    cols = [("Theta", "deg."), ("Phi", "deg."), (f"Abs({name})", unit)]
    comp_items = list((components or {}).items())
    for key, _ in comp_items:
        cols.append((f"Abs({key.capitalize()})", unit))
    header = "".join(f"{n} [{u}]".ljust(22) for n, u in cols)
    lines = [header.rstrip(), "-" * len(header)]
    for i, ph in enumerate(phi):
        for j, th in enumerate(theta):
            vals = [th, ph, total_db[i, j]] + [c[i, j] for _, c in comp_items]
            lines.append("".join(f"{v:>18.6f}    " for v in vals).rstrip())
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
