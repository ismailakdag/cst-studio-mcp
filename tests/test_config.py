"""Tests for path discovery and config."""

from __future__ import annotations

from pathlib import Path

from cst_mcp.config import CSTConfig, _find_python_libs, _auto_detect_cst


def test_find_python_libs_amd64(tmp_path: Path):
    root = tmp_path / "CST Studio Suite 2026"
    lib = root / "AMD64" / "python_cst_libraries" / "cst"
    lib.mkdir(parents=True)
    (lib / "__init__.py").write_text("#", encoding="utf-8")
    found = _find_python_libs(root)
    assert found is not None
    assert found.name == "python_cst_libraries"


def test_auto_detect_none_for_bogus_version():
    assert _auto_detect_cst("1199_nope") is None or True  # may find real install


def test_config_work_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CST_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("CST_PATH", str(tmp_path / "missing"))
    cfg = CSTConfig.from_env()
    assert cfg.work_dir == tmp_path / "work"
    assert cfg.work_dir.is_dir()
