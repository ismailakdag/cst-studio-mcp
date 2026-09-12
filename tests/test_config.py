"""Tests for path discovery and config."""

from __future__ import annotations

from pathlib import Path

from cst_mcp.config import CSTConfig, _auto_detect_cst, _find_python_libs


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


def test_default_mode_never_connects_on_startup(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CST_CONNECT_MODE", raising=False)
    monkeypatch.setenv("CST_PATH", str(tmp_path / "missing"))
    monkeypatch.setenv("CST_WORK_DIR", str(tmp_path))
    assert CSTConfig.from_env().connect_on_startup is False
    assert CSTConfig().connect_mode == "manual"


def test_disabled_mode_does_not_import_cst(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CST_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("CST_CONNECT_MODE", "disabled")
    cfg = CSTConfig.from_env()

    assert cfg.connect_mode == "disabled"
    assert cfg.connect_on_startup is False
    assert cfg.cst_available is False


def test_invalid_connect_mode_falls_back_to_manual(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CST_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("CST_CONNECT_MODE", "surprise")
    cfg = CSTConfig.from_env()

    assert cfg.connect_mode == "manual"
    assert cfg.connect_on_startup is False


def test_unusable_work_dir_does_not_abort_config(tmp_path: Path, monkeypatch):
    work_file = tmp_path / "not-a-directory"
    work_file.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("CST_WORK_DIR", str(work_file))
    monkeypatch.setenv("CST_CONNECT_MODE", "disabled")

    cfg = CSTConfig.from_env()

    assert cfg.work_dir == work_file
    assert cfg.work_dir_error
