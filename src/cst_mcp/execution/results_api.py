"""Read results via official ``cst.results.ProjectFile`` when available."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _as_float(y: Any, *, as_abs: bool = False) -> float:
    if isinstance(y, complex):
        if as_abs:
            return float(abs(y))
        return float(y.real)
    return float(y)


def _sparam_db(y: Any) -> float:
    mag = abs(complex(y))
    if mag <= 0:
        return -999.0
    return 20.0 * math.log10(mag)


def open_project_results(project_path: str) -> Any | None:
    try:
        import cst.results  # type: ignore
    except ImportError:
        return None
    try:
        return cst.results.ProjectFile(project_path, allow_interactive=True)
    except TypeError:
        try:
            return cst.results.ProjectFile(project_path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ProjectFile open failed: %s", exc)
            return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("ProjectFile open failed: %s", exc)
        return None


def list_tree_items(project_path: str) -> list[str]:
    pf = open_project_results(project_path)
    if pf is None:
        return []
    try:
        return [str(x) for x in pf.get_3d().get_tree_items()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_tree_items failed: %s", exc)
        return []


def read_1d_item(project_path: str, tree_path: str) -> dict[str, Any]:
    """Read a 1D/0D result curve: frequency (or x) + values."""
    pf = open_project_results(project_path)
    if pf is None:
        return {"status": "unavailable", "message": "cst.results not available"}
    try:
        item = pf.get_3d().get_result_item(tree_path)
        raw_y = list(item.get_ydata())
        x = [_as_float(v) for v in item.get_xdata()]
        # S-parameters come as complex linear — convert to dB magnitude
        is_sparam = "S-Parameters" in tree_path or "/S" in tree_path.replace("\\", "/")
        if is_sparam or (raw_y and isinstance(raw_y[0], complex) and "S" in tree_path):
            y = [_sparam_db(v) for v in raw_y]
            unit = "dB"
        else:
            y = [_as_float(v, as_abs=isinstance(v, complex)) for v in raw_y]
            unit = "linear"
        if not x:
            return {"status": "error", "message": f"Empty result: {tree_path}"}
        # pick extremum for metrics
        if unit == "dB" or all(v <= 0 for v in y) or any(v < 0 for v in y):
            i_ext = min(range(len(y)), key=lambda i: y[i])
            extremum = "min"
        else:
            i_ext = max(range(len(y)), key=lambda i: y[i])
            extremum = "max"
        title = getattr(item, "title", "")
        if callable(title):
            title = title()
        return {
            "status": "ok",
            "tree_path": tree_path,
            "x": x,
            "y": y,
            "n": len(x),
            "unit": unit,
            "x_at_extremum": x[i_ext],
            "y_at_extremum": y[i_ext],
            "extremum": extremum,
            "title": str(title or ""),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc), "tree_path": tree_path}


def antenna_metrics_from_results(project_path: str, frequency_ghz: float | None = None) -> dict[str, Any]:
    """Collect S11 + efficiency metrics without FarfieldPlot (avoids HEX mesh issues)."""
    items = list_tree_items(project_path)
    out: dict[str, Any] = {"status": "ok", "metrics": {}, "sources": {}, "tree_items": items}

    # S11
    s11_path = r"1D Results\S-Parameters\S1,1"
    if any(s11_path in t or t.endswith("S1,1") for t in items) or True:
        s11 = read_1d_item(project_path, s11_path)
        out["sources"]["s11"] = s11
        if s11.get("status") == "ok":
            # treat as dB magnitude
            ys = s11["y"]
            xs = s11["x"]
            i_min = min(range(len(ys)), key=lambda i: ys[i])
            out["metrics"]["s11_min_db"] = ys[i_min]
            out["metrics"]["s11_freq_at_min_ghz"] = xs[i_min]

    # Efficiencies (often single-point at design f)
    for key, path in [
        ("rad_efficiency_linear", r"1D Results\Efficiencies\Rad. Efficiency [1]"),
        ("tot_efficiency_linear", r"1D Results\Efficiencies\Tot. Efficiency [1]"),
        ("rad_efficiency_linear", r"1D Results\Efficiencies\Rad. Efficiency"),
        ("tot_efficiency_linear", r"1D Results\Efficiencies\Tot. Efficiency"),
    ]:
        if key in out["metrics"]:
            continue
        if not any(path in t or t.endswith(path.split("\\")[-1]) for t in items) and items:
            # still try common path
            pass
        eff = read_1d_item(project_path, path)
        out["sources"][key] = eff
        if eff.get("status") == "ok" and eff.get("y"):
            # pick nearest frequency if multi-point
            xs, ys = eff["x"], eff["y"]
            if frequency_ghz is not None and len(xs) > 1:
                i = min(range(len(xs)), key=lambda j: abs(xs[j] - frequency_ghz))
            else:
                i = 0
            val = ys[i]
            out["metrics"][key] = val
            if val > 0:
                out["metrics"][key.replace("_linear", "_db")] = 10 * math.log10(val)

    if not out["metrics"]:
        out["status"] = "error"
        out["message"] = "No antenna metrics found in result tree"
    return out
