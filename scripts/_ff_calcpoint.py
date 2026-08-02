from pathlib import Path
import sys
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")
import cst.interface as ci

de = ci.DesignEnvironment.connect(22108)
p = de.get_open_project(r"E:\cstprojects\patch_2p4_retry.cst")
sch = p.schematic

out = Path(r"E:/cstprojects/exports/ff_calcpoint.txt")
if out.exists():
    out.unlink()

vba = r"""
Sub Main()
Open "E:/cstprojects/exports/ff_calcpoint.txt" For Output As #1
On Error Resume Next

' Official style: settings, then select, then plot
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

Dim ok As Boolean
ok = SelectTreeItem("Farfields\farfield (f=2.4) [1]")
Print #1, "select_ok=" & CStr(ok)
FarfieldPlot.Plot
Print #1, "after_plot GetMax=" & CStr(FarfieldPlot.GetMax)
Print #1, "eff_rad=" & CStr(FarfieldPlot.GetRadiationEfficiency)
Print #1, "eff_tot=" & CStr(FarfieldPlot.GetTotalEfficiency)
Print #1, "mode=" & CStr(FarfieldPlot.GetPlotMode)
Print #1, "err1=" & Err.Description
Err.Clear

' CalculatePoint with explicit name
Dim v As Double
v = FarfieldPlot.CalculatePoint(0, 0, "spherical abs abs abs", "Farfields\farfield (f=2.4) [1]")
Print #1, "calc0_0=" & CStr(v) & " err=" & Err.Description
Err.Clear
v = FarfieldPlot.CalculatePoint(0, 0, "spherical abs abs abs", "")
Print #1, "calc_current=" & CStr(v) & " err=" & Err.Description
Err.Clear
v = FarfieldPlot.CalculatePoint(90, 0, "spherical linear theta abs", "Farfields\farfield (f=2.4) [1]")
Print #1, "calc90_theta=" & CStr(v) & " err=" & Err.Description
Err.Clear

' try gain mode names
With FarfieldPlot
  .SetPlotMode ("directivity")
  .Plot
End With
Print #1, "dir_max=" & CStr(FarfieldPlot.GetMax) & " err=" & Err.Description
Err.Clear
With FarfieldPlot
  .SetPlotMode ("gain")
  .Plot
End With
Print #1, "gain_max=" & CStr(FarfieldPlot.GetMax) & " err=" & Err.Description
Err.Clear

' try Efield mode which is in example
With FarfieldPlot
  .SetPlotMode ("Efield")
  .SetScaleLinear (True)
  .Plot
End With
Print #1, "efield_max=" & CStr(FarfieldPlot.GetMax) & " err=" & Err.Description
Err.Clear

' list monitors
Dim n As Long, i As Long
n = Monitor.GetNumberOfMonitors
Print #1, "n_monitors=" & CStr(n)
For i = 0 To n - 1
  Print #1, "mon" & CStr(i) & "=" & Monitor.GetMonitorNameFromIndex(i) & " type=" & Monitor.GetMonitorTypeFromIndex(i) & " dom=" & Monitor.GetMonitorDomainFromIndex(i) & " f=" & CStr(Monitor.GetMonitorFrequencyFromIndex(i))
Next i

Close #1
End Sub
"""
try:
    sch.execute_vba_code(vba)
    print("OK")
except Exception as e:
    print("ERR", str(e)[-700:])
print(out.read_text(encoding="utf-8", errors="replace") if out.exists() else "missing")
