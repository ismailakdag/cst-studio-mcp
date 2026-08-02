"""Port all tools from _reference into cst_mcp with package renames."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "_reference" / "src" / "mcp_cst_studio"
DST = ROOT / "src" / "cst_mcp"


def rewrite(text: str) -> str:
    return text.replace("mcp_cst_studio", "cst_mcp")


def main() -> None:
    # Support modules at package root (tools import cst_mcp.validators etc.)
    for name in ("validators.py", "types.py", "dialog_handler.py", "vba_builder.py"):
        src = REF / name
        text = rewrite(src.read_text(encoding="utf-8"))
        (DST / name).write_text(text, encoding="utf-8")
        print("support", name)

    # Keep a thin re-export for execution package
    (DST / "execution" / "vba_builder.py").write_text(
        '"""Re-export full VBA builder for execution package."""\n'
        "from cst_mcp.vba_builder import *  # noqa: F403\n"
        "from cst_mcp.vba_builder import VBABuilder, VBAScript  # noqa: F401\n",
        encoding="utf-8",
    )

    # Data
    data_dst = DST / "data"
    data_dst.mkdir(parents=True, exist_ok=True)
    for f in ("antenna_templates.json", "pcb_stackups.json", "vba_reference.json"):
        shutil.copy2(REF / "data" / f, data_dst / f)
        print("data", f)

    mat_src = REF / "data" / "materials"
    mat_dst = data_dst / "materials"
    mat_dst.mkdir(parents=True, exist_ok=True)
    for f in mat_src.glob("*.json"):
        shutil.copy2(f, mat_dst / f.name)
        print("material", f.name)

    # Tools — preserve workflows.py (ours)
    tools_src = REF / "tools"
    tools_dst = DST / "tools"
    keep_local = {"workflows.py", "registry.py"}  # rewritten separately
    for src in sorted(tools_src.glob("*.py")):
        if src.name in {"__init__.py"}:
            continue
        text = rewrite(src.read_text(encoding="utf-8"))
        (tools_dst / src.name).write_text(text, encoding="utf-8")
        print("tool", src.name)

    print("port complete")


if __name__ == "__main__":
    main()
