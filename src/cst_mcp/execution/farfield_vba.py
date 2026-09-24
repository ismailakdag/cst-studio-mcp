"""FarfieldPlot VBA helpers restricted to methods documented in CST 2026.

Source: installed CST Studio Suite 2026 Online Help, ``FarfieldPlot Object``
(mergedProjects/VBA_3D/special_vbapostproc/special_vbapostproc_farfieldploto.htm)
and ``ASCIIExport Object`` (common_vbaimpexp/asciiexport_object.htm).

Facts taken from that page (documentation only, not verified live):

* ``FarfieldPlot`` has **no** ``ASCIIExport`` / ``ASCIIExportSummary`` /
  ``Export`` / ``GetResultValue`` / ``GetNPoints`` / ``GetAngle`` /
  ``GetValue`` method.  The only export methods are ``ASCIIExportVersion``,
  ``ASCIIExportAsSource`` and ``ASCIIExportAsBroadbandSource`` -- the latter
  two write a *farfield source* (excitation) file, not a gain table.
* A gain/directivity table is obtained either by selecting the farfield tree
  item, ``FarfieldPlot.Plot`` and running the separate ``ASCIIExport`` object
  (which supports "1D and 2D/3D farfields"), or by the list route:
  ``AddListEvaluationPoint`` + ``CalculateList("")`` + ``GetList(component)``
  (component e.g. ``"spherical abs"``, ``"spherical linear theta abs"``,
  ``"Point_T"``, ``"Point_P"``).
* Secondary results: ``GetMax``, ``GetMin``, ``GetMean``,
  ``GetRadiationEfficiency``, ``GetTotalEfficiency``, ``GetTRP``,
  ``GetMainLobeVector`` (3D), ``GetMainLobeDirection`` /
  ``GetAngularWidthXdB`` / ``GetSideLobeLevel`` (polar plots only).
"""

from __future__ import annotations

import re

from cst_mcp.vba_safety import vba_escape, vba_number

# Every method/property listed on the CST 2026 FarfieldPlot help page.
DOCUMENTED_FARFIELDPLOT_METHODS = frozenset(
    """
    ASCIIExportAsBroadbandSource ASCIIExportAsSource ASCIIExportVersion AddCut
    AddListEvaluationPoint Alpha Azimuth CalculateList CalculatePoint
    CalculatePointNoApprox CartSymRange ClearCuts CopyFarfieldTo1DResults DBUnit
    DecouplingPlaneAxis DecouplingPlanePosition Distance DrawContourLines
    DrawIsoLongitudeLatitudeLines DrawStepLines Elevation EnableFixPlotMaximum
    EnablePhaseCenterCalculation Epsilon FarfieldSize GetAngularWidthXdB
    GetFixPlotMaximumValue GetFrontToBackRatio GetList GetListItem GetLogRange
    GetMainLobeDirection GetMainLobeVector GetMax GetMean GetMin GetPhaseCenterResult
    GetPhaseCenterResultExpr GetPhaseCenterResultExprAvg GetPhaseCenterResultExprEPlane
    GetPhaseCenterResultExprHPlane GetPlotMode GetRadiationEfficiency GetSideLobeLevel
    GetSideLobeSuppression GetSystemRadiationEfficiency GetSystemTotalEfficiency GetTRP
    GetTotalACS GetTotalEfficiency GetTotalRCS IncludeUnitCellSidewalls InvertAxes
    Origin Phi Phistart Plot Plottype PolarizationVector Reset ResetPlot
    SelectComponent SetAntennaType SetAutomaticCoordinateSystem SetAxesType
    SetColorByValue SetCoordinateSystemType SetFarfieldTransparent
    SetFixPlotMaximumValue SetFrequency SetInverseAxialRatio SetLockSteps SetLogNorm
    SetLogRange SetMainLobeThreshold SetMaxReferenceMode SetMovieSamples
    SetMultipolNumber SetNumberOfContourValues SetPhaseCenterAngularLimit
    SetPhaseCenterComponent SetPhaseCenterPlane SetPhiEnd SetPhiStart SetPlotMode
    SetPlotRangeOnly SetPolarizationType SetScaleLinear SetSpecials
    SetStructureTransparent SetTheta360 SetThetaEnd SetThetaStart SetTime
    SetTimeDomainFF SetUserDecouplingPlane SetUserMirrorPlane ShowPhaseCenter
    ShowStructure ShowStructureProfile SlantAngle Step Step2 StoreSettings
    SymmetricRange Theta Thetastart UseDecouplingPlane UseFarfieldApproximation
    UseMirrorPlane Userorigin Vary
    """.split()
)

DOCUMENTED_PLOT_MODES = frozenset(
    {"directivity", "gain", "realized gain", "efield", "epattern", "hfield", "pfield",
     "rcs", "rcsunits", "rcssw"}
)


def undocumented_farfieldplot_calls(vba: str) -> set[str]:
    """Names called on FarfieldPlot (``FarfieldPlot.X``, ``ff.X`` or inside
    ``With FarfieldPlot``) that are not on the CST 2026 help page."""
    names: set[str] = set()
    names.update(re.findall(r"\bFarfieldPlot\.(\w+)", vba))
    if re.search(r"Set\s+ff\s*=\s*FarfieldPlot\b", vba):
        names.update(re.findall(r"\bff\.(\w+)", vba))
    for block in re.findall(r"With\s+FarfieldPlot\b(.*?)End\s+With", vba, re.S):
        names.update(re.findall(r"^\s*\.(\w+)", block, re.M))
    return {n for n in names if n not in DOCUMENTED_FARFIELDPLOT_METHODS}


def _angles(start: float, stop: float, step: float) -> tuple[str, str, str]:
    return vba_number(start, "start"), vba_number(stop, "stop"), vba_number(step, "step")


def select_farfield_lines(tree_path: str, indent: str = "  ") -> list[str]:
    safe = vba_escape(tree_path, "tree_path")
    return [
        f'{indent}If Not SelectTreeItem("{safe}") Then',
        f'{indent}  Err.Raise vbObjectError + 1, , "Farfield tree item not found: {safe}"',
        f"{indent}End If",
    ]


def plot_setup_lines(plot_mode: str, plottype: str = "3d", step_deg: float = 5.0,
                     indent: str = "  ") -> list[str]:
    if plot_mode not in DOCUMENTED_PLOT_MODES:
        raise ValueError(f"plot_mode must be one of {sorted(DOCUMENTED_PLOT_MODES)}")
    step = vba_number(step_deg, "step_deg")
    return [
        f"{indent}With FarfieldPlot",
        f"{indent}  .Reset",
        f'{indent}  .Plottype ("{vba_escape(plottype, "plottype")}")',
        f"{indent}  .Step ({step})",
        f"{indent}  .Step2 ({step})",
        f"{indent}  .SetLockSteps (True)",
        f'{indent}  .SetPlotMode ("{plot_mode}")',
        f"{indent}  .SetScaleLinear (False)",
        f"{indent}End With",
    ]


def list_table_lines(
    out_file_expr: str | None,
    components: list[tuple[str, str]],
    *,
    theta: tuple[float, float, float] = (0, 180, 5),
    phi: tuple[float, float, float] = (0, 355, 5),
    phi_values: list[float] | None = None,
    indent: str = "  ",
) -> list[str]:
    """Evaluate a theta/phi grid via AddListEvaluationPoint + CalculateList and
    write ``Theta Phi <components...>`` rows with ``Print #``.

    ``out_file_expr`` is a VBA string *expression* (already safe), e.g.
    ``GetProjectPath("Result") & "/ff.txt"``; ``None`` prints the rows with
    ``Debug.Print`` instead (offline templates; file I/O is denylisted there).
    ``components`` are
    ``(GetList identifier, column header)`` pairs.  Values follow the current
    plot mode / scaling (``SetScaleLinear False`` -> dB for gain modes).
    """
    t0, t1, ts = _angles(*theta)
    lines = [
        f"{indent}Dim th As Double, ph As Double, i As Long, fnum As Integer",
        f"{indent}Dim pt As Variant, pp As Variant",
    ]
    for k in range(len(components)):
        lines.append(f"{indent}Dim v{k} As Variant")
    lines.append(f"{indent}FarfieldPlot.Plot")
    if phi_values is not None:
        for value in phi_values:
            ph = vba_number(value, "phi")
            lines += [
                f"{indent}For th = {t0} To {t1} Step {ts}",
                f'{indent}  FarfieldPlot.AddListEvaluationPoint(th, {ph}, 0, "spherical", "", 0)',
                f"{indent}Next th",
            ]
    else:
        p0, p1, ps = _angles(*phi)
        lines += [
            f"{indent}For ph = {p0} To {p1} Step {ps}",
            f"{indent}  For th = {t0} To {t1} Step {ts}",
            f'{indent}    FarfieldPlot.AddListEvaluationPoint(th, ph, 0, "spherical", "", 0)',
            f"{indent}  Next th",
            f"{indent}Next ph",
        ]
    lines += [
        f'{indent}FarfieldPlot.CalculateList("")',
        f'{indent}pt = FarfieldPlot.GetList("Point_T")',
        f'{indent}pp = FarfieldPlot.GetList("Point_P")',
    ]
    header = "Theta[deg]  Phi[deg]"
    row = 'CStr(pt(i)) & "  " & CStr(pp(i))'
    for k, (ident, label) in enumerate(components):
        lines.append(f'{indent}v{k} = FarfieldPlot.GetList("{vba_escape(ident, "component")}")')
        header += "  " + vba_escape(label, "label")
        row += f' & "  " & CStr(v{k}(i))'
    if out_file_expr is None:
        # Offline templates: print rows (file I/O is rejected by the VBA denylist).
        lines += [
            f'{indent}Debug.Print "{header}"',
            f"{indent}For i = LBound(pt) To UBound(pt)",
            f"{indent}  Debug.Print {row}",
            f"{indent}Next i",
        ]
        return lines
    lines += [
        f"{indent}fnum = FreeFile",
        f"{indent}Open {out_file_expr} For Output As #fnum",
        f'{indent}Print #fnum, "{header}"',
        f"{indent}For i = LBound(pt) To UBound(pt)",
        f"{indent}  Print #fnum, {row}",
        f"{indent}Next i",
        f"{indent}Close #fnum",
    ]
    return lines


__all__ = [
    "DOCUMENTED_FARFIELDPLOT_METHODS",
    "DOCUMENTED_PLOT_MODES",
    "list_table_lines",
    "plot_setup_lines",
    "select_farfield_lines",
    "undocumented_farfieldplot_calls",
]
