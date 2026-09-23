"""Connected-mode farfield acquisition for ``cst_plot_farfield``.

Official CST 2026 VBA path (Online Help: FarfieldPlot / ASCIIExport objects):
configure ``FarfieldPlot`` (3D plot type, Step/Step2, SetPlotMode, log scale,
coordinate system), ``SelectTreeItem "Farfields\\farfield (f=…) [1]"``,
``FarfieldPlot.Plot`` and then ``ASCIIExport.FileName/.Execute`` which writes
the ``Theta Phi Abs(...)`` table. If that export produces no file, a fallback
uses ``AddListEvaluationPoint`` + ``CalculateList`` + ``GetList`` and writes
the same layout from VBA. ``ASCIIExportSummary`` is never used. Nothing here
starts or waits for a solver.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

QUANTITY_MODES = {
    "realized_gain": ("realized gain", "Realized Gain"),
    "gain": ("gain", "Gain"),
    "directivity": ("directivity", "Dir."),
}


def _q(s: str) -> str:
    return s.replace('"', '""')


def _plot_setup(quantity: str, step_deg: float, basis: str) -> list[str]:
    mode = QUANTITY_MODES[quantity][0]
    return [
        "With FarfieldPlot",
        "  .Reset",
        '  .Plottype ("3d")',
        f"  .Step ({step_deg:g})",
        f"  .Step2 ({step_deg:g})",
        "  .SetLockSteps (True)",
        "  .SetPlotRangeOnly (False)",
        "  .SetTheta360 (False)",
        f'  .SetPlotMode ("{mode}")',
        "  .SetScaleLinear (False)",
        "  .UseFarfieldApproximation (True)",
        '  .Origin ("bbox")',
        f'  .SetCoordinateSystemType ("{basis}")',
        '  .SetPolarizationType ("linear")',
        "End With",
    ]


def build_ascii_export_vba(tree_path: str, out_file: str, quantity: str, step_deg: float,
                           basis: str = "ludwig3") -> str:
    lines = _plot_setup(quantity, step_deg, basis) + [
        f'If Not SelectTreeItem("{_q(tree_path)}") Then',
        '  Err.Raise vbObjectError + 1, , "Farfield tree item not found"',
        "End If",
        "FarfieldPlot.Plot",
        "With ASCIIExport",
        "  .Reset",
        f'  .FileName ("{_q(out_file)}")',
        "  .Execute",
        "End With",
    ]
    return "\n".join(lines)


def build_list_export_vba(tree_path: str, out_file: str, quantity: str, step_deg: float,
                          basis: str = "ludwig3") -> str:
    """Fallback: evaluate the full sphere with CalculateList and write CST-like ASCII."""
    mode, label = QUANTITY_MODES[quantity]
    c1, c2 = ("horizontal", "vertical") if basis == "ludwig3" else ("theta", "phi")
    n1, n2 = ("Hor", "Ver") if basis == "ludwig3" else ("Theta", "Phi")
    lines = _plot_setup(quantity, step_deg, basis) + [
        "Dim th As Double, ph As Double, i As Long, n As Long, f As Integer",
        "Dim va As Variant, vb As Variant, vc As Variant, pt As Variant, pp As Variant",
        f'If Not SelectTreeItem("{_q(tree_path)}") Then',
        '  Err.Raise vbObjectError + 1, , "Farfield tree item not found"',
        "End If",
        "FarfieldPlot.Plot",
        "FarfieldPlot.Reset",
        f'FarfieldPlot.SetPlotMode ("{mode}")',
        "FarfieldPlot.SetScaleLinear (False)",
        f"For ph = 0 To {360 - step_deg:g} Step {step_deg:g}",
        f"  For th = 0 To 180 Step {step_deg:g}",
        '    FarfieldPlot.AddListEvaluationPoint(th, ph, 0, "spherical", "", 0)',
        "  Next th",
        "Next ph",
        'FarfieldPlot.CalculateList("")',
        f'va = FarfieldPlot.GetList("{basis} abs")',
        f'vb = FarfieldPlot.GetList("{basis} linear {c1} abs")',
        f'vc = FarfieldPlot.GetList("{basis} linear {c2} abs")',
        'pt = FarfieldPlot.GetList("Point_T")',
        'pp = FarfieldPlot.GetList("Point_P")',
        "f = FreeFile",
        f'Open "{_q(out_file)}" For Output As #f',
        f'Print #f, "Theta [deg.]  Phi [deg.]  Abs({label})[dBi]  Abs({n1})[dBi]  Abs({n2})[dBi]"',
        'Print #f, "------------------------------------------------------------"',
        "For i = LBound(va) To UBound(va)",
        '  Print #f, CStr(pt(i)) & "  " & CStr(pp(i)) & "  " & CStr(va(i)) & "  " & CStr(vb(i)) & "  " & CStr(vc(i))',
        "Next i",
        "Close #f",
    ]
    return "\n".join(lines)


def build_monitor_list_vba(out_file: str) -> str:
    return "\n".join([
        "Dim i As Long, f As Integer",
        "f = FreeFile",
        f'Open "{_q(out_file)}" For Output As #f',
        "For i = 0 To Monitor.GetNumberOfMonitors - 1",
        '  Print #f, Monitor.GetMonitorNameFromIndex(i) & vbTab & Monitor.GetMonitorTypeFromIndex(i) & vbTab & '
        "CStr(Monitor.GetMonitorFrequencyFromIndex(i))",
        "Next i",
        "Close #f",
    ])


def _run(client: Any, vba: str) -> dict[str, Any]:
    runner = getattr(client, "_run_vba_no_history", None)
    if callable(runner):
        return runner(vba)
    return client.run_vba_silent(vba)


def list_monitors(client: Any, work_dir: Path) -> list[dict[str, Any]] | None:
    """Return defined monitors via official Monitor.Get* queries (None if unavailable)."""
    out = work_dir / f"fig3d_monitors_{int(time.time() * 1000)}.txt"
    try:
        run = _run(client, build_monitor_list_vba(str(out)))
        if run.get("status") != "executed" or not out.is_file():
            return None
        text = out.read_text(encoding="mbcs" if __import__("os").name == "nt" else "utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass
    monitors = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip():
            try:
                freq = float(parts[2]) if len(parts) > 2 else None
            except ValueError:
                freq = None
            monitors.append({"name": parts[0].strip(), "type": parts[1].strip(), "frequency": freq})
    return monitors


def tree_candidates(client: Any, farfield_name: str | None, frequency_ghz: float | None) -> list[str]:
    from cst_mcp.execution.farfield import farfield_tree_candidates

    cands = farfield_tree_candidates(frequency_ghz, farfield_name)
    try:
        disk = client.discover_farfield_monitors().get("monitors") or []
    except Exception:  # noqa: BLE001
        disk = []
    for mon in disk:
        if frequency_ghz is not None and mon.get("frequency_ghz") is not None and abs(
            float(mon["frequency_ghz"]) - frequency_ghz
        ) > 1e-6:
            continue
        if farfield_name and farfield_name.lower() not in str(mon.get("monitor_name", "")).lower():
            continue
        for c in mon.get("tree_candidates") or []:
            if c not in cands:
                cands.append(c)
    if not farfield_name and frequency_ghz is None:
        for mon in disk:
            for c in mon.get("tree_candidates") or []:
                if c not in cands:
                    cands.append(c)
    return [c for c in cands if "farfield" in c.lower()]


def acquire(
    client: Any,
    *,
    farfield_name: str | None,
    frequency_ghz: float | None,
    quantity: str,
    step_deg: float,
    basis: str,
    export_dir: Path,
) -> dict[str, Any]:
    """Export the farfield grid from the open project; never solves.

    Returns ``{"status": "ok", "path", "tree_path", "method"}``, a
    ``no_results`` payload with discovered monitors and guidance, ``busy``
    when a solver is active, or ``error``.
    """
    idle = getattr(client, "_idle_error", None)
    if callable(idle):
        blocked = idle()
        if blocked:
            return blocked
    export_dir.mkdir(parents=True, exist_ok=True)
    cands = tree_candidates(client, farfield_name, frequency_ghz)
    selectable: list[str] = []
    for tree in cands:
        try:
            if client.model3d.SelectTreeItem(tree):
                selectable.append(tree)
                break
        except Exception:  # noqa: BLE001
            continue
    if not selectable:
        monitors = list_monitors(client, export_dir)
        ff = [m for m in (monitors or []) if "farfield" in m.get("type", "").lower()]
        try:
            disk = client.discover_farfield_monitors().get("monitors") or []
        except Exception:  # noqa: BLE001
            disk = []
        if monitors is not None and not ff:
            guidance = ("No farfield monitor is defined. Add one (cst_add_farfield_monitor at the design "
                        "frequency), then run cst_run_simulation_async and cst_wait_for_simulation, and call "
                        "cst_plot_farfield again.")
        else:
            guidance = ("Farfield monitor(s) exist but no farfield result is available (not simulated yet or "
                        "results deleted). Run cst_run_simulation_async + cst_wait_for_simulation, then retry; "
                        "or pass data_file with a previously exported farfield ASCII.")
        return {
            "status": "no_results",
            "message": guidance,
            "farfield_monitors": ff,
            "all_monitors": monitors,
            "disk_results": disk,
            "tried_tree_paths": cands,
        }

    tree = selectable[0]
    safe = re.sub(r"[^A-Za-z0-9._=-]+", "_", tree.split("\\")[-1]).strip("_")
    attempts: list[dict[str, Any]] = []
    for method, builder in (("ascii_export", build_ascii_export_vba), ("calculate_list", build_list_export_vba)):
        out = export_dir / f"{safe}_{quantity}_{basis}_{method}.txt"
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass
        vba = builder(tree, str(out), quantity, step_deg, basis)
        run = _run(client, vba)
        entry = {"method": method, "run": run.get("status"), "message": str(run.get("message") or "")[:300]}
        attempts.append(entry)
        if out.is_file() and out.stat().st_size > 0:
            return {"status": "ok", "path": str(out), "tree_path": tree, "method": method, "attempts": attempts}
    return {
        "status": "error",
        "message": f"Farfield export produced no data for {tree}",
        "tree_path": tree,
        "attempts": attempts,
    }
