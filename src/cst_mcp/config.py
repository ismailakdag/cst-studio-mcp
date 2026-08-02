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


@dataclass
class CSTConfig:
    """Runtime configuration for the MCP server."""

    cst_path: Path | None = None
    python_lib_path: Path | None = None
    work_dir: Path = field(default_factory=lambda: Path.home() / "cst_projects")
    version: str = DEFAULT_VERSION
    log_level: str = "INFO"
    quiet_mode: bool = True

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

        work_dir.mkdir(parents=True, exist_ok=True)

        quiet = os.environ.get("CST_QUIET", "1").strip().lower() not in {"0", "false", "no"}
        log_level = os.environ.get("CST_LOG_LEVEL", "INFO")

        cfg = cls(
            cst_path=cst_path,
            python_lib_path=python_lib,
            work_dir=work_dir,
            version=version,
            log_level=log_level,
            quiet_mode=quiet,
        )
        logger.info(
            "CST config: path=%s libs=%s work=%s version=%s",
            cfg.cst_path,
            cfg.python_lib_path,
            cfg.work_dir,
            cfg.version,
        )
        return cfg

    @property
    def cst_available(self) -> bool:
        """True if the official ``cst`` Python package can be imported."""
        try:
            import cst.interface  # noqa: F401

            return True
        except ImportError:
            return False


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
    names = [
        f"CST Studio Suite {version}",
        f"CST STUDIO SUITE {version}",
    ]
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
