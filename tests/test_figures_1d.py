"""cst_plot_1d_results: metrics, rendering, no-results path, CSV overlays (no CST needed)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from cst_mcp.execution import figures_1d_source as source
from cst_mcp.execution.figures_1d_metrics import (
    bandwidth_metrics,
    impedance,
    parse_overlay_csv,
    run_labels,
    to_db,
    vswr,
)
from cst_mcp.tools import figures_1d

pytest.importorskip("matplotlib")


def lorentz_gamma(f, dips, floor=0.95):
    """|Gamma| = floor * (1 - sum depth / (1 + ((f - f0)/hw)^2)), with a phase ramp."""
    out = []
    for x in f:
        dip = sum(d / (1 + ((x - f0) / hw) ** 2) for f0, hw, d in dips)
        mag = max(floor * (1 - dip), 1e-6)
        out.append(mag * complex(math.cos(4 * x), -math.sin(4 * x)))
    return out


def grid(lo=1.0, hi=4.0, n=3001):
    return [lo + (hi - lo) * j / (n - 1) for j in range(n)]


# ----------------------------------------------------------------- metrics


def test_single_lorentzian_band_matches_analytic_edges():
    f = grid()
    f0, hw, depth = 2.4, 0.05, 0.98
    gam = lorentz_gamma(f, [(f0, hw, depth)])
    m = bandwidth_metrics(f, to_db(gam), -10)
    assert m["matched"] and len(m["bands"]) == 1
    assert m["f_res_ghz"] == pytest.approx(f0, abs=1e-3)
    assert m["s11_min_db"] == pytest.approx(20 * math.log10(0.95 * (1 - depth)), abs=0.3)
    # Analytic edges: 0.95 (1 - d/(1+u^2)) = 10^(-0.5)
    g = 10 ** (-10 / 20) / 0.95
    u = math.sqrt(depth / (1 - g) - 1)
    lo, hi = f0 - u * hw, f0 + u * hw
    band = m["bands"][0]
    assert band["f_low"] == pytest.approx(lo, abs=2e-4)
    assert band["f_high"] == pytest.approx(hi, abs=2e-4)
    assert band["bw_mhz"] == pytest.approx((hi - lo) * 1e3, rel=5e-3)
    assert band["fbw_pct"] == pytest.approx(100 * (hi - lo) / ((hi + lo) / 2), rel=5e-3)
    assert not band["lower_truncated"] and not band["upper_truncated"]


def test_multiple_bands_are_reported_separately():
    f = grid()
    gam = lorentz_gamma(f, [(1.8, 0.03, 0.95), (3.2, 0.06, 0.97)])
    m = bandwidth_metrics(f, to_db(gam), -10)
    assert len(m["bands"]) == 2
    b1, b2 = m["bands"]
    assert b1["f_low"] < 1.8 < b1["f_high"] < b2["f_low"] < 3.2 < b2["f_high"]
    assert b2["bw_mhz"] > b1["bw_mhz"]
    assert m["total_bw_mhz"] == pytest.approx(b1["bw_mhz"] + b2["bw_mhz"])
    assert b1["f_min_ghz"] == pytest.approx(1.8, abs=2e-3)


def test_no_band_when_not_matched():
    f = grid()
    m = bandwidth_metrics(f, to_db(lorentz_gamma(f, [(2.4, 0.05, 0.5)])), -10)
    assert m["bands"] == [] and not m["matched"] and m["total_bw_mhz"] == 0
    assert m["f_res_ghz"] == pytest.approx(2.4, abs=2e-3)


def test_truncated_band_at_sweep_edge():
    f = grid(2.3, 3.0)
    m = bandwidth_metrics(f, to_db(lorentz_gamma(f, [(2.3, 0.05, 0.98)])), -10)
    assert m["bands"][0]["lower_truncated"] and m["bands"][0]["f_low"] == 2.3


def test_bandwidth_rejects_bad_input():
    with pytest.raises(ValueError):
        bandwidth_metrics([1.0, 1.0], [-1, -2])
    with pytest.raises(ValueError):
        bandwidth_metrics([1.0], [-1])


def test_vswr_and_impedance_from_gamma():
    assert vswr([0.5 + 0j])[0] == pytest.approx(3.0)
    assert math.isnan(vswr([1.0 + 0j])[0])
    assert impedance([0j], 50)[0] == pytest.approx(50)
    assert impedance([1 / 3 + 0j], 50)[0] == pytest.approx(100)
    assert impedance([0j], [49.1 + 0j])[0] == pytest.approx(49.1)


def test_run_labels_use_varying_parameters():
    labels = run_labels({1: {"L": 29.0, "W": 38}, 2: {"L": 30.0, "W": 38}})
    assert labels == {1: "L = 29", 2: "L = 30"}
    assert run_labels({3: {}, 4: {}}) == {3: "Run 3", 4: "Run 4"}


def test_select_runs_policy():
    assert source.select_runs([0], None, 6) == [0]
    assert source.select_runs([0, 1], None, 6) == [1]
    assert source.select_runs([0, 1, 2, 3], None, 2) == [2, 3]
    assert source.select_runs([0, 1, 2], [0, 2], 6) == [0, 2]
    with pytest.raises(ValueError):
        source.select_runs([0, 1], [5], 6)


def test_reflection_path_prefers_s11():
    items = ["1D Results\\S-Parameters\\S2,1", "1D Results\\S-Parameters\\S2,2",
             "1D Results\\S-Parameters\\S1,1"]
    assert source.reflection_path(items) == "1D Results\\S-Parameters\\S1,1"
    assert source.reflection_path(["1D Results\\S-Parameters\\S2,1"]) is None


# -------------------------------------------------------------- CSV overlay


@pytest.mark.parametrize(
    ("text", "unit", "expected_first"),
    [
        ("Frequency / GHz, S11 / dB\n2.0, -3.0\n2.4, -20.0\n", None, 2.0),
        ("# freq_MHz; dB\n2000;-3\n2400;-20\n", None, 2.0),
        ("2000000000\t-3\n2400000000\t-20\n", None, 2.0),
        ("2000 -3\n2400 -20\n", "MHz", 2.0),
    ],
)
def test_parse_overlay_csv_units_and_delimiters(tmp_path, text, unit, expected_first):
    p = tmp_path / "meas.csv"
    p.write_text(text, encoding="utf-8")
    ov = parse_overlay_csv(p, unit)
    assert ov["n"] == 2
    assert ov["f_ghz"][0] == pytest.approx(expected_first)
    assert ov["db"] == [-3.0, -20.0]


def test_parse_overlay_csv_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_overlay_csv(tmp_path / "missing.csv")
    p = tmp_path / "bad.csv"
    p.write_text("freq,dB\nabc,def\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_overlay_csv(p)


# --------------------------------------------------------- tool, faked reader


class FakeReader:
    def __init__(self, items, curves, combos=None):
        self.items, self.curves, self.combos = items, curves, combos or {}

    def tree_items(self):
        return list(self.items)

    def run_ids(self, tree):
        return sorted({r for (t, r) in self.curves if t == tree}) or [0]

    def parameter_combination(self, run_id):
        return self.combos.get(run_id, {})

    def read(self, tree, run_id):
        f, v, z0 = self.curves[(tree, run_id)]
        return {"x": f, "values": v, "xlabel": "Frequency / GHz", "ylabel": "", "title": "",
                "z0": z0}


S11 = "1D Results\\S-Parameters\\S1,1"
EFF = "1D Results\\Efficiencies\\Tot. Efficiency [1]"


def _client():
    return SimpleNamespace(connected=False, project_path=None,
                           config=SimpleNamespace(connect_mode="auto"))


def _project(tmp_path) -> Path:
    p = tmp_path / "ant.cst"
    p.write_bytes(b"fake")
    return p


async def _call(args):
    out = await figures_1d.handle("cst_plot_1d_results", args, _client())
    return json.loads(out[0].text)


@pytest.mark.asyncio
async def test_all_figures_from_synthetic_sweep(tmp_path, monkeypatch):
    f = grid(1.5, 3.5, 801)
    curves = {}
    for r, f0 in ((0, 2.45), (1, 2.35), (2, 2.45)):
        curves[(S11, r)] = (f, lorentz_gamma(f, [(f0, 0.05, 0.97), (3.2, 0.04, 0.9)]),
                            [50 + 0j] * len(f))
        curves[(EFF, r)] = ([2.4], [0.8 + 0j], None)
    fake = FakeReader([S11, EFF], curves, {1: {"L": 29.0}, 2: {"L": 30.0}})
    monkeypatch.setattr(source, "open_reader", lambda *a, **k: fake)
    meas = tmp_path / "meas.csv"
    meas.write_text("f_GHz,dB\n" + "\n".join(f"{x},{-2 - 15 * (abs(x - 2.4) < 0.05)}"
                                              for x in grid(1.5, 3.5, 81)), encoding="utf-8")
    data = await _call({
        "project_path": str(_project(tmp_path)),
        "quantities": list(figures_1d.QUANTITIES),
        "formats": ["pdf", "png", "svg"],
        "out_dir": str(tmp_path / "fig"),
        "csv_overlays": [str(meas)],
        "title": "Patch",
    })
    assert data["status"] == "ok", data
    assert len(data["files"]) == 7 * 3
    for path in data["files"]:
        assert Path(path).is_file() and Path(path).stat().st_size > 1000
    assert data["source"]["run_ids"] == [1, 2]
    assert data["source"]["run_labels"] == {"1": "L = 29", "2": "L = 30"}
    m = data["metrics"]
    assert m["primary_run_id"] == 2 and m["f_res_ghz"] == pytest.approx(2.45, abs=5e-3)
    assert len(m["bands"]) == 2 and len(m["per_run"]) == 2
    assert {"f_low", "f_high", "bw_mhz", "fbw_pct"} <= set(m["bands"][0])
    assert m["z0_ohm"] == pytest.approx(50)
    assert m["efficiency"][0]["pct"] == [pytest.approx(80)]


@pytest.mark.asyncio
async def test_freq_range_and_default_z0(tmp_path, monkeypatch):
    f = grid(1.5, 3.5, 401)
    fake = FakeReader([S11], {(S11, 0): (f, lorentz_gamma(f, [(2.4, 0.05, 0.97)]), None)})
    monkeypatch.setattr(source, "open_reader", lambda *a, **k: fake)
    data = await _call({"project_path": str(_project(tmp_path)), "quantities": ["s11_db", "impedance"],
                        "formats": ["png"], "out_dir": str(tmp_path), "freq_range_ghz": [2.0, 2.8],
                        "width": "double"})
    assert data["status"] == "ok"
    assert data["metrics"]["z0_ohm_source"] == ["assumed 50 ohm"]
    assert len(data["metrics"]["bands"]) == 1


@pytest.mark.asyncio
async def test_no_results_lists_items_and_next_steps(tmp_path, monkeypatch):
    fake = FakeReader(["Excitation Signals\\default"], {})
    monkeypatch.setattr(source, "open_reader", lambda *a, **k: fake)
    out = await figures_1d.handle(
        "cst_plot_1d_results",
        {"project_path": str(_project(tmp_path)), "simulate_if_missing": True},
        SimpleNamespace(connected=True, project_path=None, config=SimpleNamespace(connect_mode="auto")),
    )
    data = json.loads(out[0].text)
    assert data["status"] == "no_results"
    assert data["available_tree_items"] == ["Excitation Signals\\default"]
    assert any("cst_run_simulation_async" in s for s in data["next_steps"])
    assert any("cst_wait_for_simulation" in s for s in data["next_steps"])


@pytest.mark.asyncio
async def test_missing_file_and_unreadable_are_errors(tmp_path, monkeypatch):
    data = await _call({"project_path": str(tmp_path / "nope.cst")})
    assert data["status"] == "error" and "not found" in data["message"]

    def boom(*a, **k):
        raise RuntimeError("corrupt")

    monkeypatch.setattr(source, "open_reader", boom)
    data = await _call({"project_path": str(_project(tmp_path))})
    assert data["status"] == "error" and "corrupt" in data["message"]
    data = await _call({})
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_bad_run_ids_and_tree_paths(tmp_path, monkeypatch):
    f = grid(2, 3, 11)
    fake = FakeReader([S11], {(S11, 0): (f, lorentz_gamma(f, [(2.4, 0.05, 0.5)]), None)})
    monkeypatch.setattr(source, "open_reader", lambda *a, **k: fake)
    data = await _call({"project_path": str(_project(tmp_path)), "run_ids": [7]})
    assert data["status"] == "error" and "run_ids" in data["message"]
    data = await _call({"project_path": str(_project(tmp_path)), "tree_paths": ["1D Results\\x"]})
    assert data["status"] == "error" and "tree_paths" in data["message"]


def test_tool_schema_is_registered():
    names = [t.name for t in figures_1d.TOOLS]
    assert names == ["cst_plot_1d_results"]
