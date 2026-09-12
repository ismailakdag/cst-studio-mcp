"""Build the deploy-ready static site without network or Node.js dependencies.

The landing page itself is authored in ``site/``. This script refreshes the
public documentation, presentation, and locally hosted font assets from their
canonical repository sources. Only explicit allowlists are copied so local
experiments, machine paths, and development files cannot leak into a deploy.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DOCS = ROOT / "docs"
PRESENTATION = ROOT / "presentation"

PUBLIC_DOC_FILES = (
    "index.html",
    "README.md",
    "RELIABILITY_REVIEW.md",
    "TOOLS.md",
    "tools.json",
    "VBA_ALIGNMENT.md",
)
PUBLIC_PRESENTATION_FILES = (
    "index.html",
    "index-en.html",
    "inter-OFL.txt",
    "manifest.json",
    "project.json",
    "project-en.json",
    "README.md",
    "source-serif-OFL.txt",
)
AUTHORED_SITE_FILES = (
    "index.html",
    "en/index.html",
    "styles.css",
    "app.js",
    "favicon.svg",
    "robots.txt",
    "sitemap.xml",
    "vercel.json",
)

FONT_FACE_RE = re.compile(
    r"@font-face\{font-family:'(?P<family>Source Serif 4|Inter)';"
    r"src:url\('data:font/woff2;base64,(?P<data>[^']+)'\)"
    r" format\('woff2'\);font-weight:(?P<weight>[^;]+);font-display:swap;"
    r"unicode-range:(?P<range>[^}]+)\}"
)


def reset_generated_dir(path: Path) -> None:
    """Replace a generated directory after guarding its exact site location."""
    resolved = path.resolve()
    if resolved.parent != SITE.resolve():
        raise RuntimeError(f"Refusing to replace unexpected directory: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def copy_allowlist(
    source: Path,
    target: Path,
    names: tuple[str, ...],
    *,
    optional: tuple[str, ...] = (),
) -> None:
    reset_generated_dir(target)
    for name in names:
        source_file = source / name
        if not source_file.is_file():
            if name in optional:
                continue
            raise FileNotFoundError(f"Required public source is missing: {source_file}")
        shutil.copy2(source_file, target / name)


def set_presentation_base() -> None:
    """Make presentation-relative assets resolve below the deployed subdirectory."""
    for path in (SITE / "presentation").glob("index*.html"):
        html = path.read_text(encoding="utf-8")
        if re.search(r"<base\s", html, flags=re.IGNORECASE):
            continue
        updated, count = re.subn(
            r"(<head(?:\s[^>]*)?>)",
            r'\1\n  <base href="/presentation/">',
            html,
            count=1,
            flags=re.IGNORECASE,
        )
        if count != 1:
            raise RuntimeError(f"Could not add presentation base URL: {path}")
        path.write_text(updated, encoding="utf-8", newline="")
    manifest_path = SITE / "presentation/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_files_sha256"] = manifest["files_sha256"]
    manifest["publication_transform"] = "Added /presentation/ base URL for deployed navigation."
    manifest["files_sha256"] = {
        name: hashlib.sha256((manifest_path.parent / name).read_bytes()).hexdigest()
        for name in manifest["source_files_sha256"]
        if (manifest_path.parent / name).is_file()
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def extract_fonts() -> None:
    presentation_html = (PRESENTATION / "index.html").read_text(encoding="utf-8")
    matches = list(FONT_FACE_RE.finditer(presentation_html))
    if len(matches) != 4:
        raise RuntimeError(f"Expected four embedded font subsets; found {len(matches)}")

    font_dir = SITE / "assets" / "fonts"
    assets_dir = SITE / "assets"
    reset_generated_dir(assets_dir)
    font_dir.mkdir(parents=True)

    subset_counts: dict[str, int] = {}
    css_blocks: list[str] = []
    for match in matches:
        family = match.group("family")
        slug = "source-serif-4" if family == "Source Serif 4" else "inter"
        subset_counts[slug] = subset_counts.get(slug, 0) + 1
        subset = "latin" if subset_counts[slug] == 1 else "latin-ext"
        filename = f"{slug}-{subset}.woff2"
        payload = base64.b64decode(match.group("data"), validate=True)
        (font_dir / filename).write_bytes(payload)
        css_blocks.append(
            "@font-face {\n"
            f"  font-family: '{family}';\n"
            f"  src: url('./{filename}') format('woff2');\n"
            f"  font-weight: {match.group('weight')};\n"
            "  font-style: normal;\n"
            "  font-display: swap;\n"
            f"  unicode-range: {match.group('range')};\n"
            "}"
        )

    (font_dir / "fonts.css").write_text(
        "\n\n".join(css_blocks) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    shutil.copy2(PRESENTATION / "inter-OFL.txt", font_dir / "LICENSE-Inter.txt")
    shutil.copy2(
        PRESENTATION / "source-serif-OFL.txt",
        font_dir / "LICENSE-Source-Serif-4.txt",
    )


def validate_public_text() -> None:
    forbidden = (
        re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
        re.compile(r"[A-Za-z]:\\codex-cst-studio", re.IGNORECASE),
        re.compile(r"(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*['\"][^'\"]+", re.IGNORECASE),
    )
    for path in SITE.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".woff2", ".png", ".webp", ".ico"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden:
            if pattern.search(text):
                raise RuntimeError(f"Potential private value in public output: {path}")


def write_manifest() -> None:
    manifest_path = SITE / "build-manifest.json"
    entries: dict[str, str] = {}
    for path in sorted(SITE.rglob("*")):
        if path.is_file() and path != manifest_path:
            relative = path.relative_to(SITE).as_posix()
            entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps({"sha256": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    missing = [name for name in AUTHORED_SITE_FILES if not (SITE / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing authored site files: {', '.join(missing)}")

    copy_allowlist(DOCS, SITE / "docs", PUBLIC_DOC_FILES)
    copy_allowlist(
        PRESENTATION,
        SITE / "presentation",
        PUBLIC_PRESENTATION_FILES,
        optional=("index-en.html",),
    )
    set_presentation_base()
    extract_fonts()
    validate_public_text()
    write_manifest()
    print(f"Built static site at {SITE}")


if __name__ == "__main__":
    main()
