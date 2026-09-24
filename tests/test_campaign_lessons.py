"""Lessons from a two-day CST 2026 antenna campaign (unit tests with fakes, no CST).

* Monitor.FieldType "Surfacecurrent" does not exist -> Hfield + expected tree items.
* Power balance P_acc = P_rad + P_loss (PML leakage through an 'open' boundary).
* Boundary/port sanity checks.
* Edge-launch SMA connector with an internal port (PortOnBound False).
* ExtrudeCurve direction follows the winding -> extrude_direction option.
* 1D power-loss monitor solver option.
* Surface-current ASCIIExport parsing and top-view |J| maps.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from cst_mcp.execution import model_checks, power_balance as pb, sma_connector
from cst_mcp.tools import boundaries, diagnostics, geometry, pcb, results, solvers
from cst_mcp.tools.annotations import annotations_for
from cst_mcp.types import FieldMonitorType, expected_monitor_tree_items, normalize_field_monitor_type

B = "\\"


class FakeClient:
    connected = False
    is_connected = False
    has_project = False
    project_path = None

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute_vba(self, code, history_label=None, **_kw):
        self.executed.append(code)
        return {"status": "offline", "vba": code}


def run(mod, name, args, client=None):
    client = client or FakeClient()
    out = asyncio.run(mod.handle(name, args, client))
    return json.loads(out[0].text), client


def _hint(ann, v1, v2):
    return getattr(ann, v1, None) if getattr(ann, v1, None) is not None else getattr(ann, v2, None)


# --------------------------------------------------------------------------- 1. field monitors


def test_field_type_enum_has_only_documented_values():
    values = [e.value for e in FieldMonitorType]
    assert "Surfacecurrent" not in values
    assert {"Efield", "Hfield", "Farfield", "Powerloss", "Fieldsource"} <= set(values)
    assert FieldMonitorType.SURFACE_CURRENT is FieldMonitorType.H_FIELD


@pytest.mark.parametrize("req", ["Surfacecurrent", "surface current", "surface_current", "SurfaceCurrent"])
def test_surface_current_requests_map_to_hfield(req):
    ftype, note = normalize_field_monitor_type(req)
    assert ftype == "Hfield" and "Hfield" in note


def test_invalid_field_type_rejected_and_case_normalised():
    assert normalize_field_monitor_type("efield")[0] == "Efield"
    with pytest.raises(ValueError, match="Hfield"):
        normalize_field_monitor_type("SurfaceCurrents2")


def test_add_field_monitor_translates_surface_current():
    res, client = run(results, "cst_add_field_monitor", {"monitor_type": "surface current", "frequency": 2.45})
    vba = client.executed[-1]
    assert '.FieldType "Hfield"' in vba and "Surfacecurrent" not in vba
    assert res["monitor_type"] == "Hfield" and res["requested_type"] == "surface current"
    assert f"2D/3D Results{B}Surface Current{B}surface current (f=2.45) [1]" in res["expected_tree_items"]
    assert res["monitor_name"] == "h-field (f=2.45)"
    bad, _ = run(results, "cst_add_field_monitor", {"monitor_type": "Nonsense", "frequency": 2.45})
    assert bad["status"] == "error" and "Hfield" in bad["valid_types"]


def test_expected_tree_items_and_surface_current_tool_paths():
    items = expected_monitor_tree_items("Hfield", "h-field (f=5.5)", 5.5)
    assert items[0] == f"2D/3D Results{B}H-Field{B}h-field (f=5.5) [1]"
    res, _ = run(results, "cst_get_surface_current", {"frequency": 5.5})
    assert res["tree_path"] == f"2D/3D Results{B}Surface Current{B}surface current (f=5.5) [1]"
    assert "Hfield" in res["prerequisite"] and "Surfacecurrent'" in res["prerequisite"]
    # ASCIIExport.FileName must be absolute (CST help): built from GetProjectPath.
    assert 'ascii.FileName GetProjectPath("Project") & "\\surface_current_5.5GHz.txt"' in res["vba_script"]


def test_no_tool_emits_surfacecurrent_field_type():
    root = Path(__file__).resolve().parents[1] / "src" / "cst_mcp"
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        assert 'FieldType", "Surfacecurrent' not in text and 'FieldType "Surfacecurrent' not in text, p


# --------------------------------------------------------------------------- 2. power balance

FREQS = [2.45, 5.5]


def _curves(p_rad, loss_diel, loss_metal=(0.0004, 0.0005), dense_acc=(0.46, 0.44)):
    xs = [1.5 + 0.1 * i for i in range(51)]
    acc = [dense_acc[0] + (dense_acc[1] - dense_acc[0]) * (x - 2.45) / (5.5 - 2.45) for x in xs]
    return {
        "P_stim": {"x": xs, "y": [0.5] * len(xs)},
        "P_acc": {"x": xs, "y": acc},
        "P_rad": {"x": FREQS, "y": list(p_rad)},
        "P_loss_diel": {"x": FREQS, "y": list(loss_diel)},
        "P_loss_metal": {"x": FREQS, "y": list(loss_metal)},
    }


def test_balance_flags_pml_leak_and_explains():
    # Campaign 'open' boundary model: P_rad/P_acc 0.726, 1 - P_loss/P_acc 0.971 -> ~24.5 % unaccounted.
    c = _curves(p_rad=(0.46 * 0.726, 0.44 * 0.769), loss_diel=(0.46 * 0.029 - 0.0004, 0.44 * 0.071 - 0.0005))
    out = pb.compute_balance(c, FREQS)
    row = out["frequencies"]["2.45"]
    assert row["eta_farfield"] == pytest.approx(0.726, abs=1e-3)
    assert row["eta_loss"] == pytest.approx(0.971, abs=1e-3)
    assert row["unaccounted_fraction"] == pytest.approx(0.245, abs=2e-3)
    assert row["flag"] and out["flagged_frequencies_ghz"] == FREQS and out["balance_closes"] is False
    assert "PML" in out["warning"] and "virtually infinite" in out["warning"]
    assert "PortOnBound False" in out["recommendation"] and "expanded open" in out["recommendation"]


def test_balance_closes_for_sma_model_and_pattern_estimate():
    c = _curves(p_rad=(0.46 * 0.975, 0.44 * 0.911), loss_diel=(0.46 * 0.027 - 0.0004, 0.44 * 0.088 - 0.0005))
    out = pb.compute_balance(c, FREQS, pattern_means={2.45: 0.975 * 0.46 / 0.5})
    row = out["frequencies"]["2.45"]
    assert not row["flag"] and row["closes"] is True and out["balance_closes"] is True
    assert row["eta_pattern"] == pytest.approx(0.975, abs=1e-6)
    assert row["mismatch_efficiency"] == pytest.approx(0.92, abs=1e-6)
    assert "warning" not in out


def test_losses_missing_at_non_monitor_frequency():
    c = _curves(p_rad=(0.45, 0.40), loss_diel=(0.012, 0.038))
    out = pb.compute_balance(c, [3.0])
    row = out["frequencies"]["3"]
    assert row["P_loss"] is None and row["sampling"]["P_loss_diel"] == "no_sample"
    assert "ActivatePowerLoss1DMonitor" in out["loss_note"] and out["balance_closes"] is None


def test_zero_loss_sample_gets_note():
    # Live CST 2026: Hfield-only monitor without the 1D loss monitor -> Loss in Dielectrics == 0.
    c = _curves(p_rad=(0.46 * 0.962, 0.40), loss_diel=(0.0, 0.03), loss_metal=(0.0, 0.0))
    out = pb.compute_balance(c, [2.45])
    assert out["frequencies"]["2.45"]["P_loss"] == 0.0
    assert "exactly 0" in out["zero_loss_note"] and "ActivatePowerLoss1DMonitor" in out["zero_loss_note"]
    assert "zero_loss_note" not in pb.compute_balance(_curves((0.45, 0.4), (0.012, 0.03)), FREQS)


def test_sphere_mean_of_isotropic_and_dipole_patterns():
    th = [5.0 * i for i in range(37)]
    ph = [5.0 * i for i in range(72)]
    assert pb.sphere_mean_linear(th, ph, [[0.0] * len(th) for _ in ph]) == pytest.approx(1.0, abs=1e-9)
    dip = [[10 * math.log10(max(1.5 * math.sin(math.radians(t)) ** 2, 1e-30)) for t in th] for _ in ph]
    assert pb.sphere_mean_linear(th, ph, dip) == pytest.approx(1.0, abs=0.01)


def test_check_power_balance_tool_inline_and_project(monkeypatch, tmp_path):
    c = _curves(p_rad=(0.46 * 0.726, 0.44 * 0.769), loss_diel=(0.0129, 0.031))
    res, _ = run(diagnostics, "cst_check_power_balance", {"power_curves": c, "frequencies_ghz": FREQS})
    assert res["status"] == "ok" and res["flagged_frequencies_ghz"] == FREQS and res["read_only"]

    seen = []

    def fake_read(project_path, tree_path, run_id=0, *, allow_interactive=False):
        seen.append(tree_path)
        key = next(k for k, v in pb.POWER_ITEMS.items() if tree_path.endswith(v))
        return {"status": "ok", "x": c[key]["x"], "real": c[key]["y"], "imag": [0.0] * len(c[key]["x"])}

    monkeypatch.setattr("cst_mcp.execution.curves.read_curve", fake_read)
    res, _ = run(diagnostics, "cst_check_power_balance", {"project_path": str(tmp_path / "a.cst")})
    assert res["status"] == "ok" and list(res["frequencies"]) == ["2.45", "5.5"]  # default = loss samples
    assert seen[0] == f"1D Results{B}Power{B}Excitation [1]{B}Power Stimulated"
    none, _ = run(diagnostics, "cst_check_power_balance", {})
    assert none["status"] == "error"
    ann = annotations_for("cst_check_power_balance")
    assert _hint(ann, "readOnlyHint", "read_only_hint") is True


def test_farfield_metrics_gets_power_balance_warning(monkeypatch):
    from cst_mcp.cst_client import CSTClient

    c = _curves(p_rad=(0.46 * 0.726, 0.44 * 0.769), loss_diel=(0.0129, 0.031))

    def fake_read(project_path, tree_path, run_id=0, *, allow_interactive=False):
        key = next(k for k, v in pb.POWER_ITEMS.items() if tree_path.endswith(v))
        return {"status": "ok", "x": c[key]["x"], "real": c[key]["y"]}

    monkeypatch.setattr("cst_mcp.execution.curves.read_curve", fake_read)
    client = CSTClient()
    client._project_path = "fake.cst"
    monkeypatch.setattr(client, "_get_farfield_metrics_impl",
                        lambda *a, **k: {"status": "ok", "method": "x", "metrics": {}, "sources": {}})
    out = client.get_farfield_metrics(2.45)
    assert out["power_balance_warning"]["unaccounted_fraction"] > 0.2
    assert "PML" in out["power_balance_warning"]["message"]
    assert client.get_farfield_metrics(None).get("power_balance_warning") is None


# --------------------------------------------------------------------------- 3. boundary sanity


def test_port_on_open_face_with_structure_is_error():
    rep = model_checks.check_setup(
        {"x_min": "expanded open", "x_max": "expanded open", "y_min": "open", "y_max": "expanded open",
         "z_min": "expanded open", "z_max": "expanded open"},
        [{"port_number": 1, "orientation": "ymin", "plane": 0.0}],
        structure_bbox={"xmin": -13, "xmax": 13, "ymin": 0.0, "ymax": 37.6, "zmin": -1.6, "zmax": 0},
    )
    codes = [i["code"] for i in rep["issues"]]
    assert "waveguide_port_on_open_boundary" in codes and rep["ok"] is False
    issue = rep["issues"][codes.index("waveguide_port_on_open_boundary")]
    assert issue["severity"] == "error" and "PML" in issue["message"] and "PortOnBound False" in issue["fix"]


def test_expanded_open_with_internal_port_is_clean():
    rep = model_checks.check_setup({f: "expanded open" for f in model_checks.FACES},
                                   [{"orientation": "ymin", "port_on_bound": False, "plane": -6.3}],
                                   power_loss_1d=True, farfield_frequencies=[2.45])
    assert rep["ok"] and rep["issues"] == []
    rep = model_checks.check_setup({f: "expanded open" for f in model_checks.FACES}, [],
                                   farfield_frequencies=[2.45, 5.5], field_monitor_frequencies=[2.45])
    assert rep["issues"][0]["code"] == "losses_missing_at_farfield_frequencies"
    assert rep["issues"][0]["frequencies_ghz"] == [5.5]


def test_check_model_setup_tool_and_set_boundary_warning():
    res, _ = run(diagnostics, "cst_check_model_setup",
                 {"boundaries": {"ymin": "open"}, "ports": [{"orientation": "ymin", "port_on_bound": True}]})
    assert res["issues"][0]["code"] == "waveguide_port_on_open_boundary"
    assert _hint(annotations_for("cst_check_model_setup"), "readOnlyHint", "read_only_hint") is True
    faces = {f: "expanded open" for f in model_checks.FACES}
    faces["y_min"] = "open"
    res, _ = run(boundaries, "cst_set_boundary", {**faces, "waveguide_port_faces": ["y_min"]})
    assert res["warnings"][0]["code"] == "waveguide_port_on_open_boundary"
    res, _ = run(boundaries, "cst_set_boundary", {f: "expanded open" for f in model_checks.FACES})
    assert "warnings" not in res


# --------------------------------------------------------------------------- 4. SMA connector


def test_sma_ymin_cpw_geometry_and_internal_port():
    res, client = run(pcb, "cst_add_sma_edge_connector",
                      {"edge": "ymin", "copper_z_convention": "copper_below_top"})
    vba = client.executed[-1]
    assert '.PortOnBound "False"' in vba and '.Orientation "ymin"' in vba
    assert '.Yrange "-6.3", "-6.3"' in vba  # coax back face = -(gap + body length)
    assert res["axis_z"] == pytest.approx(0.635) and res["coax"]["z0_ohm"] == pytest.approx(49.5, abs=0.1)
    assert '.Zrange "0", "0.635"' in vba  # solder from the copper top face to the pin axis
    assert '.Yrange "-6.3", "1.5"' in vba  # pin across the gap onto the strip
    assert '.Epsilon "2.1"' in vba and 'Solid.Subtract "sma:body", "sma:bore"' in vba
    assert '.Xrange "2.9", "4.4"' in vba and '.Xrange "-4.4", "-2.9"' in vba  # legs on both grounds
    ann = annotations_for("cst_add_sma_edge_connector")
    assert _hint(ann, "readOnlyHint", "read_only_hint") is False


def test_sma_copper_above_top_and_xmax_edge():
    vba, s = sma_connector.build_sma_vba({"edge": "xmax", "edge_position": 20, "feed_center": 3,
                                          "copper_z_convention": "copper_above_top", "copper_thickness": 0.035})
    assert s["copper_top_z"] == pytest.approx(0.035) and s["axis_z"] == pytest.approx(0.67)
    assert '.Axis "x"' in vba and '.Ycenter "3"' in vba and '.Orientation "xmax"' in vba
    assert s["port"]["plane"] == pytest.approx(26.3)
    assert '.Xrange "26.3", "26.3"' in vba


def test_sma_validation_and_impedance():
    with pytest.raises(ValueError, match="copper_z_convention"):
        sma_connector.build_sma_vba({"edge": "ymin"})
    _, s = sma_connector.build_sma_vba({"edge": "ymax", "copper_z_convention": "copper_below_top",
                                        "target_impedance": 50})
    assert s["coax"]["outer_radius"] == pytest.approx(2.126, abs=2e-3)
    assert s["coax"]["z0_ohm"] == pytest.approx(50, abs=0.05)
    with pytest.raises(ValueError):
        sma_connector.build_sma_vba({"edge": "ymin", "copper_z_convention": "copper_below_top",
                                     "outer_radius": 5.0})  # bore larger than the body
    res, _ = run(pcb, "cst_add_sma_edge_connector",
                 {"edge": "ymin", "copper_z_convention": "copper_below_top", "component": 'a"\nRunAndWait "x'})
    assert res["status"] == "error"
    vba, _ = sma_connector.build_sma_vba({"edge": "ymin", "copper_z_convention": "copper_below_top",
                                          "ground_type": "microstrip", "substrate_thickness": 1.6})
    assert '.Zrange "-2.135", "-1.635"' in vba  # bottom leg under the back-side ground


# --------------------------------------------------------------------------- 5. extrude direction

SQUARE = [[0, 0], [1, 0], [1, 1], [0, 1]]


def test_polygon_extrude_default_unchanged_and_down_reverses_winding():
    base = {"component": "c", "name": "p", "points": SQUARE, "height": 0.035}
    default = geometry._build_polygon_extrude(dict(base))
    up = geometry._build_polygon_extrude({**base, "extrude_direction": "up"})
    down = geometry._build_polygon_extrude({**base, "extrude_direction": "down"})
    assert default.replace("(up, ", "(") == up.replace("(up, ", "(")
    pts_up = [ln for ln in up.splitlines() if ".Point" in ln]
    pts_down = [ln for ln in down.splitlines() if ".Point" in ln]
    assert pts_down[:-1] == pts_up[:-1][::-1]  # same vertices, opposite winding
    assert '.Thickness "0.035"' in down
    with pytest.raises(ValueError):
        geometry._build_polygon_extrude({**base, "extrude_direction": "sideways"})
    res, _ = run(geometry, "cst_create_polygon_extrude", {**base, "extrude_direction": "down", "z_offset": 0})
    assert res["extrusion"]["expected_range"] == [-0.035, 0.0]
    res, _ = run(geometry, "cst_create_polygon_extrude", {**base, "z_offset": 1.6})
    assert res["extrusion"]["expected_range"] == pytest.approx([1.6, 1.635])


# --------------------------------------------------------------------------- 6. solver option


def test_power_loss_1d_option():
    res, client = run(solvers, "cst_configure_time_domain_solver",
                      {"activate_power_loss_1d": True, "power_loss_1d_extra_frequencies": [3.0]})
    vba = client.executed[-1]
    assert '.ActivatePowerLoss1DMonitor "True"' in vba
    assert '.UseFarFieldMonitorForPowerLoss1DMonitor "True"' in vba
    assert '.UseExtraFreqForPowerLoss1DMonitor "True"' in vba and '.AddPowerLoss1DMonitorExtraFreq "3"' in vba
    assert res["power_loss_1d"]["activated"]
    _, client = run(solvers, "cst_configure_time_domain_solver", {})
    assert "PowerLoss1D" not in client.executed[-1]


def test_time_domain_solver_uses_documented_solver_methods():
    # Live CST 2026 rejected .AccuracyOrder ("no such property or method"), which
    # aborted the whole block including ActivatePowerLoss1DMonitor.
    res, client = run(solvers, "cst_configure_time_domain_solver",
                      {"accuracy": -30, "fixed_impedance": 75, "max_time_steps": 5000,
                       "excitation_type": "Smooth", "activate_power_loss_1d": True})
    vba = client.executed[-1]
    assert '.SteadyStateLimit "-30"' in vba
    assert '.AutoNormImpedance "True"' in vba and '.NormingImpedance "75"' in vba
    for bad in ("AccuracyOrder", "MaxTimeSteps", "NormalizeToFixedImpedance", ".FixedImpedance",
                "ExcitationType"):
        assert bad not in vba
    assert len(res["notes"]) == 2
    _, client = run(solvers, "cst_configure_time_domain_solver", {"normalize_to_fixed_impedance": False})
    vba = client.executed[-1]
    assert '.AutoNormImpedance "False"' in vba and "NormingImpedance" not in vba


# --------------------------------------------------------------------------- 7. surface current

HEADER = ("           x [mm]           y [mm]           z [mm]       KxRe [A/m]       KxIm [A/m]       KyRe [A/m]"
          "       KyIm [A/m]       KzRe [A/m]       KzIm [A/m]      Area [mm^2]\n" + "-" * 170 + "\n")


def _write_sc(path: Path, scale: float = 1.0) -> Path:
    rows = []
    for i in range(10):
        for j in range(10):
            x, y = 0.05 + 0.1 * i, 0.05 + 0.1 * j
            k = scale * (10.0 if (i, j) == (7, 2) else 1.0)
            # top face z=0 and bottom face z=-0.035 carry the same current -> sum doubles it
            for z in (0.0, -0.035):
                rows.append(f"{x:17.6f}{y:17.6f}{z:17.6f}{k:17.6f}{0:17.6f}{0:17.6f}{0:17.6f}{0:17.6f}{0:17.6f}"
                            f"{0.01:17.6f}")
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_parse_and_grid_sum_face_layers(tmp_path):
    pytest.importorskip("numpy")
    from cst_mcp.execution.surface_current import grid_top_view, parse_surface_current_ascii

    s = parse_surface_current_ascii(_write_sc(tmp_path / "j.txt"))
    assert s.k.shape == (200, 3) and s.length_unit == "mm"
    g = grid_top_view(s, cell=0.1, extent=(0, 1, 0, 1))
    assert g["layers"] == 2 and g["max_A_per_m"] == pytest.approx(20.0)
    assert g["max_at"] == pytest.approx([0.75, 0.25])
    with pytest.raises(ValueError):
        parse_surface_current_ascii(text="x y\n1 2\n")


def test_plot_surface_current_offline_shared_scale(tmp_path):
    pytest.importorskip("matplotlib")
    from cst_mcp.tools import figures_3d

    a, b = _write_sc(tmp_path / "a.txt"), _write_sc(tmp_path / "b.txt", scale=0.5)
    client = SimpleNamespace(is_connected=False, config=SimpleNamespace(work_dir=tmp_path))
    res, _ = run(figures_3d, "cst_plot_surface_current",
                 {"data_files": [str(a), str(b)], "labels": ["A", "B"], "cell": 0.1, "out_dir": str(tmp_path / "f")},
                 client)
    assert res["status"] == "ok", res
    assert Path(res["files"][0]).is_file()
    assert res["scale_ref_A_per_m"] == pytest.approx(20.0)
    assert [p["scale_ref_A_per_m"] for p in res["panels"]] == pytest.approx([20.0, 20.0])
    res, _ = run(figures_3d, "cst_plot_surface_current", {}, client)
    assert res["status"] == "error" and "data_files" in res["message"]


class _ScClient:
    is_connected = True
    has_project = True
    project_path = None

    def __init__(self, tmp_path: Path, selectable: bool = True):
        self.config = SimpleNamespace(work_dir=tmp_path)
        self.vba: list[str] = []
        self.selected: list[str] = []
        outer = self

        class _M3D:
            def SelectTreeItem(self, tree):  # noqa: N802
                outer.selected.append(tree)
                return selectable and tree.endswith("surface current (f=2.45) [1]")

        self.model3d = _M3D()
        self._tmp = tmp_path

    def _run_vba_no_history(self, vba):
        self.vba.append(vba)
        line = next(ln for ln in vba.splitlines() if ".FileName" in ln)
        _write_sc(Path(line.split('"')[1]))
        return {"status": "executed"}


def test_plot_surface_current_connected_ascii_export(tmp_path):
    pytest.importorskip("matplotlib")
    from cst_mcp.tools import figures_3d

    client = _ScClient(tmp_path)
    res, _ = run(figures_3d, "cst_plot_surface_current",
                 {"frequency_ghz": 2.45, "cell": 0.1, "subvolume": [-1, 2, -1, 2, -0.2, 0.3],
                  "out_dir": str(tmp_path / "f")}, client)
    assert res["status"] == "ok", res
    assert res["sources"][0]["tree_path"] == f"2D/3D Results{B}Surface Current{B}surface current (f=2.45) [1]"
    vba = client.vba[-1]
    assert "With ASCIIExport" in vba and '.Mode "FixedWidth"' in vba and ".UseSubvolume True" in vba
    assert "ExportImage" not in vba
    none = _ScClient(tmp_path, selectable=False)
    res, _ = run(figures_3d, "cst_plot_surface_current", {"frequency_ghz": 2.45}, none)
    assert res["status"] == "no_results" and "Hfield" in res["message"]


def test_surface_current_grid_defaults_to_copper_sheet_when_export_spans_connector():
    np = pytest.importorskip("numpy")
    from cst_mcp.execution.surface_current import SurfaceCurrentSamples, grid_top_view

    # Copper (z 0 and 0.035) carries 10 A/m; a connector face at z=5 carries 1 A/m
    # over the same footprint and would dilute the copper map if averaged in.
    xs = np.repeat([0.2, 0.6, 1.0], 3)
    ys = np.tile([0.2, 0.6, 1.0], 3)
    x = np.concatenate([xs, xs, xs])
    y = np.concatenate([ys, ys, ys])
    z = np.concatenate([np.zeros(9), np.full(9, 0.035), np.full(9, 5.0)])
    k = np.zeros((27, 3), complex)
    k[:18, 0] = 5.0   # 5 A/m on each copper face -> 10 A/m summed
    k[18:, 0] = 1.0
    s = SurfaceCurrentSamples(x=x, y=y, z=z, k=k, area=np.full(27, 0.16))

    g = grid_top_view(s, cell=0.4)
    assert g["n_samples"] == 18
    assert g["max_A_per_m"] == pytest.approx(10.0)
