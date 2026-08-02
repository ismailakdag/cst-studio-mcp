# VBA alignment notes (vba_cst)

Source: local CST Online Help dump in `vba_cst/vba_data.js` (169 objects).

## Fixes applied against official help

| Area | Issue found | Fix |
|------|-------------|-----|
| Sphere | Used non-existent `CenterX/Y/Z` + `Radius` | Official `CenterRadius`, `TopRadius`, `BottomRadius`, `Center x,y,z` |
| Transform translate | Fake `TranslateX/Y/Z` | Official `Vector u,v,w` + `MultipleObjects` |
| Transform rotate/mirror/scale | Property names with spaces (`Origin X`) | Official `Origin`, `Center`, `Angle`, `PlaneNormal`, `ScaleFactor` |
| DiscretePort | Invalid `Point1`/`Point2` | Official `SetP1` / `SetP2` (picked, x, y, z); Type `Sparameter` |
| Torus | `CenterX` / wrong radius casing | Official `Xcenter/Ycenter/Zcenter`, `OuterRadius`/`InnerRadius` |
| Waveguide Port | Mostly OK | Uses `PortNumber`, `Orientation`, `Coordinates` |

## Composite workflows added

- `cst_export_structure_views` — Plot.ExportImage multi-view screenshots
- `cst_workflow_design_report` — params + S11 + farfield (best effort) + images
- `cst_workflow_simulate_and_report` — solve then report package

Each report section fails soft so partial success is still usable.

## Farfield (CST 2026)

| Area | Guidance |
|------|----------|
| Monitor | `.Frequency`, `FieldType "Farfield"`, prefer `EnableNearfieldCalculation` |
| Tree | `Farfields\farfield (f=<freq>) [1]` after TD solve |
| Metrics | Prefer `FarfieldPlot.GetMax` / efficiencies; avoid `ASCIIExportSummary` spam |
| MCP | `cst_get_farfield_metrics` (1D Results + GetMax) |

See also the Installation / Farfield sections in `docs/index.html` and root `README.md`.
