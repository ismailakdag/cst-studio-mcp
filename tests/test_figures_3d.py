"""cst_plot_farfield: CST farfield ASCII parsing, metrics and figure output (offline)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("matplotlib")

from cst_mcp.execution.figures_3d_data import (  # noqa: E402
    beam_metrics,
    extract_cut,
    parse_farfield_ascii,
    pattern_metrics,
    write_cst_ascii,
)
from cst_mcp.execution import figures_3d_cst as fc  # noqa: E402
from cst_mcp.tools import figures_3d  # noqa: E402

N = 4
BACK = 0.01


def _cosn_grid(step: float = 1.0):
    theta = np.arange(0, 180 + 1e-9, step)
    phi = np.arange(0, 360, step)
    T, P = np.meshgrid(np.deg2rad(theta), np.deg2rad(phi))
    g0 = 2 * (N + 1)
    base = g0 * (np.clip(np.cos(T), 0, None) ** N + BACK)
    total = 10 * np.log10(base)
    eth = 10 * np.log10(base * np.cos(P) ** 2 + 1e-12)
    eph = 10 * np.log10(base * np.sin(P) ** 2 + 1e-12)
    return theta, phi, total, {"theta": eth, "phi": eph}


def _analytic_hpbw() -> float:
    c = 0.5 * (1 + BACK) - BACK
    return 2 * math.degrees(math.acos(c ** (1 / N)))


@pytest.fixture
def cosn_file(tmp_path: Path) -> Path:
    th, ph, tot, comps = _cosn_grid(1.0)
    return write_cst_ascii(tmp_path / "farfield (f=2.4) [1].txt", th, ph, tot, components=comps)


def test_parse_cst_layout_and_metrics(cosn_file: Path) -> None:
    grid = parse_farfield_ascii(cosn_file)
    assert grid.header_found and grid.quantity == "realized_gain" and grid.unit == "dBi"
    assert grid.total_db.shape == (360, 181)
    assert set(grid.components_db) == {"theta", "phi"}
    cuts = [extract_cut(grid, "phi", 0), extract_cut(grid, "phi", 90)]
    m = pattern_metrics(grid, cuts)
    assert m["max_value"] == pytest.approx(10 * math.log10(2 * (N + 1) * (1 + BACK)), abs=1e-3)
    assert m["max_direction_deg"]["theta"] == 0
    assert m["front_to_back_db"] == pytest.approx(10 * math.log10((1 + BACK) / BACK), abs=0.05)
    for c in m["cuts"]:
        assert c["hpbw_deg"] == pytest.approx(_analytic_hpbw(), abs=0.5)
        assert c["peak_angle_deg"] == pytest.approx(0, abs=1e-6)
    assert m["polarization"]["co"] in {"theta", "phi"}
    # full-circle phi cut: signed theta from -179 to 180
    assert cuts[0].angle.min() < -170 and cuts[0].angle.max() == 180


def test_hpbw_on_coarse_5deg_grid(tmp_path: Path) -> None:
    th, ph, tot, _ = _cosn_grid(5.0)
    grid = parse_farfield_ascii(write_cst_ascii(tmp_path / "ff.txt", th, ph, tot))
    bm = beam_metrics(extract_cut(grid, "phi", 0))
    assert bm["hpbw_deg"] == pytest.approx(_analytic_hpbw(), abs=2.5)


def test_side_lobe_level_uniform_array(tmp_path: Path) -> None:
    theta = np.arange(0, 181, 0.5)
    phi = np.arange(0, 360, 5.0)
    T, P = np.meshgrid(np.deg2rad(theta), np.deg2rad(phi))
    psi = np.pi * np.sin(T) * np.cos(P)
    with np.errstate(invalid="ignore", divide="ignore"):
        af = np.where(np.abs(np.sin(psi / 2)) < 1e-9, 1.0, np.sin(8 * psi / 2) / (8 * np.sin(psi / 2)))
    lin = af**2 * np.clip(np.cos(T), 1e-3, None) + 1e-6
    grid = parse_farfield_ascii(write_cst_ascii(tmp_path / "arr.txt", theta, phi, 10 * np.log10(lin),
                                                name="Dir.", unit="dBi"))
    assert grid.quantity == "directivity"
    bm = beam_metrics(extract_cut(grid, "phi", 0))
    assert -14.0 < bm["sll_db"] < -11.5


def test_header_variants(tmp_path: Path) -> None:
    rows = [(t, p, 10 * math.cos(math.radians(t)) ** 2 + 0.1) for p in (0, 90, 180, 270) for t in range(0, 181, 5)]
    # Linear directivity, CST empty-unit brackets, dashed rule
    lin = tmp_path / "lin.txt"
    lin.write_text("Theta [deg.]  Phi   [deg.]  Abs(Dir.)[      ]  Phase(Theta)[deg.]\n" + "-" * 60 + "\n"
                   + "\n".join(f"{t:10.3f} {p:10.3f} {v:14.6e} {0.0:10.3f}" for t, p, v in rows))
    g = parse_farfield_ascii(lin)
    assert g.scale_input == "linear" and g.quantity == "directivity"
    assert np.nanmax(g.total_db) == pytest.approx(10 * math.log10(10.1), abs=1e-4)
    # CSV with quotes and semicolons
    csv = tmp_path / "ff.csv"
    csv.write_text('"Theta [deg.]";"Phi [deg.]";"Abs(Gain)[dBi]"\n'
                   + "\n".join(f"{t};{p};{10 * math.log10(v):.5f}" for t, p, v in rows))
    g2 = parse_farfield_ascii(csv)
    assert g2.quantity == "gain" and g2.total_db.shape == (4, 37)
    # Headerless numeric table (dB assumed), '#'-comment lines
    bare = tmp_path / "bare.txt"
    bare.write_text("# exported farfield, frequency = 2.4 GHz\n"
                    + "\n".join(f"{t} {p} {10 * math.log10(v):.4f}" for t, p, v in rows))
    g3 = parse_farfield_ascii(bare)
    assert not g3.header_found and g3.frequency_ghz == pytest.approx(2.4)
    # Theta360 layout (theta 0..355, phi 0..175) folds onto the standard sphere
    t360 = tmp_path / "t360.txt"
    t360.write_text("Theta [deg.] Phi [deg.] Abs(Realized Gain)[dBi]\n" + "\n".join(
        f"{t} {p} {10 * math.log10(10 * math.cos(math.radians(t)) ** 2 + 0.1):.4f}"
        for p in (0, 90) for t in range(0, 360, 5)))
    g4 = parse_farfield_ascii(t360)
    assert set(np.round(g4.phi)) == {0, 90, 180, 270} and g4.theta.max() == 180
    # Ludwig-3 columns become co/cross components
    l3 = tmp_path / "l3.txt"
    l3.write_text("Theta [deg.] Phi [deg.] Abs(Realized Gain)[dBi] Abs(Hor )[dBi] Phase(Hor )[deg.] "
                  "Abs(Ver )[dBi] Phase(Ver )[deg.]\n" + "\n".join(
                      f"{t} {p} {10 * math.log10(v):.4f} {10 * math.log10(v) - 25:.4f} 0 {10 * math.log10(v):.4f} 0"
                      for t, p, v in rows))
    g5 = parse_farfield_ascii(l3)
    assert set(g5.components_db) == {"horizontal", "vertical"}
    assert pattern_metrics(g5, [extract_cut(g5, "phi", 0)])["polarization"]["co"] == "vertical"


def test_parser_rejects_garbage(tmp_path: Path) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_text("no numbers here\njust text\n")
    with pytest.raises(ValueError):
        parse_farfield_ascii(bad)


def _decode(content) -> dict:
    return json.loads(content[0].text)


def _offline_client(tmp_path: Path):
    return SimpleNamespace(is_connected=False, has_project=False, project_path=None,
                           config=SimpleNamespace(work_dir=tmp_path))


@pytest.mark.asyncio
async def test_tool_renders_all_plots_from_data_file(tmp_path: Path, cosn_file: Path) -> None:
    out = tmp_path / "figs"
    res = _decode(await figures_3d.handle("cst_plot_farfield", {
        "data_file": str(cosn_file), "plots": ["polar", "rect", "heatmap", "3d"],
        "cuts": [0, "H-plane", "theta=60"], "formats": ["png", "pdf"], "out_dir": str(out),
    }, _offline_client(tmp_path)))
    assert res["status"] == "ok", res
    assert res["source"]["kind"] == "data_file"
    assert len(res["files"]) == 8
    for f in res["files"]:
        assert Path(f).is_file() and Path(f).stat().st_size > 1000
    assert len(res["metrics"]["cuts"]) == 3
    assert res["metrics"]["max_realized_gain_dbi"] == pytest.approx(10.043, abs=0.01)

    uv = _decode(await figures_3d.handle("cst_plot_farfield", {
        "data_file": str(cosn_file), "plots": ["heatmap"], "heatmap_projection": "uv",
        "formats": ["svg"], "out_dir": str(out), "width": "double",
    }, _offline_client(tmp_path)))
    assert uv["status"] == "ok" and uv["files"][0].endswith("_heatmap_uv.svg")


@pytest.mark.asyncio
async def test_tool_input_validation_and_offline_errors(tmp_path: Path) -> None:
    client = _offline_client(tmp_path)
    schema = figures_3d._schema(figures_3d.TOOLS[0])
    assert schema["additionalProperties"] is False
    bad = _decode(await figures_3d.handle("cst_plot_farfield", {"bogus": 1}, client))
    assert bad["status"] == "error"
    bad = _decode(await figures_3d.handle("cst_plot_farfield", {"step_deg": 7}, client))
    assert bad["status"] == "error"
    missing = _decode(await figures_3d.handle("cst_plot_farfield", {"data_file": str(tmp_path / "x.txt")}, client))
    assert missing["status"] == "error"
    offline = _decode(await figures_3d.handle("cst_plot_farfield", {}, client))
    assert offline["status"] == "error" and "data_file" in offline["message"]
    proj = tmp_path / "p.cst"
    proj.write_bytes(b"")
    nores = _decode(await figures_3d.handle("cst_plot_farfield", {"project_path": str(proj)}, client))
    assert nores["status"] == "no_results"


class _FakeModel:
    def __init__(self, selectable: bool):
        self.selectable = selectable

    def SelectTreeItem(self, path):  # noqa: N802
        return self.selectable and path.startswith("Farfields\\farfield (f=2.4) [1]")


class _FakeClient:
    def __init__(self, tmp_path: Path, selectable: bool, monitors_text: str = "", export: bool = True):
        self.config = SimpleNamespace(work_dir=tmp_path)
        self.is_connected = True
        self.has_project = True
        self.project_path = str(tmp_path / "p.cst")
        self.model3d = _FakeModel(selectable)
        self.monitors_text = monitors_text
        self.export = export
        self.vba: list[str] = []

    def _idle_error(self):
        return None

    def discover_farfield_monitors(self):
        return {"monitors": []}

    def _run_vba_no_history(self, vba: str):
        import re

        self.vba.append(vba)
        target = re.search(r'(?:FileName \(|Open )"([^"]+)"', vba).group(1)
        if "Monitor.GetNumberOfMonitors" in vba:
            Path(target).write_text(self.monitors_text)
        elif self.export and "ASCIIExport" in vba:
            th, ph, tot, comps = _cosn_grid(5.0)
            write_cst_ascii(target, th, ph, tot, components=comps)
        return {"status": "executed"}


@pytest.mark.asyncio
async def test_connected_export_and_no_results(tmp_path: Path) -> None:
    client = _FakeClient(tmp_path, selectable=True)
    res = _decode(await figures_3d.handle("cst_plot_farfield", {
        "frequency_ghz": 2.4, "plots": ["rect"], "formats": ["png"], "out_dir": str(tmp_path / "f"),
    }, client))
    assert res["status"] == "ok", res
    assert res["source"]["tree_path"] == "Farfields\\farfield (f=2.4) [1]"
    assert res["source"]["method"] == "ascii_export"
    vba = client.vba[-1]
    assert 'SetPlotMode ("realized gain")' in vba and ".Step (5)" in vba and "ASCIIExportSummary" not in vba

    none = _FakeClient(tmp_path, selectable=False, monitors_text="farfield (f=2.4)\tFarfield\t2.4\n")
    res = _decode(await figures_3d.handle("cst_plot_farfield", {"frequency_ghz": 2.4}, none))
    assert res["status"] == "no_results" and res["farfield_monitors"][0]["name"] == "farfield (f=2.4)"
    assert "cst_run_simulation_async" in res["message"]

    empty = _FakeClient(tmp_path, selectable=False, monitors_text="e-field (f=2.4)\tEfield\t2.4\n")
    res = _decode(await figures_3d.handle("cst_plot_farfield", {}, empty))
    assert res["status"] == "no_results" and "No farfield monitor" in res["message"]


def test_vba_builders_use_official_api() -> None:
    a = fc.build_ascii_export_vba("Farfields\\farfield (f=2.4) [1]", "C:/x.txt", "directivity", 5)
    assert 'Plottype ("3d")' in a and "With ASCIIExport" in a and ".Execute" in a
    b = fc.build_list_export_vba("Farfields\\farfield (f=2.4) [1]", "C:/x.txt", "gain", 5)
    assert "CalculateList" in b and 'GetList("Point_T")' in b
