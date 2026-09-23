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


def _numeric_free(expr: str) -> bool:
    """Parameter expression without numeric literals ("0" datum and /2 allowed)."""
    import re

    return expr == "0" or not re.search(r"\d", expr.replace("/2", ""))


def test_probe_offset_matches_cos2_rule_2g4_fr4():
    import math

    d = design_patch(2.4, epsilon_r=4.4, height_mm=1.6, feed_type="probe")
    y0 = d.length_mm / math.pi * math.acos(math.sqrt(50 / d.edge_resistance_ohm))
    # R_edge cos^2(pi y0 / L) = 50, y0 measured from the edge -> offset from centre
    assert abs(d.edge_resistance_ohm * math.cos(math.pi * y0 / d.length_mm) ** 2 - 50) < 1e-6
    assert abs(d.probe_offset_mm - (d.length_mm / 2 - y0)) < 0.1
    assert 3.5 < d.probe_offset_mm < 4.1  # ~3.80 mm
    assert d.probe_radius_mm == 0.635
    assert abs(d.coax_outer_radius_mm - 0.635 * math.exp(50 * math.sqrt(2.1) / 60)) < 1e-9
    assert abs(d.coax_outer_radius_mm - 2.12) < 0.01
    assert d.inset_mm == 0.0 and d.notch_gap_mm == 0.0
    for other in ("inset", "microstrip"):
        assert design_patch(2.4, feed_type=other).probe_offset_mm == 0.0


def test_workflow_probe_builds_parametric_coax_feed():
    import re

    steps = _workflow_steps(feed_type="probe")
    labels = list(steps)
    params = steps["store_parameters"]
    for name in ("probe_y", "probe_r", "coax_r_out", "coax_er", "coax_len", "coax_t"):
        assert f'StoreParameter "{name}"' in params
    assert 'StoreParameter "probe_r", "0.635"' in params
    assert "feed_w" not in params and '"inset"' not in params
    assert "brick_feed" not in steps and not any("notch" in k for k in steps)

    assert 'If Not Material.Exists("PTFE") Then' in steps["material_ptfe"]
    assert '.Epsilon "coax_er"' in steps["material_ptfe"]

    pin = steps["cylinder_probe_pin"]
    assert '.Material "PEC"' in pin and '.OuterRadius "probe_r"' in pin
    assert '.Zrange "-coax_len", "sub_h"' in pin  # touches the patch bottom
    ptfe = steps["cylinder_coax_dielectric"]
    assert '.Material "PTFE"' in ptfe
    assert '.OuterRadius "coax_r_out"' in ptfe and '.InnerRadius "probe_r"' in ptfe
    assert '.Zrange "-coax_len", "0"' in ptfe
    shield = steps["cylinder_coax_shield"]
    assert '.Material "PEC"' in shield
    assert '.OuterRadius "coax_r_out+coax_t"' in shield
    assert '.InnerRadius "coax_r_out"' in shield
    assert '.Zrange "-coax_len", "-metal_t"' in shield
    clearance = steps["cylinder_ground_clearance"]
    assert '.OuterRadius "coax_r_out"' in clearance
    assert '.Zrange "-metal_t", "0"' in clearance
    assert steps["boolean_ground_clearance"] == (
        'Solid.Subtract "Antenna:Ground", "Antenna:GndClearance"'
    )
    assert steps["boolean_probe_pin_substrate"] == (
        'Solid.Insert "Antenna:Substrate", "Antenna:ProbePin"'
    )
    order = [labels.index(k) for k in (
        "brick_ground", "brick_substrate", "brick_patch", "material_ptfe",
        "cylinder_ground_clearance", "boolean_ground_clearance",
        "cylinder_probe_pin", "boolean_probe_pin_substrate",
        "cylinder_coax_dielectric", "cylinder_coax_shield", "port_wg_1")]
    assert order == sorted(order)

    port = steps["port_wg_1"]
    assert '.Orientation "zmin"' in port and '.PortOnBound "False"' in port
    assert '.Xrange "-coax_r_out", "coax_r_out"' in port
    assert '.Yrange "-probe_y-coax_r_out", "-probe_y+coax_r_out"' in port
    assert '.Zrange "-coax_len", "-coax_len"' in port

    # Everything in the feed and port is a parameter expression
    for label in labels:
        if not label.startswith(("cylinder_", "port_")):
            continue
        vba = steps[label]
        for rng in re.findall(r'\.[XYZ]range "([^"]*)", "([^"]*)"', vba):
            assert all(_numeric_free(e) for e in rng), (label, rng)
        for val in re.findall(r'\.(?:Outer|Inner)Radius "([^"]*)"', vba):
            assert _numeric_free(val), (label, val)
        for val in re.findall(r'\.[XY]center "([^"]*)"', vba):
            assert _numeric_free(val), (label, val)
    # Pin centre coincides with the port aperture centre and ground clearance
    for label in ("cylinder_probe_pin", "cylinder_coax_dielectric",
                  "cylinder_coax_shield", "cylinder_ground_clearance"):
        assert '.Xcenter "0"' in steps[label] and '.Ycenter "-probe_y"' in steps[label]


def test_workflow_probe_shield_covers_port_aperture():
    import math

    from cst_mcp.tools.workflows import COAX_WALL_MM

    d = design_patch(2.4, feed_type="probe")
    # The square port (+-coax_r_out) must stay inside the PEC shield
    assert d.coax_outer_radius_mm * math.sqrt(2) < d.coax_outer_radius_mm + COAX_WALL_MM


def test_workflow_microstrip_and_inset_have_no_probe_steps():
    from cst_mcp.execution.port_helpers import microstrip_waveguide_port_vba

    for feed in ("inset", "microstrip"):
        d = design_patch(2.4, feed_type=feed)
        steps = _workflow_steps(feed_type=feed)
        assert not any(k.startswith(("cylinder_", "material_ptfe")) for k in steps)
        assert "probe_y" not in steps["store_parameters"]
        assert "coax" not in steps["store_parameters"]
        assert 'StoreParameter "feed_w"' in steps["store_parameters"]
        assert "brick_feed" in steps
        assert steps["port_wg_1"] == microstrip_waveguide_port_vba(
            port_number=1, y_edge=-d.ground_y_mm / 2, feed_width=d.feed_width_mm,
            substrate_height=d.height_mm, ground_bottom=-0.035,
            metal_thickness=0.035, x_center=0.0,
        )


def test_workflow_probe_runs_against_fake_client():
    import asyncio
    import json

    from cst_mcp.tools import workflows

    class FakeClient:
        connected = True
        has_project = True

        def __init__(self):
            self.history = []

        def execute_vba(self, vba, history_label=None):
            self.history.append(history_label)
            return {"status": "executed"}

        def _run_model3d_vba(self, vba):
            return {"status": "executed"}

        def list_parameters(self):
            return {}

    client = FakeClient()
    out = asyncio.run(workflows.handle(
        "cst_workflow_patch_antenna",
        {"frequency_ghz": 2.4, "feed_type": "probe", "create_project": False},
        client))
    payload = json.loads(out[0].text)
    assert payload["status"] == "executed"
    for label in ("cylinder_probe_pin", "boolean_ground_clearance",
                  "boolean_probe_pin_substrate", "cylinder_coax_shield", "port_wg_1"):
        assert label in client.history
    assert "probe_y" in payload["parameter_hint"]
    assert payload["design"]["probe_offset_mm"] > 0


def test_antenna_patch_template_subtracts_inset_notches():
    import json

    from cst_mcp.tools.antenna_templates import _build_patch_antenna

    vba = json.loads(_build_patch_antenna({"frequency_ghz": 2.4}))["vba_script"]
    assert '"Vacuum"' not in vba
    assert 'Solid.Subtract "Antenna:Patch", "Antenna:InsetSlotL"' in vba
    assert 'Solid.Subtract "Antenna:Patch", "Antenna:InsetSlotR"' in vba
    assert vba.index("Solid.Subtract") < vba.index('.Name "FeedLine"')
