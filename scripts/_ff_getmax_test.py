from pathlib import Path
import sys
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")
import cst.interface as ci

de = ci.DesignEnvironment.connect(22108)
p = de.get_open_project(r"E:\cstprojects\patch_2p4_retry.cst")
sch = p.schematic

metrics_path = Path(r"E:/cstprojects/exports/ff_metrics_live.txt")
pattern_path = Path(r"E:/cstprojects/exports/ff_pattern_live.txt")
for f in (metrics_path, pattern_path):
    if f.exists():
        f.unlink()

vba = r"""
Sub Main()
With FarfieldPlot
  .Reset
  .Plottype "3d"
  .Step 5
  .Step2 5
  .SetLockSteps "True"
  .SetPlotMode "realized gain"
  .SetScaleLinear "False"
  .SetColorByValue "True"
  .Origin "bbox"
End With
SelectTreeItem "Farfields\farfield (f=2.4) [1]"
FarfieldPlot.Plot

Open "E:/cstprojects/exports/ff_metrics_live.txt" For Output As #1
On Error Resume Next
Print #1, "GetMax=" & CStr(FarfieldPlot.GetMax)
Print #1, "GetMin=" & CStr(FarfieldPlot.GetMin)
Print #1, "GetMean=" & CStr(FarfieldPlot.GetMean)
Print #1, "GetRadiationEfficiency=" & CStr(FarfieldPlot.GetRadiationEfficiency)
Print #1, "GetTotalEfficiency=" & CStr(FarfieldPlot.GetTotalEfficiency)
Print #1, "GetTRP=" & CStr(FarfieldPlot.GetTRP)
Print #1, "GetPlotMode=" & CStr(FarfieldPlot.GetPlotMode)
Print #1, "IsScaleLinear=" & CStr(FarfieldPlot.IsScaleLinear)
Dim x As Double, y As Double, z As Double
FarfieldPlot.GetMainLobeVector x, y, z
Print #1, "MainLobeVector=" & CStr(x) & "," & CStr(y) & "," & CStr(z)
Print #1, "GetFrontToBackRatio=" & CStr(FarfieldPlot.GetFrontToBackRatio)
Print #1, "Err=" & Err.Description
Close #1
End Sub
"""

try:
    sch.execute_vba_code(vba)
    print("metrics VBA OK")
except Exception as e:
    print("metrics ERR", str(e)[-600:])

if metrics_path.exists():
    print(metrics_path.read_text(encoding="utf-8", errors="replace"))
else:
    print("metrics missing")

# second: pattern via CalculateList - select first without Reset clearing selection oddly
vba2 = r"""
Sub Main()
SelectTreeItem "Farfields\farfield (f=2.4) [1]"
With FarfieldPlot
  .Reset
  .Plottype "3d"
  .SetPlotMode "realized gain"
  .SetScaleLinear "False"
  .Step 10
  .Plot
End With

FarfieldPlot.Reset
Dim theta As Double, phi As Double
For theta = 0 To 180 Step 15
  For phi = 0 To 345 Step 30
    FarfieldPlot.AddListEvaluationPoint theta, phi, 0, "spherical", "", 0
  Next phi
Next theta
FarfieldPlot.CalculateList ""

Open "E:/cstprojects/exports/ff_pattern_live.txt" For Output As #2
On Error Resume Next
Dim vals As Variant
vals = FarfieldPlot.GetList("Spherical abs abs abs")
If Err.Number <> 0 Then
  Print #2, "err_abs=" & Err.Description
  Err.Clear
  vals = FarfieldPlot.GetList("spherical abs abs abs")
End If
If IsArray(vals) Then
  Print #2, "n=" & CStr(UBound(vals) - LBound(vals) + 1)
  Dim i As Long, mx As Double, imx As Long
  mx = -1E30
  imx = -1
  For i = LBound(vals) To UBound(vals)
    If vals(i) > mx Then
      mx = vals(i)
      imx = i
    End If
  Next i
  Print #2, "max=" & CStr(mx) & " idx=" & CStr(imx)
  For i = LBound(vals) To LBound(vals) + 15
    Print #2, CStr(i) & "=" & CStr(vals(i))
  Next i
Else
  Print #2, "not array err=" & Err.Description
End If
Close #2
End Sub
"""
try:
    sch.execute_vba_code(vba2)
    print("pattern VBA OK")
except Exception as e:
    print("pattern ERR", str(e)[-600:])

if pattern_path.exists():
    print(pattern_path.read_text(encoding="utf-8", errors="replace")[:2000])
else:
    print("pattern missing")
