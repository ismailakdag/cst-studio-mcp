"""Read-only audit against the locally installed official help; no CST session.

Search matches are documentation evidence, never live execution certification.
Vendor help text is not copied to the output, only paths and hashes.
"""

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools.official import TextOnly


def main():
    client = CSTClient()
    help_root = client.config.cst_path / "Online Help"
    pages = []
    for folder in ["mergedProjects/VBA_3D", "mergedProjects/VBA_DES", "advanced"]:
        for path in (help_root / folder).rglob("*.htm*"):
            parser = TextOnly()
            parser.feed(path.read_text(encoding="utf-8", errors="replace"))
            pages.append((path, " ".join(parser.parts).lower()))
    missing_client = []
    pairs = {}
    for path in (ROOT / "src/cst_mcp").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "client"
            ):
                if not hasattr(client, node.attr):
                    missing_client.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.attr}")
            if not isinstance(node, ast.Call):
                continue
            current, members = node, []
            while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
                if current.func.attr in {
                    "set",
                    "set_number",
                    "set_double",
                    "set_triple",
                    "set_bool",
                    "set_raw",
                    "call",
                    "call_with_args",
                }:
                    if (
                        current.args
                        and isinstance(current.args[0], ast.Constant)
                        and isinstance(current.args[0].value, str)
                    ):
                        members.append(current.args[0].value)
                current = current.func.value
            if (
                isinstance(current, ast.Call)
                and isinstance(current.func, ast.Name)
                and current.func.id == "VBABuilder"
                and current.args
                and isinstance(current.args[0], ast.Constant)
            ):
                for member in members:
                    pairs.setdefault((current.args[0].value, member), set()).add(
                        str(path.relative_to(ROOT))
                    )
    results = []
    import re

    for (obj, member), source in sorted(pairs.items()):
        candidates = [
            (p, t)
            for p, t in pages
            if re.search(r"\b" + re.escape(obj.lower()) + r"\s*(?:object|\b)", t[:1200])
        ]
        matches = [
            p for p, t in candidates if re.search(r"\b" + re.escape(member.lower()) + r"\b", t)
        ]
        results.append(
            {
                "object": obj,
                "member": member,
                "sources": sorted(source),
                "status": "name_found_in_help" if matches else "needs_review",
                "help": [str(p.relative_to(help_root)).replace("\\", "/") for p in matches[:3]],
            }
        )
    docs = [
        "Python/source/cst.results.html",
        "Python/source/cst.interface.html",
        "mergedProjects/VBA_3D/common_vbaimpexp/asciiexport_object.htm",
        "mergedProjects/VBA_3D/common_vbabasicsolids/common_vbabrick_object.htm",
    ]
    output = {
        "installation": str(client.config.cst_path),
        "missing_client_members": missing_client,
        "scope": "Statically resolvable literal VBABuilder chains only; raw VBA and runtime arguments need separate validation. Name presence does not validate signatures or execution.",
        "documentation": [
            {"path": p, "sha256": hashlib.sha256((help_root / p).read_bytes()).hexdigest()}
            for p in docs
        ],
        "builder_members": results,
    }
    target = ROOT / "docs/installed-api-audit.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "pairs": len(results),
                "needs_review": [
                    f"{r['object']}.{r['member']}" for r in results if r["status"] == "needs_review"
                ],
                "missing_client": missing_client,
            }
        )
    )


if __name__ == "__main__":
    main()
