"""Read-only access to saved 1D results for figure tools (cst.results, no GUI).

:class:`SavedResults` wraps ``cst.results.ProjectFile(...).get_3d()`` behind
a tiny interface so the tool logic can be tested with a fake reader.
"""

from __future__ import annotations

import math
import re
from typing import Any

from cst_mcp.execution.curves import frequency_scale

S_PARAM_PREFIX = "1D Results\\S-Parameters\\"
EFFICIENCY_PREFIX = "1D Results\\Efficiencies\\"
REF_IMP_PREFIX = "1D Results\\Reference Impedance\\"


class SavedResults:
    """Thin adapter over the official cst.results 3D module."""

    def __init__(self, project_path: str, allow_interactive: bool = False) -> None:
        import cst.results

        self.project_path = project_path
        self._module = cst.results.ProjectFile(
            project_path, allow_interactive=allow_interactive
        ).get_3d()

    def tree_items(self) -> list[str]:
        return [str(p) for p in self._module.get_tree_items()]

    def run_ids(self, tree_path: str) -> list[int]:
        return [int(r) for r in self._module.get_run_ids(tree_path)]

    def parameter_combination(self, run_id: int) -> dict[str, Any]:
        try:
            return dict(self._module.get_parameter_combination(run_id) or {})
        except Exception:
            return {}

    def read(self, tree_path: str, run_id: int) -> dict[str, Any]:
        item = self._module.get_result_item(tree_path, run_id)
        x = [float(v) for v in item.get_xdata()]
        y = [complex(v) for v in item.get_ydata()]
        z0 = None
        try:
            ref = item.get_ref_imp_data()
            if ref is not None and len(ref) == len(y):
                z0 = [complex(v) for v in ref]
        except Exception:
            z0 = None
        return {"x": x, "values": y, "xlabel": str(item.xlabel), "ylabel": str(item.ylabel),
                "title": str(item.title), "z0": z0}


def open_reader(project_path: str, allow_interactive: bool = False):
    """Factory kept module-level so tests can monkeypatch it."""
    return SavedResults(project_path, allow_interactive=allow_interactive)


def to_series(raw: dict[str, Any], label: str, run_id: int, tree_path: str) -> dict[str, Any]:
    """Convert a raw read into a GHz series; validates finiteness and ordering."""
    x, values = raw["x"], raw["values"]
    if not x or len(x) != len(values):
        raise ValueError(f"{tree_path} (run {run_id}): empty or mismatched axes")
    if not all(math.isfinite(v) for v in x):
        raise ValueError(f"{tree_path} (run {run_id}): non-finite x samples")
    if not all(math.isfinite(v.real) and math.isfinite(v.imag) for v in values):
        raise ValueError(f"{tree_path} (run {run_id}): non-finite samples")
    try:
        scale = frequency_scale(raw.get("xlabel", "")) / 1e9
        is_freq = True
    except ValueError:
        scale, is_freq = 1.0, False
    return {
        "label": label,
        "run_id": run_id,
        "tree_path": tree_path,
        "f": [v * scale for v in x],
        "values": list(values),
        "z0": raw.get("z0"),
        "xlabel": "Frequency (GHz)" if is_freq else raw.get("xlabel", "x"),
        "ylabel": raw.get("ylabel", ""),
        "is_frequency": is_freq,
    }


_SIJ = re.compile(r"S(\d+)(?:\((\d+)\))?,(\d+)(?:\((\d+)\))?$")


def s_param_paths(items: list[str]) -> list[str]:
    return [p for p in items if p.startswith(S_PARAM_PREFIX)]


def reflection_path(items: list[str]) -> str | None:
    """First reflection coefficient (Sii), preferring S1,1."""
    sp = s_param_paths(items)
    refl = []
    for p in sp:
        m = _SIJ.search(p.rsplit("\\", 1)[-1].replace(" ", ""))
        if m and m.group(1) == m.group(3) and (m.group(2) or "") == (m.group(4) or ""):
            refl.append(p)
    for p in refl:
        if p.endswith("\\S1,1") or p.endswith("\\S1(1),1(1)"):
            return p
    return refl[0] if refl else None


def s_param_latex(tree_path: str) -> str:
    name = tree_path.rsplit("\\", 1)[-1]
    m = _SIJ.search(name.replace(" ", ""))
    if not m:
        return name
    i, j = m.group(1), m.group(3)
    return rf"$|S_{{{i}{j}}}|$" if len(i + j) == 2 else rf"$|S_{{{i},{j}}}|$"


def efficiency_paths(items: list[str]) -> list[str]:
    return [p for p in items if p.startswith(EFFICIENCY_PREFIX)]


def ref_impedance_path(items: list[str], port: str = "1") -> str | None:
    for p in items:
        if p.startswith(REF_IMP_PREFIX) and re.search(rf"ZRef {port}\b", p):
            return p
    return None


def select_runs(available: list[int], requested: list[int] | None, max_runs: int) -> list[int]:
    """Pick run IDs to plot.

    Explicit ``requested`` IDs are validated. By default run 0 (CST's copy of
    the current/last run) is used only when it is the sole run; otherwise the
    newest ``max_runs`` parametric runs are compared.
    """
    avail = sorted(set(available))
    if requested:
        missing = [r for r in requested if r not in avail]
        if missing:
            raise ValueError(f"run_ids {missing} not available; available: {avail}")
        return list(dict.fromkeys(requested))
    parametric = [r for r in avail if r != 0]
    if not parametric:
        return avail[:1]
    return parametric[-max_runs:]
