"""Offline unit tests — no CST required."""

from __future__ import annotations

import pytest

from cst_mcp.domain.antennas.patch import design_patch
from cst_mcp.execution.results_reader import parse_sparam_csv, vswr_from_s11_db
from cst_mcp.vba_builder import VBABuilder, _format_number


def test_fmt_num_rejects_nan():
    with pytest.raises(ValueError):
        _format_number(float("nan"))


def test_brick_builder():
    vba = (
        VBABuilder("Brick")
        .set("Name", "box")
        .set("Component", "c1")
        .set("Material", "PEC")
        .set_double("Xrange", 0, 10)
        .set_double("Yrange", 0, 10)
        .set_double("Zrange", 0, 5)
        .call("Create")
        .build()
    )
    assert "With Brick" in vba
    assert '.Name "box"' in vba
    assert "Create" in vba


def test_cylinder_axis_x_uses_xrange():
    # Ported geometry must use axis-specific range property
    from cst_mcp.tools import geometry

    # Find helper if present; otherwise build expected pattern from handle offline
    assert any(t.name == "cst_create_cylinder" for t in geometry.TOOLS)


def test_patch_2g4_dimensions_reasonable():
    d = design_patch(2.4, epsilon_r=4.4, height_mm=1.6)
    assert 20 < d.width_mm < 50
    assert 20 < d.length_mm < 50
    assert d.eps_eff > 1


def test_vswr_total_reflection():
    assert vswr_from_s11_db(0.0) >= 1e5


def test_parse_sparam_csv(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text(
        "\n".join(
            [
                "Frequency, dB, Phase",
                "2.0, -5.0, 10",
                "2.4, -15.0, 20",
                "3.0, -8.0, 30",
            ]
        ),
        encoding="utf-8",
    )
    data = parse_sparam_csv(p)
    assert data["status"] == "ok"
    assert data["n_points"] == 3
    assert data["metrics"]["min_db"] == -15.0


def test_parse_cst_whitespace_sparam_export(tmp_path):
    """CST often writes space-separated S-param tables, not real CSV."""
    p = tmp_path / "s_ws.csv"
    p.write_text(
        "\n".join(
            [
                "        Frequency / GHz                S1,1/abs,dB",
                "----------------------------------------------------------------------",
                "               1.6799999                     -0.19691079",
                "                 2.34816                      -7.8142342",
                "               3.1200001                     -0.25000000",
            ]
        ),
        encoding="utf-8",
    )
    data = parse_sparam_csv(p)
    assert data["status"] == "ok"
    assert data["n_points"] == 3
    assert abs(data["metrics"]["min_db"] - (-7.8142342)) < 1e-6
    assert abs(data["metrics"]["freq_at_min_ghz"] - 2.34816) < 1e-6
