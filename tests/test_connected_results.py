"""Connected-mode contracts: no solver, GUI, license, or fabricated responses."""

import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from cst_mcp.cst_client import CSTClient
from cst_mcp.execution.curves import derived_s, format_curve, read_curve
from cst_mcp.tools import results, optimization


def curve(values=(0.5 + 0.5j, 0.1 + 0.1j, 0.5 + 0.5j), x=(1.0, 2.0, 3.0)):
    return dict(
        status="ok",
        real=[v.real for v in values],
        imag=[v.imag for v in values],
        x=list(x),
        xlabel="Frequency / GHz",
        n=len(values),
    )


def test_all_tool_client_members_exist():
    client = CSTClient()
    missing = []
    for path in Path("src/cst_mcp/tools").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "client"
            ):
                if not hasattr(client, node.attr):
                    missing.append(f"{path}:{node.lineno} {node.attr}")
    assert not missing


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("cst_get_s_parameters", {"format": "db"}),
        ("cst_get_s_parameters", {"format": "real_imag"}),
        ("cst_get_s_parameter_phase", {"unwrap": True}),
        ("cst_get_vswr", {}),
        ("cst_get_group_delay", {}),
        ("cst_get_smith_chart_data", {}),
        ("cst_get_bandwidth", {}),
    ],
)
async def test_connected_tools_calculate_quantities(name, args):
    client = SimpleNamespace(connected=True, get_result=lambda path, run_id=0: curve())
    data = json.loads((await results.handle(name, args, client))[0].text)
    assert data["status"] == "ok"
    if name == "cst_get_s_parameters" and args["format"] == "db":
        assert data["y"][0] == pytest.approx(-3.01029995664)
    elif name == "cst_get_s_parameter_phase":
        assert data["y"] == pytest.approx([45, 45, 45])
    elif name == "cst_get_group_delay":
        assert data["y"] == pytest.approx([0, 0, 0])
    elif name == "cst_get_vswr":
        assert data["y"][0] == pytest.approx(5.8284271247)
    elif name == "cst_get_smith_chart_data":
        assert data["impedance_real"][0] == pytest.approx(50)
        assert data["impedance_imag"][0] == pytest.approx(100)
    elif name == "cst_get_bandwidth":
        assert len(data["bands"]) == 1
        assert not data["bands"][0]["lower_truncated"]
    json.dumps(data, allow_nan=False)


def test_delay_uses_units_and_unwrap():
    data = curve([complex(math.cos(p), math.sin(p)) for p in [3, 2, 1]], [100, 200, 300])
    data["xlabel"] = "Frequency / MHz"
    delay = derived_s(data, "cst_get_group_delay", {})
    assert delay["y"] == pytest.approx([1 / (2 * math.pi * 1e8)] * 3)
    data["xlabel"] = "Unknown"
    with pytest.raises(ValueError, match="unit"):
        derived_s(data, "cst_get_group_delay", {})


def test_null_singularities_and_multiple_bands():
    data = curve([0j, 1 + 0j, 0j])
    assert format_curve(data, "db")["y"][0] is None
    assert derived_s(data, "cst_get_vswr", {})["y"][1] is None
    assert derived_s(data, "cst_get_smith_chart_data", {})["impedance_real"][1] is None
    bands = derived_s(data, "cst_get_bandwidth", {})["bands"]
    assert len(bands) == 2 and bands[0]["lower_truncated"] and bands[1]["upper_truncated"]


def test_legacy_export_is_db_and_parseable(tmp_path, monkeypatch):
    client = CSTClient()
    monkeypatch.setattr(client, "get_result", lambda path: curve())
    target = tmp_path / "s11.txt"
    assert (
        client.export_result("1D Results\\S-Parameters\\S1,1", str(target))["status"] == "exported"
    )
    x, y = optimization._parse_s11_data(str(target))
    assert x == [1, 2, 3]
    assert y[0] == pytest.approx(-3.01029995664)


@pytest.mark.parametrize("state", [True, None])
def test_result_read_guard(state, monkeypatch):
    client = CSTClient()
    client._de = object()
    client._project = object()
    client._project_path = "unread.cst"
    monkeypatch.setattr(client, "is_solver_running", lambda **kw: state)
    assert client.get_result("1D Results\\S-Parameters\\S1,1")["status"] == "busy"


def test_vendor_read_preserves_complex_and_run_id(monkeypatch):
    import sys

    seen = {}
    item = SimpleNamespace(
        get_xdata=lambda: [1, 2],
        get_ydata=lambda: [1j, 0.5 - 0.2j],
        xlabel="Frequency / GHz",
        ylabel="S",
        title="S11",
    )

    class Module:
        def get_result_item(self, path, run_id):
            seen.update(path=path, run_id=run_id)
            return item

    def project(path, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(get_3d=lambda: Module())

    fake = SimpleNamespace(ProjectFile=project)
    monkeypatch.setitem(sys.modules, "cst", SimpleNamespace(results=fake))
    monkeypatch.setitem(sys.modules, "cst.results", fake)
    data = read_curve("saved.cst", "1D Results\\S-Parameters\\S1,1", 7)
    assert data["imag"] == [1, -0.2] and data["real"] == [0, 0.5]
    assert seen["run_id"] == 7 and seen["allow_interactive"] is False
    item.get_ydata = lambda: [float("nan"), 1]
    assert read_curve("saved.cst", "x")["status"] == "error"


def test_csv_requires_labels_not_sign_heuristics(tmp_path):
    from cst_mcp.execution.results_reader import parse_sparam_csv

    path = tmp_path / "s.csv"
    path.write_text("Frequency / MHz,Real,Imag\n100,-0.5,0.2\n200,0.1,-0.3\n", encoding="utf-8")
    data = parse_sparam_csv(path)
    assert data["real"] == [-0.5, 0.1] and data["imag"] == [0.2, -0.3]
    assert data["frequency_ghz"] == [0.1, 0.2]
    path.write_text("100,-0.5,0.2\n200,0.1,-0.3\n", encoding="utf-8")
    assert parse_sparam_csv(path)["status"] == "error"
    path.write_text("Frequency / GHz,dB\n1,-5\n2,-10\n", encoding="utf-8")
    data = parse_sparam_csv(path)
    assert data["complex_available"] is False and data["imag"] == [None, None]


def test_native_optimizer_uses_documented_goal_lifecycle():
    from cst_mcp.execution.native_optimizer import build_optimizer

    code = build_optimizer(
        dict(
            method="Nelder Mead",
            parameters=[dict(name="w", min=1, max=2)],
            goal_type="minimize",
            result_path="1D Results\\S-Parameters\\S1,1",
        )
    )
    assert '.SetOptimizerType "Nelder_Mead_Simplex"' in code
    assert '.AddGoal "1DC Primary Result"' in code
    assert '.SetGoalScalarType "magdb20"' in code
    assert '.SelectParameter "w", "True"' in code
    assert ".SetMaxEval " in code and "InitGoal" not in code and "\n  .Start\n" not in code
    with pytest.raises(ValueError, match="Evaluation-capped"):
        build_optimizer(dict(method="Genetic Algorithm"))


def test_native_vba_timeout_is_not_replayed(monkeypatch):
    def timeout(code, **kwargs):
        raise TimeoutError("API timed out")

    client = CSTClient()
    client._de = object()
    client._project = SimpleNamespace(
        model3d=SimpleNamespace(is_solver_running=lambda **kw: False),
        schematic=SimpleNamespace(execute_vba_code=timeout),
    )
    monkeypatch.setattr(client, "run_history", lambda *a, **kw: pytest.fail("replayed mutation"))
    assert client.run_vba_silent("x")["status"] == "timeout"


def test_query_output_replaces_popups(tmp_path, monkeypatch):
    import re

    client = CSTClient()
    client.config.work_dir = tmp_path
    client._de = object()
    client._project = object()
    monkeypatch.setattr(client, "is_solver_running", lambda **kw: False)

    def execute(code):
        assert "MsgBox" not in code and "Debug.Print" not in code
        path = re.search(r'Open "([^"]+)" For Output', code)[1]
        Path(path).write_text("w\t12.5\n", encoding="ascii")
        return {"status": "executed"}

    monkeypatch.setattr(client, "run_vba_silent", execute)
    data = client.execute_vba('MsgBox "hello"')
    assert data["output"] == "w\t12.5\n" and not data["popup"]
    assert not list(tmp_path.glob("query_*.txt"))


def test_history_timeout_returns_without_followup_native_calls(monkeypatch):
    def timeout(label, code, *, timeout):
        assert timeout == 30
        raise TimeoutError("native command timed out")
    client = CSTClient()
    client._de = object()
    client._project = SimpleNamespace(model3d=SimpleNamespace(
        is_solver_running=lambda **kw: False, add_to_history=timeout))
    monkeypatch.setattr(client, "get_cst_messages", lambda **kw: pytest.fail("follow-up native call"))
    result = client.run_history("x")
    assert result["status"] == "timeout" and result["execution_state"] == "unknown"


def test_preview_cap_preserves_finite_minimum_and_endpoints():
    from cst_mcp.execution.results_reader import downsample_series
    data = dict(n_points=100, frequency_ghz=list(range(100)), magnitude_db=[0]*100)
    data["magnitude_db"][37] = -20
    data["magnitude_db"][25] = None
    result = downsample_series(data, 10)
    assert result["n_points"] <= 10
    assert {0, 37, 99} <= set(result["frequency_ghz"])
    assert downsample_series(data, 0) == data
