"""cst_technical_drawing: STL parsing, feature edges, hidden lines, offline rendering."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("matplotlib")

from cst_mcp.execution.drawing_geometry import (
    box_triangles,
    chain_segments,
    feature_edges,
    hidden_mask,
    load_stl_dir,
    project,
    read_stl,
    ring_triangles,
    split_edges,
    view_basis,
    write_stl,
)
from cst_mcp.tools import drawing

W, L, H, T = 40.0, 30.0, 1.6, 0.035


def _fixture(root: Path, *, manifest: bool = True, scale: float = 1.0) -> Path:
    stl = root / "stl"
    stl.mkdir(parents=True)
    s = scale
    write_stl(stl / "substrate.stl", box_triangles(-W / 2 * s, W / 2 * s, -L / 2 * s, L / 2 * s, 0, H * s))
    write_stl(stl / "patch.stl", box_triangles(-9 * s, 9 * s, -7 * s, 7 * s, H * s, (H + T) * s), binary=False)
    write_stl(stl / "ring.stl", ring_triangles(0, 0, 4 * s, 5 * s, -T * s, 0, 48))
    if manifest:
        (stl / "manifest.json").write_text(json.dumps({
            "units": "mm", "project": "demo.cst",
            "solids": [
                {"file": "substrate.stl", "name": "component1:substrate", "material": "FR-4 (lossy)"},
                {"file": "patch.stl", "name": "component1:patch", "material": "Copper (annealed)"},
                {"file": "ring.stl", "name": "component1:ring", "material": "Copper (annealed)"},
            ],
        }))
    return stl


def _call(arguments, client=None):
    import asyncio

    content = asyncio.run(drawing.handle("cst_technical_drawing", arguments, client))
    return json.loads(content[0].text)


def test_binary_and_ascii_stl_round_trip(tmp_path):
    tris = box_triangles(0, 1, 0, 2, 0, 3)
    write_stl(tmp_path / "b.stl", tris, binary=True)
    write_stl(tmp_path / "a.stl", tris, binary=False)
    # Binary file whose header begins with "solid" must still parse as binary.
    write_stl(tmp_path / "tricky.stl", tris, binary=True, name="solid tricky")
    for name in ("b.stl", "a.stl", "tricky.stl"):
        got = read_stl(tmp_path / name)
        assert got.shape == (12, 3, 3)
        np.testing.assert_allclose(got, tris, atol=1e-6)


def test_ascii_stl_with_crlf_and_exponents(tmp_path):
    text = (
        "solid x\r\n facet normal 0 0 1\r\n  outer loop\r\n"
        "   vertex 0 0 0\r\n   vertex 1.0E+00 0 0\r\n   vertex 0 -1e0 +0.0\r\n"
        "  endloop\r\n endfacet\r\nendsolid x\r\n"
    )
    (tmp_path / "c.stl").write_bytes(text.encode())
    got = read_stl(tmp_path / "c.stl")
    np.testing.assert_allclose(got[0], [[0, 0, 0], [1, 0, 0], [0, -1, 0]])


def test_invalid_stl_raises(tmp_path):
    (tmp_path / "bad.stl").write_bytes(b"\x00" * 10)
    with pytest.raises(ValueError):
        read_stl(tmp_path / "bad.stl")


def test_box_feature_edges_are_its_12_edges():
    edges, faces = feature_edges(box_triangles(0, 1, 0, 1, 0, 1))
    assert len(edges) == 12  # face diagonals are coplanar and dropped
    assert (faces >= 0).all()


def test_ring_top_view_edges_are_circles_only():
    ring = ring_triangles(0, 0, 4, 5, 0, 0.1, 32)
    edges, _ = feature_edges(ring)
    # 2 circles x 2 (top/bottom) x 32 segments; wall seams and face diagonals removed.
    assert len(edges) == 4 * 32


def test_hidden_mask_marks_edges_under_a_cover():
    basis = view_basis("top")
    cover = project(box_triangles(-2, 2, -2, 2, 1, 2), basis)
    under = project(np.array([[[-1, 0, 0], [1, 0, 0]], [[3, 0, 0], [4, 0, 0]]], float), basis)
    mask = hidden_mask(under, cover, 1e-9)
    assert mask.tolist() == [True, False]
    pieces = split_edges(under, 0.5)
    assert len(pieces) == 4 + 2


def test_chain_segments_joins_a_loop():
    t = np.linspace(0, 2 * np.pi, 9)[:-1]
    pts = np.stack([np.cos(t), np.sin(t)], axis=1)
    segs = np.stack([pts, np.roll(pts, -1, axis=0)], axis=1)
    lines = chain_segments(segs, 1e-9)
    assert len(lines) == 1 and len(lines[0]) == 9


def test_load_stl_dir_uses_manifest_and_units(tmp_path):
    stl = _fixture(tmp_path, manifest=False, scale=1e-3)  # file in metres
    solids, info = load_stl_dir(stl, units="m")
    assert info["units_in_file"] == "m"
    sub = next(s for s in solids if s.name == "substrate")
    np.testing.assert_allclose(sub.size, [W, L, H], atol=1e-4)


def test_offline_sheet_drawing(tmp_path):
    stl = _fixture(tmp_path)
    out = tmp_path / "out"
    data = _call({
        "stl_dir": str(stl), "output_dir": str(out),
        "views": ["top", "front", "side", "iso"], "parameters": {"W": W, "h": H},
    })
    assert data["status"] == "ok", data
    assert {Path(f).suffix for f in data["files"]} == {".pdf", ".svg", ".png"}
    for f in data["files"]:
        assert Path(f).is_file() and Path(f).stat().st_size > 1000
    bbox = data["bbox_mm"]
    assert bbox["dx"] == pytest.approx(W)
    assert bbox["dy"] == pytest.approx(L)
    assert bbox["dz"] == pytest.approx(H + 2 * T)
    by_name = {s["name"]: s for s in data["solids"]}
    assert by_name["component1:patch"]["material"] == "Copper (annealed)"
    assert by_name["component1:patch"]["bbox_mm"]["dx"] == pytest.approx(18)
    assert by_name["component1:ring"]["bbox_mm"]["dx"] == pytest.approx(10, abs=1e-3)
    assert by_name["component1:substrate"]["bbox_mm"]["dz"] == pytest.approx(H)
    assert [v["view"] for v in data["views"]] == ["top", "front", "side", "iso"]
    assert data["z_exaggeration"] > 1  # thin planar stack is stretched in side views
    assert data["parameters"] == {"W": W, "h": H}
    svg = Path(next(f for f in data["files"] if f.endswith(".svg"))).read_text(encoding="utf-8")
    assert "TOP VIEW" in svg and "40" in svg


def test_offline_separate_views_png_only(tmp_path):
    stl = _fixture(tmp_path, manifest=False)
    data = _call({
        "stl_dir": str(stl), "output_dir": str(tmp_path / "o"), "layout": "separate",
        "views": ["top", "side"], "formats": ["png"], "dpi": 150, "z_exaggeration": 1,
        "solids": ["substrate", "patch"],
    })
    assert data["status"] == "ok", data
    assert sorted(Path(f).name for f in data["files"]) == [
        "technical_drawing_side.png", "technical_drawing_top.png"]
    assert {s["name"] for s in data["solids"]} == {"substrate", "patch"}
    assert data["z_exaggeration"] == 1


def test_errors(tmp_path):
    offline = SimpleNamespace(has_project=False, config=SimpleNamespace(work_dir=tmp_path))
    assert _call({}, offline)["status"] == "error"
    assert _call({"stl_dir": str(tmp_path / "missing")}, offline)["status"] == "error"
    (tmp_path / "empty").mkdir()
    assert _call({"stl_dir": str(tmp_path / "empty")}, offline)["status"] == "error"
    assert _call({"stl_dir": str(tmp_path), "basename": "../x"}, offline)["status"] == "error"


def test_connected_export_parses_cst_output(tmp_path):
    target = tmp_path / "stl"

    class FakeClient:
        has_project = True
        project_path = str(tmp_path / "p.cst")
        config = SimpleNamespace(work_dir=tmp_path)

        def capture_vba_output(self, code):
            import re

            assert "With STL" in code and ".Write" in code and '.ExportFileUnits "mm"' in code
            folder = Path(re.search(r'fileName = "(.*)\\solid_"', code).group(1))
            folder.mkdir(parents=True, exist_ok=True)
            write_stl(folder / "solid_000.stl", box_triangles(0, 40, 0, 30, 0, 1.6))
            return {"status": "ok", "output": "UNIT\t0,001\nSOLID\t0\tcomp/sub:substrate\tFR-4\n"}

        def list_parameters(self):
            return {"status": "ok", "parameters": {"h": "1.6"}}

    result = drawing.export_model_stls(FakeClient(), target)
    assert result["status"] == "ok" and result["units"] == "mm"
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["solids"][0]["component"] == "comp/sub"
    assert manifest["units"] == "mm" and manifest["project_units"] == "mm"

    data = _call({"output_dir": str(tmp_path / "draw"), "formats": ["svg"]}, FakeClient())
    assert data["status"] == "ok", data
    assert data["source"] == "cst_export"
    assert data["parameters"] == {"h": "1.6"}


def test_schema_is_strict():
    tool = drawing.TOOLS[0]
    assert tool.name == "cst_technical_drawing"
    schema = getattr(tool, "input_schema", None) or tool.inputSchema
    assert schema["additionalProperties"] is False
