"""Compatibility client: CSTSession + dialog APIs used by ported tools.

Tools from the original mcp-cst-studio package expect a ``CSTClient`` with
``execute_vba``, ``connected``, dialog helpers, etc.  This module provides
that surface on top of our Python-first ``CSTSession``.
"""

from __future__ import annotations

import logging
from typing import Any

from cst_mcp.config import CSTConfig
from cst_mcp.dialog_handler import DialogWatcher, dismiss_cst_dialogs, find_cst_dialogs
from cst_mcp.session import CSTSession

logger = logging.getLogger(__name__)


class CSTClient(CSTSession):
    """Session + legacy method names expected by full tool modules."""

    _dialog_watcher: DialogWatcher | None = None

    def __init__(self, config: CSTConfig | None = None) -> None:
        super().__init__(config=config)

    # -- aliases used throughout ported tools ---------------------------------

    @property
    def connected(self) -> bool:
        return self.is_connected

    @property
    def _config(self) -> CSTConfig:  # type: ignore[override]
        return self.config

    def execute_vba(self, vba_code: str, history_label: str | None = None) -> dict:
        """History VBA execution (connected) or offline script return."""
        result = self.run_history(vba_code, label=history_label)
        # Normalize keys expected by older tools
        if result.get("status") == "offline" and "vba" not in result:
            result["vba"] = vba_code
        if result.get("status") == "executed" and "vba" not in result:
            # some tools echo vba in offline only; keep parity
            pass
        return result

    def execute_vba_silent(self, vba_code: str) -> dict:
        return self.run_vba_silent(vba_code)

    # -- dialog management (from original package) ----------------------------

    def dismiss_dialogs(self) -> dict:
        dismissed = dismiss_cst_dialogs()
        if dismissed:
            return {"status": "dismissed", "count": len(dismissed), "dialogs": dismissed}
        return {"status": "ok", "message": "No CST dialogs found."}

    def read_dialogs(self) -> dict:
        dialogs = find_cst_dialogs()
        for d in dialogs:
            d.pop("hwnd", None)
        if dialogs:
            return {"status": "found", "count": len(dialogs), "dialogs": dialogs}
        return {"status": "ok", "message": "No CST dialogs found."}

    def start_dialog_watcher(self) -> dict:
        if CSTClient._dialog_watcher is not None and CSTClient._dialog_watcher.running:
            return {"status": "already_running"}
        CSTClient._dialog_watcher = DialogWatcher(poll_interval=0.5)
        CSTClient._dialog_watcher.start()
        return {"status": "started"}

    def stop_dialog_watcher(self) -> dict:
        if CSTClient._dialog_watcher is None or not CSTClient._dialog_watcher.running:
            return {"status": "not_running"}
        log = CSTClient._dialog_watcher.get_log()
        CSTClient._dialog_watcher.stop()
        return {"status": "stopped", "dismissed_count": len(log), "log": log}

    def get_dialog_log(self) -> dict:
        if CSTClient._dialog_watcher is None:
            return {"status": "not_running", "log": []}
        log = CSTClient._dialog_watcher.get_log()
        return {"status": "ok", "count": len(log), "log": log}

    # -- project helpers with dialog safety -----------------------------------

    def new_project(self, path: str, project_type: str = "MWS") -> dict[str, Any]:
        self.start_dialog_watcher()
        try:
            return super().new_project(path, project_type)
        finally:
            self.stop_dialog_watcher()

    def save_project(self, path: str | None = None) -> dict[str, Any]:
        self.start_dialog_watcher()
        try:
            return super().save_project(path)
        finally:
            self.stop_dialog_watcher()

    def run_history(self, vba: str, label: str | None = None) -> dict[str, Any]:
        """Execute with background dialog watcher (connected mode)."""
        if self.is_connected and self.has_project:
            watcher = DialogWatcher(poll_interval=0.5)
            watcher.start()
            try:
                result = super().run_history(vba, label=label)
            finally:
                watcher.stop()
            log = watcher.get_log()
            if log:
                result = dict(result)
                result["dialogs_dismissed"] = len(log)
                result["dialog_log"] = log
            return result
        return super().run_history(vba, label=label)

    def status(self) -> dict[str, Any]:
        base = super().status()
        base["dialog_watcher"] = (
            CSTClient._dialog_watcher is not None and CSTClient._dialog_watcher.running
        )
        return base
