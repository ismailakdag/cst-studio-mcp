"""Parse CST result exports and optional ``cst.results`` tree access."""

from __future__ import annotations

import csv
import logging
import math
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_sparam_csv(path: str | Path) -> dict[str, Any]:
    """Parse a CST ASCIIExport CSV of S-parameters into structured arrays.

    CST CSV layouts vary by version; this handles the common cases:
    - frequency, Re, Im
    - frequency, mag, phase
    - frequency, dB, phase
    """
    path = Path(path)
    if not path.is_file():
        return {"status": "error", "message": f"File not found: {path}"}

    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return {"status": "error", "message": f"Empty result file: {path}"}

    # CST ASCII exports are often *whitespace*-separated (not CSV commas):
    #   Frequency / GHz                S1,1/abs,dB
    #   ----------------------------------------------------------------------
    #          1.6799999                     -0.19691079
    rows: list[list[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if set(line) <= {"-", "=", " ", "\t"}:
            continue  # dashed separator banners
        line = line.replace(";", ",").replace("\t", ",")
        if "," in line and any(c.isdigit() for c in line.split(",", 1)[0]):
            # Real comma-separated numeric row (not a header containing "S1,1")
            first = line.split(",", 1)[0].strip()
            try:
                float(first.replace("e", "E"))
                parts = [p.strip() for p in line.split(",") if p.strip() != ""]
            except ValueError:
                parts = [p for p in re.split(r"\s+", line) if p]
        else:
            parts = [p for p in re.split(r"\s+", line) if p]
        if not parts:
            continue
        try:
            float(parts[0].replace("e", "E"))
        except ValueError:
            continue
        rows.append(parts)

    if not rows:
        return {"status": "error", "message": f"No numeric rows in {path}"}

    freq: list[float] = []
    col1: list[float] = []
    col2: list[float] = []

    for parts in rows:
        try:
            f = float(parts[0])
            a = float(parts[1]) if len(parts) > 1 else float("nan")
            b = float(parts[2]) if len(parts) > 2 else float("nan")
        except ValueError:
            continue
        freq.append(f)
        col1.append(a)
        col2.append(b)

    if not freq:
        return {"status": "error", "message": f"Could not parse numeric data from {path}"}

    # Heuristic: if |col1| mostly <= 1.5 and col2 looks like phase (-180..180)
    # treat as mag/phase; if col1 is largely negative treat as dB.
    sample = col1[: min(20, len(col1))]
    mostly_db = sum(1 for v in sample if v < 0) > len(sample) / 2
    mostly_mag = all(0 <= abs(v) <= 1.5 for v in sample if math.isfinite(v))

    mag_lin: list[float] = []
    mag_db: list[float] = []
    phase_deg: list[float] = []
    re_parts: list[float] = []
    im_parts: list[float] = []

    if mostly_db:
        for db, ph in zip(col1, col2):
            mag_db.append(db)
            lin = 10 ** (db / 20.0) if math.isfinite(db) else float("nan")
            mag_lin.append(lin)
            phase_deg.append(ph)
            rad = math.radians(ph) if math.isfinite(ph) else float("nan")
            re_parts.append(lin * math.cos(rad) if math.isfinite(rad) else float("nan"))
            im_parts.append(lin * math.sin(rad) if math.isfinite(rad) else float("nan"))
        layout = "db_phase"
    elif mostly_mag and not mostly_db:
        # could still be re/im if col2 not phase-like — prefer re/im if |col2| often > 1
        phase_like = sum(1 for v in col2[:20] if abs(v) <= 180) > 10
        if phase_like:
            for mag, ph in zip(col1, col2):
                mag_lin.append(mag)
                mag_db.append(20 * math.log10(mag) if mag > 0 else -999.0)
                phase_deg.append(ph)
                rad = math.radians(ph)
                re_parts.append(mag * math.cos(rad))
                im_parts.append(mag * math.sin(rad))
            layout = "mag_phase"
        else:
            for re_v, im_v in zip(col1, col2):
                re_parts.append(re_v)
                im_parts.append(im_v)
                mag = math.hypot(re_v, im_v)
                mag_lin.append(mag)
                mag_db.append(20 * math.log10(mag) if mag > 0 else -999.0)
                phase_deg.append(math.degrees(math.atan2(im_v, re_v)))
            layout = "re_im"
    else:
        for re_v, im_v in zip(col1, col2):
            re_parts.append(re_v)
            im_parts.append(im_v)
            mag = math.hypot(re_v, im_v)
            mag_lin.append(mag)
            mag_db.append(20 * math.log10(mag) if mag > 0 else -999.0)
            phase_deg.append(math.degrees(math.atan2(im_v, re_v)))
        layout = "re_im"

    # Frequency unit heuristic: if values look like Hz, convert to GHz
    f_unit = "GHz"
    f_out = list(freq)
    if freq and max(freq) > 1e6:
        f_out = [f / 1e9 for f in freq]
        f_unit = "GHz (from Hz)"
    elif freq and max(freq) > 500:  # likely MHz
        f_out = [f / 1e3 for f in freq]
        f_unit = "GHz (from MHz)"

    # Metrics
    metrics: dict[str, Any] = {}
    finite_db = [(f, db) for f, db in zip(f_out, mag_db) if math.isfinite(db)]
    if finite_db:
        f_min, db_min = min(finite_db, key=lambda t: t[1])
        metrics["min_db"] = db_min
        metrics["freq_at_min_ghz"] = f_min
        # -10 dB bandwidth around min (simple contiguous scan)
        below = [f for f, db in finite_db if db <= -10]
        if below:
            metrics["bw_10db_ghz"] = max(below) - min(below)
            metrics["bw_10db_low_ghz"] = min(below)
            metrics["bw_10db_high_ghz"] = max(below)

    return {
        "status": "ok",
        "path": str(path),
        "layout_detected": layout,
        "frequency_unit": f_unit,
        "n_points": len(f_out),
        "frequency_ghz": f_out,
        "magnitude_db": mag_db,
        "magnitude_linear": mag_lin,
        "phase_deg": phase_deg,
        "real": re_parts,
        "imag": im_parts,
        "metrics": metrics,
    }


def downsample_series(data: dict[str, Any], max_points: int = 200) -> dict[str, Any]:
    """Reduce array length for MCP responses while keeping endpoints and min."""
    n = data.get("n_points") or 0
    if n <= max_points:
        return data

    freq = data["frequency_ghz"]
    step = max(1, n // max_points)
    indices = list(range(0, n, step))
    if indices[-1] != n - 1:
        indices.append(n - 1)

    # Ensure global min-db index is kept
    mag = data.get("magnitude_db") or []
    if mag:
        min_i = min(range(len(mag)), key=lambda i: mag[i] if math.isfinite(mag[i]) else 0)
        if min_i not in indices:
            indices.append(min_i)
            indices.sort()

    out = dict(data)
    for key in (
        "frequency_ghz",
        "magnitude_db",
        "magnitude_linear",
        "phase_deg",
        "real",
        "imag",
    ):
        if key in out and isinstance(out[key], list):
            out[key] = [out[key][i] for i in indices]
    out["n_points"] = len(indices)
    out["downsampled_from"] = n
    return out


class ResultsReader:
    """High-level result extraction helpers."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir

    def read_sparam_file(self, path: str | Path, *, max_points: int = 200) -> dict[str, Any]:
        parsed = parse_sparam_csv(path)
        if parsed.get("status") != "ok":
            return parsed
        return downsample_series(parsed, max_points=max_points)

    def try_project_file(self, project_path: str, tree_item: str) -> dict[str, Any]:
        """Best-effort read via ``cst.results.ProjectFile`` (version-dependent)."""
        try:
            import cst.results  # type: ignore
        except ImportError:
            return {"status": "unavailable", "message": "cst.results not importable"}

        try:
            pf = cst.results.ProjectFile(project_path)
            item = pf.get_3d().get_tree_item(tree_item)
            return {"status": "ok", "tree_item": tree_item, "data": str(item)}
        except Exception as exc:  # noqa: BLE001
            logger.debug("cst.results read failed: %s", exc)
            return {"status": "error", "message": str(exc)}


def vswr_from_s11_db(s11_db: float) -> float:
    """VSWR from |S11| in dB. Returns inf-like large number at total reflection."""
    if not math.isfinite(s11_db):
        return float("nan")
    mag = 10 ** (s11_db / 20.0)
    if mag >= 1.0 - 1e-15:
        return 1e6
    return (1.0 + mag) / (1.0 - mag)
