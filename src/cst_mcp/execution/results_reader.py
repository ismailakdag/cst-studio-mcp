"""Parse CST result exports and optional ``cst.results`` tree access."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_sparam_csv(path: str | Path) -> dict[str, Any]:
    from cst_mcp.execution.csv_curves import parse_sparam_csv as parse
    return parse(path)


def downsample_series(data: dict[str, Any], max_points: int = 200) -> dict[str, Any]:
    """Reduce array length for MCP responses while keeping endpoints and min."""
    n = data.get("n_points") or 0
    if n <= max_points:
        return data

    if max_points == 0:
        return data
    if max_points < 3:
        raise ValueError("max_points must be 0 (full data) or at least 3")
    # Reserve a point for the finite global minimum; never exceed the cap.
    indices = {round(i * (n - 1) / (max_points - 2)) for i in range(max_points - 1)}
    mag = data.get("magnitude_db") or []
    finite = [i for i, value in enumerate(mag) if value is not None and math.isfinite(value)]
    if finite:
        indices.add(min(finite, key=lambda i: mag[i]))
    indices = sorted(indices)

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
        from cst_mcp.execution.curves import read_curve
        return read_curve(project_path, tree_item)



def vswr_from_s11_db(s11_db: float) -> float:
    """VSWR from |S11| in dB. Returns inf-like large number at total reflection."""
    if not math.isfinite(s11_db):
        return float("nan")
    mag = 10 ** (s11_db / 20.0)
    if mag >= 1.0 - 1e-15:
        return 1e6
    return (1.0 + mag) / (1.0 - mag)
