"""Orthographic technical drawings (2D views with dimensions) of CST geometry."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from mcp.types import Tool

from cst_mcp.tools.registry import as_json, err

_VIEWS = ["top", "front", "side", "iso"]
_FORMATS = ["pdf", "svg", "png"]
_UNITS = ["m", "cm", "mm", "um", "nm", "in", "mil", "ft"]

TOOLS: list[Tool] = [
    Tool(
        name="cst_technical_drawing",
        description=(
            "Render an academic, dimensioned orthographic technical drawing (third-angle "
            "top/front/side views, optional isometric) of the CST model. Connected mode "
            "exports every solid to STL (no history entry) under CST_WORK_DIR and reads the "
            "parameter list; offline mode re-renders from a previous export via stl_dir "
            "(manifest.json supplies names/materials/units, else file stem and 'units'). "
            "Draws feature edges with hidden lines dashed, grayscale material fills, overall "
            "W x L, layer thicknesses and per-solid dimensions in mm, parameter table and "
            "title block. Writes PDF/SVG/PNG (600 dpi). Thin planar stacks are Z-exaggerated "
            "in front/side views (labelled); dimension values are always true size."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "stl_dir": {
                    "type": "string",
                    "description": "Directory of existing .stl files; skips CST entirely.",
                },
                "units": {
                    "type": "string", "enum": _UNITS,
                    "description": "Units of STL coordinates in stl_dir (default: manifest or mm).",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory (default CST_WORK_DIR/exports/drawings/<time>).",
                },
                "basename": {"type": "string", "default": "technical_drawing",
                             "pattern": "^[A-Za-z0-9_.-]{1,80}$"},
                "views": {
                    "type": "array", "items": {"type": "string", "enum": _VIEWS},
                    "minItems": 1, "uniqueItems": True, "default": ["top", "front", "side"],
                },
                "layout": {"type": "string", "enum": ["sheet", "separate"], "default": "sheet"},
                "formats": {
                    "type": "array", "items": {"type": "string", "enum": _FORMATS},
                    "minItems": 1, "uniqueItems": True, "default": _FORMATS,
                },
                "dpi": {"type": "integer", "minimum": 72, "maximum": 1200, "default": 600},
                "title": {"type": "string", "maxLength": 120},
                "title_block": {"type": "boolean", "default": True},
                "include_parameters": {"type": "boolean", "default": True},
                "parameters": {
                    "type": "object",
                    "additionalProperties": {"type": ["string", "number"]},
                    "description": "Extra/override name=value rows for the parameter table.",
                },
                "solids": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Only draw solids whose name contains one of these substrings.",
                },
                "max_solid_dims": {"type": "integer", "minimum": 0, "maximum": 12, "default": 4},
                "hidden_lines": {"type": "string", "enum": ["dashed", "hide", "show"],
                                 "default": "dashed"},
                "fill": {"type": "boolean", "default": True},
                "z_exaggeration": {
                    "type": "number", "minimum": 0, "maximum": 10000, "default": 0,
                    "description": "Z stretch in front/side views; 0 = auto, 1 = true scale.",
                },
                "feature_angle_deg": {"type": "number", "minimum": 1, "maximum": 89, "default": 20},
                "decimals": {"type": "integer", "minimum": 0, "maximum": 4, "default": 2},
            },
            "required": [],
            "additionalProperties": False,
        },
    )
]


def _export_vba(target: Path) -> str:
    """VBA that prints unit factor + one line per solid and writes one STL per solid."""
    folder = str(target).replace('"', '""')
    return "\n".join([
        "Dim n As Long, i As Long, p As Long",
        "Dim fullName As String, compName As String, solidName As String, fileName As String",
        'Debug.Print "UNIT" & vbTab & CStr(Units.GetGeometryUnitToSI())',
        "n = Solid.GetNumberOfShapes()",
        "For i = 0 To n - 1",
        "  fullName = Solid.GetNameOfShapeFromIndex(i)",
        '  p = InStrRev(fullName, ":")',
        "  If p > 0 Then",
        "    compName = Left(fullName, p - 1)",
        "    solidName = Mid(fullName, p + 1)",
        f'    fileName = "{folder}\\solid_" & Format(i, "000") & ".stl"',
        "    With STL",
        "      .Reset",
        "      .FileName fileName",
        "      .Name solidName",
        "      .Component compName",
        "      .ExportFromActiveCoordinateSystem False",
        '      .ExportFileUnits "mm"',
        "      .Write",
        "    End With",
        (
            '    Debug.Print "SOLID" & vbTab & CStr(i) & vbTab & fullName & vbTab & '
            "Solid.GetMaterialNameForShape(fullName)"
        ),
        "  End If",
        "Next i",
    ])


_SI_TO_UNIT = {1.0: "m", 1e-2: "cm", 1e-3: "mm", 1e-6: "um", 1e-9: "nm",
               0.0254: "in", 2.54e-5: "mil", 0.3048: "ft"}


def _unit_from_factor(factor: float) -> str | None:
    for si, name in _SI_TO_UNIT.items():
        if abs(factor - si) <= 1e-9 * max(si, 1e-12) + 1e-15:
            return name
    return None


def export_model_stls(client, target: Path) -> dict[str, Any]:
    """Export every solid of the open project to ``target`` and write manifest.json."""
    target.mkdir(parents=True, exist_ok=True)
    result = client.capture_vba_output(_export_vba(target))
    if result.get("status") != "ok":
        return {"status": "error", "message": "STL export failed", "detail": result}
    # STL has no unit field; CST writes metres unless ExportFileUnits is set,
    # which the export VBA does ("mm"). UNIT reports the project geometry unit.
    units, project_unit, solids = "mm", None, []
    for line in result.get("output", "").splitlines():
        parts = line.rstrip("\r").split("\t")
        if parts[0] == "UNIT" and len(parts) > 1:
            try:
                unit = _unit_from_factor(float(parts[1].strip().replace(",", ".")))
            except ValueError:
                unit = None
            project_unit = unit
        elif parts[0] == "SOLID" and len(parts) >= 3:
            idx = int(parts[1])
            full = parts[2].strip()
            comp, _, _name = full.rpartition(":")
            solids.append({
                "file": f"solid_{idx:03d}.stl", "name": full, "component": comp,
                "material": parts[3].strip() if len(parts) > 3 else "",
            })
    missing = [s["name"] for s in solids if not (target / s["file"]).is_file()]
    manifest = {"units": units, "project_units": project_unit,
                "project": str(getattr(client, "project_path", "") or ""),
                "solids": [s for s in solids if s["name"] not in missing]}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not manifest["solids"]:
        return {"status": "error", "message": "CST exported no STL files (model has no solids?)",
                "missing": missing}
    return {"status": "ok", "stl_dir": str(target), "units": units, "count": len(manifest["solids"]),
            "missing": missing}


def _options(arguments: dict[str, Any], parameters: dict[str, Any], project_name: str):
    from cst_mcp.execution.drawing_render import DrawingOptions

    return DrawingOptions(
        views=list(arguments.get("views") or ["top", "front", "side"]),
        layout=arguments.get("layout", "sheet"),
        formats=list(arguments.get("formats") or _FORMATS),
        dpi=int(arguments.get("dpi", 600)),
        title=arguments.get("title") or (Path(project_name).stem if project_name else "Technical drawing"),
        title_block=bool(arguments.get("title_block", True)),
        parameters=parameters,
        max_solid_dims=int(arguments.get("max_solid_dims", 4)),
        hidden_lines=arguments.get("hidden_lines", "dashed"),
        fill=bool(arguments.get("fill", True)),
        z_exaggeration=float(arguments.get("z_exaggeration", 0) or 0),
        decimals=int(arguments.get("decimals", 2)),
        project_name=Path(project_name).name if project_name else "",
    )


def technical_drawing(arguments: dict[str, Any], client) -> dict[str, Any]:
    from cst_mcp.execution import academic_style
    from cst_mcp.execution.drawing_geometry import bbox_dict, load_stl_dir, overall_bbox

    try:
        academic_style.require_matplotlib()
    except ImportError as exc:
        return {"status": "error", "message": str(exc)}

    work_dir = Path(getattr(getattr(client, "config", None), "work_dir", None) or Path.cwd())
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(arguments["output_dir"]) if arguments.get("output_dir") else (
        work_dir / "exports" / "drawings" / stamp)
    params: dict[str, Any] = {}
    export = None
    stl_dir = arguments.get("stl_dir")
    if not stl_dir:
        if not getattr(client, "has_project", False):
            return {"status": "error",
                    "message": "No open CST project: connect and open a project, or pass stl_dir "
                               "with previously exported STL files."}
        export = export_model_stls(client, out_dir / "stl")
        if export.get("status") != "ok":
            return export
        stl_dir = export["stl_dir"]
        if arguments.get("include_parameters", True):
            listed = client.list_parameters()
            if listed.get("status") == "ok":
                params.update(listed.get("parameters", {}))
    try:
        solids, info = load_stl_dir(stl_dir, units=arguments.get("units"),
                                    angle_deg=float(arguments.get("feature_angle_deg", 20)))
    except (OSError, ValueError) as exc:
        return {"status": "error", "message": str(exc)}
    filters = [f.lower() for f in arguments.get("solids") or []]
    if filters:
        solids = [s for s in solids if any(f in s.name.lower() for f in filters)]
    if not solids:
        return {"status": "error", "message": f"No non-empty STL solids found in {stl_dir}"}
    if arguments.get("include_parameters", True):
        params.update(arguments.get("parameters") or {})
    else:
        params = {}
    project_name = info.get("project") or (getattr(client, "project_path", None) or "")

    from cst_mcp.execution.drawing_render import render

    opts = _options(arguments, params, str(project_name))
    rendered = render(solids, out_dir, arguments.get("basename", "technical_drawing"), opts)
    lo, hi = overall_bbox(solids)
    return {
        "status": "ok",
        "files": rendered["files"],
        "views": rendered["views"],
        "layout": opts.layout,
        "z_exaggeration": rendered["z_exaggeration"],
        "bbox_mm": bbox_dict(lo, hi),
        "solids": [s.summary() for s in solids],
        "stl_dir": str(stl_dir),
        "units_in_file": info["units_in_file"],
        "parameters": params,
        "source": "cst_export" if export else "stl_dir",
    }


async def handle(name, arguments, client):
    if name != "cst_technical_drawing":
        return err(f"Unknown tool: {name}")
    basename = arguments.get("basename", "technical_drawing")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", basename) or ".." in basename:
        return err("basename may only contain letters, digits, '_', '-', '.'")
    try:
        result = technical_drawing(arguments, client)
    except Exception as exc:  # noqa: BLE001 - surface rendering failures as tool errors
        return err(f"Technical drawing failed: {exc}")
    if result.get("status") != "ok":
        return err(result.pop("message", "Technical drawing failed"),
                   **{k: v for k, v in result.items() if k != "status"})
    return as_json(result)


from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
