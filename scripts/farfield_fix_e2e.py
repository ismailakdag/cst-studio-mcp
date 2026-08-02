"""Fresh farfield fix verification using CSTClient + improved monitor + GetMax metrics."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import workflows


PROJ = Path(r"E:\cstprojects\patch_2p4_fffix.cst")
OUT = Path(r"E:\cstprojects\exports\farfield_fix.json")


async def main() -> int:
    c = CSTClient(CSTConfig.from_env())
    print("CONNECT", c.connect())

    print("BUILD")
    r = await workflows.handle(
        "cst_workflow_patch_antenna",
        {
            "frequency_ghz": 2.4,
            "create_project": True,
            "project_path": str(PROJ),
            "epsilon_r": 4.4,
            "height_mm": 1.6,
            "tan_delta": 0.02,
            "feed_type": "inset",
        },
        c,
    )
    build = json.loads(r[0].text)
    print("build", build.get("status"))
    for s in build.get("steps") or []:
        if isinstance(s, dict) and s.get("label"):
            print(f"  {s.get('label'):20} {s.get('status')}")

    # Reinforce farfield monitor with EnableNearfieldCalculation
    mon_vba = """
With Monitor
  .Reset
  .Name "farfield (f=2.4)"
  .Domain "Frequency"
  .FieldType "Farfield"
  .Frequency "2.4"
  .ExportFarfieldSource "False"
  .EnableNearfieldCalculation "True"
  .UseSubvolume "False"
  .Create
End With
"""
    # Delete old monitor if needed then recreate — Monitor.Delete may exist
    del_vba = """
On Error Resume Next
Monitor.Delete "farfield (f=2.4)"
"""
    print("RECREATE MONITOR", c.run_history(del_vba + mon_vba, label="farfield_mon_nf"))

    print("SOLVE")
    t0 = time.time()
    solve = c.run_solver(timeout_s=1200)
    print(solve, "t=", round(time.time() - t0, 1))
    c.save_project()

    # disk discovery
    disk = c.discover_farfield_monitors()
    print("DISK", disk)

    # Python select
    session = c.session
    m3d = session.model3d
    for tree in [
        r"Farfields\farfield (f=2.4) [1]",
        r"Farfields\farfield (f=2.4)",
        r"1D Results\S-Parameters\S1,1",
    ]:
        try:
            print("select", tree, "->", m3d.SelectTreeItem(tree))
        except Exception as e:
            print("select fail", tree, e)

    # GetMax metrics immediately after solve (mesh may still be present)
    metrics_file = Path(r"E:\cstprojects\exports\ff_fix_metrics.txt")
    if metrics_file.exists():
        metrics_file.unlink()
    tree = r"Farfields\farfield (f=2.4) [1]"
    vba = f'''Sub Main()
Dim ok As Boolean
Open "{metrics_file.as_posix()}" For Output As #1
On Error Resume Next
ok = SelectTreeItem("{tree}")
Print #1, "select=" & CStr(ok)
If Not ok Then
  ok = SelectTreeItem("Farfields\\farfield (f=2.4)")
  Print #1, "select_bare=" & CStr(ok)
End If
With FarfieldPlot
  .Reset
  .Plottype ("3d")
  .Step (5)
  .Step2 (5)
  .SetLockSteps (True)
  .SetPlotMode ("realized gain")
  .SetScaleLinear (False)
  .UseFarfieldApproximation (True)
  .Origin ("bbox")
End With
ok = SelectTreeItem("{tree}")
Print #1, "select_after_settings=" & CStr(ok)
If Not ok Then
  ok = SelectTreeItem("Farfields\\farfield (f=2.4)")
  Print #1, "select_bare2=" & CStr(ok)
End If
FarfieldPlot.Plot
Print #1, "GetMax=" & CStr(FarfieldPlot.GetMax)
Print #1, "GetMin=" & CStr(FarfieldPlot.GetMin)
Print #1, "GetMean=" & CStr(FarfieldPlot.GetMean)
Print #1, "GetRadiationEfficiency=" & CStr(FarfieldPlot.GetRadiationEfficiency)
Print #1, "GetTotalEfficiency=" & CStr(FarfieldPlot.GetTotalEfficiency)
Print #1, "GetTRP=" & CStr(FarfieldPlot.GetTRP)
Print #1, "mode=" & CStr(FarfieldPlot.GetPlotMode)
Print #1, "err=" & Err.Description
' list tree
Dim s As String
s = Resulttree.GetFirstChildName("Farfields")
Print #1, "firstFar=" & s
Dim guard As Long
guard = 0
Do While s <> "" And guard < 20
  Print #1, "child=" & s
  s = Resulttree.GetNextItemName(s)
  guard = guard + 1
Loop
Close #1
End Sub'''
    try:
        session._project.schematic.execute_vba_code(vba)
        print("metrics VBA OK")
    except Exception as e:
        print("metrics VBA ERR", str(e)[-500:])

    text = metrics_file.read_text(encoding="utf-8", errors="replace") if metrics_file.exists() else ""
    print("METRICS:\n", text)

    s11 = c.get_s_parameters(1, 1, max_points=40)
    ff = c.get_farfield_metrics(2.4)
    print("S11", s11.get("status"), s11.get("metrics"))
    print("FF MCP", ff.get("status"), ff.get("method"), ff.get("metrics"))

    report = {
        "project": str(PROJ),
        "build": build.get("status"),
        "solve": solve,
        "disk": disk,
        "plot_metrics_raw": text,
        "s11": s11.get("metrics"),
        "ff_mcp": ff,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
