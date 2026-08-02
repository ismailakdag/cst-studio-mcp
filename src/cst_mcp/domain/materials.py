"""Material database loaded from packaged JSON files."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent.parent / "data" / "materials"


@lru_cache(maxsize=1)
def _load_all() -> dict[str, list[dict[str, Any]]]:
    categories: dict[str, list[dict[str, Any]]] = {}
    mapping = {
        "metals": "common_metals.json",
        "dielectrics": "common_dielectrics.json",
        "substrates": "substrates.json",
        "ferrites": "ferrites.json",
    }
    for cat, fname in mapping.items():
        path = _DATA / fname
        if not path.is_file():
            categories[cat] = []
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Support either list or {materials: [...]} or dict of name->props
        if isinstance(raw, list):
            categories[cat] = raw
        elif isinstance(raw, dict):
            if "materials" in raw and isinstance(raw["materials"], list):
                categories[cat] = raw["materials"]
            elif cat in raw and isinstance(raw[cat], list):
                # e.g. substrates.json → {"substrates": [ ... ]}
                categories[cat] = raw[cat]
            elif any(isinstance(v, list) for v in raw.values()):
                # first list-valued key
                for v in raw.values():
                    if isinstance(v, list):
                        categories[cat] = v
                        break
                else:
                    categories[cat] = []
            else:
                items = []
                for name, props in raw.items():
                    if isinstance(props, dict):
                        items.append({"name": name, **props})
                    else:
                        items.append({"name": name, "value": props})
                categories[cat] = items
        else:
            categories[cat] = []
    return categories


def list_categories() -> list[str]:
    return list(_load_all().keys())


def list_materials(category: str | None = None) -> dict[str, Any]:
    data = _load_all()
    if category is None or category in ("all", "*"):
        return {"status": "ok", "categories": {k: len(v) for k, v in data.items()}, "materials": data}
    if category not in data:
        return {
            "status": "error",
            "message": f"Unknown category '{category}'. Use one of: {list(data)}",
        }
    return {"status": "ok", "category": category, "materials": data[category]}


def get_material(name: str) -> dict[str, Any] | None:
    needle = name.strip().lower()
    for cat, items in _load_all().items():
        for item in items:
            if str(item.get("name", "")).lower() == needle:
                return {"category": cat, **item}
    return None
