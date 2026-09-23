"""MCP tool annotations derived centrally from tool names.

Tool modules do not declare ``annotations`` themselves; the registry calls
:func:`annotations_for` for every tool that lacks them.  Hints follow the MCP
``ToolAnnotations`` semantics:

* ``readOnlyHint`` -- the tool does not modify the CST project, the CST
  session, or files (queries, offline help, pure calculators).
* ``destructiveHint`` -- the tool may delete, stop, close, consume, or
  irreversibly overwrite existing state.  Only meaningful when not read-only.
* ``idempotentHint`` -- repeating the call with the same arguments has no
  additional effect (``set_*``/``configure_*`` style configuration).
* ``openWorldHint`` -- always ``False``: every tool acts on the local CST
  installation and filesystem only.

Name rules cover the bulk of the catalog; the explicit sets below document
every exception.  Keep them in sync when adding tools.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

# Substrings marking pure queries / offline help (read-only).
_READ_ONLY_PATTERNS = (
    "_get_",
    "_list_",
    "_info",
    "_status",
    "_tree",
    "_search_help",
    "_read_",
    "_discover_",
    "_vba_help",
)

# Read-only tools the patterns above do not catch: offline calculators and
# design helpers that never touch CST.
_READ_ONLY_EXTRA = frozenset(
    {
        "cst_design_patch_only",
        # Polls solver state until done; never starts or stops the solver.
        "cst_wait_for_simulation",
        "cst_evaluate_antenna",
        # Interpolates saved sweep runs via cst.results; no parameter change.
        "cst_parameter_interpolation",
        "cst_analyze_impedance",
        "cst_array_compute_factor",
        "cst_array_beam_steering",
        "cst_array_taper_design",
        "cst_array_grating_lobe_analysis",
        "cst_pcb_calculate_coupling",
        "cst_matching_l_network",
        "cst_matching_pi_network",
        "cst_matching_t_network",
        "cst_matching_stub",
        "cst_matching_quarter_wave",
        "cst_impedance_smith_transform",
        "cst_matching_microstrip_impedance",
    }
)

# Pattern matches that nevertheless change state.  Keep each entry justified:
# clients may auto-approve read-only tools, so a wrong readOnlyHint is unsafe.
_NOT_READ_ONLY: frozenset[str] = frozenset(
    {
        # Mesh/solver queries currently run through history VBA, so every call
        # appends a model-history entry.  Revisit once they use a no-history
        # path (verify with a connected test before removing).
        "cst_get_mesh_info",
        "cst_get_mesh_quality",
        "cst_get_solver_info",
        # Connected mode resets the FarfieldPlot state and writes CSV/ASCII
        # exports under the work directory.
        "cst_get_farfield",
        "cst_get_radiation_pattern_3d",
        # try_farfield_plot=true (the default) selects a farfield tree item,
        # resets FarfieldPlot and writes a farfield_metrics_*.txt export.
        "cst_get_farfield_metrics",
    }
)

# Tools that write output files (figures, drawings) but never change the CST
# project model.  They are not read-only (files are written, and connected
# mode may change plot/selection state via CST exports), not destructive, and
# idempotent: the same arguments regenerate the same files.  Listed
# explicitly so name rules (``_plot_``/``_get_`` etc.) cannot misclassify them.
_FILE_OUTPUT_TOOLS = frozenset(
    {
        "cst_technical_drawing",
        "cst_plot_1d_results",
        "cst_plot_farfield",
    }
)

# Substrings marking tools that delete, stop, or clear state.
_DESTRUCTIVE_PATTERNS = ("_delete_", "_clear", "_remove")

_DESTRUCTIVE_EXTRA = frozenset(
    {
        "cst_stop_simulation",
        "cst_close_project",
        # CST boolean add/subtract/intersect consume (delete) solid2.
        "cst_boolean_add",
        "cst_boolean_subtract",
        "cst_boolean_intersect",
        # Arbitrary VBA can do anything, including deleting the project.
        "cst_execute_vba",
        # Dismissing a modal dialog may pick its default (e.g. discard) action.
        "cst_dismiss_dialogs",
        # Overwrites design parameter values over many solver iterations.
        "cst_refine_antenna",
        # Changing a parameter rebuilds the model; delete_results=true deletes
        # existing results first.
        "cst_set_parameter",
        # delete_results=true deletes results; run=true starts solver runs that
        # replace them.
        "cst_parameter_sweep",
        "cst_optimizer",
        "cst_multi_objective_optimizer",
        "cst_constrained_optimizer",
        # A new solver run overwrites the existing results of the project.
        "cst_run_simulation",
        "cst_run_simulation_async",
        # The watcher auto-dismisses modal dialogs, which may pick their
        # default (e.g. discard) action.
        "cst_start_dialog_watcher",
        # With ``path`` the project file at that location is overwritten.
        "cst_save_project",
        # Exports write to caller-chosen paths and overwrite existing files.
        "cst_export_project",
        "cst_export_cad",
        "cst_export_touchstone",
        "cst_export_farfield",
        "cst_export_result",
        "cst_export_structure_views",
    }
)

# Pattern matches that are not destructive (stopping a helper, not CST work).
_NOT_DESTRUCTIVE = frozenset({"cst_stop_dialog_watcher"})

# Prefixes/substrings marking configuration setters (idempotent).
_IDEMPOTENT_PATTERNS = ("cst_set_", "_set_", "cst_configure_", "cst_delete_")

_IDEMPOTENT_EXTRA = frozenset(
    {
        # A second connect on a live session is a no-op ("Already connected").
        "cst_connect",
        "cst_disconnect",
        # cst_open_project is deliberately absent: each call re-opens the file
        # through the Design Environment, which can open a second copy.
        "cst_save_project",
        "cst_close_project",
        "cst_assign_material",
        "cst_load_material",
        "cst_pause_simulation",
        "cst_resume_simulation",
        "cst_stop_simulation",
        "cst_start_dialog_watcher",
        "cst_stop_dialog_watcher",
        "cst_dismiss_dialogs",
        "cst_export_project",
        "cst_export_cad",
        "cst_export_touchstone",
        "cst_export_farfield",
        "cst_export_result",
        "cst_export_structure_views",
        # Repeating a farfield query rewrites the same export/plot state.
        "cst_get_farfield",
        "cst_get_radiation_pattern_3d",
        "cst_get_farfield_metrics",
    }
)

# Words whose title-case spelling is wrong for display titles.
_TITLE_WORDS = {
    "vba": "VBA",
    "pcb": "PCB",
    "cad": "CAD",
    "siw": "SIW",
    "cpw": "CPW",
    "ifa": "IFA",
    "pifa": "PIFA",
    "vswr": "VSWR",
    "pml": "PML",
    "ie": "IE",
    "s11": "S11",
    "s": "S",
    "3d": "3D",
    "l": "L",
    "t": "T",
    "pi": "Pi",
    "and": "and",
    "of": "of",
}


def is_read_only(name: str) -> bool:
    if name in _NOT_READ_ONLY or name in _FILE_OUTPUT_TOOLS:
        return False
    return name in _READ_ONLY_EXTRA or any(p in name for p in _READ_ONLY_PATTERNS)


def is_destructive(name: str) -> bool:
    if is_read_only(name) or name in _NOT_DESTRUCTIVE or name in _FILE_OUTPUT_TOOLS:
        return False
    return name in _DESTRUCTIVE_EXTRA or any(p in name for p in _DESTRUCTIVE_PATTERNS)


def is_idempotent(name: str) -> bool:
    if is_read_only(name) or name in _FILE_OUTPUT_TOOLS:
        return True
    return name in _IDEMPOTENT_EXTRA or any(p in name for p in _IDEMPOTENT_PATTERNS)


def tool_title(name: str) -> str:
    """Human-readable title: ``cst_get_s_parameters`` -> ``Get S Parameters``."""
    stem = name.removeprefix("cst_")
    words = [w for w in stem.split("_") if w]
    return " ".join(_TITLE_WORDS.get(w, w.capitalize()) for w in words) or name


def annotations_for(name: str) -> ToolAnnotations:
    """Return the MCP annotations for a tool name."""
    read_only = is_read_only(name)
    return ToolAnnotations(
        title=tool_title(name),
        readOnlyHint=read_only,
        destructiveHint=is_destructive(name),
        idempotentHint=is_idempotent(name),
        openWorldHint=False,
    )
