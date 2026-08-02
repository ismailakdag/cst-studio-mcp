"""CST Design Environment session manager.

Python-first connection lifecycle.  Geometry and most modeling commands still
execute as history VBA (CST architecture), but project control, solver run,
parameter store/rebuild, and result export use the official Python API.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from cst_mcp.config import CSTConfig
from cst_mcp.execution.results_reader import ResultsReader

logger = logging.getLogger(__name__)


class SessionError(RuntimeError):
    """Raised for session/project state problems."""


class CSTSession:
    """Manages one Design Environment connection and the active project."""

    _history_seq: int = 0

    def __init__(self, config: CSTConfig | None = None) -> None:
        self.config = config or CSTConfig.from_env()
        self._de: Any = None
        self._project: Any = None
        self._project_path: str | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mode(self) -> str:
        return "connected" if self.is_connected else "offline"

    @property
    def is_connected(self) -> bool:
        return self._de is not None

    @property
    def has_project(self) -> bool:
        return self._project is not None

    @property
    def project_path(self) -> str | None:
        return self._project_path

    @property
    def model3d(self) -> Any:
        if self._project is None:
            raise SessionError("No project open")
        return self._project.model3d

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> dict[str, Any]:
        """Connect to a running CST or launch a new Design Environment."""
        if not self.config.cst_available:
            hint = (
                "CST Python library not importable. "
                f"cst_path={self.config.cst_path!s}, "
                f"python_lib_path={self.config.python_lib_path!s}. "
                "Set CST_PATH and ensure AMD64/python_cst_libraries is on PYTHONPATH."
            )
            self._last_error = hint
            return {"status": "offline", "message": hint}

        try:
            import cst.interface  # type: ignore
        except ImportError as exc:
            self._last_error = str(exc)
            return {"status": "offline", "message": f"import cst.interface failed: {exc}"}

        try:
            # Preferred modern API
            if hasattr(cst.interface.DesignEnvironment, "connect_to_any_or_new"):
                self._de = cst.interface.DesignEnvironment.connect_to_any_or_new()
                msg = "Connected via connect_to_any_or_new()"
            else:
                running = []
                if hasattr(cst.interface, "running_design_environments"):
                    running = list(cst.interface.running_design_environments() or [])
                if running:
                    self._de = cst.interface.DesignEnvironment.connect(running[0])
                    msg = f"Connected to running DE (pid={running[0]})"
                else:
                    self._de = cst.interface.DesignEnvironment()
                    msg = "Launched new Design Environment"

            if self.config.quiet_mode and hasattr(self._de, "set_quiet_mode"):
                try:
                    self._de.set_quiet_mode(True)
                except Exception:  # noqa: BLE001
                    logger.debug("set_quiet_mode failed", exc_info=True)

            # Attach to already-open project if any
            open_projects = []
            try:
                open_projects = list(self._de.get_open_projects() or [])
            except Exception:  # noqa: BLE001
                pass
            if open_projects and self._project is None:
                self._project = open_projects[0]
                self._project_path = self._safe_filename(self._project)

            return {
                "status": "connected",
                "message": msg,
                "open_projects": len(open_projects),
                "project_path": self._project_path,
                "cst_path": str(self.config.cst_path) if self.config.cst_path else None,
                "python_lib_path": (
                    str(self.config.python_lib_path) if self.config.python_lib_path else None
                ),
            }
        except Exception as exc:  # noqa: BLE001
            self._de = None
            self._last_error = str(exc)
            logger.exception("CST connect failed")
            return {"status": "offline", "message": f"Connect failed: {exc}"}

    def disconnect(self) -> dict[str, Any]:
        if self._de is not None:
            try:
                self._de.close()
            except Exception:  # noqa: BLE001
                pass
        self._de = None
        self._project = None
        self._project_path = None
        return {"status": "disconnected"}

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    _FACTORIES = {
        "MWS": "new_mws",
        "EMS": "new_ems",
        "PS": "new_ps",
        "MPS": "new_mps",
        "CS": "new_cs",
        "DS": "new_ds",
        "PCB": "new_pcbs",
        "PCBS": "new_pcbs",
        "FD3D": "new_fd3d",
    }

    def new_project(self, path: str, project_type: str = "MWS") -> dict[str, Any]:
        path = str(Path(path).expanduser())
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        if not self.is_connected:
            return {
                "status": "offline",
                "path": path,
                "type": project_type,
                "message": "Not connected — project not created in CST.",
            }

        try:
            # Prefer a fresh unique path if target already exists (CST often refuses overwrite)
            target = Path(path)
            if target.exists():
                alt = target.with_name(f"{target.stem}_{int(time.time())}{target.suffix}")
                path = str(alt)

            factory_name = self._FACTORIES.get(project_type.upper(), "new_mws")
            factory = getattr(self._de, factory_name, self._de.new_mws)
            project = factory()
            try:
                project.save(path)
            except Exception as save_exc:
                # Last resort: unique suffix
                stem = Path(path)
                alt = stem.with_name(f"{stem.stem}_{int(time.time())}{stem.suffix}")
                try:
                    project.save(str(alt))
                    path = str(alt)
                except Exception:
                    try:
                        project.close()
                    except Exception:  # noqa: BLE001
                        pass
                    return {
                        "status": "error",
                        "message": f"Failed to save project: {save_exc}",
                        "path": path,
                    }
            self._project = project
            self._project_path = path
            return {"status": "created", "path": path, "type": project_type.upper()}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def open_project(self, path: str) -> dict[str, Any]:
        path = str(Path(path).expanduser())
        if not self.is_connected:
            self._project_path = path
            return {"status": "offline", "path": path, "message": "Path recorded offline only."}

        try:
            self._project = self._de.open_project(path)
            self._project_path = path
            return {"status": "opened", "path": path}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def save_project(self, path: str | None = None) -> dict[str, Any]:
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        save_path = path or self._project_path
        try:
            if save_path:
                self._project.save(save_path)
                self._project_path = save_path
            else:
                self._project.save()
            return {"status": "saved", "path": self._project_path}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def close_project(self) -> dict[str, Any]:
        if self._project is not None:
            try:
                self._project.close()
            except Exception:  # noqa: BLE001
                pass
        self._project = None
        self._project_path = None
        return {"status": "closed"}

    # ------------------------------------------------------------------
    # Execution: history VBA + Python API
    # ------------------------------------------------------------------

    def run_history(self, vba: str, label: str | None = None) -> dict[str, Any]:
        """Execute VBA via ``model3d.add_to_history`` (connected) or return script."""
        if not self.is_connected or not self.has_project:
            return {
                "status": "offline",
                "vba": vba,
                "message": "VBA generated — execute in CST or connect first.",
            }

        CSTSession._history_seq += 1
        hist_label = label or f"cst_mcp_{CSTSession._history_seq}"
        try:
            result = self.model3d.add_to_history(hist_label, vba)
            return {
                "status": "executed",
                "label": hist_label,
                "result": str(result) if result not in (None, "") else "ok",
            }
        except Exception as exc:  # noqa: BLE001
            # Surface CST-side context so the agent does not rely only on user paste
            extra: dict[str, Any] = {}
            try:
                msgs = self.get_cst_messages(max_chars=2500)
                if msgs.get("status") == "ok":
                    extra["cst_messages_tail"] = msgs.get("tail")
                    extra["cst_message_file"] = msgs.get("path")
            except Exception:  # noqa: BLE001
                pass
            try:
                dlg = self.read_dialogs() if hasattr(self, "read_dialogs") else {}
                if dlg.get("count"):
                    extra["cst_dialogs"] = dlg
            except Exception:  # noqa: BLE001
                pass
            return {
                "status": "error",
                "message": str(exc),
                "vba": vba,
                "label": hist_label,
                **extra,
            }

    @staticmethod
    def _ensure_sub_main(code: str) -> str:
        import re

        if re.search(r"(?is)\bsub\s+main\b", code):
            return code if code.endswith("\n") else code + "\n"
        body = code.strip("\n")
        return f"Sub Main()\n{body}\nEnd Sub\n"

    @staticmethod
    def _strip_sub_main(code: str) -> str:
        """Remove Sub Main wrapper for add_to_history (history macros must be bare)."""
        import re

        m = re.search(
            r"(?is)^\s*sub\s+main\s*\(\s*\)\s*(.*)\s*end\s+sub\s*$",
            code.strip(),
        )
        if m:
            return m.group(1).strip() + "\n"
        return code

    def run_vba_silent(self, vba_code: str) -> dict[str, Any]:
        """Run VBA without history (schematic / model3d private fallback).

        Accepts bare VBA **or** code already wrapped in ``Sub Main``.
        History fallback uses bare code only — wrapping Sub Main in history
        causes ``Unterminated block statement (Sub Main())``.
        """
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "vba": vba_code}

        wrapped = self._ensure_sub_main(vba_code)
        bare = self._strip_sub_main(vba_code)
        errors: list[str] = []

        # 1) schematic.execute_vba_code (requires Sub Main)
        try:
            schematic = getattr(self._project, "schematic", None)
            if schematic is not None and hasattr(schematic, "execute_vba_code"):
                schematic.execute_vba_code(wrapped)
                return {"status": "executed", "entrypoint": "schematic.execute_vba_code"}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"schematic: {exc}")

        # 2) model3d._execute_vba_code (CST 2026)
        try:
            m3d = self.model3d
            exe = getattr(m3d, "_execute_vba_code", None)
            if callable(exe):
                exe(wrapped)
                return {"status": "executed", "entrypoint": "model3d._execute_vba_code"}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"model3d._execute_vba_code: {exc}")

        # 3) history fallback — NEVER pass Sub Main here
        try:
            return {
                **self.run_history(bare, label="mcp_silent_fallback"),
                "entrypoint": "add_to_history_fallback",
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"history: {exc}")

        return {
            "status": "error",
            "message": " ; ".join(errors) if errors else "silent VBA unavailable",
            "vba": wrapped,
        }
    def store_parameters(self, params: dict[str, float | str]) -> dict[str, Any]:
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        try:
            m3d = self.model3d
            for name, value in params.items():
                m3d.StoreParameter(name, str(value))
            return {"status": "ok", "params": params}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def rebuild(self) -> dict[str, Any]:
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        try:
            self.model3d.Rebuild()
            return {"status": "ok"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def delete_results(self) -> dict[str, Any]:
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        try:
            self.model3d.DeleteResults()
            return {"status": "ok"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def is_solver_running(self) -> bool:
        if not self.has_project:
            return False
        try:
            return bool(self.model3d.is_solver_running())
        except Exception:  # noqa: BLE001
            return False

    def wait_solver(self, timeout_s: float = 3600, poll_s: float = 2.0) -> dict[str, Any]:
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        deadline = time.monotonic() + timeout_s
        while self.is_solver_running():
            if time.monotonic() > deadline:
                return {"status": "error", "message": f"Solver still running after {timeout_s}s"}
            time.sleep(poll_s)
        return {"status": "ok"}

    def run_solver(self, timeout_s: float = 3600) -> dict[str, Any]:
        """Run solver via Python API (blocks until complete)."""
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "message": "Solver requires connected mode"}

        try:
            if self.is_solver_running():
                waited = self.wait_solver(timeout_s=timeout_s)
                if waited.get("status") != "ok":
                    return waited
            result = self.model3d.run_solver()
            return {"status": "executed", "result": str(result) if result else "ok"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def export_tree_csv(self, tree_path: str, filepath: str | None = None) -> dict[str, Any]:
        """Export a result tree item to CSV using model3d.ASCIIExport."""
        if not self.has_project:
            return {"status": "error", "message": "No project open"}

        if filepath is None:
            safe = re_sub_path(tree_path)
            filepath = str(self.config.work_dir / f"export_{safe}.csv")

        out = Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()

        safe_path = str(out).replace("\\", "/")
        try:
            m3d = self.model3d
            m3d.SelectTreeItem(tree_path)
            ae = m3d.ASCIIExport
            ae.Reset()
            ae.FileName(safe_path)
            ae.SetFileType("csv")
            ae.Execute()

            if not out.is_file() or out.stat().st_size == 0:
                return {
                    "status": "error",
                    "message": (
                        f"Export produced no data for tree item '{tree_path}'. "
                        "Check that the simulation finished and the path exists."
                    ),
                    "path": str(out),
                }
            return {"status": "exported", "path": str(out), "tree_path": tree_path}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc), "tree_path": tree_path}

    def get_s_parameters(
        self,
        port_out: int = 1,
        port_in: int = 1,
        *,
        max_points: int = 200,
    ) -> dict[str, Any]:
        """Export and parse S-parameters into structured JSON."""
        tree = f"1D Results\\S-Parameters\\S{port_out},{port_in}"
        tmp = self.config.work_dir / f"s{port_out}_{port_in}_{int(time.time())}.csv"
        exported = self.export_tree_csv(tree, str(tmp))
        if exported.get("status") != "exported":
            return exported

        reader = ResultsReader(self.config.work_dir)
        parsed = reader.read_sparam_file(tmp, max_points=max_points)
        parsed["tree_path"] = tree
        parsed["port_out"] = port_out
        parsed["port_in"] = port_in
        return parsed

    def set_params_rebuild_solve(
        self,
        params: dict[str, float | str],
        *,
        export_s11: bool = True,
        port: int = 1,
        timeout_s: float = 3600,
    ) -> dict[str, Any]:
        """Parameter change → delete results → rebuild → solve → optional S11."""
        if not self.has_project:
            return {"status": "error", "message": "No project open"}

        try:
            m3d = self.model3d
            for name, value in params.items():
                m3d.StoreParameter(name, str(value))
            try:
                m3d.DeleteResults()
            except Exception:  # noqa: BLE001
                logger.debug("DeleteResults failed", exc_info=True)
            m3d.Rebuild()
            if self.is_solver_running():
                self.wait_solver(timeout_s=timeout_s)
            m3d.run_solver()

            out: dict[str, Any] = {"status": "ok", "params": params}
            if export_s11:
                out["s_parameters"] = self.get_s_parameters(port, port)
            return out
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def list_parameters(self) -> dict[str, Any]:
        """Best-effort parameter table dump via VBA GetNumberOfParameters."""
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "parameters": {}}
        # Silent VBA is fragile for return values; try Python API first
        try:
            m3d = self.model3d
            params: dict[str, str] = {}
            # Common pattern on recent CST Python bindings
            if hasattr(m3d, "GetNumberOfParameters"):
                n = int(m3d.GetNumberOfParameters())
                for i in range(n):
                    name = str(m3d.GetParameterName(i))
                    try:
                        val = str(m3d.GetParameterNValue(i))
                    except Exception:  # noqa: BLE001
                        val = str(m3d.RestoreParameter(name)) if hasattr(m3d, "RestoreParameter") else ""
                    params[name] = val
                return {"status": "ok", "parameters": params, "count": len(params)}
        except Exception as exc:  # noqa: BLE001
            logger.debug("list_parameters failed: %s", exc)
        return {"status": "error", "message": "Could not enumerate parameters", "parameters": {}}

    def _find_message_output(self) -> str | None:
        """Locate CST Message output / solver log for the active project."""
        if not self._project_path:
            return None
        base = Path(self._project_path)
        candidates = [
            base.with_suffix("") / "Result" / "output.txt",
            base.with_suffix("") / "Result" / "Model.log",
            base.with_suffix("") / "Result" / "MCalc.log",
        ]
        for c in candidates:
            if c.is_file() and c.stat().st_size > 0:
                return str(c)
        return None

    def get_cst_messages(self, max_chars: int = 4000) -> dict[str, Any]:
        """Return tail of CST message/solver log so agents see CST errors without user paste."""
        path = self._find_message_output()
        if not path:
            # Also try work_dir dumps
            return {"status": "empty", "message": "No CST message/log file found yet."}
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            return {
                "status": "ok",
                "path": path,
                "tail": text[-max_chars:] if len(text) > max_chars else text,
                "size": len(text),
            }
        except OSError as exc:
            return {"status": "error", "message": str(exc), "path": path}
    def export_plot_images(
        self,
        out_dir: str | Path | None = None,
        *,
        width: int = 1280,
        height: int = 720,
        views: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export structure screenshots from distinct camera views.

        Uses reserved ``Plot.RestoreView`` names (Front/Top/Left/…) when
        available, with ``Plot.Rotate`` fallbacks so views are not identical.
        """
        if not self.is_connected or not self.has_project:
            return {
                "status": "offline",
                "message": "Plot export requires connected mode with an open project.",
            }

        out = Path(out_dir) if out_dir else (self.config.work_dir / "exports" / "views")
        out.mkdir(parents=True, exist_ok=True)
        # Quiet mode often yields blank identical screenshots — disable for export
        quiet_restored = False
        try:
            if self._de is not None and hasattr(self._de, "set_quiet_mode"):
                self._de.set_quiet_mode(False)
                quiet_restored = True
        except Exception:  # noqa: BLE001
            pass
        # Logical names → CST reserved view + optional rotate tweaks
        # RestoreView reserved: Left, Right, Front, Back, Top, Bottom, Perspective
        views = views or ["perspective", "front", "top", "left", "right"]

        def _export_path(name: str) -> str:
            return (out / f"view_{name}.png").as_posix()

        def _view(name: str, reserved: str, extra_rotates: list[str] | None = None) -> str:
            lines = [
                'Plot.DrawBox "True"',
                f'Plot.RestoreView "{reserved}"',
            ]
            for r in extra_rotates or []:
                lines.append(f'Plot.Rotate "{r}"')
            lines.extend(
                [
                    "Plot.ZoomToStructure",
                    "Plot.Update",
                    f'Plot.ExportImage "{_export_path(name)}", {width}, {height}',
                ]
            )
            return "\n".join(lines)

        # Reserved RestoreView names + DrawBox so shots are not identical blanks
        view_scripts: dict[str, str] = {
            "perspective": _view("perspective", "Perspective", ["left", "up"]),
            "front": _view("front", "Front"),
            "back": _view("back", "Back"),
            "top": _view("top", "Top"),
            "bottom": _view("bottom", "Bottom"),
            "left": _view("left", "Left"),
            "right": _view("right", "Right"),
            "xy": _view("xy", "Top"),
            "xz": _view("xz", "Front"),
            "yz": _view("yz", "Left"),
        }
        results: list[dict[str, Any]] = []
        for view in views:
            script = view_scripts.get(view)
            path = out / f"view_{view}.png"
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
            if not script:
                # Fallback: rotate from current view
                script = "\n".join(
                    [
                        "Plot.ZoomToStructure",
                        'Plot.Rotate "left"',
                        'Plot.Rotate "left"',
                        "Plot.Update",
                        f'Plot.ExportImage "{path.as_posix()}", {width}, {height}',
                    ]
                )
            wrapped = f"Sub Main()\n{script}\nEnd Sub\n"
            run = self.run_vba_silent(wrapped)
            # If reserved view failed, try rotate-based fallback once
            if run.get("status") != "executed" or not path.exists():
                fallback = "\n".join(
                    [
                        "Plot.ZoomToStructure",
                        *(
                            ['Plot.Rotate "up"', 'Plot.Rotate "up"']
                            if view in {"top", "xy"}
                            else ['Plot.Rotate "left"', 'Plot.Rotate "left"']
                            if view in {"left", "yz"}
                            else ['Plot.Rotate "right"', 'Plot.Rotate "right"']
                            if view in {"right"}
                            else ['Plot.Rotate "down"']
                            if view in {"front", "xz"}
                            else ['Plot.Rotate "left"', 'Plot.Rotate "up"']
                        ),
                        "Plot.Update",
                        f'Plot.ExportImage "{path.as_posix()}", {width}, {height}',
                    ]
                )
                run = self.run_vba_silent(f"Sub Main()\n{fallback}\nEnd Sub\n")
            results.append(
                {
                    "view": view,
                    "status": run.get("status"),
                    "path": str(path) if path.exists() else None,
                    "exists": path.exists(),
                    "entrypoint": run.get("entrypoint"),
                    "error": run.get("message"),
                }
            )

        if quiet_restored:
            try:
                if self._de is not None and hasattr(self._de, "set_quiet_mode"):
                    self._de.set_quiet_mode(True)
            except Exception:  # noqa: BLE001
                pass

        ok_any = any(r.get("exists") for r in results)
        distinct_sizes = {r.get("path") and Path(str(r["path"])).stat().st_size
                          for r in results if r.get("exists") and r.get("path")}
        return {
            "status": "ok" if ok_any else "error",
            "out_dir": str(out),
            "images": results,
            "distinct_file_sizes": len({s for s in distinct_sizes if s}),
            "message": None
            if ok_any
            else "No images were written. CST may block ExportImage in quiet/headless mode.",
        }

    def discover_farfield_monitors(self) -> dict[str, Any]:
        """Discover farfield monitors from project Result folder + path heuristics."""
        from cst_mcp.execution.farfield import discover_farfield_from_project_dir

        disk = discover_farfield_from_project_dir(self._project_path)
        return {
            "status": "ok",
            "project_path": self._project_path,
            "monitors": disk,
            "count": len(disk),
        }

    def export_farfield_ascii(
        self,
        frequency_ghz: float | None = None,
        filepath: str | Path | None = None,
        monitor_name: str | None = None,
    ) -> dict[str, Any]:
        """Export farfield data via tree ASCIIExport with aggressive path discovery."""
        from cst_mcp.execution.farfield import (
            farfield_tree_candidates,
            parse_farfield_pattern_csv,
            parse_farfield_summary_text,
        )

        candidates = farfield_tree_candidates(frequency_ghz, monitor_name)
        # Enrich from disk discovery
        discovered = self.discover_farfield_monitors().get("monitors") or []
        for mon in discovered:
            for c in mon.get("tree_candidates") or []:
                if c not in candidates:
                    candidates.insert(0, c)

        out = Path(filepath) if filepath else (
            self.config.work_dir / "exports" / f"farfield_{frequency_ghz or 'auto'}.csv"
        )
        out.parent.mkdir(parents=True, exist_ok=True)

        last_err: dict[str, Any] | None = None
        tried: list[str] = []
        for tree in candidates:
            tried.append(tree)
            res = self.export_tree_csv(tree, str(out))
            if res.get("status") == "exported":
                parsed = parse_farfield_pattern_csv(out)
                return {
                    **res,
                    "tree_path": tree,
                    "tried_paths": tried,
                    "parsed": parsed,
                }
            last_err = res

        return {
            **(last_err or {"status": "error", "message": "No farfield tree item found"}),
            "tried_paths": tried,
            "discovered_monitors": discovered,
        }

    def export_farfield_summary(
        self,
        frequency_ghz: float | None = None,
        monitor_name: str | None = None,
        filepath: str | Path | None = None,
        *,
        max_attempts: int = 1,
        use_history: bool = False,
    ) -> dict[str, Any]:
        """Farfield metrics via official FarfieldPlot.GetMax path (CST 2026).

        Uses SelectTreeItem + Plot + GetMax / GetRadiationEfficiency — **not**
        ASCIIExportSummary (that API is unreliable and spams Message with
        ``No data available for export`` / ``No HEX mesh found``).

        ``use_history=False`` (default): never push macros into history.
        """
        from cst_mcp.execution.farfield import (
            build_farfield_metrics_vba,
            farfield_tree_candidates,
            parse_farfield_metrics_kv,
        )

        if not self.is_connected or not self.has_project:
            return {
                "status": "offline",
                "message": "Farfield summary requires connected mode with results.",
            }

        out = Path(filepath) if filepath else (
            self.config.work_dir
            / "exports"
            / f"farfield_metrics_{frequency_ghz or 'auto'}.txt"
        )
        out.parent.mkdir(parents=True, exist_ok=True)

        candidates = farfield_tree_candidates(frequency_ghz, monitor_name)
        # Only concrete monitor paths — never parent "Farfields" folder
        candidates = [
            c
            for c in candidates
            if c.count("\\") >= 1 and "farfield (f=" in c.lower()
        ]
        # Prefer paths that SelectTreeItem accepts right now
        ordered: list[str] = []
        for tree in candidates:
            try:
                if self.model3d.SelectTreeItem(tree):
                    ordered.insert(0, tree)
                else:
                    ordered.append(tree)
            except Exception:  # noqa: BLE001
                ordered.append(tree)
        candidates = ordered[: max(1, int(max_attempts))]

        tried: list[dict[str, Any]] = []
        for tree in candidates:
            entry: dict[str, Any] = {"tree_path": tree}
            if out.exists():
                try:
                    out.unlink()
                except OSError:
                    pass

            vba = build_farfield_metrics_vba(tree, str(out))
            if use_history:
                run = self.run_vba_silent(vba)
            else:
                run = self._run_vba_no_history(vba)
            entry["run"] = run.get("status")
            entry["entrypoint"] = run.get("entrypoint")
            if run.get("message"):
                entry["error"] = str(run.get("message"))[:200]
            tried.append(entry)

            if out.is_file() and out.stat().st_size > 0:
                text = out.read_text(encoding="utf-8", errors="replace")
                metrics = parse_farfield_metrics_kv(text)
                # Valid if we got a real max and select succeeded
                has_gain = "max_realized_gain_dbi" in metrics
                select_ok = metrics.get("select_ok", True)
                empty_marker = (
                    has_gain
                    and metrics.get("max_realized_gain_dbi") == 0
                    and metrics.get("radiation_efficiency_db") is None
                    and metrics.get("min_plot_value") == 0
                )
                if select_ok and has_gain and not empty_marker:
                    return {
                        "status": "ok",
                        "method": "farfield_plot_getmax",
                        "tree_path": tree,
                        "path": str(out),
                        "metrics": metrics,
                        "summary_preview": text[:2000],
                        "tried": tried,
                    }
                entry["metrics_partial"] = metrics
                entry["raw"] = text[:500]

        return {
            "status": "error",
            "message": (
                "FarfieldPlot.GetMax unavailable — check that "
                "Farfields\\farfield (f=…) [1] exists after solve, "
                "or use 1D Results efficiencies."
            ),
            "tried": tried,
            "path": str(out),
        }

    def _run_vba_no_history(self, vba_code: str) -> dict[str, Any]:
        """Like run_vba_silent but never falls back to add_to_history (no Message spam)."""
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "vba": vba_code}
        wrapped = self._ensure_sub_main(vba_code)
        errors: list[str] = []
        try:
            schematic = getattr(self._project, "schematic", None)
            if schematic is not None and hasattr(schematic, "execute_vba_code"):
                schematic.execute_vba_code(wrapped)
                return {"status": "executed", "entrypoint": "schematic.execute_vba_code"}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"schematic: {exc}")
        try:
            exe = getattr(self.model3d, "_execute_vba_code", None)
            if callable(exe):
                exe(wrapped)
                return {"status": "executed", "entrypoint": "model3d._execute_vba_code"}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"model3d: {exc}")
        return {
            "status": "error",
            "message": " ; ".join(errors) if errors else "VBA execute unavailable (history disabled)",
            "vba": wrapped,
        }
    def get_farfield_metrics(
        self,
        frequency_ghz: float | None = None,
        monitor_name: str | None = None,
        *,
        try_farfield_plot: bool = True,
    ) -> dict[str, Any]:
        """Antenna radiation metrics for reports.

        1. Always reads 1D Results via ``cst.results`` (S11 + efficiencies).
        2. By default also runs official FarfieldPlot.GetMax (one quiet VBA
           attempt, no history, no ASCIIExportSummary spam) to get max
           realized gain when ``Farfields\\… [1]`` is available.

        Pass ``try_farfield_plot=False`` to skip the plot step entirely.
        """
        metrics: dict[str, Any] = {}
        sources: dict[str, Any] = {}

        if self._project_path:
            try:
                from cst_mcp.execution.results_api import antenna_metrics_from_results

                api = antenna_metrics_from_results(self._project_path, frequency_ghz)
                sources["results_api"] = {
                    "status": api.get("status"),
                    "tree_items_n": len(api.get("tree_items") or []),
                }
                if api.get("metrics"):
                    metrics.update(api["metrics"])
            except Exception as exc:  # noqa: BLE001
                sources["results_api"] = {"status": "error", "message": str(exc)}

        # Disk discovery (proves .ffm exists even if tree select fails)
        try:
            sources["disk_monitors"] = self.discover_farfield_monitors()
        except Exception as exc:  # noqa: BLE001
            sources["disk_monitors"] = {"status": "error", "message": str(exc)}

        if not try_farfield_plot:
            if metrics:
                return {
                    "status": "ok",
                    "method": "results_api_1d",
                    "metrics": metrics,
                    "sources": sources,
                    "note": (
                        "1D Results only (S11 + efficiencies). "
                        "Pass try_farfield_plot=true for max gain via FarfieldPlot.GetMax."
                    ),
                }
            return {
                "status": "error",
                "message": "No 1D efficiency/S11 metrics found.",
                "sources": sources,
            }

        # Official GetMax path — quiet, no history, one attempt
        summary = self.export_farfield_summary(
            frequency_ghz, monitor_name, max_attempts=2, use_history=False
        )
        sources["farfield_plot"] = {
            "status": summary.get("status"),
            "method": summary.get("method"),
            "tree_path": summary.get("tree_path"),
            "message": summary.get("message"),
        }
        if summary.get("status") == "ok" and summary.get("metrics"):
            # Prefer plot gain numbers; keep 1D efficiencies if plot lacks them
            plot_m = dict(summary["metrics"])
            for k, v in plot_m.items():
                if k in {"select_ok", "vba_err", "error", "plot_mode"}:
                    continue
                metrics[k] = v
            return {
                "status": "ok",
                "method": "farfield_plot_getmax+results_api",
                "metrics": metrics,
                "path": summary.get("path"),
                "tree_path": summary.get("tree_path"),
                "sources": sources,
                "available": True,
            }
        if metrics:
            disk_n = 0
            dm = sources.get("disk_monitors") or {}
            if isinstance(dm, dict):
                disk_n = int(dm.get("count") or 0)
            return {
                "status": "ok",
                "method": "results_api_1d",
                "metrics": metrics,
                "sources": sources,
                "available": disk_n > 0,
                "farfield_plot_error": summary.get("message"),
                "note": (
                    "1D efficiencies available. "
                    "Pattern/gain via FarfieldPlot failed — open "
                    "Farfields\\farfield (f=…) [1] in the GUI or re-solve "
                    "with a farfield monitor."
                    if disk_n
                    else "No farfield .ffm on disk — add monitor and re-solve."
                ),
            }
        return {
            "status": "error",
            "message": summary.get("message") or "No metrics available",
            "sources": sources,
            "available": False,
        }
    def design_report(
        self,
        *,
        port: int = 1,
        frequency_ghz: float | None = None,
        include_images: bool = True,
        include_sparams: bool = True,
        include_farfield: bool = True,
        include_parameters: bool = True,
        max_points: int = 200,
        out_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """One-shot design package: params, S11, optional farfield + views.

        Safe aggregation: each section is independent; failures are reported
        per-section without aborting the whole report.
        """
        base = Path(out_dir) if out_dir else (
            self.config.work_dir / "exports" / f"report_{int(time.time())}"
        )
        base.mkdir(parents=True, exist_ok=True)

        report: dict[str, Any] = {
            "status": "ok",
            "project_path": self._project_path,
            "out_dir": str(base),
            "sections": {},
        }

        report["sections"]["status"] = self.status()

        if include_parameters:
            report["sections"]["parameters"] = self.list_parameters()

        if include_sparams:
            s = self.get_s_parameters(port, port, max_points=max_points)
            # also copy export file into report dir if present
            report["sections"]["s_parameters"] = s
            if s.get("path"):
                try:
                    src = Path(str(s["path"]))
                    if src.is_file():
                        dest = base / f"S{port}_{port}.csv"
                        dest.write_bytes(src.read_bytes())
                        s["report_copy"] = str(dest)
                except OSError:
                    pass

        if include_farfield:
            # Prefer summary metrics (gain/directivity); keep ascii as secondary
            ff = self.get_farfield_metrics(frequency_ghz)
            report["sections"]["farfield"] = ff
            report["sections"]["farfield_monitors"] = self.discover_farfield_monitors()

        if include_images:
            report["sections"]["views"] = self.export_plot_images(
                base / "views", width=1280, height=720
            )

        # overall soft-fail status
        failed = [
            k
            for k, v in report["sections"].items()
            if isinstance(v, dict) and v.get("status") in {"error", "offline"}
        ]
        report["partial_failures"] = failed
        if failed and include_sparams and report["sections"].get("s_parameters", {}).get("status") != "ok":
            report["status"] = "partial"
        return report

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "cst_available": self.config.cst_available,
            "cst_path": str(self.config.cst_path) if self.config.cst_path else None,
            "python_lib_path": (
                str(self.config.python_lib_path) if self.config.python_lib_path else None
            ),
            "cst_version": self.config.version,
            "work_dir": str(self.config.work_dir),
            "project_open": self.has_project,
            "project_path": self._project_path,
            "solver_running": self.is_solver_running() if self.has_project else False,
            "last_error": self._last_error,
        }

    @staticmethod
    def _safe_filename(project: Any) -> str | None:
        try:
            fname = project.filename
            return str(fname() if callable(fname) else fname)
        except Exception:  # noqa: BLE001
            return None


def re_sub_path(tree_path: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in tree_path)[:80]
