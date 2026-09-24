import json
from types import SimpleNamespace

import pytest

from cst_mcp.tools import official
from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient


@pytest.mark.asyncio
async def test_help_is_local_paginated_and_confined(tmp_path):
    folder = tmp_path / "Online Help/Python/source"
    folder.mkdir(parents=True)
    (folder / "cst.results.html").write_text(
        "<h1>Python results</h1><script>hidden()</script><p>get_ydata</p>", encoding="utf-8"
    )
    client = CSTClient(CSTConfig(cst_path=tmp_path, work_dir=tmp_path / "work"))
    result = json.loads(
        (await official.handle("cst_search_help", {"query": "cst.results"}, client))[0].text
    )
    assert result["count"] == 1
    result = json.loads(
        (await official.handle("cst_read_help", {"topic": result["topics"][0]}, client))[0].text
    )
    assert "get_ydata" in result["text"] and "hidden" not in result["text"]
    result = json.loads(
        (await official.handle("cst_read_help", {"topic": "../../secret.html"}, client))[0].text
    )
    assert result["status"] == "error"


def _fake_help(tmp_path):
    vba = tmp_path / "Online Help/mergedProjects/VBA_3D"
    (vba / "common_vbacurves").mkdir(parents=True)
    (vba / "special_vbaports").mkdir(parents=True)
    (vba / "whgdata").mkdir(parents=True)
    (vba / "common_vbacurves/common_vbacurves_polygon_object.htm").write_text(
        "<html><head><title>Polygon Object</title><script>var AddPotentialNumerically;</script>"
        "</head><body><h1>Polygon Object</h1><p>Point ( double x, double y )</p>"
        "<p>Use ExtrudeCurve to turn the closed polygon into a solid.</p></body></html>",
        encoding="utf-8",
    )
    (vba / "common_vbacurves/common_vbacurves_extrudecurve_object.htm").write_text(
        "<html><head><title>ExtrudeCurve Object</title></head><body>"
        "<p>Curve ( string curvename ) Thickness ( double value )</p></body></html>",
        encoding="utf-8",
    )
    (vba / "special_vbaports/special_vbaports_port_object.htm").write_text(
        "<html><head><title>Port Object</title></head><body><p>Mode Settings</p>"
        "<p>AddPotentialNumerically ( int modeset, enum {\"Positive\", \"Negative\"} potential )"
        " defines a potential.</p></body></html>",
        encoding="utf-8",
    )
    # RoboHelp search data must never be returned as a topic.
    (vba / "whgdata/whlstf11.htm").write_text(
        "<p>AddPotentialNumerically Polygon ExtrudeCurve</p>", encoding="utf-8"
    )
    return CSTClient(CSTConfig(cst_path=tmp_path, work_dir=tmp_path / "work"))


async def _search(client, query, **extra):
    return json.loads(
        (await official.handle("cst_search_help", {"query": query, **extra}, client))[0].text
    )


@pytest.mark.asyncio
async def test_help_full_text_search_multiword_and_in_page_methods(tmp_path, monkeypatch):
    monkeypatch.setattr(official, "_HELP_INDEX_CACHE", {})
    client = _fake_help(tmp_path)

    result = await _search(client, "AddPotentialNumerically")
    assert result["count"] == 1
    hit = result["results"][0]
    assert hit["topic"].endswith("special_vbaports_port_object.htm")
    assert hit["match"] == "body" and "AddPotentialNumerically" in hit["snippet"]
    assert all("whgdata" not in t for t in result["topics"])

    # AND semantics across file name/title/body; title hits rank first.
    result = await _search(client, "Polygon ExtrudeCurve")
    assert result["count"] == 1
    assert result["results"][0]["title"] == "Polygon Object"
    assert result["results"][0]["match"] == "title+body"
    result = await _search(client, "ExtrudeCurve")
    assert [r["title"] for r in result["results"]] == ["ExtrudeCurve Object", "Polygon Object"]
    assert [r["match"] for r in result["results"]] == ["title", "body"]

    assert (await _search(client, "Polygon nonexistentword"))["count"] == 0
    # Script contents are stripped, not indexed.
    result = await _search(client, "AddPotentialNumerically")
    assert all(not r["topic"].endswith("polygon_object.htm") for r in result["results"])


@pytest.mark.asyncio
async def test_help_index_is_built_once_and_cached_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(official, "_HELP_INDEX_CACHE", {})
    client = _fake_help(tmp_path)
    calls = []
    original = official._html_to_text
    monkeypatch.setattr(official, "_html_to_text", lambda raw: calls.append(1) or original(raw))
    await _search(client, "Polygon")
    built = len(calls)
    assert built == 3
    await _search(client, "Port")
    assert len(calls) == built  # in-memory cache
    assert list((tmp_path / "work/.cst_mcp_cache").glob("help_index_*.json"))
    monkeypatch.setattr(official, "_HELP_INDEX_CACHE", {})
    result = await _search(client, "AddPotentialNumerically")
    assert len(calls) == built and result["count"] == 1  # loaded from disk cache


@pytest.mark.asyncio
async def test_preview_is_explicit_and_never_claims_full_curve(tmp_path, monkeypatch):
    path = tmp_path / "model.cst"
    path.touch()
    monkeypatch.setattr(
        official,
        "read_curve",
        lambda *args, **kwargs: dict(status="ok", n=5, x=list(range(5)), real=[1] * 5, imag=[0] * 5),
    )
    client = CSTClient(CSTConfig())
    result = json.loads(
        (
            await official.handle(
                "cst_read_saved_result",
                {"project_path": str(path), "tree_path": "x", "max_points": 2},
                client,
            )
        )[0].text
    )
    assert result["x"] == [0, 4] and result["total_points"] == 5 and result["sampled"]


@pytest.mark.parametrize("running", [True, None])
@pytest.mark.parametrize("operation", ["close_project", "run_history", "run_vba_silent"])
def test_mutations_do_not_interrupt_solver(running, operation):
    def forbidden(*args, **kwargs):
        raise AssertionError("Mutation attempted")

    model = SimpleNamespace(is_solver_running=lambda **kw: running, add_to_history=forbidden)
    client = CSTClient(CSTConfig())
    client._de = object()
    client._project = SimpleNamespace(model3d=model, close=forbidden)
    result = getattr(client, operation)(*(["x"] if operation != "close_project" else []))
    assert result["status"] == "busy"


def test_official_builder_signatures():
    from cst_mcp.tools.geometry import _build_polygon_extrude, _build_wire
    from cst_mcp.tools.parameters import _build_parameter_sweep, _build_yield_analysis
    from cst_mcp.tools.import_export import _build_export_touchstone
    from cst_mcp.vba_builder import VBABuilder

    assert (
        '.SetP1 False, "1", "2", "3"'
        in VBABuilder("DiscretePort").set_point("SetP1", 1, 2, 3).build()
    )
    code = _build_wire(
        dict(
            component="c",
            name="w",
            radius=0.1,
            start_x=0,
            start_y=0,
            start_z=0,
            end_x=1,
            end_y=0,
            end_z=0,
        )
    )
    assert "StartPoint" not in code and "With Cylinder" in code and "ConvertToSolidShape" not in code
    code = _build_polygon_extrude(
        dict(component="c", name="p", height=1, points=[[0, 0], [1, 0], [1, 1]], axis="x")
    )
    assert ".Axis" not in code and "Polygon3D" in code and '.Twistangle "0"' in code
    code = _build_parameter_sweep(dict(parameter="p", start=1, stop=2, steps=3))
    assert "AddParameter_Samples" in code and ".Create" not in code and ".Reset" not in code
    code = _build_export_touchstone(dict(file_path="test.s2p"))
    assert "With TOUCHSTONE" in code and '.Format "RI"' in code and ".Write" in code
    code = _build_yield_analysis(
        dict(
            parameters=[dict(name="p", nominal=1, tolerance=0.1)],
            pass_criteria=[dict(result_path="s", operator="<", threshold=1)],
            num_samples=3,
        )
    )
    assert code.count(".AddSequence") == 3 and code.count(".AddParameter_ArbitraryPoints") == 3


def test_polygon_extrude_base_plane_offset_and_holes():
    from cst_mcp.tools.geometry import _build_polygon_extrude

    square = [[0, 0], [10, 0], [10, 10], [0, 10]]
    code = _build_polygon_extrude(
        dict(component="c", name="p", height=0.035, points=square, z_offset=1.6,
             holes=[[[2, 2], [2, 4], [4, 4], [4, 2]], [[6, 6], [8, 6], [8, 8]]])
    )
    assert '.Point "0", "0", "1.6"' in code and '.Point "10", "10", "1.6"' in code
    assert code.count("With ExtrudeCurve") == 3 and code.count("With Polygon3D") == 3
    assert '.Curve "p_curves:p_hole1_profile"' in code and '.Name "p_hole2"' in code
    assert 'Solid.Subtract "c:p", "c:p_hole1"' in code
    assert 'Solid.Subtract "c:p", "c:p_hole2"' in code
    # Subtract only after both the main solid and the hole solid exist.
    assert code.index('.Name "p_hole1"') < code.index('Solid.Subtract "c:p", "c:p_hole1"')
    # Clockwise hole is re-wound to match the counter-clockwise outline.
    hole1 = code[code.index('.Name "p_hole1_profile"'):]
    assert hole1.index('"4", "2", "1.6"') < hole1.index('"2", "2", "1.6"')

    # Clockwise outline is re-wound counter-clockwise: live CST 2026 extrudes a
    # clockwise Polygon3D towards -z (z=1.565..1.6 instead of 1.6..1.635).
    code = _build_polygon_extrude(
        dict(component="c", name="w", height=0.035, points=square[::-1], z_offset=1.6,
             holes=[[[2, 2], [4, 2], [4, 4], [2, 4]]])
    )
    outline = code[code.index('.Name "w_profile"'):code.index("With ExtrudeCurve")]
    assert outline.index('"10", "0", "1.6"') < outline.index('"10", "10", "1.6"')
    hole = code[code.index('.Name "w_hole1_profile"'):]
    assert hole.index('"4", "2", "1.6"') < hole.index('"4", "4", "1.6"')

    code = _build_polygon_extrude(
        dict(component="c", name="q", height=1, points=[[0, 0], [1, 0], [1, 1]], axis="x", x_offset=-2.5)
    )
    assert '.Point "-2.5", "1", "1"' in code and "Solid.Subtract" not in code
    code = _build_polygon_extrude(
        dict(component="c", name="q", height=1, points=[[0, 0], [1, 0], [1, 1]], axis="y", y_offset=3)
    )
    assert '.Point "1", "3", "-1"' in code
    with pytest.raises(ValueError):
        _build_polygon_extrude(
            dict(component="c", name="q", height=1, points=[[0, 0], [1, 0], [1, 1]], axis="x", z_offset=1)
        )
    with pytest.raises(ValueError):
        _build_polygon_extrude(
            dict(component="c", name="q", height=1, points=[[0, 0], [1, 0], [1, 1]],
                 holes=[[[0, 0], ["1 : Kill", 0], [1, 1]]])
        )


def test_extrude_pointlist_syntax_offset_and_holes():
    from cst_mcp.tools.geometry import _build_extrude

    code = _build_extrude(dict(component="c", name="e", height=2, points=[[0, 0], [1, 0], [1, 1]]))
    # CST 2026 Extrude object: Mode "pointlist", Origin/Uvector/Vvector take 3 doubles.
    assert '.Mode "pointlist"' in code and '.Mode "0"' not in code
    assert '.Origin "0", "0", "0"' in code
    assert '.Uvector "1", "0", "0"' in code and '.Vvector "0", "1", "0"' in code
    assert code.rstrip().endswith("End With") and "Solid.Subtract" not in code

    code = _build_extrude(
        dict(component="c", name="e", height=2, points=[[0, 0], [4, 0], [4, 4], [0, 4]],
             z_offset=-1.5, holes=[[[1, 1], [2, 1], [2, 2]]])
    )
    assert code.count("With Extrude") == 2 and code.count('.Origin "0", "0", "-1.5"') == 2
    assert '.Name "e_hole1"' in code and 'Solid.Subtract "c:e", "c:e_hole1"' in code
    code = _build_extrude(dict(component="c", name="e", height=2, points=[[0, 0], [1, 0], [1, 1]],
                               axis="y", y_offset=0.5))
    assert '.Origin "0", "0.5", "0"' in code and '.Vvector "0", "0", "-1"' in code


@pytest.mark.asyncio
async def test_extrude_tool_rejects_injection_in_holes():
    from cst_mcp.tools import geometry

    class Client:
        def execute_vba(self, code):
            raise AssertionError("must not execute")

    result = await geometry.handle(
        "cst_create_polygon_extrude",
        dict(component="c", name="p", height=1, points=[[0, 0], [1, 0], [1, 1]],
             holes=[[[0, 0], ["1\nKill", 0], [1, 1]]]),
        Client(),
    )
    assert json.loads(result[0].text)["status"] == "error"
