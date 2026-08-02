# Documentation / Belgeler

Interactive **English / Türkçe** documentation for **cst-studio-mcp**, including installation,
environment variables, MCP client setup, and the full tool catalog.

| File | EN | TR |
|------|----|----|
| [**index.html**](index.html) | Interactive guide + tool browser | İnteraktif kurulum + araç rehberi |
| [TOOLS.md](TOOLS.md) | Markdown catalog | Markdown katalog |
| [tools.json](tools.json) | Machine-readable schemas | Makine-okur şemalar |
| [VBA_ALIGNMENT.md](VBA_ALIGNMENT.md) | Fixes vs `vba_cst` help dump | `vba_cst` yardım dökümüne göre düzeltmeler |
| [../README.md](../README.md) | Full project README (install, troubleshoot) | Ana kurulum ve sorun giderme |

## Open the site

```powershell
start docs\index.html
# or
python -m http.server 8080 --directory docs
```

In the UI:

- Toggle **English / Türkçe**
- Toggle **Light / Dark** (stored in `localStorage`)
- Search tools, open categories, expand parameters
- **Copy** copies the full tool text (name, description, parameters)

The top of the page includes **installation**, **environment variables**, **MCP config**,
**verify**, and **farfield tips** — aligned with the root README.

Design: academic paper + engineering reference (warm paper / slate dark, IBM Plex / Source Serif).

## Rebuild

From the repository root:

```powershell
python scripts/build_docs.py
```

Regenerates:

- `docs/index.html` (from `_template.html` + live tools)
- `docs/tools.json`
- `docs/TOOLS.md`
- README tool catalog section (`<!-- TOOL_CATALOG_START -->` …)
- `docs/VBA_ALIGNMENT.md` (notes file)

Requires the package importable (`pip install -e .`) and MCP dependency installed.
