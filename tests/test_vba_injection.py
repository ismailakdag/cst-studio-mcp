"""VBA injection through tool string/number arguments.

Tool handlers build VBA from caller arguments and run it with
``client.execute_vba`` -- a path that bypasses the ``CST_ALLOW_RAW_VBA`` gate.
Every caller value must therefore stay inside a single VBA string literal (or
be rejected), and numeric slots must hold real numbers.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from cst_mcp import vba_safety
from cst_mcp.tools import boolean, geometry, optimization, results, workflows

QUOTE_PAYLOAD = '1D Results\\S-Parameters\\S1,1" : RunAndWait "calc.exe" : \''
NEWLINE_PAYLOAD = '1D Results\\S-Parameters\\S1,1"\nRunAndWait "calc.exe"\n\''
DANGEROUS = ("runandwait", "shell", "createobject")


class FakeClient:
    connected = True
    is_connected = True
    has_project = True
    project_path = None

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute_vba(self, code, history_label=None, **_kw):
        self.executed.append(code)
        return {"status": "executed"}

    def execute_vba_silent(self, code, **_kw):
        self.executed.append(code)
        return {"status": "executed"}


class OfflineClient(FakeClient):
    connected = False
    is_connected = False
    has_project = False


def code_outside_strings(vba: str) -> list[str]:
    """Per physical line, the code with string literals and comments removed."""
    out = []
    for line in vba.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        buf, i, n = [], 0, len(line)
        while i < n:
            ch = line[i]
            if ch == '"':
                j = i + 1
                while j < n:
                    if line[j] == '"':
                        if j + 1 < n and line[j + 1] == '"':
                            j += 2
                            continue
                        break
                    j += 1
                assert j < n, f"unterminated string literal in line: {line!r}"
                buf.append('""')
                i = j + 1
                continue
            if ch == "'":
                break
            buf.append(ch)
            i += 1
        out.append("".join(buf))
    return out


def assert_payload_contained(vba: str) -> None:
    for code in code_outside_strings(vba):
        low = code.lower()
        for word in DANGEROUS:
            assert word not in low, f"payload escaped its string literal: {code!r}\n---\n{vba}"


def call(module, name, args, client):
    out = asyncio.run(module.handle(name, args, client))
    return json.loads(out[0].text)


def is_rejected(payload: dict) -> bool:
    return payload.get("status") == "error"


# ---------------------------------------------------------------------------
# vba_safety helpers
# ---------------------------------------------------------------------------

def test_vba_string_literal_doubles_quotes():
    assert vba_safety.vba_string_literal('a"b') == '"a""b"'
    assert vba_safety.vba_string_literal("") == '""'


@pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\x00b", "a\u2028b"])
def test_vba_string_literal_rejects_line_breaks(bad):
    with pytest.raises(ValueError):
        vba_safety.vba_string_literal(bad, "field")


def test_vba_string_literal_rejects_non_strings():
    with pytest.raises(ValueError):
        vba_safety.vba_string_literal(5)


@pytest.mark.parametrize(
    "legit",
    ["Patch Antenna", "S1,1", "C:\\Users\\me\\out dir\\f.csv", "Kupfer — ünïcødé 天线", "a'b"],
)
def test_legit_values_round_trip(legit):
    lit = vba_safety.vba_string_literal(legit)
    assert lit == '"' + legit + '"'
    assert code_outside_strings(f"SelectTreeItem {lit}") == ['SelectTreeItem ""']


def test_validate_paths():
    assert vba_safety.validate_tree_path('Farfields\\farfield (f=2.4) "x"') == 'Farfields\\farfield (f=2.4) ""x""'
    with pytest.raises(ValueError):
        vba_safety.validate_tree_path("")
    with pytest.raises(ValueError):
        vba_safety.validate_file_path('C:\\a"b.csv')
    with pytest.raises(ValueError):
        vba_safety.validate_file_path("C:\\a\nb.csv")
    assert vba_safety.validate_file_path("C:\\dir\\f.csv") == "C:\\dir\\f.csv"


def test_numeric_coercion():
    assert vba_safety.vba_number(2) == "2"
    assert vba_safety.vba_number(2.5) == "2.5"
    assert vba_safety.vba_number("3") == "3"
    for bad in ["1 : RunAndWait \"calc\"", "nan", float("inf"), True, None]:
        with pytest.raises(ValueError):
            vba_safety.vba_number(bad)
    assert vba_safety.vba_int(4.0) == 4
    with pytest.raises(ValueError):
        vba_safety.vba_int("1: RunAndWait")
    with pytest.raises(ValueError):
        vba_safety.vba_int(1.5)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ["csv", "txt", "touchstone"])
def test_export_result_quote_payload_stays_in_literal(fmt):
    client = FakeClient()
    res = call(results, "cst_export_result",
               {"result_path": QUOTE_PAYLOAD, "output_file": "out.csv", "format": fmt}, client)
    if is_rejected(res):
        return
    assert client.executed, res
    for vba in client.executed:
        assert_payload_contained(vba)
        assert 'S1,1"" : RunAndWait ""calc.exe"" :' in vba


def test_export_result_newline_payload_rejected():
    client = FakeClient()
    res = call(results, "cst_export_result",
               {"result_path": NEWLINE_PAYLOAD, "output_file": "out.csv", "format": "csv"}, client)
    assert is_rejected(res)
    assert not client.executed


def test_export_result_output_file_quote_rejected():
    client = FakeClient()
    res = call(results, "cst_export_result",
               {"result_path": "1D Results\\S-Parameters\\S1,1",
                "output_file": 'out.csv" : RunAndWait "calc.exe" : \'', "format": "csv"}, client)
    if not is_rejected(res):
        for vba in client.executed:
            assert_payload_contained(vba)


def test_export_result_legit_path_works():
    client = FakeClient()
    path = "1D Results\\S-Parameters\\S1,1 (ünïcødé, run 2)"
    res = call(results, "cst_export_result",
               {"result_path": path, "output_file": "C:\\out dir\\s11.csv", "format": "csv"}, client)
    assert not is_rejected(res), res
    vba = client.executed[-1]
    assert f'SelectTreeItem "{path}"' in vba
    assert '.FileName "C:\\out dir\\s11.csv"' in vba
    assert_payload_contained(vba)


@pytest.mark.parametrize("client_cls", [FakeClient, OfflineClient])
def test_list_results_tree_path_payload(client_cls):
    client = client_cls()
    res = call(results, "cst_list_results", {"tree_path": QUOTE_PAYLOAD}, client)
    if is_rejected(res):
        return
    scripts = client.executed or [res["vba_script"]]
    for vba in scripts:
        assert_payload_contained(vba)


def test_list_results_newline_rejected():
    client = FakeClient()
    res = call(results, "cst_list_results", {"tree_path": NEWLINE_PAYLOAD}, client)
    assert is_rejected(res)
    assert not client.executed


def test_farfield_monitor_name_payload_offline_script():
    res = call(results, "cst_get_farfield",
               {"frequency": 2.4, "monitor_name": 'ff" : RunAndWait "calc.exe" : \''},
               OfflineClient())
    if is_rejected(res):
        return
    assert_payload_contained(res["vba_script"])


def test_farfield_monitor_name_newline_rejected():
    client = FakeClient()
    res = call(results, "cst_get_farfield",
               {"frequency": 2.4, "monitor_name": 'ff"\nRunAndWait "calc.exe"'}, client)
    assert is_rejected(res)
    assert not client.executed


def test_surface_current_component_payload():
    res = call(results, "cst_get_surface_current",
               {"frequency": 2.4, "component": 'c" : RunAndWait "calc.exe" : \''}, OfflineClient())
    if not is_rejected(res):
        assert_payload_contained(res.get("vba_script", ""))


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("cst_get_pattern_cut", {"frequency": 2.4, "plane": "custom",
                                 "phi_cut": '0" : RunAndWait "calc.exe" : \''}),
        ("cst_get_axial_ratio", {"frequency": 2.4, "theta_cut": "1: RunAndWait \"calc.exe\""}),
        ("cst_get_farfield", {"frequency": "2.4\" : RunAndWait \"calc.exe\" : '"}),
        ("cst_get_vswr", {"port": "1\" : RunAndWait \"calc.exe\" : '"}),
    ],
)
def test_numeric_injection_rejected(name, args):
    client = FakeClient()
    res = call(results, name, args, client)
    assert is_rejected(res), res
    assert not client.executed


def test_geometry_newline_in_name_rejected():
    client = FakeClient()
    res = call(geometry, "cst_create_brick", {
        "name": 'b"\nRunAndWait "calc.exe"', "component": "c", "material": "PEC",
        "x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1, "z_min": 0, "z_max": 1,
    }, client)
    assert is_rejected(res)
    assert not client.executed


def test_boolean_solid_payload_rejected_or_contained():
    client = FakeClient()
    try:
        out = asyncio.run(boolean.handle(
            "cst_boolean_add",
            {"solid1": 'a:b" : RunAndWait "calc.exe" : \'', "solid2": "a:c"}, client))
        text = out[0].text
    except ValueError:  # validation error raised by the handler
        return
    assert "error" in text.lower() or not client.executed
    for vba in client.executed:
        assert_payload_contained(vba)


def test_optimization_export_path_rejects_quote():
    with pytest.raises(ValueError):
        optimization._export_s11_vba('C:/x.csv" : RunAndWait "calc.exe" : \'')
    with pytest.raises(ValueError):
        optimization._export_s11_vba("C:/x.csv", port="1: RunAndWait")
    assert '.FileName "C:/dir/x.csv"' in optimization._export_s11_vba("C:\\dir\\x.csv")


def test_workflow_brick_expr_escaped():
    vba = workflows._brick_expr('c" : RunAndWait "calc.exe" : \'', "n", "PEC",
                                "0", "1", "0", "1", "0", "1")
    assert_payload_contained(vba)
    with pytest.raises(ValueError):
        workflows._brick_expr("c", "n\nRunAndWait", "PEC", "0", "1", "0", "1", "0", "1")


def test_guard_allows_legit_unicode_and_spaces():
    vba_safety.check_arguments(results.TOOLS, "cst_export_result", {
        "result_path": "1D Results\\S-Parameters\\S1,1 ünïcødé", "output_file": "C:\\a b\\c.csv",
    })
    vba_safety.check_arguments(results.TOOLS, "cst_get_pattern_cut", {"frequency": 2, "phi_cut": 45.5})
