from pathlib import Path
import sys, json
sys.path.insert(0, r"E:\cst_mcp_update\src")
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")
from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient

c = CSTClient(CSTConfig.from_env())
print(c.connect())
print([a for a in dir(c) if not a.startswith('__')])
# open fffix project
print(c.open_project(r"E:\cstprojects\patch_2p4_fffix.cst"))

# access internal session
sess = getattr(c, "_session", None) or getattr(c, "session", None)
print("sess", sess)
if sess is None:
    # maybe client IS session wrapper
    print("attrs with project", [a for a in dir(c) if "project" in a.lower() or "model" in a.lower()])

m3d = None
for path in ["model3d", "_session.model3d", "session.model3d"]:
    pass
if hasattr(c, "model3d"):
    m3d = c.model3d
elif hasattr(c, "_session"):
    m3d = c._session.model3d
print("m3d", m3d)

for tree in [
    r"Farfields\farfield (f=2.4) [1]",
    r"Farfields\farfield (f=2.4)",
    r"1D Results\S-Parameters\S1,1",
]:
    try:
        print("select", tree, "->", m3d.SelectTreeItem(tree))
    except Exception as e:
        print("select fail", tree, e)

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
Print #1, "select_after=" & CStr(ok)
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
' also try ASCIIExportAsSource after select+plot 2d
With FarfieldPlot
  .Plottype ("2d")
  .Step (5)
  .Step2 (5)
  .SetPlotMode ("realized gain")
  .Plot
  .ASCIIExportAsSource "E:/cstprojects/exports/ff_fix_source.ffs"
End With
Print #1, "source_err=" & Err.Description
Close #1
End Sub'''
proj = c._session._project if hasattr(c, "_session") else None
if proj is None:
    # dig
    for a in dir(c):
        o = getattr(c, a, None)
        if o is not None and type(o).__name__ == "CSTSession":
            proj = o._project
            print("found session via", a)
            break
if proj is None and hasattr(c, "_session"):
    proj = c._session._project

# try run_vba_silent
if hasattr(c, "run_vba_silent"):
    print("run_vba_silent", c.run_vba_silent(vba))
elif hasattr(c, "_session"):
    try:
        c._session._project.schematic.execute_vba_code(vba)
        print("schematic OK")
    except Exception as e:
        print("schematic ERR", str(e)[-500:])
else:
    print("no exec path")

print("FILE", metrics_file.read_text(encoding="utf-8", errors="replace") if metrics_file.exists() else "missing")
print("S11", c.get_s_parameters(1,1,max_points=20).get("metrics"))
print("FF", c.get_farfield_metrics(2.4))
print("disk", c.discover_farfield_monitors())
