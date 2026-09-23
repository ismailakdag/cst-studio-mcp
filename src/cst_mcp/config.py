"""Configuration and CST installation discovery.

Designed for real Windows installs (any drive letter), not only
``C:\\Program Files``.  Locates both ``AMD64`` and legacy ``LinuxAMD64``
Python library layouts used by CST 2024–2026.
"""

from __future__ import annotations

import logging
import os
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_VERSION = "2026"
CONNECT_MODES = frozenset({"auto", "manual", "disabled"})

# Tool categories selectable through ``CST_TOOLSETS``. Each maps to one tool
# module (``antenna`` -> ``antenna_templates``, ``boundaries`` also answers to
# ``setup``).
TOOLSET_CATEGORIES: tuple[str, ...] = (
    "connection",
    "official",
    "project",
    "geometry",
    "boolean",
    "transforms",
    "materials",
    "ports",
    "boundaries",
    "mesh",
    "solvers",
    "simulation",
    "results",
    "import_export",
    "parameters",
    "optimization",
    "diagnostics",
    "antenna",
    "arrays",
    "pcb",
    "matching",
    "vba",
    "workflows",
    "drawing",
    "figures",
)
TOOLSET_ALIASES: dict[str, frozenset[str]] = {
    "all": frozenset(TOOLSET_CATEGORIES),
    # Enough for a full design loop: open, tweak parameters, run, read results,
    # and diagnose/dismiss CST dialogs. Drawing/figure output stays opt-in.
    "core": frozenset(
        {
            "connection",
            "official",
            "project",
            "workflows",
            "simulation",
            "results",
            "parameters",
            "diagnostics",
        }
    ),
    "setup": frozenset({"boundaries"}),
    "antenna_templates": frozenset({"antenna"}),
    "import": frozenset({"import_export"}),
    "export": frozenset({"import_export"}),
}
# Present regardless of CST_TOOLSETS so a client can always inspect and manage
# the CST session.
ALWAYS_ENABLED_TOOLS = frozenset({"cst_connect", "cst_disconnect", "cst_connection_status"})


def parse_toolsets(raw: str | None) -> frozenset[str] | None:
    """Parse ``CST_TOOLSETS`` into enabled categories; ``None`` means all tools.

    Names are comma-separated and case-insensitive (``-`` is read as ``_``).
    Unknown names are logged and ignored. If nothing valid remains, every
    tool stays enabled so a typo cannot silently hide the catalog.
    """
    if raw is None or not raw.strip():
        return None
    selected: set[str] = set()
    unknown: list[str] = []
    for item in raw.split(","):
        key = item.strip().lower().replace("-", "_")
        if not key:
            continue
        if key in TOOLSET_ALIASES:
            selected |= TOOLSET_ALIASES[key]
        elif key in TOOLSET_CATEGORIES:
            selected.add(key)
        else:
            unknown.append(item.strip())
    if unknown:
        logger.warning(
            "Ignoring unknown CST_TOOLSETS name(s): %s. Valid: %s, aliases: %s",
            ", ".join(unknown),
            ", ".join(TOOLSET_CATEGORIES),
            ", ".join(sorted(TOOLSET_ALIASES)),
        )
    if not selected:
        logger.warning("CST_TOOLSETS=%r selects no valid toolset; enabling all tools", raw)
        return None
    if selected >= set(TOOLSET_CATEGORIES):
        return None
    return frozenset(selected | {"connection"})


@dataclass
class CSTConfig:
    """Runtime configuration for the MCP server."""

    cst_path: Path | None = None
    python_lib_path: Path | None = None
    work_dir: Path = field(default_factory=lambda: Path.home() / "cst_projects")
    version: str = DEFAULT_VERSION
    log_level: str = "INFO"
    quiet_mode: bool = True
    connect_mode: str = "manual"
    work_dir_error: str | None = None
    # Enabled tool categories from CST_TOOLSETS; None exposes every tool.
    toolsets: frozenset[str] | None = None

    @classmethod
    def from_env(cls) -> CSTConfig:
        version = os.environ.get("CST_VERSION", DEFAULT_VERSION)
        work_raw = os.environ.get("CST_WORK_DIR") or str(Path.home() / "cst_projects")
        work_dir = Path(work_raw).expanduser()

        cst_raw = os.environ.get("CST_PATH")
        cst_path = Path(cst_raw) if cst_raw else _auto_detect_cst(version)

        python_lib = None
        if cst_path:
            python_lib = _find_python_libs(cst_path)
            if python_lib:
                _ensure_on_sys_path(python_lib)

        work_dir_error = None
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # A bad project directory must not prevent the MCP initialize
            # handshake. Tools that need the directory will still report the
            # concrete filesystem error when called.
            work_dir_error = str(exc)
            logger.warning("CST work directory is unavailable: %s", exc)

        quiet = os.environ.get("CST_QUIET", "1").strip().lower() not in {"0", "false", "no"}
        log_level = os.environ.get("CST_LOG_LEVEL", "INFO")
        connect_mode = os.environ.get("CST_CONNECT_MODE", "manual").strip().lower()
        if connect_mode not in CONNECT_MODES:
            logger.warning(
                "Invalid CST_CONNECT_MODE=%r; using 'manual' for safe startup",
                connect_mode,
            )
            connect_mode = "manual"
        toolsets = parse_toolsets(os.environ.get("CST_TOOLSETS"))

        cfg = cls(
            cst_path=cst_path,
            python_lib_path=python_lib,
            work_dir=work_dir,
            version=version,
            log_level=log_level,
            quiet_mode=quiet,
            connect_mode=connect_mode,
            work_dir_error=work_dir_error,
            toolsets=toolsets,
        )
        logger.info(
            "CST config: path=%s libs=%s work=%s version=%s toolsets=%s",
            cfg.cst_path,
            cfg.python_lib_path,
            cfg.work_dir,
            cfg.version,
            "all" if cfg.toolsets is None else ",".join(sorted(cfg.toolsets)),
        )
        return cfg

    @property
    def cst_available(self) -> bool:
        """True if the official ``cst`` Python package can be imported."""
        if self.connect_mode == "disabled":
            return False
        try:
            import cst.interface  # noqa: F401

            return True
        except Exception:  # Import may fail with a DLL/ABI error, not ImportError.
            logger.debug("CST Python package is unavailable", exc_info=True)
            return False

    @property
    def connect_on_startup(self) -> bool:
        """Whether the MCP process should attach to or launch CST at startup."""
        return self.connect_mode == "auto"


def _windows_drive_letters() -> list[str]:
    if sys.platform != "win32":
        return []
    present: list[str] = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.isdir(root):
            present.append(letter)
    return present


def _auto_detect_cst(version: str) -> Path | None:
    """Search common install locations on all available drives."""
    # Prefer newer years if version folder missing: try requested first, then nearby
    years = [version]
    try:
        y = int(version)
        years.extend(str(y + d) for d in (-1, 1, -2, 2) if 2018 <= y + d <= 2035)
    except ValueError:
        pass

    candidates: list[Path] = []
    for year in years:
        for name in (f"CST Studio Suite {year}", f"CST STUDIO SUITE {year}"):
            for letter in _windows_drive_letters() or ["C"]:
                candidates.extend(
                    [
                        Path(f"{letter}:/Program Files") / name,
                        Path(f"{letter}:/Program Files (x86)") / name,
                        Path(f"{letter}:/") / name,
                    ]
                )
            candidates.append(Path.home() / name)

    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if path.is_dir():
            logger.info("Auto-detected CST at %s", path)
            return path
    return None


def _find_python_libs(cst_path: Path) -> Path | None:
    """Return path to ``python_cst_libraries`` under a CST install."""
    relative = [
        Path("AMD64") / "python_cst_libraries",
        Path("LinuxAMD64") / "python_cst_libraries",  # older docs / dual layouts
        Path("python_cst_libraries"),
    ]
    for rel in relative:
        candidate = cst_path / rel
        if (candidate / "cst").is_dir() or (candidate / "cst").is_file():
            return candidate
        # package may be a namespace dir without trailing check
        if candidate.is_dir() and any(candidate.glob("cst*")):
            return candidate
    return None


def _ensure_on_sys_path(lib_path: Path) -> None:
    """Prepend CST Python libs so ``import cst`` works in this process."""
    s = str(lib_path.resolve())
    if s not in sys.path:
        sys.path.insert(0, s)
        logger.debug("Added to sys.path: %s", s)
    # Also expose via PYTHONPATH for child processes
    existing = os.environ.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if s not in parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([s, *parts])
