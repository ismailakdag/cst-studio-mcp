"""Type definitions for CST Studio MCP server."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProjectType(str, Enum):
    MWS = "MWS"  # Microwave Studio
    EMS = "EMS"  # EM Studio
    PS = "PS"  # Particle Studio
    MPS = "MPS"  # Mphysics Studio
    CS = "CS"  # Cable Studio
    DS = "DS"  # Design Studio
    PCB = "PCB"  # PCB Studio


class SolverType(str, Enum):
    TIME_DOMAIN = "Time Domain"
    FREQUENCY_DOMAIN = "Frequency Domain"
    EIGENMODE = "Eigenmode"
    INTEGRAL_EQUATION = "Integral Equation"
    MULTILAYER = "Multilayer"
    ASYMPTOTIC = "Asymptotic"


class BoundaryType(str, Enum):
    OPEN = "open"
    OPEN_ADD_SPACE = "open (add space)"
    ELECTRIC = "electric"
    MAGNETIC = "magnetic"
    PERIODIC = "periodic"
    CONDUCTING_WALL = "conducting wall"
    UNIT_CELL = "unit cell"
    PML = "expanded open"


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


class PortType(str, Enum):
    WAVEGUIDE = "Waveguide"
    DISCRETE = "Discrete"
    LUMPED = "Lumped Element"
    PLANE_WAVE = "Plane Wave"
    FLOQUET = "Floquet"


class ExcitationType(str, Enum):
    GAUSSIAN = "Gaussian"
    RECTANGULAR = "Rectangular"
    SMOOTH = "Smooth"
    CONSTANT = "Constant"
    USER_DEFINED = "User defined"


class MaterialType(str, Enum):
    PEC = "PEC"
    NORMAL = "Normal"
    ANISOTROPIC = "Anisotropic"
    LOSSY_METAL = "Lossy metal"
    CORRUGATED_WALL = "Corrugated wall"
    OHMIC_SHEET = "Ohmic sheet"
    TENSOR_FORMULA = "Tensor formula"
    DEBYE = "Debye"
    LORENTZ = "Lorentz"
    DRUDE = "Drude"
    FERRITE = "Ferrite"
    COLE_COLE = "Cole-Cole"


class BooleanOp(str, Enum):
    ADD = "Add"
    SUBTRACT = "Subtract"
    INTERSECT = "Intersect"
    INSERT = "Insert"


class ExportFormat(str, Enum):
    STL = "stl"
    SAT = "sat"
    STEP = "stp"
    IGES = "igs"
    OBJ = "obj"
    NASTRAN = "nas"


class ImportFormat(str, Enum):
    STL = "stl"
    SAT = "sat"
    STEP = "stp"
    IGES = "igs"
    OBJ = "obj"
    DXF = "dxf"
    GERBER = "gbr"


class SymmetryPlane(str, Enum):
    NONE = "none"
    ELECTRIC = "electric"
    MAGNETIC = "magnetic"


class AntennaType(str, Enum):
    PATCH = "patch"
    DIPOLE = "dipole"
    MONOPOLE = "monopole"
    HORN = "horn"
    YAGI = "yagi"
    HELIX = "helix"
    VIVALDI = "vivaldi"
    SLOT = "slot"
    IFA = "ifa"
    PIFA = "pifa"
    SPIRAL = "spiral"
    BOWTIE = "bowtie"
    LOOP = "loop"


@dataclass
class Point3D:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def to_vba(self) -> str:
        return f"{self.x}, {self.y}, {self.z}"


@dataclass
class BoundingBox:
    x_min: float = 0.0
    x_max: float = 0.0
    y_min: float = 0.0
    y_max: float = 0.0
    z_min: float = 0.0
    z_max: float = 0.0


@dataclass
class FrequencyRange:
    f_min: float = 0.0
    f_max: float = 10.0
    unit: str = "GHz"


@dataclass
class MaterialProperties:
    name: str = ""
    epsilon: float = 1.0
    mu: float = 1.0
    tan_d_e: float = 0.0
    tan_d_m: float = 0.0
    conductivity: float = 0.0
    rho: float = 0.0
    color: tuple[float, float, float] = (0.6, 0.6, 0.6)
    transparency: float = 0.0


@dataclass
class PortDefinition:
    port_number: int = 1
    port_type: PortType = PortType.WAVEGUIDE
    orientation: str = "zmax"
    x_range: tuple[float, float] = (0.0, 0.0)
    y_range: tuple[float, float] = (0.0, 0.0)
    z_range: tuple[float, float] = (0.0, 0.0)
    impedance: float = 50.0
    mode_number: int = 1


@dataclass
class SolverSettings:
    solver_type: SolverType = SolverType.TIME_DOMAIN
    accuracy: float = -40.0  # dB
    max_time_steps: int = 0  # 0 = auto
    mesh_cells_per_wavelength: int = 15
    adaptive_mesh_refinement: bool = True
    max_mesh_adaptation: int = 3


@dataclass
class PCBLayer:
    name: str = ""
    layer_type: str = "signal"  # signal, ground, power, dielectric
    thickness_mm: float = 0.035
    material: str = "Copper"
    epsilon_r: float = 1.0


@dataclass
class PCBStackup:
    name: str = ""
    layers: list[PCBLayer] = field(default_factory=list)
    total_thickness_mm: float = 0.0


@dataclass
class AntennaDesign:
    antenna_type: AntennaType = AntennaType.PATCH
    frequency_ghz: float = 2.45
    substrate_name: str = "FR-4"
    substrate_height_mm: float = 1.6
    substrate_epsilon_r: float = 4.4
    substrate_tan_d: float = 0.02
    ground_plane: bool = True
    parameters: dict = field(default_factory=dict)
    vba_script: str = ""
    notes: str = ""


@dataclass
class SimulationStatus:
    running: bool = False
    progress: float = 0.0
    solver_type: str = ""
    mesh_cells: int = 0
    current_step: int = 0
    max_steps: int = 0
    elapsed_time: float = 0.0
    estimated_remaining: float = 0.0
    converged: bool = False


@dataclass
class SParameterResult:
    frequency_ghz: list[float] = field(default_factory=list)
    s11_db: list[float] = field(default_factory=list)
    s11_phase: list[float] = field(default_factory=list)
    s21_db: list[float] = field(default_factory=list)
    s21_phase: list[float] = field(default_factory=list)
    impedance_real: list[float] = field(default_factory=list)
    impedance_imag: list[float] = field(default_factory=list)


@dataclass
class FarfieldResult:
    frequency_ghz: float = 0.0
    gain_dbi: float = 0.0
    directivity_dbi: float = 0.0
    efficiency: float = 0.0
    beam_width_e: float = 0.0
    beam_width_h: float = 0.0
    front_to_back_db: float = 0.0
    polarization: str = "linear"


@dataclass
class GroupDelayResult:
    frequency_ghz: list[float] = field(default_factory=list)
    group_delay_ns: list[float] = field(default_factory=list)


@dataclass
class PatternCutResult:
    angle_deg: list[float] = field(default_factory=list)
    gain_dbi: list[float] = field(default_factory=list)
    plane: str = "E"
    frequency_ghz: float = 0.0


@dataclass
class EfficiencyBreakdown:
    radiation_efficiency: float = 0.0
    total_efficiency: float = 0.0
    mismatch_loss_db: float = 0.0
    conductor_loss_db: float = 0.0
    dielectric_loss_db: float = 0.0
