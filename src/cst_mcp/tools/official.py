"""Local official documentation and read-only saved-project Python API tools."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from html.parser import HTMLParser
from pathlib import Path

from mcp.types import Tool

from cst_mcp.execution.curves import format_curve, read_curve
from cst_mcp.tools.registry import as_json, err

logger = logging.getLogger(__name__)


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
        "Full-text search of the installed official CST Python/VBA help (offline; does not start CST). "
        "Every query word must appear in the topic's file name, title or page text (AND semantics, "
        "case-insensitive substring), so multi-word queries such as 'Polygon ExtrudeCurve' and in-page "
        "method names such as 'AddPotentialNumerically' are found. Title/file-name hits rank above "
        "body-only hits; each result carries a text snippet around the match. The index is built once "
        "(cached in memory and under the work dir). Read the matching help with cst_read_help before "
        "constructing API calls.",
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
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "dt", "dd"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self.skip:
            self.parts.append(data)


_HELP_DIRS = ("Python", "PythonTutorial", "mergedProjects/VBA_3D", "mergedProjects/VBA_DES")
# RoboHelp/Sphinx search-engine data and generated index pages are not topics.
_HELP_SKIP_PARTS = {"whgdata", "whxdata", "_static", "_sources", "_images", "_plantuml"}
_HELP_SKIP_NAMES = {"search.html", "genindex.html", "py-modindex.html"}
_HELP_INDEX_VERSION = 1
_HELP_INDEX_CACHE: dict[str, list[dict]] = {}
_HELP_INDEX_LOCK = threading.Lock()


def _html_to_text(raw: str) -> tuple[str, str]:
    parser = TextOnly()
    parser.feed(raw)
    parser.close()
    text = re.sub(r"[ \t\r\f\v\xa0]+", " ", "".join(parser.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return parser.title.strip(), text


def _help_files(root: Path) -> list[Path]:
    files = []
    for directory in _HELP_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*.htm*"):
            rel_parts = path.relative_to(root).parts
            if _HELP_SKIP_PARTS.intersection(p.lower() for p in rel_parts):
                continue
            if path.name.lower() in _HELP_SKIP_NAMES or path.suffix.lower() not in {".htm", ".html"}:
                continue
            files.append(path)
    return sorted(files)


def _help_signature(root: Path, files: list[Path]) -> str:
    digest = hashlib.sha1(f"{_HELP_INDEX_VERSION}|{root}".encode("utf-8"))
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        digest.update(f"{rel}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8"))
    return digest.hexdigest()


def _help_index(root: Path, work_dir=None) -> list[dict]:
    """Full-text index of the installed help, built once per process.

    Cached in memory and, when a writable work dir exists, as JSON under
    ``<work_dir>/.cst_mcp_cache`` keyed by a signature of file names, sizes
    and mtimes (so a CST update rebuilds it).  Never touches the network.
    """
    key = str(root)
    with _HELP_INDEX_LOCK:
        cached = _HELP_INDEX_CACHE.get(key)
        if cached is not None:
            return cached
        files = _help_files(root)
        signature = _help_signature(root, files)
        cache_file = None
        if work_dir:
            try:
                cache_file = Path(work_dir) / ".cst_mcp_cache" / f"help_index_{signature[:16]}.json"
                if cache_file.is_file():
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    if data.get("signature") == signature:
                        _HELP_INDEX_CACHE[key] = data["entries"]
                        return data["entries"]
            except (OSError, ValueError, KeyError, TypeError):
                logger.debug("help index cache unreadable", exc_info=True)
        entries = []
        for path in files:
            try:
                title, text = _html_to_text(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:  # noqa: BLE001 - one broken page must not kill search
                logger.debug("could not index %s", path, exc_info=True)
                continue
            entries.append({"topic": path.relative_to(root).as_posix(), "title": title, "text": text})
        _HELP_INDEX_CACHE[key] = entries
        if cache_file is not None:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache_file.with_suffix(".tmp")
                tmp.write_text(json.dumps({"signature": signature, "entries": entries}), encoding="utf-8")
                tmp.replace(cache_file)
            except OSError:
                logger.debug("help index cache not written", exc_info=True)
        return entries


def _snippet(text: str, words: list[str], width: int = 110) -> str:
    low = text.lower()
    found = [(low.find(w), len(w)) for w in words if w in low]
    if not found:
        return re.sub(r"\s+", " ", text[: 2 * width]).strip()
    # Anchor on the longest (most specific) word's first occurrence.
    anchor = max(found, key=lambda t: t[1])[0]
    start, end = max(0, anchor - width), min(len(text), anchor + width)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("..." if start else "") + snippet + ("..." if end < len(text) else "")


def _search_index(index: list[dict], words: list[str], query: str) -> list[dict]:
    phrase = re.sub(r"\s+", " ", query.strip().lower())
    scored = []
    for entry in index:
        head = (entry["topic"] + " " + entry["title"]).lower()
        body = entry["text"].lower()
        in_head = [w in head for w in words]
        if not all(h or (w in body) for w, h in zip(words, in_head)):
            continue
        head_hits = sum(in_head)
        tier = 0 if all(in_head) else (1 if head_hits else 2)
        body_count = sum(body.count(w) for w in words)
        phrase_hit = len(words) > 1 and phrase in body
        key = (tier, -head_hits, not phrase_hit, -body_count, len(entry["topic"]), entry["topic"])
        scored.append(
            (
                key,
                {
                    "topic": entry["topic"],
                    "title": entry["title"],
                    "match": "title" if tier == 0 else ("title+body" if tier == 1 else "body"),
                    "body_hits": body_count,
                    "snippet": _snippet(entry["text"], words),
                },
            )
        )
    scored.sort(key=lambda item: item[0])
    return [item[1] for item in scored]


async def handle(name, arguments, client):
    if name in {"cst_search_help", "cst_read_help"}:
        if not client.config.cst_path:
            return err("CST installation not found; set CST_PATH")
        root = (Path(client.config.cst_path) / "Online Help").resolve()
        if name == "cst_search_help":
            words = re.findall(r"[a-z0-9_]+", arguments["query"].lower())
            if not words:
                return err("Enter a Python/VBA topic name")
            index = _help_index(root, getattr(client.config, "work_dir", None))
            results = _search_index(index, words, arguments["query"])
            limit = arguments.get("limit", 15)
            return as_json(
                {
                    "status": "ok",
                    "installation": str(client.config.cst_path),
                    "query_words": words,
                    "indexed_topics": len(index),
                    "count": len(results),
                    "topics": [r["topic"] for r in results[:limit]],
                    "results": results[:limit],
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
    # The session's own open project may be read with allow_interactive=True
    # once the solver is verified idle (same contract as CSTClient.get_result).
    own_project = False
    try:
        own_project = bool(client.project_path) and Path(client.project_path).resolve() == path
    except (OSError, TypeError, ValueError):
        own_project = False
    if own_project:
        if client.is_solver_running(timeout_s=5) is not False:
            return err("Project is busy or solver state is unknown")
    if name == "cst_list_saved_results":
        try:
            import cst.results

            module = cst.results.ProjectFile(str(path), allow_interactive=own_project).get_3d()
            tree_items = list(module.get_tree_items())
        except Exception as exc:  # cst.results raises UserWarning/RuntimeError etc.
            hint = (
                " The project is open in another CST instance; close it there or use the"
                " session that opened it." if not own_project and "interactive" in str(exc).lower() else ""
            )
            return err(f"Could not open saved results: {type(exc).__name__}: {exc}.{hint}")
        paths = [
            str(p)
            for p in tree_items
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
        try:
            data = format_curve(
                read_curve(
                    str(path),
                    arguments["tree_path"],
                    arguments.get("run_id", 0),
                    allow_interactive=own_project,
                ),
                arguments.get("format", "real_imag"),
            )
        except Exception as exc:
            return err(f"Could not read saved result: {type(exc).__name__}: {exc}")
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


from cst_mcp.vba_safety import guard_handler as _guard_handler  # noqa: E402

handle = _guard_handler(TOOLS, handle)
