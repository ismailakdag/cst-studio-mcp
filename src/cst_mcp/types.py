"""Type definitions for CST Studio MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProjectType(str, Enum):
    MWS = "MWS"  # Microwave Studio
    EMS = "EMS"  # EM Studio
    PS = "PS"  # Particle Studio
    MPS = "MPS"  # Mphysics Studio
    CS = "CS"  # Cable Studio
    DS = "DS"  # Design Studio
    PCB = "PCB"  # PCB Studio


class MeshType(str, Enum):
    HEXAHEDRAL = "Hexahedral"
    TETRAHEDRAL = "Tetrahedral"
    SURFACE = "Surface"
    HEXAHEDRAL_TLM = "Hexahedral TLM"


class FieldMonitorType(str, Enum):
    """``Monitor.FieldType`` values documented for CST 2026 (VBA Monitor object).

    There is no "Surfacecurrent" field type: CST 2026 silently ignores it and
    creates no usable monitor.  Surface current comes from an ``Hfield``
    monitor, which yields both ``2D/3D Results\\H-Field\\...`` and
    ``2D/3D Results\\Surface Current\\surface current (f=...) [1]``.
    ``SURFACE_CURRENT`` is kept as an enum *alias* of ``H_FIELD`` for backward
    compatibility, so iterating the enum lists only valid CST values.
    """

    E_FIELD = "Efield"
    H_FIELD = "Hfield"
    POWER_FLOW = "Powerflow"
    CURRENT = "Current"
    POWER_LOSS = "Powerloss"
    E_ENERGY = "Eenergy"
    H_ENERGY = "Henergy"
    FARFIELD = "Farfield"
    FIELD_SOURCE = "Fieldsource"
    SPACE_CHARGE = "Spacecharge"
    PARTICLE_CURRENT_DENSITY = "Particlecurrentdensity"
    # Alias (same value) -> FieldMonitorType.SURFACE_CURRENT is FieldMonitorType.H_FIELD
    SURFACE_CURRENT = "Hfield"


# Request spellings that do not exist as a CST FieldType but map to one.
_FIELD_TYPE_ALIASES: dict[str, str] = {
    "surfacecurrent": "Hfield",
    "surface current": "Hfield",
    "surface_current": "Hfield",
    "surface-current": "Hfield",
    "surfacecurrentdensity": "Hfield",
    "js": "Hfield",
    "e-field": "Efield",
    "e_field": "Efield",
    "e field": "Efield",
    "h-field": "Hfield",
    "h_field": "Hfield",
    "h field": "Hfield",
    "power flow": "Powerflow",
    "poynting": "Powerflow",
    "power loss": "Powerloss",
    "loss": "Powerloss",
    "far field": "Farfield",
    "far-field": "Farfield",
}


def normalize_field_monitor_type(value: str) -> tuple[str, str | None]:
    """Map a requested monitor type to a documented ``Monitor.FieldType``.

    Returns ``(field_type, note)``; ``note`` explains a translation (e.g.
    "surface current" -> "Hfield") and is ``None`` for an exact match.
    Raises ``ValueError`` for values CST does not document.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("monitor_type must be a non-empty string")
    raw = value.strip()
    valid = [e.value for e in FieldMonitorType]
    if raw in valid:
        return raw, None
    lowered = raw.lower()
    for v in valid:
        if v.lower() == lowered:
            return v, f"monitor_type '{raw}' normalised to CST FieldType '{v}'."
    alias = _FIELD_TYPE_ALIASES.get(lowered)
    if alias:
        note = f"monitor_type '{raw}' is not a CST FieldType; using '{alias}'."
        if alias == "Hfield" and ("surface" in lowered or lowered == "js"):
            note = (
                f"'{raw}' is not a valid CST 2026 Monitor.FieldType (CST silently ignores "
                "'Surfacecurrent'). Surface current is produced by an 'Hfield' monitor, which "
                "creates both the H-Field and the Surface Current result items."
            )
        return alias, note
    raise ValueError(
        f"Invalid monitor_type '{raw}'. CST 2026 Monitor.FieldType values: {valid} "
        "(use 'Hfield' for surface current)."
    )


def expected_monitor_tree_items(field_type: str, name: str, frequency: float) -> list[str]:
    """Result-tree items a frequency monitor of ``field_type`` produces after a solve.

    The ``[1]`` suffix is the excitation index (port 1); multi-port runs add ``[2]`` etc.
    Only types whose tree layout was observed live are listed (the Surface
    Current naming comes from a CST 2026 campaign with Hfield monitors named
    "h-field (f=X)"); other types return ``[]`` -- list the result tree after
    the solve (cst_list_results) instead of guessing.
    """
    f = f"{float(frequency):g}"
    items = {
        "Efield": [f"2D/3D Results\\E-Field\\{name} [1]"],
        "Hfield": [
            f"2D/3D Results\\H-Field\\{name} [1]",
            f"2D/3D Results\\Surface Current\\surface current (f={f}) [1]",
        ],
        "Farfield": [f"Farfields\\{name} [1]"],
    }
    return items.get(field_type, [])


class ExcitationType(str, Enum):
    GAUSSIAN = "Gaussian"
    RECTANGULAR = "Rectangular"
    SMOOTH = "Smooth"
    CONSTANT = "Constant"
    USER_DEFINED = "User defined"


class ExportFormat(str, Enum):
    STL = "stl"
    SAT = "sat"
    STEP = "stp"
    IGES = "igs"
    OBJ = "obj"
    NASTRAN = "nas"


@dataclass
class FrequencyRange:
    f_min: float = 0.0
    f_max: float = 10.0
    unit: str = "GHz"
