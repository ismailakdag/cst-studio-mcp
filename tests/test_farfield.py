"""Farfield discovery and metrics parsing tests (offline)."""

from __future__ import annotations

from pathlib import Path

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
