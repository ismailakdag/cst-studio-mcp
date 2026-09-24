"""CST Design Environment session manager.

Python-first connection lifecycle.  Geometry and most modeling commands still
execute as history VBA (CST architecture), but project control, solver run,
parameter store/rebuild, and result export use the official Python API.
"""

from __future__ import annotations

import logging
import math
import re
import time
from pathlib import Path
from typing import Any

from cst_mcp.config import CSTConfig
from cst_mcp.vba_safety import vba_escape

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
        self._last_solver_error: str | None = None
        # Set by start_solver (async start) until a wait confirms the finish:
        # {"t0": monotonic start time, "seen_running": bool}. It lets
        # cst_wait_for_simulation tell "not started yet" from "finished".
        self._pending_solve: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mode(self) -> str:
        return "connected" if self.is_connected else "offline"

    @property
    def is_connected(self) -> bool:
        if self._de is None:
            return False
        checker = getattr(self._de, "is_connected", None)
        if not callable(checker):
            return True
        try:
            return bool(checker())
        except Exception:  # noqa: BLE001
            logger.debug("Design Environment connection check failed", exc_info=True)
            return False

    @property
    def has_project(self) -> bool:
        return self._project is not None and self.is_connected

    @property
    def project_path(self) -> str | None:
        return self._project_path

    @property
    def pending_solve(self) -> dict[str, Any] | None:
        """Copy of the async-solve record set by :meth:`start_solver`, or ``None``."""
        return dict(self._pending_solve) if self._pending_solve is not None else None

    def clear_pending_solve(self) -> None:
        self._pending_solve = None

    @property
    def model3d(self) -> Any:
        if self._project is None:
            raise SessionError("No project open")
        return self._project.model3d

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    CONNECT_MODES = ("any", "new")

    @staticmethod
    def _running_de_pids(interface: Any) -> list[int] | None:
        """PIDs of running Design Environments, or ``None`` when unknown."""
        lister = getattr(interface, "running_design_environments", None)
        if not callable(lister):
            return None
        try:
            pids = []
            for item in list(lister() or []):
                try:
                    pids.append(int(item))
                except (TypeError, ValueError):
                    pids.append(item)
            return pids
        except Exception:  # noqa: BLE001
            logger.debug("running_design_environments failed", exc_info=True)
            return None

    @staticmethod
    def _de_pid(de: Any) -> int | None:
        getter = getattr(de, "pid", None)
        if not callable(getter):
            return None
        try:
            return int(getter())
        except Exception:  # noqa: BLE001
            logger.debug("DesignEnvironment.pid() failed", exc_info=True)
            return None

    @staticmethod
    def _open_project_paths(de: Any, open_projects: list[Any]) -> list[str]:
        """Paths of projects open in ``de`` (list_open_projects, else handles)."""
        lister = getattr(de, "list_open_projects", None)
        if callable(lister):
            try:
                return [str(p) for p in list(lister() or [])]
            except Exception:  # noqa: BLE001
                logger.debug("list_open_projects failed", exc_info=True)
        paths = []
        for ref in open_projects:
            if isinstance(ref, (str, Path)):
                paths.append(str(ref))
                continue
            try:
                paths.append(str(ref.filename()))
            except Exception:  # noqa: BLE001
                paths.append(repr(ref))
        return paths

    def connect(self, mode: str = "any") -> dict[str, Any]:
        """Connect to a Design Environment.

        ``mode="any"`` (default, backwards compatible) attaches to any running
        DE -- possibly one the user opened interactively -- or starts a new one
        when none is running (``connect_to_any_or_new``).  ``mode="new"``
        always starts a fresh DE via ``DesignEnvironment.new()`` and never
        attaches to an existing DE or project.  The result always reports the
        attached PID (when the binding exposes ``pid()``), whether the DE was
        newly started, and the projects that were already open in it.
        """
        mode = str(mode or "any").lower()
        if mode not in self.CONNECT_MODES:
            return {
                "status": "error",
                "message": f"Unknown connect mode {mode!r}; use one of {list(self.CONNECT_MODES)}",
            }
        if self.is_connected:
            return {
                "status": "connected",
                "message": "Already connected",
                "project_path": self._project_path,
                "de_pid": self._de_pid(self._de),
            }

        # A failed/stale connection must not leave a project handle associated
        # with the next Design Environment we attach to.
        self._de = None
        self._project = None
        self._project_path = None

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
            factory = cst.interface.DesignEnvironment
            before = self._running_de_pids(cst.interface)
            newly_started: bool | None
            if mode == "new":
                if hasattr(factory, "new"):
                    self._de = factory.new()
                else:
                    self._de = factory()  # default StartMode.New
                msg = "Started a new Design Environment (mode='new')"
                newly_started = True
            elif hasattr(factory, "connect_to_any_or_new"):
                self._de = factory.connect_to_any_or_new()
                msg = "Connected via connect_to_any_or_new() (mode='any')"
                newly_started = None
            else:
                running = list(before or [])
                if running:
                    self._de = factory.connect(running[0])
                    msg = f"Connected to running DE (pid={running[0]})"
                    newly_started = False
                else:
                    self._de = factory()
                    msg = "Launched new Design Environment"
                    newly_started = True

            pid = self._de_pid(self._de)
            if newly_started is None:
                if before is not None and pid is not None:
                    newly_started = pid not in before
                elif before == []:
                    newly_started = True

            # Attach to the active project when possible.  Depending on the CST
            # binding build, get_open_projects() may return Project handles or
            # path strings, so normalize both documented shapes.
            open_projects = []
            try:
                open_projects = list(self._de.get_open_projects() or [])
            except Exception:  # noqa: BLE001
                pass
            if open_projects and self._project is None:
                active = None
                try:
                    if self._de.has_active_project():
                        active = self._de.active_project()
                except Exception:  # noqa: BLE001
                    logger.debug("active_project lookup failed", exc_info=True)
                self._project = active or self._project_from_open_ref(self._de, open_projects[0])
                self._project_path = self._safe_filename(self._project)

            open_paths = self._open_project_paths(self._de, open_projects)
            result: dict[str, Any] = {
                "status": "connected",
                "message": msg,
                "mode": mode,
                "de_pid": pid,
                "newly_started": newly_started,
                "running_des_before": before,
                "open_projects": len(open_projects),
                "open_project_paths": open_paths,
                "project_path": self._project_path,
                "cst_path": str(self.config.cst_path) if self.config.cst_path else None,
                "python_lib_path": (
                    str(self.config.python_lib_path) if self.config.python_lib_path else None
                ),
            }
            if newly_started is not True:
                result["warning"] = (
                    "Attached to a Design Environment that was already running"
                    if newly_started is False
                    else "Could not determine whether this Design Environment was already running"
                ) + (
                    f" (pid={pid}); it may be the user's interactive session"
                    f" with {len(open_paths)} open project(s)."
                    " Use cst_connect mode='new' for an isolated Design Environment."
                )
            return result
        except Exception as exc:  # noqa: BLE001
            self._de = None
            self._project = None
            self._project_path = None
            self._last_error = str(exc)
            logger.exception("CST connect failed")
            return {"status": "offline", "message": f"Connect failed: {exc}"}

    def disconnect(self) -> dict[str, Any]:
        """Release local API handles without closing the user's CST application.

        The official ``DesignEnvironment.close()`` closes the Design Environment
        itself.  A client disconnect must therefore only forget its handles.
        """
        self._de = None
        self._project = None
        self._project_path = None
        self._pending_solve = None
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

        if not self.is_connected:
            return {
                "status": "offline",
                "path": path,
                "type": project_type,
                "message": "Not connected — project not created in CST.",
            }

        project_type = project_type.upper()
        factory_name = self._FACTORIES.get(project_type)
        if factory_name is None:
            return {
                "status": "error",
                "message": f"Unsupported project type: {project_type}",
                "type": project_type,
            }

        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            # Prefer a fresh unique path if target already exists (CST often refuses overwrite)
            target = Path(path)
            if target.exists():
                alt = target.with_name(f"{target.stem}_{int(time.time())}{target.suffix}")
                path = str(alt)

            factory = getattr(self._de, factory_name)
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
            return {"status": "created", "path": path, "type": project_type}
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
            blocked = self._idle_error()
            if blocked:
                return blocked
            try:
                self._project.close()
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": str(exc), "path": self._project_path}
        self._project = None
        self._project_path = None
        self._pending_solve = None
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

        blocked = self._idle_error()
        if blocked:
            return blocked
        if self.results_present() is True:
            # Editing history on a project with results makes CST open the modal
            # "Results May Get Incompatible With Model" dialog inside the
            # add_to_history call; the dialog cannot be answered while the call is
            # pending, which freezes CST until it is force-quit.
            return {
                "status": "error",
                "code": "results_exist",
                "message": ("The project has simulation results, and changing the model would make "
                            "CST block on a modal 'Results May Get Incompatible With Model' dialog. "
                            "Call cst_delete_results first (export anything you need), then retry."),
            }
        CSTSession._history_seq += 1
        hist_label = label or f"cst_mcp_{CSTSession._history_seq}"
        try:
            result = self.model3d.add_to_history(hist_label, vba, timeout=30)
            return {
                "status": "executed",
                "label": hist_label,
                "result": str(result) if result not in (None, "") else "ok",
            }
        except Exception as exc:  # noqa: BLE001
            # A timed-out native call may still be running; do not issue more API
            # requests or replay its mutation while CST's state is uncertain.
            if self._is_timeout_error(exc):
                return {"status": "timeout", "message": str(exc), "label": hist_label,
                        "execution_state": "unknown", "vba": vba,
                        "note": "Command exceeded 30 seconds; no replay or solver termination was attempted."}
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
        """Remove Sub Main wrapper for add_to_history (history macros must be bare).

        Leading blank lines, comments (``'`` / ``Rem``) and module-level
        ``Option ...`` lines before ``Sub Main`` are tolerated: comments are
        kept, ``Option`` lines are dropped (they are invalid inside a Sub).
        """
        lines = code.strip().splitlines()
        prefix: list[str] = []
        idx = 0
        while idx < len(lines):
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith("'") or re.match(r"(?i)rem(\s|$)", stripped):
                if stripped:
                    prefix.append(stripped)
            elif not re.match(r"(?i)option\s+\w+", stripped):
                break
            idx += 1
        rest = "\n".join(lines[idx:])
        m = re.search(
            r"(?is)^\s*sub\s+main\s*(?:\(\s*\))?[ \t]*\r?\n(.*?)\s*end\s+sub\s*$",
            rest,
        )
        if m:
            body = m.group(1).strip()
            return "\n".join([*prefix, body]).strip() + "\n"
        return code

    def run_vba_silent(self, vba_code: str, *, history_fallback: bool = True) -> dict[str, Any]:
        """Run VBA without history (schematic / model3d private fallback).

        Accepts bare VBA **or** code already wrapped in ``Sub Main``.
        History fallback uses bare code only — wrapping Sub Main in history
        causes ``Unterminated block statement (Sub Main())``.
        """
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "vba": vba_code}

        blocked = self._idle_error()
        if blocked:
            return blocked
        wrapped = self._ensure_sub_main(vba_code)
        bare = self._strip_sub_main(vba_code)
        errors: list[str] = []

        # 1) schematic.execute_vba_code (requires Sub Main)
        try:
            schematic = getattr(self._project, "schematic", None)
            if schematic is not None and hasattr(schematic, "execute_vba_code"):
                schematic.execute_vba_code(wrapped, timeout=30)
                return {"status": "executed", "entrypoint": "schematic.execute_vba_code"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "timeout" if self._is_timeout_error(exc) else "error",
                    "message": str(exc), "entrypoint": "schematic.execute_vba_code",
                    "note": "Execution may have partially completed; no fallback replay was attempted."}

        # 2) model3d._execute_vba_code (CST 2026)
        try:
            m3d = self.model3d
            exe = getattr(m3d, "_execute_vba_code", None)
            if callable(exe):
                exe(wrapped, timeout=30)
                return {"status": "executed", "entrypoint": "model3d._execute_vba_code"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "timeout" if self._is_timeout_error(exc) else "error",
                    "message": str(exc), "entrypoint": "model3d._execute_vba_code",
                    "note": "Execution may have partially completed; no fallback replay was attempted."}

        # 3) history fallback — NEVER pass Sub Main here
        if not history_fallback:
            return {"status": "error", "entrypoint": None,
                    "message": "No non-history VBA entrypoint is available in this CST binding; "
                               "read-only queries are never written to the model history."}
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

    def _run_model3d_vba(self, vba_code: str) -> dict[str, Any]:
        """Execute modeler VBA without history, with no implicit dialog handling."""
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "vba": vba_code}
        execute = getattr(self.model3d, "_execute_vba_code", None)
        if not callable(execute):
            return {
                "status": "error",
                "message": "This CST binding does not expose model3d._execute_vba_code",
            }
        try:
            execute(self._ensure_sub_main(vba_code), timeout=30)
            return {"status": "executed", "entrypoint": "model3d._execute_vba_code"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc), "vba": vba_code}

    def start_blocking_vba(self, vba_code: str, *, what: str, probe_timeout_s: float = 10.0) -> dict[str, Any]:
        """Launch a VBA command that blocks until a long CST job ends.

        ``ParameterSweep.Start`` / ``Optimizer.Start`` do not return until every
        solver run is done.  Verified on CST 2026: when the client-side timeout
        of ``_execute_vba_code`` expires, the job keeps running inside CST and
        ``is_solver_running`` keeps answering (``True`` during the job).  So the
        call is issued with a short timeout; a timeout followed by a running
        solver means "started" and is recorded like an async solve so
        ``cst_wait_for_simulation`` can poll it.  No history entry is written.
        Callers must make sure the project holds no results first.
        """
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "vba": vba_code}
        blocked = self._idle_error()
        if blocked:
            return blocked
        execute = getattr(self.model3d, "_execute_vba_code", None)
        if not callable(execute):
            return {"status": "error",
                    "message": "This CST binding does not expose model3d._execute_vba_code"}
        t0 = time.monotonic()
        try:
            execute(self._ensure_sub_main(vba_code), timeout=self._api_timeout(probe_timeout_s))
        except Exception as exc:  # noqa: BLE001
            if not self._is_timeout_error(exc):
                return {"status": "error", "stage": "start", "message": str(exc), "what": what}
            running = self.is_solver_running(timeout_s=5)
            if running is True:
                self._pending_solve = {"t0": t0, "seen_running": True, "what": what}
                return {"status": "started", "running": True, "what": what,
                        "message": (f"{what} is running inside CST. Poll cst_wait_for_simulation "
                                    "until it reports finished, then read per-run results "
                                    "(cst_list_saved_results shows run_ids).")}
            return {"status": "timeout", "running": running, "what": what,
                    "execution_state": "unknown", "message": str(exc),
                    "note": "The start call timed out but no running solver was reported; "
                            "check cst_get_messages / dialogs before retrying."}
        return {"status": "completed", "what": what, "elapsed_s": round(time.monotonic() - t0, 2)}

    _RESULT_FOLDERS = ("1D Results", "2D/3D Results", "Farfields")
    # Present before any solve (material dispersion curves), so not a result.
    _NON_RESULT_ITEMS = frozenset({"1D Results\\Materials"})

    def results_present(self) -> bool | None:
        """Whether the open project holds simulation results (``None`` if unknown).

        Uses a no-history output-capture query, so it never raises a CST dialog.
        """
        if not self.is_connected or not self.has_project:
            return None
        # A missing folder raises in CST; treat that as "no results there".
        # mcpNext is reset before each call so a failing GetNextItemName ends
        # the loop instead of repeating the same item; mcpCount caps it anyway.
        probe_lines = ["On Error Resume Next", "Dim mcpChild As String",
                       "Dim mcpNext As String", "Dim mcpCount As Integer"]
        for folder in self._RESULT_FOLDERS:
            probe_lines += [
                'mcpChild = ""',
                f'mcpChild = Resulttree.GetFirstChildName("{folder}")',
                "mcpCount = 0",
                'Do While mcpChild <> "" And mcpCount < 50',
                '  Debug.Print "item" & vbTab & mcpChild',
                '  mcpNext = ""',
                "  mcpNext = Resulttree.GetNextItemName(mcpChild)",
                "  mcpChild = mcpNext",
                "  mcpCount = mcpCount + 1",
                "Loop",
            ]
        probe_lines.append('Debug.Print "done"')
        probe = "\n".join(probe_lines)
        result = self.capture_vba_output(probe)
        if result.get("status") != "ok":
            return None
        lines = [line.rstrip("\r") for line in str(result.get("output", "")).splitlines()]
        if "done" not in lines:
            return None
        items = {line.partition("\t")[2].strip() for line in lines if line.startswith("item\t")}
        return any(item and item not in self._NON_RESULT_ITEMS for item in items)

    def capture_vba_output(self, code: str) -> dict[str, Any]:
        """Return legacy Debug.Print/MsgBox query text through MCP, with no popup."""
        import uuid
        from cst_mcp.vba_builder import _escape_vba_string

        blocked = self._idle_error()
        if blocked:
            return blocked
        out = self.config.work_dir / f"query_{uuid.uuid4().hex}.txt"
        body = self._strip_sub_main(code)
        body = re.sub(r"(?im)^(\s*)(?:Debug\.Print|MsgBox)\s+(.+)$", r"\1Print #mcpOutput, \2", body)
        wrapped = ('Dim mcpOutput As Integer\nDim mcpError As String\n'
                   'mcpOutput = FreeFile\nOpen "' + _escape_vba_string(str(out)) + '" For Output As #mcpOutput\n'
                   'On Error GoTo mcpQueryFailed\n' + body + '\nClose #mcpOutput\nExit Sub\n'
                   'mcpQueryFailed:\nmcpError = Err.Description\nClose #mcpOutput\n'
                   'Err.Raise vbObjectError + 1, , mcpError')
        try:
            # Queries must never reach the model history (read-only contract).
            result = self.run_vba_silent(wrapped, history_fallback=False)
            if result.get("status") != "executed":
                return result
            if not out.is_file():
                return {"status": "error", "message": "CST returned without writing query output"}
            # VBA Print uses the Windows ANSI code page, not UTF-8.
            text = out.read_text(encoding="mbcs" if __import__("os").name == "nt" else "utf-8", errors="replace")
            return {"status": "ok", "output": text, "source": "VBA query via Python", "popup": False}
        finally:
            try:
                out.unlink(missing_ok=True)
            except OSError:
                logger.debug("Query output remains locked: %s", out)

    @staticmethod
    def _parameter_vba(params: dict[str, float | str]) -> str:
        lines: list[str] = []
        for name, value in params.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"Invalid CST parameter name: {name!r}")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Parameter {name!r} must be finite")
            raw_value = str(value)
            if any(char in raw_value for char in ("\r", "\n", "\x00")):
                raise ValueError(f"Parameter {name!r} contains an invalid control character")
            safe_value = raw_value.replace('"', '""')
            lines.append(f'StoreParameter "{name}", "{safe_value}"')
        return "\n".join(lines)

    def store_parameters(self, params: dict[str, float | str]) -> dict[str, Any]:
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        try:
            state = self.solver_status()
            if state.get("status") != "ok":
                return state
            if state.get("running"):
                return {"status": "busy", "message": "Parameters were not changed", "running": True}
            result = self.run_history(self._parameter_vba(params), label="store_parameters")
            if result.get("status") != "executed":
                return result
            return {"status": "ok", "params": params, "execution": result}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def rebuild(self, timeout_s: float = 30.0) -> dict[str, Any]:
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        try:
            state = self.solver_status(timeout_s=min(30.0, timeout_s))
            if state.get("status") != "ok":
                return state
            if state.get("running"):
                return {"status": "busy", "message": "Model was not rebuilt", "running": True}
            rebuild = getattr(self.model3d, "full_history_rebuild", None)
            if not callable(rebuild):
                return {
                    "status": "error",
                    "message": "This CST binding does not expose model3d.full_history_rebuild",
                }
            rebuild(timeout=self._api_timeout(timeout_s))
            return {"status": "ok"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def delete_results(self) -> dict[str, Any]:
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        try:
            state = self.solver_status()
            if state.get("status") != "ok":
                return state
            if state.get("running"):
                return {"status": "busy", "message": "Results were not deleted", "running": True}
            result = self._run_model3d_vba("DeleteResults")
            return {**result, "status": "ok"} if result.get("status") == "executed" else result
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def _api_timeout(timeout_s: float) -> int:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero")
        return max(1, int(timeout_s))

    def _idle_error(self) -> dict[str, Any] | None:
        state = self.is_solver_running(timeout_s=5)
        if state is not False:
            return {"status": "busy", "running": state,
                    "message": "Operation blocked: solver is active or its state is unknown. Check status; do not retry mutations until idle."}
        return None

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return isinstance(exc, TimeoutError) or "timeout" in message or "timed out" in message

    def is_solver_running(self, timeout_s: float = 30.0) -> bool | None:
        """Return solver activity, or ``None`` when CST cannot answer."""
        if not self.has_project:
            return False
        try:
            value = self.model3d.is_solver_running(timeout=self._api_timeout(timeout_s))
            self._last_solver_error = None if isinstance(value, bool) else "CST solver state is unknown"
            if value is True and self._pending_solve is not None:
                self._pending_solve["seen_running"] = True
            return value if isinstance(value, bool) else None
        except Exception as exc:  # noqa: BLE001
            self._last_solver_error = str(exc)
            logger.debug("is_solver_running failed", exc_info=True)
            return None

    @staticmethod
    def _label_run_info(run_info: dict[str, Any], running: bool | None) -> dict[str, Any]:
        """Mark CST's run info as historical unless it carries a timestamp.

        ``get_solver_run_info`` reports the outcome of the *last* solver run or
        history update (e.g. a stale ERROR from a rejected command) and keeps
        reporting it until the next run. Without a timestamp agents must not
        read ``state`` as the current solver condition.
        """
        time_keys = [k for k in run_info if re.search(r"(?i)time|date|stamp", k)]
        if time_keys:
            run_info["reported_at"] = run_info[time_keys[0]]
            return run_info
        if "state" in run_info:
            run_info["last_reported_state"] = run_info.pop("state")
            run_info["state_note"] = (
                "Last state CST reported for a previous solver run/history update; it carries "
                "no timestamp and may be stale. Use 'running' for the current solver condition."
                + (" The solver is idle now." if running is False else "")
            )
        return run_info

    def solver_status(
        self, timeout_s: float = 30.0, *, running_only: bool = False
    ) -> dict[str, Any]:
        """Return solver state through the read-only CST Python API.

        A full status makes up to three CST calls (running flag, active solver
        name, last run info), each bounded by ``timeout_s``. ``running_only``
        makes just the ``is_solver_running`` call, for cheap bounded polling.
        """
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "message": "Solver status requires connected mode"}

        timeout = self._api_timeout(timeout_s)
        try:
            running = self.is_solver_running(timeout_s=timeout)
            if running is None:
                return {"status": "error", "message": self._last_solver_error or "CST solver state is unknown", "running": None}
            out: dict[str, Any] = {
                "status": "ok",
                "running": running,
            }
            if not running_only:
                out.update(self.solver_details(timeout_s=timeout, running=running))
            return out
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc), "running": None}

    def solver_details(
        self, timeout_s: float = 30.0, *, running: bool | None = None
    ) -> dict[str, Any]:
        """Best-effort ``active_solver`` and ``run_info`` (two CST calls, each
        bounded by ``timeout_s``). Missing/failed values are simply omitted."""
        out: dict[str, Any] = {}
        if not self.has_project:
            return out
        timeout = self._api_timeout(timeout_s)
        try:
            m3d = self.model3d
        except Exception:  # noqa: BLE001
            return out
        get_name = getattr(m3d, "get_active_solver_name", None)
        if callable(get_name):
            try:
                out["active_solver"] = str(get_name(timeout=timeout))
            except Exception:  # noqa: BLE001
                logger.debug("get_active_solver_name failed", exc_info=True)
        get_info = getattr(m3d, "get_solver_run_info", None)
        if callable(get_info):
            try:
                info = get_info(timeout=timeout)
                if isinstance(info, dict):
                    run_info = {
                        str(key): value
                        if value is None or isinstance(value, (str, int, float, bool))
                        else str(value)
                        for key, value in info.items()
                    }
                    out["run_info"] = self._label_run_info(run_info, running)
            except Exception:  # noqa: BLE001
                logger.debug("get_solver_run_info failed", exc_info=True)
        return out

    def wait_solver(self, timeout_s: float = 3600, poll_s: float = 2.0) -> dict[str, Any]:
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        if timeout_s <= 0 or poll_s <= 0:
            return {"status": "error", "message": "timeout_s and poll_s must be greater than zero"}
        deadline = time.monotonic() + timeout_s
        while True:
            state = self.solver_status(timeout_s=min(30.0, timeout_s))
            if state.get("status") != "ok":
                return state
            if not state.get("running"):
                return {"status": "ok"}
            if time.monotonic() > deadline:
                return {
                    "status": "timeout",
                    "message": f"Solver still running after {timeout_s}s",
                    "running": True,
                }
            time.sleep(poll_s)

    def run_solver(self, timeout_s: float = 3600) -> dict[str, Any]:
        """Run solver via Python API (blocks until complete)."""
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "message": "Solver requires connected mode"}

        try:
            timeout = self._api_timeout(timeout_s)
            state = self.solver_status(timeout_s=min(30, timeout))
            if state.get("status") != "ok":
                return state
            if state.get("running"):
                return {
                    "status": "busy",
                    "message": "A solver is already running; no second solve was started.",
                    "running": True,
                }
            result = self.model3d.run_solver(timeout=timeout)
            # A completed blocking solve supersedes any earlier async start.
            self._pending_solve = None
            return {"status": "executed", "result": str(result) if result else "ok"}
        except Exception as exc:  # noqa: BLE001
            if self._is_timeout_error(exc):
                state = self.solver_status(timeout_s=min(30.0, timeout_s))
                return {
                    "status": "timeout",
                    "message": str(exc),
                    "running": state.get("running"),
                }
            return {"status": "error", "message": str(exc)}

    def start_solver(self, timeout_s: float = 30.0) -> dict[str, Any]:
        """Start the configured solver asynchronously through the official API."""
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "message": "Solver requires connected mode"}
        try:
            timeout = self._api_timeout(timeout_s)
            state = self.solver_status(timeout_s=timeout)
            if state.get("status") != "ok":
                return state
            if state.get("running"):
                return {
                    "status": "busy",
                    "message": "A solver is already running; no second solve was started.",
                    "running": True,
                }
            result = self.model3d.start_solver(timeout=timeout)
            self._pending_solve = {"t0": time.monotonic(), "seen_running": False}
            return {"status": "started", "result": str(result) if result else "ok"}
        except Exception as exc:  # noqa: BLE001
            if self._is_timeout_error(exc):
                state = self.solver_status(timeout_s=min(30.0, timeout_s))
                return {
                    "status": "timeout",
                    "message": str(exc),
                    "running": state.get("running"),
                }
            return {"status": "error", "message": str(exc)}

    def _solver_control(self, method_name: str, timeout_s: float = 30.0) -> dict[str, Any]:
        if not self.is_connected or not self.has_project:
            return {"status": "offline", "message": "Solver control requires connected mode"}
        try:
            timeout = self._api_timeout(timeout_s)
            method = getattr(self.model3d, method_name)
            result = method(timeout=timeout)
            return {
                "status": "executed",
                "command": method_name.removesuffix("_solver"),
                "result": str(result) if result else "ok",
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def pause_solver(self, timeout_s: float = 30.0) -> dict[str, Any]:
        return self._solver_control("pause_solver", timeout_s)

    def resume_solver(self, timeout_s: float = 30.0) -> dict[str, Any]:
        return self._solver_control("resume_solver", timeout_s)

    def abort_solver(self, timeout_s: float = 30.0) -> dict[str, Any]:
        result = self._solver_control("abort_solver", timeout_s)
        if result.get("status") == "executed":
            self._pending_solve = None
        return result

    def export_tree_csv(self, tree_path: str, filepath: str | None = None) -> dict[str, Any]:
        """Export a result tree item to CSV using model3d.ASCIIExport."""
        if not self.has_project:
            return {"status": "error", "message": "No project open"}
        blocked = self._idle_error()
        if blocked:
            return blocked

        if filepath is None:
            safe = re_sub_path(tree_path)
            filepath = str(self.config.work_dir / f"export_{safe}.csv")

        out = Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()

        safe_path = str(out).replace("\\", "/")
        try:
            from cst_mcp.vba_builder import _escape_vba_string
            # Model3D exposes add_to_history/run_solver, not COM-style ASCIIExport.
            # ASCIIExport is an official VBA object; execute it through the Python bridge.
            vba = ('If Not SelectTreeItem("' + _escape_vba_string(tree_path) + '") Then\n'
                   'Err.Raise vbObjectError + 1, , "Result tree item not found"\nEnd If\n'
                   + ('FarfieldPlot.Plot\n' if tree_path.startswith('Farfields\\') else '') +
                   'With ASCIIExport\n.Reset\n.FileName "' + _escape_vba_string(safe_path) + '"\n'
                   '.SetFileType "csv"\n.Execute\nEnd With')
            executed = self.run_vba_silent(vba)
            if executed.get("status") != "executed":
                return executed

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
        """Read complex S-parameters through the official Python results API."""
        from cst_mcp.execution.curves import read_curve, format_curve, frequency_scale
        from cst_mcp.execution.results_reader import downsample_series

        if not self.has_project or not self.project_path:
            return {"status": "error", "message": "Open and save a project before reading results"}
        running = self.is_solver_running(timeout_s=5)
        if running is not False:
            return {"status": "busy", "running": running, "message": "Solver is active or its state is unknown"}
        tree = f"1D Results\\S-Parameters\\S{port_out},{port_in}"
        raw = read_curve(self.project_path, tree, allow_interactive=True)
        if raw.get("status") != "ok":
            return raw
        try:
            scale = frequency_scale(raw["xlabel"]) / 1e9
            freqs = [v * scale for v in raw["x"]]
            db = format_curve(raw, "db")["y"]
            finite = [(f, y) for f, y in zip(freqs, db) if y is not None]
            metrics = {}
            if finite:
                f, y = min(finite, key=lambda p: p[1])
                metrics = {"min_db": y, "freq_at_min_ghz": f}
            data = {"status": "ok", "source": "cst.results", "tree_path": tree,
                    "port_out": port_out, "port_in": port_in, "n_points": len(freqs),
                    "frequency_unit": "GHz", "frequency_ghz": freqs,
                    "real": raw["real"], "imag": raw["imag"], "magnitude_db": db,
                    "magnitude_linear": format_curve(raw, "mag")["y"],
                    "phase_deg": format_curve(raw, "phase")["y"], "metrics": metrics,
                    "snapshot": raw["snapshot"]}
            return downsample_series(data, max_points=max_points) if max_points else data
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def set_params_rebuild_solve(
        self,
        params: dict[str, float | str],
        *,
        export_s11: bool = True,
        export_path: str | None = None,
        port: int = 1,
        timeout_s: float = 3600,
    ) -> dict[str, Any]:
        """Parameter change → delete results → rebuild → solve → optional S11."""
        if not self.has_project:
            return {"status": "error", "message": "No project open"}

        try:
            state = self.solver_status(timeout_s=min(30.0, timeout_s))
            if state.get("status") != "ok":
                return state
            if state.get("running"):
                return {
                    "status": "busy",
                    "message": "A solver is already running; parameters were not changed.",
                    "running": True,
                }
            update = self._run_model3d_vba(self._parameter_vba(params) + "\nDeleteResults")
            if update.get("status") != "executed":
                return {**update, "stage": "parameters"}
            rebuild = getattr(self.model3d, "full_history_rebuild", None)
            if not callable(rebuild):
                return {
                    "status": "error",
                    "stage": "rebuild",
                    "message": "This CST binding does not expose model3d.full_history_rebuild",
                }
            rebuild(timeout=self._api_timeout(min(30.0, timeout_s)))
            solved = self.run_solver(timeout_s=timeout_s)
            if solved.get("status") != "executed":
                return {**solved, "stage": "solve", "params": params}

            out: dict[str, Any] = {"status": "ok", "params": params, "solver": solved}
            if export_s11:
                s_parameters = self.get_s_parameters(port, port, max_points=0 if export_path else 200)
                if export_path and s_parameters.get("status") == "ok":
                    values = s_parameters["magnitude_db"]
                    if any(value is None for value in values):
                        return {"status": "error", "stage": "export", "message": "Undefined dB samples; use complex results"}
                    destination = Path(export_path)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text("Frequency / GHz    S / dB\n" + "\n".join(
                        f"{frequency:.17g} {value:.17g}" for frequency, value in
                        zip(s_parameters["frequency_ghz"], values)) + "\n", encoding="utf-8")
                if s_parameters.get("status") != "ok":
                    return {
                        **s_parameters,
                        "status": "error",
                        "stage": "s_parameters",
                        "params": params,
                        "solver": solved,
                    }
                out["s_parameters"] = s_parameters
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
        result = self.capture_vba_output('Dim i As Long\nFor i = 0 To GetNumberOfParameters() - 1\nDebug.Print GetParameterName(i) & vbTab & CStr(GetParameterNValue(i))\nNext i')
        if result.get("status") != "ok":
            return result
        parameters = {}
        for line in result["output"].splitlines():
            if "\t" in line:
                name, value = line.split("\t", 1)
                parameters[name.strip()] = value.strip()
        return {"status": "ok", "parameters": parameters, "count": len(parameters), "source": "VBA via Python"}

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
        if self.has_project:
            getter = getattr(self._project, "get_messages", None)
            if callable(getter):
                try:
                    messages = getter()
                    text = str(messages) if messages is not None else ""
                    if text and text not in {"[]", "{}"}:
                        return {"status": "ok", "source": "Project.get_messages", "tail": text[-max_chars:], "size": len(text)}
                except Exception:
                    logger.debug("Project.get_messages failed; trying saved log", exc_info=True)
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
                *_STRUCTURE_VIEW_PREAMBLE,
                'Plot.DrawBox "True"',
                f'Plot.RestoreView "{reserved}"',
            ]
            for r in extra_rotates or []:
                lines.append(f'Plot.Rotate "{r}"')
            lines.extend(
                [
                    "Plot.ZoomToStructure",
                    "Plot.Update",
                    f'Plot.ExportImage "{vba_escape(_export_path(name), "path")}", {width}, {height}',
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
                        *_STRUCTURE_VIEW_PREAMBLE,
                        "Plot.ZoomToStructure",
                        'Plot.Rotate "left"',
                        'Plot.Rotate "left"',
                        "Plot.Update",
                        f'Plot.ExportImage "{vba_escape(path.as_posix(), "path")}", {width}, {height}',
                    ]
                )
            wrapped = f"Sub Main()\n{script}\nEnd Sub\n"
            run = self.run_vba_silent(wrapped)
            # If reserved view failed, try rotate-based fallback once
            if run.get("status") != "executed" or not path.exists():
                fallback = "\n".join(
                    [
                        *_STRUCTURE_VIEW_PREAMBLE,
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
                        f'Plot.ExportImage "{vba_escape(path.as_posix(), "path")}", {width}, {height}',
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
                schematic.execute_vba_code(wrapped, timeout=30)
                return {"status": "executed", "entrypoint": "schematic.execute_vba_code"}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"schematic: {exc}")
        try:
            exe = getattr(self.model3d, "_execute_vba_code", None)
            if callable(exe):
                exe(wrapped, timeout=30)
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
        blocked = self._idle_error()
        if blocked:
            return blocked
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
        project_open = self.has_project
        solver_state = (
            self.solver_status()
            if project_open
            else {"status": "unavailable", "running": False}
        )
        result = {
            "mode": self.mode,
            "cst_available": self.config.cst_available,
            "cst_path": str(self.config.cst_path) if self.config.cst_path else None,
            "python_lib_path": (
                str(self.config.python_lib_path) if self.config.python_lib_path else None
            ),
            "cst_version": self.config.version,
            "work_dir": str(self.config.work_dir),
            "project_open": project_open,
            "project_path": self._project_path,
            "solver_running": solver_state.get("running"),
            "solver_status": solver_state.get("status"),
            "last_error": self._last_error,
        }
        if solver_state.get("status") == "error":
            result["solver_status_error"] = solver_state.get("message", "Unknown CST API error")
        return result

    @staticmethod
    def _project_from_open_ref(design_environment: Any, project_ref: Any) -> Any:
        """Normalize get_open_projects() entries across CST binding versions."""
        if hasattr(project_ref, "model3d"):
            return project_ref
        return design_environment.get_open_project(project_ref)

    @staticmethod
    def _safe_filename(project: Any) -> str | None:
        try:
            fname = project.filename
            return str(fname() if callable(fname) else fname)
        except Exception:  # noqa: BLE001
            return None


# Switch the main view back to the 3D model before a structure screenshot;
# otherwise ExportImage captures whatever result (e.g. a farfield) is shown.
_STRUCTURE_VIEW_PREAMBLE = ('SelectTreeItem "Components"', "Plot.Update")


def re_sub_path(tree_path: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in tree_path)[:80]
