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
        import re
        if self.has_project and re.search(r"(?im)^\s*(?:Debug\.Print|MsgBox)\s+", vba_code):
            return self.capture_vba_output(vba_code)
        result = self.run_history(vba_code, label=history_label)
        # Normalize keys expected by older tools
        if result.get("status") == "offline" and "vba" not in result:
            result["vba"] = vba_code
        if result.get("status") == "executed" and "vba" not in result:
            # some tools echo vba in offline only; keep parity
            pass
        return result

    @staticmethod
    def build_query_vba(fields: list[tuple[str, str]]) -> str:
        """VBA printing ``key<TAB>value`` per expression, each isolated by
        ``On Error Resume Next`` so one unavailable value (e.g. no mesh yet)
        does not abort the whole query."""
        lines = ["Dim mcpValue As String", "On Error Resume Next"]
        for key, expr in fields:
            lines += [
                "Err.Clear",
                f"mcpValue = CStr({expr})",
                "If Err.Number = 0 Then",
                f'  Debug.Print "{key}" & vbTab & mcpValue',
                "Else",
                f'  Debug.Print "{key}.error" & vbTab & Err.Description',
                "End If",
            ]
        return "\n".join(lines)

    def query_values(self, fields: list[tuple[str, str]]) -> dict:
        """Read-only VBA query via output capture; never writes model history.

        Returns ``{"status": "ok", "values": {...}, "errors": {...}}``.
        """
        script = self.build_query_vba(fields)
        if not self.connected or not self.has_project:
            return {"status": "offline", "vba": script}
        result = self.capture_vba_output(script)
        if result.get("status") != "ok":
            return {**result, "vba": script}
        values: dict[str, str] = {}
        errors: dict[str, str] = {}
        for line in str(result.get("output", "")).splitlines():
            key, sep, value = line.rstrip("\r").partition("\t")
            if not sep:
                continue
            if key.endswith(".error"):
                errors[key[: -len(".error")]] = value
            else:
                values[key] = value
        return {"status": "ok", "values": values, "errors": errors,
                "source": "VBA query via output capture (no model history)"}

    def execute_vba_silent(self, vba_code: str, *, history_fallback: bool = True) -> dict:
        return self.run_vba_silent(vba_code, history_fallback=history_fallback)

    def get_result(self, tree_path: str, run_id: int = 0) -> dict:
        """Read a saved 1D curve without changing GUI plot settings."""
        from cst_mcp.execution.curves import read_curve

        if not self.has_project or not self.project_path:
            return {"status": "error", "message": "Open and save a project before reading results"}
        running = self.is_solver_running(timeout_s=5)
        if running is not False:
            return {"status": "busy", "running": running,
                    "message": "Results are not read while the solver is active or its state is unknown"}
        if not tree_path.startswith(("1D Results\\", "0D Results\\")):
            return {"status": "error", "code": "requires_dedicated_field_export",
                    "message": "This tree item is not a 1D curve. Use a dedicated field/farfield export; no scalar curve is fabricated.",
                    "tree_path": tree_path}
        return read_curve(self.project_path, tree_path, run_id, allow_interactive=True)

    def read_project_messages(self) -> dict:
        return self.get_cst_messages()

    def export_result(self, tree_path: str, filepath: str) -> dict:
        """Legacy optimization contract: frequency in GHz and reflection dB."""
        from pathlib import Path
        from cst_mcp.execution.curves import format_curve, frequency_scale

        result = self.get_result(tree_path)
        if result.get("status") != "ok":
            return result
        try:
            scale = frequency_scale(result["xlabel"]) / 1e9
            curve = format_curve(result, "db")
            # Optimization cannot use undefined dB points as finite measurements.
            if any(y is None for y in curve["y"]):
                return {"status": "error", "message": "Zero-amplitude samples have undefined finite dB; inspect raw complex data"}
            out = Path(filepath)
            out.parent.mkdir(parents=True, exist_ok=True)
            text = "Frequency / GHz    S / dB\n" + "\n".join(
                f"{x * scale:.17g} {y:.17g}" for x, y in zip(result["x"], curve["y"])) + "\n"
            out.write_text(text, encoding="utf-8")
            return {"status": "exported", "path": str(out), "tree_path": tree_path, "source": "cst.results", "format": "db"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

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

    def status(self) -> dict[str, Any]:
        base = super().status()
        base["dialog_watcher"] = (
            CSTClient._dialog_watcher is not None and CSTClient._dialog_watcher.running
        )
        return base
