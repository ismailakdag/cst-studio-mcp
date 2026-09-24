"""Farfield discovery and metrics parsing tests (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cst_mcp.execution.farfield import (
    build_farfield_metrics_vba,
    discover_farfield_from_project_dir,
    extract_frequency_ghz,
    farfield_monitor_vba,
    farfield_tree_candidates,
    parse_farfield_metrics_kv,
    parse_farfield_summary_text,
)


def test_extract_frequency():
    assert extract_frequency_ghz("farfield (f=2.45)") == 2.45
    assert extract_frequency_ghz("farfield (f=867) [1]") == 867.0


def test_tree_candidates_include_port_suffix():
    paths = farfield_tree_candidates(2.4)
    assert any(p.startswith("Farfields\\") and "farfield (f=2.4)" in p for p in paths)
    assert any("[1]" in p for p in paths)
    # Prefer [1] excitation path first
    assert paths[0] == r"Farfields\farfield (f=2.4) [1]"
    # Bare name without Farfields\ must not appear
    assert "farfield (f=2.4)" not in paths
    assert paths[0].startswith("Farfields\\")


def test_farfield_metrics_vba_official_getmax():
    vba = build_farfield_metrics_vba(r"Farfields\farfield (f=2.4) [1]", r"E:/tmp/ff.txt")
    assert "Sub Main" not in vba
    assert "GetMax" in vba
    assert "ASCIIExportSummary" not in vba
    assert r'Farfields\farfield (f=2.4) [1]' in vba
    assert "SelectTreeItem" in vba
    assert "FarfieldPlot.Plot" in vba


def test_parse_getmax_kv_metrics():
    # Live dump from CST 2026 patch @ 2.4 GHz
    text = """
select=-1
GetMax=2.34283400307291
GetMin=-19.0519207409118
GetMean=-7.19018904486541
GetRadiationEfficiency=-3.46283291999167
GetTotalEfficiency=-4.71306190871945
GetTRP=0.168913287086863
GetPlotMode=realized gain
err=
"""
    m = parse_farfield_metrics_kv(text)
    assert m["select_ok"] is True
    assert abs(m["max_realized_gain_dbi"] - 2.34283400307291) < 1e-6
    assert abs(m["radiation_efficiency_db"] - (-3.46283291999167)) < 1e-6
    assert m["radiation_efficiency"] < 1.0
    assert m["trp_w"] > 0


def test_parse_summary_metrics():
    # Real CST 2026 ASCIIExportSummary shape (legacy)
    text = """
Farfield Summary
---------------------
Array pattern: Single antenna
Monitor name: farfield (f=867) [1]
Plot mode: Realized Gain
Frequency : 867 MHz
Radiation efficiency: -2.79557 dB
Total efficiency: -23.9706 dB
Maximum directivity [dB]: 2.16449
Maximum gain [dB]: -0.631086
Maximum realized gain [dB]: -21.8061
"""
    m = parse_farfield_summary_text(text)
    assert abs(m["max_gain_dbi"] - (-0.631086)) < 1e-6
    assert abs(m["directivity_dbi"] - 2.16449) < 1e-6
    assert abs(m["max_realized_gain_dbi"] - (-21.8061)) < 1e-6
    assert abs(m["frequency_ghz"] - 0.867) < 1e-6
    assert "radiation_efficiency_db" in m
    assert m["radiation_efficiency"] < 1.0


def test_farfield_monitor_vba_nearfield():
    vba = farfield_monitor_vba("farfield (f=2.4)", 2.4)
    assert 'FieldType "Farfield"' in vba
    assert "EnableNearfieldCalculation" in vba
    assert 'Frequency "2.4"' in vba


def test_discover_from_project_dir(tmp_path: Path):
    # Fake project layout
    proj = tmp_path / "demo.cst"
    proj.write_text("x", encoding="utf-8")
    res = tmp_path / "demo" / "Result"
    res.mkdir(parents=True)
    (res / "farfield (f=2.45)_1.ffm").write_bytes(b"00")
    found = discover_farfield_from_project_dir(str(proj))
    assert found
    assert found[0]["frequency_ghz"] == 2.45


def test_farfield_vba_uses_only_documented_cst2026_farfieldplot_methods():
    """Every generated FarfieldPlot call must exist on the CST 2026 help page."""
    from cst_mcp.execution import figures_3d_cst
    from cst_mcp.execution.farfield import build_farfield_metrics_vba
    from cst_mcp.execution.farfield_vba import undocumented_farfieldplot_calls
    from cst_mcp.tools import results
    from cst_mcp.tools.import_export import _build_export_farfield

    scripts = {
        "farfield": results._build_farfield_vba(2.4, None),
        "gain": results._build_gain_vba(2.4),
        "efficiency": results._build_efficiency_vba(2.4),
        "breakdown": results._build_efficiency_breakdown_vba(2.4),
        "cut_E": results._build_pattern_cut_vba(2.4, "E", 0, 0),
        "cut_custom": results._build_pattern_cut_vba(2.4, "custom", 30, 2),
        "xpol_l3": results._build_cross_polarization_vba(2.4, "Ludwig3"),
        "xpol_circ": results._build_cross_polarization_vba(2.4, "circular"),
        "ar_angle": results._build_axial_ratio_vba(2.4, "vs_angle", 0, 45),
        "ar_point": results._build_axial_ratio_vba(2.4, "vs_frequency", 10, 20),
        "pattern_3d": results._build_radiation_pattern_3d_vba(2.4, 5, "spherical"),
        "export_csv": _build_export_farfield(dict(file_path="C:/x/ff.txt", frequency=2.4)),
        "export_ffs": _build_export_farfield(dict(file_path="C:/x/ff.ffs", frequency=2.4, format="ffs")),
        "metrics": build_farfield_metrics_vba(r"Farfields\farfield (f=2.4) [1]", "C:/x/m.txt"),
        "fig_ascii": figures_3d_cst.build_ascii_export_vba(r"Farfields\f", "C:/x/a.txt", "gain", 5),
        "fig_list": figures_3d_cst.build_list_export_vba(r"Farfields\f", "C:/x/a.txt", "gain", 5),
    }
    for label, vba in scripts.items():
        assert undocumented_farfieldplot_calls(vba) == set(), label
        assert "GetResultValue" not in vba and "ASCIIExportSummary" not in vba, label


def test_pattern_3d_is_a_gain_table_not_a_farfield_source():
    from cst_mcp.tools import results

    vba = results._build_radiation_pattern_3d_vba(2.4, 10, "spherical")
    assert "ASCIIExportAsSource" not in vba
    assert "AddListEvaluationPoint(th, ph, 0, \"spherical\", \"\", 0)" in vba
    assert 'CalculateList("")' in vba and 'GetList("spherical abs")' in vba
    assert "For ph = 0 To 350 Step 10" in vba and '.SetPlotMode ("gain")' in vba
    with pytest.raises(ValueError):
        results._build_radiation_pattern_3d_vba(2.4, 5, "cartesian")


def test_export_farfield_formats_and_documented_objects():
    from cst_mcp.tools.import_export import _build_export_farfield

    csv = _build_export_farfield(dict(file_path="C:/x/ff.txt", frequency=2.4))
    assert "With ASCIIExport" in csv and ".Execute" in csv and "FarfieldPlot.Export" not in csv
    assert r'SelectTreeItem("Farfields\farfield (f=2.4)")' in csv
    ffs = _build_export_farfield(dict(file_path="C:/x/ff.ffs", frequency=2.4, format="ffs"))
    assert '.ASCIIExportAsSource ("C:/x/ff.ffs")' in ffs and "With ASCIIExport" not in ffs
    with pytest.raises(ValueError, match="nsf"):
        _build_export_farfield(dict(file_path="C:/x/ff.nsf", frequency=2.4, format="nsf"))
    with pytest.raises(ValueError):
        _build_export_farfield(dict(file_path='C:/x/f"f.txt', frequency=2.4))


@pytest.mark.asyncio
async def test_export_farfield_connected_csv_uses_silent_documented_path():
    import json as _json
    from types import SimpleNamespace

    from cst_mcp.tools import import_export

    calls = []
    client = SimpleNamespace(
        connected=True,
        export_farfield_ascii=lambda f, filepath=None, monitor_name=None: calls.append(
            (f, filepath, monitor_name)) or {"status": "exported"},
        execute_vba=lambda code: (_ for _ in ()).throw(AssertionError("no history VBA")),
        execute_vba_silent=lambda code, history_fallback=True: calls.append(("silent", history_fallback))
        or {"status": "executed"},
    )
    out = _json.loads((await import_export.handle(
        "cst_export_farfield", dict(file_path="C:/x/ff.txt", frequency=2.4), client))[0].text)
    assert out["status"] == "exported" and calls[0] == (2.4, "C:/x/ff.txt", None)
    out = _json.loads((await import_export.handle(
        "cst_export_farfield", dict(file_path="C:/x/ff.ffs", frequency=2.4, format="ffs"), client))[0].text)
    assert out["status"] == "executed" and calls[1] == ("silent", False)


@pytest.mark.asyncio
async def test_export_farfield_ffs_tries_port_suffixed_tree_names():
    """Live CST 2026: the TD farfield item is 'farfield (f=2.4) [1]'."""
    import json as _json
    from types import SimpleNamespace

    from cst_mcp.tools import import_export

    codes = []

    def silent(code, history_fallback=True):
        codes.append(code)
        ok = r'SelectTreeItem("Farfields\farfield (f=2.4)[1]")' in code
        return {"status": "executed"} if ok else {"status": "error", "message": "not found"}

    client = SimpleNamespace(connected=True, execute_vba_silent=silent)
    out = _json.loads((await import_export.handle(
        "cst_export_farfield", dict(file_path="C:/x/ff.ffs", frequency=2.4, format="ffs"), client))[0].text)
    assert out["status"] == "executed"
    assert out["tree_path"] == r"Farfields\farfield (f=2.4)[1]"
    assert out["tried_paths"][0] == r"Farfields\farfield (f=2.4) [1]" and len(codes) == 2


# Header + first rows of a live CST 2026 ASCIIExport (patch antenna, 2.4 GHz).
_LIVE_ASCII = """Theta [deg.]  Phi   [deg.]  Abs(Grlz)[dBi   ]   Abs(Theta)[dBi   ]  Phase(Theta)[deg.]  Abs(Phi  )[dBi   ]  Phase(Phi  )[deg.]  Ax.Ratio[dB    ]    
------------------------------------------------------------------------------------------------------------------------------------------------------
   0.000           0.000           -6.511e+00          -1.260e+02             336.544          -6.511e+00             179.583           4.000e+01     
  90.000           0.000           -9.000e+00          -2.432e+01             104.999          -8.361e+00             176.552           1.644e+01 
  90.000         180.000           -8.000e+00          -2.432e+01             104.999          -9.361e+00             176.552           1.644e+01 
 180.000         180.000           -20.00e+00          -2.432e+01             104.999          -30.00e+00             176.552           1.644e+01 
   0.000          90.000           -6.511e+00          -1.260e+02             336.544          -6.511e+00             179.583           4.000e+01     
"""


def test_parse_live_cst_ascii_export_uses_abs_column(tmp_path: Path):
    from cst_mcp.execution.farfield import parse_cst_farfield_ascii, parse_farfield_pattern_csv

    f = tmp_path / "ff.txt"
    f.write_text(_LIVE_ASCII)
    table = parse_cst_farfield_ascii(_LIVE_ASCII)
    assert table["columns"][:3] == ["Theta [deg.]", "Phi [deg.]", "Abs(Grlz) [dBi]"]
    assert table["columns"][5] == "Abs(Phi) [dBi]" and table["value_col"] == 2
    parsed = parse_farfield_pattern_csv(f)
    assert parsed["status"] == "ok" and parsed["n_points"] == 5
    # Peak of Abs(Grlz), not of the last/fourth column.
    assert parsed["metrics"]["peak_value"] == -6.511 and parsed["value_column"] == "Abs(Grlz) [dBi]"


def test_pattern_cut_from_table_signed_theta():
    from cst_mcp.execution.farfield import parse_cst_farfield_ascii
    from cst_mcp.tools.results import _pattern_cut_from_table

    cut = _pattern_cut_from_table(parse_cst_farfield_ascii(_LIVE_ASCII), 0.0)
    # phi=0 rows at +theta; phi=180 rows at -theta (theta 0/180 poles not duplicated).
    assert cut["angle_deg"] == [-90.0, 0.0, 90.0] and cut["value"] == [-8.0, -6.511, -9.0]


def test_metrics_kv_separates_gain_directivity_and_realized():
    text = "select=-1\nGetMax=-6.51\nGetRadiationEfficiency=-3.215\nGetTotalEfficiency=-13.4\n" \
           "GetPlotMode=realized gain\nGetMaxGain=3.68\nGetMaxDirectivity=6.9\nerr=\n"
    m = parse_farfield_metrics_kv(text)
    assert m["max_realized_gain_dbi"] == -6.51 and m["max_gain_dbi"] == 3.68
    assert m["max_directivity_dbi"] == 6.9
    assert abs(m["radiation_efficiency"] - 10 ** (-0.3215)) < 1e-9
    vba = build_farfield_metrics_vba(r"Farfields\farfield (f=2.4) [1]", "C:/x/m.txt")
    assert vba.index('SetPlotMode ("gain")') > vba.index("GetPlotMode")
    assert 'Print #1, "GetMaxDirectivity=" & CStr(FarfieldPlot.GetMax)' in vba
