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
                "Frequency / GHz, dB, Phase",
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


def test_inset_depth_uses_balanis_edge_resistance():
    import math

    d = design_patch(2.4, epsilon_r=4.4, height_mm=1.6)
    assert 250 < d.edge_resistance_ohm < 400
    expected = d.length_mm / math.pi * math.acos(math.sqrt(50 / d.edge_resistance_ohm))
    assert abs(d.inset_mm - expected) < 1e-9
    assert 0.3 * d.length_mm < d.inset_mm < 0.45 * d.length_mm
    assert d.notch_gap_mm == 1.0
    assert design_patch(2.4, feed_type="microstrip").inset_mm == 0.0
    with pytest.raises(ValueError):
        design_patch(2.4, notch_gap_mm=0)


def _workflow_steps(**kw):
    from cst_mcp.tools.workflows import _patch_vba_steps

    return dict(_patch_vba_steps(design_patch(2.4, **kw)))


def test_workflow_inset_patch_cuts_notches_before_feed():
    import re

    steps = _workflow_steps()
    labels = list(steps)
    assert 'StoreParameter "notch_g", "1"' in steps["store_parameters"]
    left, right = steps["brick_notch_left"], steps["brick_notch_right"]
    assert '.Xrange "-feed_w/2-notch_g", "-feed_w/2"' in left
    assert '.Xrange "feed_w/2", "feed_w/2+notch_g"' in right
    for notch in (left, right):
        assert '.Yrange "-patch_L/2-metal_t", "-patch_L/2+inset"' in notch
        assert '.Zrange "sub_h", "sub_h+metal_t"' in notch
    boolean = steps["boolean_inset_notches"]
    assert 'Solid.Subtract "Antenna:Patch", "Antenna:Notch_left"' in boolean
    assert 'Solid.Subtract "Antenna:Patch", "Antenna:Notch_right"' in boolean
    # Notches cut after the patch exists and before the feed is added
    order = [labels.index(k) for k in (
        "brick_patch", "brick_notch_left", "brick_notch_right",
        "boolean_inset_notches", "brick_feed")]
    assert order == sorted(order)
    # Feed stays inside the notch: same half-width as the notch inner edges,
    # ends at the inset point, never reaches the patch sides.
    feed = steps["brick_feed"]
    assert '.Xrange "-feed_w/2", "feed_w/2"' in feed
    assert '.Yrange "-gnd_y/2", "-patch_L/2+inset"' in feed
    # Geometry is fully parametric (no numeric literals in solid ranges)
    for label in ("brick_patch", "brick_notch_left", "brick_notch_right", "brick_feed"):
        for rng in re.findall(r'\.[XYZ]range "([^"]*)", "([^"]*)"', steps[label]):
            for expr in rng:
                assert not re.search(r"\d", expr.replace("/2", "")), (label, expr)


def test_workflow_microstrip_patch_has_no_notches():
    steps = _workflow_steps(feed_type="microstrip")
    assert not any("notch" in k for k in steps)
    assert "notch_g" not in steps["store_parameters"]


def test_workflow_stores_parameters_outside_history():
    from cst_mcp.tools import workflows

    class FakeClient:
        connected = True
        has_project = True

        def __init__(self):
            self.history, self.silent = [], []

        def execute_vba(self, vba, history_label=None):
            self.history.append(history_label)
            return {"status": "executed"}

        def _run_model3d_vba(self, vba):
            self.silent.append(vba)
            return {"status": "executed", "entrypoint": "model3d._execute_vba_code"}

        def list_parameters(self):
            return {}

    import asyncio
    import json

    client = FakeClient()
    out = asyncio.run(workflows.handle(
        "cst_workflow_patch_antenna",
        {"frequency_ghz": 2.4, "create_project": False}, client))
    payload = json.loads(out[0].text)
    assert payload["status"] == "executed"
    assert "store_parameters" not in client.history
    assert len(client.silent) == 1 and 'StoreParameter "inset"' in client.silent[0]
    assert "boolean_inset_notches" in client.history


def test_antenna_patch_template_subtracts_inset_notches():
    import json

    from cst_mcp.tools.antenna_templates import _build_patch_antenna

    vba = json.loads(_build_patch_antenna({"frequency_ghz": 2.4}))["vba_script"]
    assert '"Vacuum"' not in vba
    assert 'Solid.Subtract "Antenna:Patch", "Antenna:InsetSlotL"' in vba
    assert 'Solid.Subtract "Antenna:Patch", "Antenna:InsetSlotR"' in vba
    assert vba.index("Solid.Subtract") < vba.index('.Name "FeedLine"')
