"""Local official documentation and read-only saved-project Python API tools."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from mcp.types import Tool

from cst_mcp.execution.curves import format_curve, read_curve
from cst_mcp.tools.registry import as_json, err


def tool(name, description, properties, required=()):
    return Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    )


TOOLS = [
    tool(
        "cst_search_help",
        "Search the installed official CST Python/VBA help by topic filename. Does not start CST. Read the matching help before constructing API calls.",
        {
            "query": {"type": "string", "minLength": 2},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15},
        },
        ["query"],
    ),
    tool(
        "cst_read_help",
        "Read a paginated official local CST help topic returned by cst_search_help. No GUI or solver.",
        {
            "topic": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "max_chars": {"type": "integer", "minimum": 100, "maximum": 20000, "default": 10000},
        },
        ["topic"],
    ),
    tool(
        "cst_list_saved_results",
        "List exact result tree paths and run IDs from a saved, unpacked, completed .cst file using cst.results. No connection or CST GUI is required. Do not use a file currently being solved.",
        {
            "project_path": {"type": "string"},
            "contains": {"type": "string", "default": ""},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        },
        ["project_path"],
    ),
    tool(
        "cst_read_saved_result",
        "Read a complete complex 1D curve by exact tree path and run_id from a completed saved .cst, without opening CST. Raw real/imag are preserved; format adds derived values. max_points=0 returns all samples; otherwise returns an explicitly sampled preview.",
        {
            "project_path": {"type": "string"},
            "tree_path": {"type": "string"},
            "run_id": {"type": "integer", "minimum": 0, "default": 0},
            "format": {
                "type": "string",
                "enum": ["real_imag", "db", "mag", "phase"],
                "default": "real_imag",
            },
            "max_points": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 200},
        },
        ["project_path", "tree_path"],
    ),
]


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "dt", "dd"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


async def handle(name, arguments, client):
    if name in {"cst_search_help", "cst_read_help"}:
        if not client.config.cst_path:
            return err("CST installation not found; set CST_PATH")
        root = (Path(client.config.cst_path) / "Online Help").resolve()
        if name == "cst_search_help":
            words = re.findall(r"[a-z0-9]+", arguments["query"].lower())
            if not words:
                return err("Enter a Python/VBA topic name")
            matches = []
            for directory in [
                root / "Python",
                root / "PythonTutorial",
                root / "mergedProjects/VBA_3D",
                root / "mergedProjects/VBA_DES",
            ]:
                for path in directory.rglob("*.htm*"):
                    rel = path.relative_to(root).as_posix()
                    if all(word in rel.lower() for word in words):
                        matches.append(rel)
            matches.sort(key=lambda s: (len(s), s))
            return as_json(
                {
                    "status": "ok",
                    "installation": str(client.config.cst_path),
                    "count": len(matches),
                    "topics": matches[: arguments.get("limit", 15)],
                }
            )
        path = (root / arguments["topic"]).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() not in {".htm", ".html"}:
            return err("Topic must be an HTML file inside the installed Online Help directory")
        parser = TextOnly()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        offset, count = arguments.get("offset", 0), arguments.get("max_chars", 10000)
        return as_json(
            {
                "status": "ok",
                "source": str(path),
                "text": text[offset : offset + count],
                "total_chars": len(text),
                "next_offset": offset + count if offset + count < len(text) else None,
            }
        )
    if client.config.connect_mode == "disabled":
        return err("CST access is disabled; use manual mode for saved-result reading")
    path = Path(arguments["project_path"]).resolve()
    if path.suffix.lower() != ".cst" or not path.is_file():
        return err("project_path must be an existing saved .cst file")
    if client.project_path and Path(client.project_path).resolve() == path:
        if client.is_solver_running(timeout_s=5) is not False:
            return err("Project is busy or solver state is unknown")
    if name == "cst_list_saved_results":
        import cst.results

        module = cst.results.ProjectFile(str(path), allow_interactive=False).get_3d()
        paths = [
            str(p)
            for p in module.get_tree_items()
            if arguments.get("contains", "").lower() in str(p).lower()
        ]
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 50)
        entries = []
        for tree in paths[offset : offset + limit]:
            try:
                entries.append({"tree_path": tree, "run_ids": list(module.get_run_ids(tree))})
            except Exception as exc:
                entries.append({"tree_path": tree, "run_ids": [], "message": str(exc)})
        return as_json(
            {
                "status": "ok",
                "project_path": str(path),
                "entries": entries,
                "total": len(paths),
                "next_offset": offset + limit if offset + limit < len(paths) else None,
            }
        )
    if name == "cst_read_saved_result":
        data = format_curve(
            read_curve(str(path), arguments["tree_path"], arguments.get("run_id", 0)),
            arguments.get("format", "real_imag"),
        )
        maximum = arguments.get("max_points", 200)
        if data.get("status") == "ok":
            n = data["n"]
            if maximum and maximum < n:
                indices = (
                    sorted({round(j * (n - 1) / (maximum - 1)) for j in range(maximum)})
                    if maximum > 1
                    else [0]
                )
                for key in ["x", "y", "real", "imag"]:
                    if key in data:
                        data[key] = [data[key][j] for j in indices]
                data.update(n=len(indices), total_points=n, sampled=True, sample_indices=indices)
            else:
                data.update(total_points=n, sampled=False)
        return as_json(data)
    return err(f"Unknown tool: {name}")
