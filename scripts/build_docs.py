"""Build bilingual professional docs site + README catalog from live tools."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp.server import Server  # noqa: E402

from cst_mcp.config import CSTConfig  # noqa: E402
from cst_mcp.cst_client import CSTClient  # noqa: E402

CATEGORIES: list[dict] = [
    {
        "id": "workflows",
        "title_en": "Workflows (start here)",
        "title_tr": "İş akışları (buradan başla)",
        "blurb_en": "One-shot helpers for common tasks. New users should start here.",
        "blurb_tr": "Sık işler için tek adımlık yardımcılar. Yeni kullanıcılar buradan başlamalı.",
        "module": "workflows",
    },
    {
        "id": "project",
        "title_en": "Project & connection",
        "title_tr": "Proje ve bağlantı",
        "blurb_en": "Create, open, save projects and check CST connection.",
        "blurb_tr": "Proje aç/kaydet ve CST bağlantısını kontrol et.",
        "module": "project",
    },
    {
        "id": "geometry",
        "title_en": "Geometry",
        "title_tr": "Geometri",
        "blurb_en": "3D shapes: bricks, cylinders, spheres, extrusions, wires…",
        "blurb_tr": "3B şekiller: kutu, silindir, küre, extrude, tel…",
        "module": "geometry",
    },
    {
        "id": "boolean",
        "title_en": "Boolean operations",
        "title_tr": "Boolean işlemler",
        "blurb_en": "Combine solids: add, subtract, intersect, insert.",
        "blurb_tr": "Katıları birleştir: ekle, çıkar, kesişim, insert.",
        "module": "boolean",
    },
    {
        "id": "transforms",
        "title_en": "Transforms",
        "title_tr": "Dönüşümler",
        "blurb_en": "Move, rotate, mirror, and scale solids.",
        "blurb_tr": "Taşı, döndür, ayna, ölçekle.",
        "module": "transforms",
    },
    {
        "id": "materials",
        "title_en": "Materials",
        "title_tr": "Malzemeler",
        "blurb_en": "Metals, dielectrics, and advanced material models.",
        "blurb_tr": "Metaller, dielektrikler ve gelişmiş malzeme modelleri.",
        "module": "materials",
    },
    {
        "id": "ports",
        "title_en": "Ports & excitations",
        "title_tr": "Portlar ve uyarmalar",
        "blurb_en": "Waveguide, discrete, plane wave, Floquet…",
        "blurb_tr": "Dalga kılavuzu, discrete, düzlem dalga, Floquet…",
        "module": "ports",
    },
    {
        "id": "boundaries",
        "title_en": "Boundaries & setup",
        "title_tr": "Sınırlar ve kurulum",
        "blurb_en": "Open/electric walls, background, symmetry, frequency range.",
        "blurb_tr": "Açık/elektrik duvar, arka plan, simetri, frekans aralığı.",
        "module": "boundaries",
    },
    {
        "id": "mesh",
        "title_en": "Mesh",
        "title_tr": "Mesh",
        "blurb_en": "Mesh type, density, refinement, adaptive meshing.",
        "blurb_tr": "Mesh tipi, yoğunluk, iyileştirme, adaptif mesh.",
        "module": "mesh",
    },
    {
        "id": "solvers",
        "title_en": "Solvers",
        "title_tr": "Çözücüler",
        "blurb_en": "Time domain, frequency domain, eigenmode, IE…",
        "blurb_tr": "Zaman alanı, frekans alanı, özmod, IE…",
        "module": "solvers",
    },
    {
        "id": "simulation",
        "title_en": "Simulation control",
        "title_tr": "Simülasyon kontrolü",
        "blurb_en": "Run, pause, resume, stop simulations.",
        "blurb_tr": "Simülasyonu çalıştır, duraklat, sürdür, durdur.",
        "module": "simulation",
    },
    {
        "id": "results",
        "title_en": "Results",
        "title_tr": "Sonuçlar",
        "blurb_en": "S-parameters, far-field, VSWR, gain, Smith, bandwidth…",
        "blurb_tr": "S-parametreleri, uzak alan, VSWR, kazanç, Smith, bant…",
        "module": "results",
    },
    {
        "id": "import_export",
        "title_en": "Import / export",
        "title_tr": "İçe / dışa aktarma",
        "blurb_en": "CAD and Touchstone import/export, far-field export.",
        "blurb_tr": "CAD ve Touchstone içe/dışa aktarma, farfield export.",
        "module": "import_export",
    },
    {
        "id": "parameters",
        "title_en": "Parameters & optimizers",
        "title_tr": "Parametreler ve optimizasyon",
        "blurb_en": "Design parameters, sweeps, optimizers, sensitivity, yield.",
        "blurb_tr": "Tasarım parametreleri, tarama, optimizer, hassasiyet, yield.",
        "module": "parameters",
    },
    {
        "id": "optimization",
        "title_en": "Antenna evaluation",
        "title_tr": "Anten değerlendirme",
        "blurb_en": "Goal-driven evaluation and refinement helpers.",
        "blurb_tr": "Hedef odaklı değerlendirme ve iyileştirme yardımcıları.",
        "module": "optimization",
    },
    {
        "id": "diagnostics",
        "title_en": "Diagnostics",
        "title_tr": "Tanılama",
        "blurb_en": "Logs, delete results, auto-dismiss blocking CST dialogs.",
        "blurb_tr": "Loglar, sonuç silme, engelleyen CST diyaloglarını kapatma.",
        "module": "diagnostics",
    },
    {
        "id": "antenna_templates",
        "title_en": "Antenna templates",
        "title_tr": "Anten şablonları",
        "blurb_en": "Parametric antennas: patch, dipole, horn, Yagi, helix…",
        "blurb_tr": "Parametrik antenler: patch, dipole, horn, Yagi, helix…",
        "module": "antenna_templates",
    },
    {
        "id": "arrays",
        "title_en": "Antenna arrays",
        "title_tr": "Anten dizileri",
        "blurb_en": "Linear/planar/circular arrays, beam steering, taper.",
        "blurb_tr": "Doğrusal/düzlemsel/dairesel dizi, hüzme yönlendirme, taper.",
        "module": "arrays",
    },
    {
        "id": "pcb",
        "title_en": "PCB / SI",
        "title_tr": "PCB / SI",
        "blurb_en": "Stackups, traces, vias, ground planes, Gerber import.",
        "blurb_tr": "Stackup, hat, via, toprak düzlemi, Gerber import.",
        "module": "pcb",
    },
    {
        "id": "matching",
        "title_en": "Matching networks",
        "title_tr": "Empedans eşleme",
        "blurb_en": "L / Pi / T networks, stubs, quarter-wave, Smith transforms.",
        "blurb_tr": "L / Pi / T ağları, stub, çeyrek dalga, Smith dönüşümleri.",
        "module": "matching",
    },
    {
        "id": "vba",
        "title_en": "VBA escape hatch",
        "title_tr": "VBA acil çıkış",
        "blurb_en": "Raw VBA execution and built-in VBA object reference.",
        "blurb_tr": "Ham VBA çalıştırma ve yerleşik VBA nesne referansı.",
        "module": "vba",
    },
]


def collect_tools() -> list[dict]:
    from cst_mcp.tools import (
        antenna_templates,
        arrays,
        boolean,
        boundaries,
        diagnostics,
        geometry,
        import_export,
        matching,
        materials,
        mesh,
        optimization,
        parameters,
        pcb,
        ports,
        project,
        results,
        simulation,
        solvers,
        transforms,
        vba,
        workflows,
    )

    module_map = {
        c["module"]: globals().get(c["module"])
        or __import__(f"cst_mcp.tools.{c['module']}", fromlist=["TOOLS"])
        for c in CATEGORIES
    }
    # fix: explicit map more reliable
    module_map = {
        "workflows": workflows,
        "project": project,
        "geometry": geometry,
        "boolean": boolean,
        "transforms": transforms,
        "materials": materials,
        "ports": ports,
        "boundaries": boundaries,
        "mesh": mesh,
        "solvers": solvers,
        "simulation": simulation,
        "results": results,
        "import_export": import_export,
        "parameters": parameters,
        "optimization": optimization,
        "diagnostics": diagnostics,
        "antenna_templates": antenna_templates,
        "arrays": arrays,
        "pcb": pcb,
        "matching": matching,
        "vba": vba,
    }

    tools: list[dict] = []
    for cat in CATEGORIES:
        mod = module_map[cat["module"]]
        for t in mod.TOOLS:
            schema = t.inputSchema if isinstance(t.inputSchema, dict) else {}
            props = schema.get("properties") or {}
            required = schema.get("required") or []
            params = []
            for k, v in props.items():
                params.append(
                    {
                        "name": k,
                        "type": v.get("type", "any"),
                        "description": v.get("description") or "",
                        "default": v.get("default", None),
                        "enum": v.get("enum"),
                        "required": k in required,
                    }
                )
            tools.append(
                {
                    "name": t.name,
                    "description": (t.description or "").strip(),
                    "category_id": cat["id"],
                    "params": params,
                    "required": list(required),
                }
            )
    return tools


def build_catalog(tools: list[dict]) -> dict:
    by_cat: dict[str, list] = {}
    for t in tools:
        by_cat.setdefault(t["category_id"], []).append(t)
    categories = []
    for cat in CATEGORIES:
        items = by_cat.get(cat["id"], [])
        categories.append({**cat, "count": len(items), "tools": items})
    return {
        "name": "cst-studio-mcp",
        "version": "1.0.0",
        "total_tools": len(tools),
        "categories": categories,
        "vba_reference_note": {
            "en": "Geometry/port/transform VBA aligned with CST Online Help dumps in vba_cst/.",
            "tr": "Geometri/port/transform VBA’ları vba_cst/ içindeki CST Online Help dökümüyle hizalandı.",
        },
    }



def render_html(catalog: dict) -> str:
    """Load HTML shell and inject catalog JSON (avoids f-string / JS brace issues)."""
    data = json.dumps(catalog, ensure_ascii=False).replace("</", "<\\/")
    template_path = ROOT / "docs" / "_template.html"
    if not template_path.is_file():
        raise FileNotFoundError(template_path)
    shell = template_path.read_text(encoding="utf-8")
    if "__CATALOG_JSON__" not in shell:
        raise ValueError("docs/_template.html missing __CATALOG_JSON__ placeholder")
    return shell.replace("__CATALOG_JSON__", data)


def render_readme_tables(catalog: dict) -> str:
    lines = [
        f"## Full tool catalog ({catalog['total_tools']} tools)",
        "",
        "Interactive bilingual docs: open [`docs/index.html`](docs/index.html) "
        "(EN/TR toggle, search, full-width cards). Rebuild: `python scripts/build_docs.py`.",
        "",
        "VBA for geometry/ports/transforms is cross-checked against the CST help dump in "
        "[`vba_cst/`](vba_cst/).",
        "",
    ]
    for cat in catalog["categories"]:
        title = cat["title_en"]
        lines.append(f"### {title} ({cat['count']})")
        lines.append("")
        lines.append(cat["blurb_en"])
        lines.append("")
        lines.append("| Tool | What it does |")
        lines.append("|------|--------------|")
        for t in cat["tools"]:
            desc = (t["description"] or "").replace("\n", " ").replace("|", "\\|")
            if len(desc) > 140:
                desc = desc[:137] + "…"
            lines.append(f"| `{t['name']}` | {desc} |")
        lines.append("")
    return "\n".join(lines)


def patch_readme(table_md: str, total: int) -> None:
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    marker_start = "<!-- TOOL_CATALOG_START -->"
    marker_end = "<!-- TOOL_CATALOG_END -->"
    block = f"{marker_start}\n{table_md}\n{marker_end}"
    if marker_start in text and marker_end in text:
        pre = text.split(marker_start)[0]
        post = text.split(marker_end, 1)[1]
        text = pre + block + post
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    text = text.replace("~173", str(total)).replace("173 tools", f"{total} tools")
    # ensure docs mention bilingual
    if "EN/TR" not in text and "bilingual" not in text.lower():
        text = text.replace(
            "Interactive tool browser (beginner-friendly):",
            "Interactive **EN/TR** tool browser (beginner-friendly):",
        )
    readme.write_text(text, encoding="utf-8")


def main() -> None:
    tools = collect_tools()
    catalog = build_catalog(tools)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "tools.json").write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (docs / "index.html").write_text(render_html(catalog), encoding="utf-8")
    tables = render_readme_tables(catalog)
    (docs / "TOOLS.md").write_text(tables + "\n", encoding="utf-8")
    patch_readme(tables, catalog["total_tools"])

    # Comparison note vs vba_cst
    compare = ROOT / "docs" / "VBA_ALIGNMENT.md"
    compare.write_text(
        """# VBA alignment notes (vba_cst)

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
| Tree | `Farfields\\farfield (f=<freq>) [1]` after TD solve |
| Metrics | Prefer `FarfieldPlot.GetMax` / efficiencies; avoid `ASCIIExportSummary` spam |
| MCP | `cst_get_farfield_metrics` (1D Results + GetMax) |

See also the Installation / Farfield sections in `docs/index.html` and root `README.md`.
""",
        encoding="utf-8",
    )
    print(f"OK: {catalog['total_tools']} tools → docs/index.html + catalog")


if __name__ == "__main__":
    main()
