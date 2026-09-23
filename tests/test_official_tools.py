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
    client = CSTClient(CSTConfig(cst_path=tmp_path))
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
