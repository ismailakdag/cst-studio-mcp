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
    E_FIELD = "Efield"
    H_FIELD = "Hfield"
    POWER_FLOW = "Powerflow"
    CURRENT = "Current"
    POWER_LOSS = "Powerloss"
    E_ENERGY = "Eenergy"
    H_ENERGY = "Henergy"
    FARFIELD = "Farfield"
    SURFACE_CURRENT = "Surfacecurrent"


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
