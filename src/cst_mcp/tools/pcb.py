"""PCB layout and signal integrity tools for CST Studio Suite.

Provides 6 MCP tools for creating PCB stackups, traces, vias, ground planes,
importing Gerber files, and listing predefined stackup templates.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.types import Tool, TextContent

from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBABuilder, VBAScript
from cst_mcp.validators import (
    validate_file_path,
    validate_name,
    validate_positive,
    validate_range,
)

if TYPE_CHECKING:
    from mcp.server import Server

DATA_DIR = Path(__file__).parent.parent / "data"

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # 1. Create PCB stackup
    Tool(
        name="cst_pcb_create_stackup",
        description=(
            "Create a PCB layer stackup in CST Studio. Generates brick geometry for "
            "each layer (signal, ground, power, dielectric) positioned vertically with "
            "correct materials. Returns total thickness and layer positions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "layers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Layer name (e.g. 'Top', 'Core', 'GND')",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["signal", "ground", "power", "dielectric"],
                                "description": "Layer type",
                            },
                            "thickness_mm": {
                                "type": "number",
                                "description": "Layer thickness in mm (e.g. 0.035 for 1oz copper)",
                            },
                            "material": {
                                "type": "string",
                                "description": "Material name (e.g. 'Copper', 'FR-4')",
                            },
                            "epsilon_r": {
                                "type": "number",
                                "description": "Relative permittivity (1.0 for copper, 4.4 for FR-4)",
                            },
                        },
                        "required": ["name", "type", "thickness_mm", "material", "epsilon_r"],
                    },
                    "minItems": 2,
                    "description": (
                        "Ordered list of layers from top to bottom. Example 4-layer: "
                        "signal-dielectric-ground-dielectric(core)-power-dielectric-signal"
                    ),
                },
                "board_width_mm": {
                    "type": "number",
                    "description": "Board width in mm (X dimension)",
                },
                "board_length_mm": {
                    "type": "number",
                    "description": "Board length in mm (Y dimension)",
                },
            },
            "required": ["layers", "board_width_mm", "board_length_mm"],
        },
    ),

    # 2. Create PCB trace
    Tool(
        name="cst_pcb_create_trace",
        description=(
            "Create a PCB trace (microstrip, stripline, coplanar waveguide, or grounded "
            "CPW) in CST Studio. Optionally calculates trace width from a target impedance "
            "using Hammerstad-Jensen (microstrip) or Cohn (stripline) formulas."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "trace_type": {
                    "type": "string",
                    "enum": ["microstrip", "stripline", "coplanar_waveguide", "grounded_cpw"],
                    "description": "Type of transmission line",
                },
                "width_mm": {
                    "type": "number",
                    "description": (
                        "Trace width in mm. If impedance_target is specified, this is "
                        "ignored and the width is calculated automatically."
                    ),
                },
                "length_mm": {
                    "type": "number",
                    "description": "Trace length in mm",
                },
                "layer": {
                    "type": "string",
                    "description": "Layer name where the trace is placed (e.g. 'Top')",
                },
                "x_start": {
                    "type": "number",
                    "description": "X coordinate of trace start (mm)",
                    "default": 0,
                },
                "y_start": {
                    "type": "number",
                    "description": "Y coordinate of trace start (mm)",
                    "default": 0,
                },
                "direction": {
                    "type": "string",
                    "description": (
                        "Trace direction: 'x' for +X, 'y' for +Y, or angle in degrees "
                        "from +X axis (e.g. '45')"
                    ),
                    "default": "x",
                },
                "impedance_target": {
                    "type": "number",
                    "description": (
                        "Target characteristic impedance in ohms. When specified, trace "
                        "width is auto-calculated. Requires substrate_height_mm and epsilon_r."
                    ),
                },
                "substrate_height_mm": {
                    "type": "number",
                    "description": (
                        "Substrate height between trace and reference plane (mm). "
                        "Required when impedance_target is given."
                    ),
                },
                "epsilon_r": {
                    "type": "number",
                    "description": (
                        "Substrate relative permittivity. Required when impedance_target is given."
                    ),
                },
                "copper_thickness_mm": {
                    "type": "number",
                    "description": "Copper thickness in mm (default 0.035 for 1oz)",
                    "default": 0.035,
                },
                "z_position": {
                    "type": "number",
                    "description": (
                        "Z position of the trace bottom surface in mm. If omitted, "
                        "defaults to 0 (top surface of the board)."
                    ),
                    "default": 0,
                },
            },
            "required": ["trace_type", "length_mm", "layer"],
        },
    ),

    # 3. Create PCB via
    Tool(
        name="cst_pcb_create_via",
        description=(
            "Create a PCB via (through, blind, or buried) in CST Studio. Generates "
            "the cylindrical via barrel with specified drill and pad dimensions. "
            "Pad and antipad diameters are validated and reported but the geometry "
            "covers the barrel only; add pads separately if needed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "Via X position in mm",
                },
                "y": {
                    "type": "number",
                    "description": "Via Y position in mm",
                },
                "drill_diameter_mm": {
                    "type": "number",
                    "description": "Drill hole diameter in mm",
                    "default": 0.3,
                },
                "pad_diameter_mm": {
                    "type": "number",
                    "description": "Annular pad diameter in mm",
                    "default": 0.6,
                },
                "antipad_diameter_mm": {
                    "type": "number",
                    "description": "Antipad (clearance) diameter in plane layers in mm",
                    "default": 0.8,
                },
                "start_layer": {
                    "type": "string",
                    "description": "Name of the starting layer (e.g. 'Top')",
                },
                "end_layer": {
                    "type": "string",
                    "description": "Name of the ending layer (e.g. 'Bottom')",
                },
                "start_z": {
                    "type": "number",
                    "description": "Z coordinate of the via start (top) in mm",
                },
                "end_z": {
                    "type": "number",
                    "description": "Z coordinate of the via end (bottom) in mm",
                },
                "via_type": {
                    "type": "string",
                    "enum": ["through", "blind", "buried"],
                    "description": "Via type",
                    "default": "through",
                },
                "name": {
                    "type": "string",
                    "description": "Via name for the CST model (auto-generated if omitted)",
                },
            },
            "required": ["x", "y", "start_layer", "end_layer", "start_z", "end_z"],
        },
    ),

    # 4. Create ground/power plane
    Tool(
        name="cst_pcb_create_ground_plane",
        description=(
            "Create a ground or power plane with optional cutouts (split planes, "
            "isolation slots) in CST Studio. Generates a solid copper brick and "
            "subtracts cutout regions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "layer": {
                    "type": "string",
                    "description": "Layer name (e.g. 'GND', 'PWR')",
                },
                "width_mm": {
                    "type": "number",
                    "description": "Plane width in mm (X dimension)",
                },
                "length_mm": {
                    "type": "number",
                    "description": "Plane length in mm (Y dimension)",
                },
                "z_position": {
                    "type": "number",
                    "description": "Z position of the plane bottom surface in mm",
                    "default": 0,
                },
                "thickness_mm": {
                    "type": "number",
                    "description": "Copper thickness in mm (default 0.035 for 1oz)",
                    "default": 0.035,
                },
                "cutouts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x_min": {"type": "number", "description": "Cutout X minimum in mm"},
                            "x_max": {"type": "number", "description": "Cutout X maximum in mm"},
                            "y_min": {"type": "number", "description": "Cutout Y minimum in mm"},
                            "y_max": {"type": "number", "description": "Cutout Y maximum in mm"},
                        },
                        "required": ["x_min", "x_max", "y_min", "y_max"],
                    },
                    "description": "Optional list of rectangular cutout regions",
                },
            },
            "required": ["layer", "width_mm", "length_mm"],
        },
    ),

    # 5. Import Gerber files
    Tool(
        name="cst_pcb_import_gerber",
        description=(
            "Import a Gerber/ODB++/DXF file for PCB analysis in CST Studio. Generates "
            "VBA for the CST Gerber import wizard. In offline mode, explains the import "
            "process and required settings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Gerber file (.gbr, .ger, .gtl, .gbl, etc.)",
                },
                "layer_name": {
                    "type": "string",
                    "description": "Target layer name in the CST model",
                },
                "file_type": {
                    "type": "string",
                    "enum": ["gerber", "odb++", "dxf"],
                    "description": "Import file format",
                    "default": "gerber",
                },
            },
            "required": ["file_path", "layer_name"],
        },
    ),

    # 6. List stackup templates
    Tool(
        name="cst_pcb_list_stackup_templates",
        description=(
            "List predefined PCB stackup templates with complete layer definitions. "
            "Includes standard 2/4/6-layer FR-4 and RF-grade Rogers stackups. "
            "Use the returned layer data directly with cst_pcb_create_stackup."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "Optional filter string to match template names "
                        "(e.g. '4-layer', 'Rogers', 'RF'). Case-insensitive."
                    ),
                },
            },
            "required": [],
        },
    ),

    # 7. Create differential pair traces
    Tool(
        name="cst_pcb_differential_pair",
        description=(
            "Create a differential pair of PCB traces in CST Studio. Generates two "
            "parallel bricks separated by a gap and calculates the differential "
            "impedance using coupled-line theory (Zdiff = 2*Z0*(1-k))."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Base name for the differential pair (e.g. 'USB_DP')",
                },
                "component": {
                    "type": "string",
                    "description": "CST component name",
                    "default": "PCB",
                },
                "trace_width_mm": {
                    "type": "number",
                    "description": "Width of each trace in mm",
                },
                "gap_mm": {
                    "type": "number",
                    "description": "Gap between the two traces in mm",
                },
                "length_mm": {
                    "type": "number",
                    "description": "Trace length in mm",
                },
                "layer": {
                    "type": "string",
                    "description": "Layer name (e.g. 'Top')",
                },
                "target_impedance_diff": {
                    "type": "number",
                    "description": "Target differential impedance in ohms",
                    "default": 100,
                },
                "epsilon_r": {
                    "type": "number",
                    "description": "Substrate relative permittivity",
                    "default": 4.4,
                },
                "height_mm": {
                    "type": "number",
                    "description": "Substrate height to reference plane in mm",
                    "default": 1.5,
                },
                "x_start": {
                    "type": "number",
                    "description": "X coordinate of the pair center start in mm",
                    "default": 0,
                },
                "y_start": {
                    "type": "number",
                    "description": "Y coordinate of the pair center start in mm",
                    "default": 0,
                },
            },
            "required": ["name", "trace_width_mm", "gap_mm", "length_mm", "layer"],
        },
    ),

    # 8. Detailed via model with parasitics
    Tool(
        name="cst_pcb_via_model",
        description=(
            "Create a detailed PCB via model in CST Studio with parasitic inductance "
            "and capacitance estimates. Uses the Goldfarb model for via inductance "
            "and a simplified capacitance formula."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Via name for the CST model",
                },
                "component": {
                    "type": "string",
                    "description": "CST component name",
                    "default": "PCB",
                },
                "drill_diameter_mm": {
                    "type": "number",
                    "description": "Drill hole diameter in mm",
                },
                "pad_diameter_mm": {
                    "type": "number",
                    "description": "Annular pad diameter in mm",
                },
                "antipad_diameter_mm": {
                    "type": "number",
                    "description": "Antipad (clearance) diameter in mm",
                },
                "barrel_plating_um": {
                    "type": "number",
                    "description": "Barrel plating thickness in micrometers",
                    "default": 25,
                },
                "start_layer": {
                    "type": "string",
                    "description": "Name of the starting (top) layer",
                },
                "end_layer": {
                    "type": "string",
                    "description": "Name of the ending (bottom) layer",
                },
                "x": {
                    "type": "number",
                    "description": "Via X position in mm",
                },
                "y": {
                    "type": "number",
                    "description": "Via Y position in mm",
                },
                "board_thickness_mm": {
                    "type": "number",
                    "description": "Board thickness in mm",
                    "default": 1.6,
                },
                "epsilon_r": {
                    "type": "number",
                    "description": "Substrate relative permittivity",
                    "default": 4.4,
                },
            },
            "required": [
                "name", "drill_diameter_mm", "pad_diameter_mm",
                "antipad_diameter_mm", "start_layer", "end_layer", "x", "y",
            ],
        },
    ),

    # 9. Via fence for isolation or SIW
    Tool(
        name="cst_pcb_via_fence",
        description=(
            "Create a row (or multiple rows) of vias along a path for isolation "
            "or Substrate Integrated Waveguide (SIW) construction. Generates an "
            "array of cylinders from start to end point with specified spacing."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Base name for the via fence",
                },
                "component": {
                    "type": "string",
                    "description": "CST component name",
                    "default": "PCB",
                },
                "x_start": {
                    "type": "number",
                    "description": "X coordinate of the fence start in mm",
                },
                "y_start": {
                    "type": "number",
                    "description": "Y coordinate of the fence start in mm",
                },
                "x_end": {
                    "type": "number",
                    "description": "X coordinate of the fence end in mm",
                },
                "y_end": {
                    "type": "number",
                    "description": "Y coordinate of the fence end in mm",
                },
                "via_spacing_mm": {
                    "type": "number",
                    "description": "Center-to-center spacing between vias in mm",
                },
                "via_diameter_mm": {
                    "type": "number",
                    "description": "Via drill diameter in mm",
                },
                "pad_diameter_mm": {
                    "type": "number",
                    "description": "Via pad diameter in mm",
                },
                "rows": {
                    "type": "integer",
                    "description": "Number of parallel rows (1-3)",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 3,
                },
                "row_offset_mm": {
                    "type": "number",
                    "description": "Lateral offset between rows for staggering in mm",
                    "default": 0,
                },
            },
            "required": [
                "name", "x_start", "y_start", "x_end", "y_end",
                "via_spacing_mm", "via_diameter_mm", "pad_diameter_mm",
            ],
        },
    ),

    # 10. CPW to microstrip transition
    Tool(
        name="cst_pcb_cpw_transition",
        description=(
            "Create a coplanar waveguide (CPW) to microstrip transition in CST Studio. "
            "Generates a tapered geometry that linearly tapers the center conductor "
            "width and gap over the transition length. Calculates CPW and microstrip "
            "impedances."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the transition structure",
                },
                "component": {
                    "type": "string",
                    "description": "CST component name",
                    "default": "PCB",
                },
                "transition_type": {
                    "type": "string",
                    "enum": ["cpw_to_microstrip", "gcpw_to_microstrip"],
                    "description": "Type of transition",
                    "default": "cpw_to_microstrip",
                },
                "cpw_width_mm": {
                    "type": "number",
                    "description": "CPW center conductor width in mm",
                },
                "cpw_gap_mm": {
                    "type": "number",
                    "description": "CPW gap width in mm",
                },
                "microstrip_width_mm": {
                    "type": "number",
                    "description": "Microstrip trace width at the end of the transition in mm",
                },
                "transition_length_mm": {
                    "type": "number",
                    "description": "Length of the tapered transition in mm",
                },
                "layer": {
                    "type": "string",
                    "description": "Layer name (e.g. 'Top')",
                },
                "height_mm": {
                    "type": "number",
                    "description": "Substrate height to reference plane in mm",
                },
                "epsilon_r": {
                    "type": "number",
                    "description": "Substrate relative permittivity",
                    "default": 4.4,
                },
            },
            "required": [
                "name", "cpw_width_mm", "cpw_gap_mm", "microstrip_width_mm",
                "transition_length_mm", "layer", "height_mm",
            ],
        },
    ),

    # 11. Calculate coupling between parallel traces (pure Python)
    Tool(
        name="cst_pcb_calculate_coupling",
        description=(
            "Calculate electromagnetic coupling between parallel PCB traces. "
            "Computes even/odd mode impedances, coupling coefficient, and "
            "near-end/far-end crosstalk estimates using coupled microstrip formulas. "
            "Pure calculation — no VBA or CST geometry is generated."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "trace_width_mm": {
                    "type": "number",
                    "description": "Width of each trace in mm",
                },
                "separation_mm": {
                    "type": "number",
                    "description": "Edge-to-edge separation between traces in mm",
                },
                "height_mm": {
                    "type": "number",
                    "description": "Substrate height to reference plane in mm",
                },
                "epsilon_r": {
                    "type": "number",
                    "description": "Substrate relative permittivity",
                },
                "coupling_length_mm": {
                    "type": "number",
                    "description": "Parallel coupling length in mm",
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Operating frequency in GHz",
                },
            },
            "required": [
                "trace_width_mm", "separation_mm", "height_mm",
                "epsilon_r", "coupling_length_mm", "frequency_ghz",
            ],
        },
    ),

    # 12. Substrate Integrated Waveguide
    Tool(
        name="cst_pcb_siw_waveguide",
        description=(
            "Create a Substrate Integrated Waveguide (SIW) in CST Studio. Generates "
            "top and bottom copper planes with two rows of via fences forming the "
            "waveguide sidewalls. Calculates effective width, cutoff frequency, and "
            "guided wavelength using Cassivi et al. formulas."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the SIW structure",
                },
                "component": {
                    "type": "string",
                    "description": "CST component name",
                    "default": "PCB",
                },
                "width_mm": {
                    "type": "number",
                    "description": "SIW width (center-to-center of via rows) in mm",
                },
                "via_diameter_mm": {
                    "type": "number",
                    "description": "Via drill diameter in mm",
                },
                "via_pitch_mm": {
                    "type": "number",
                    "description": "Center-to-center via spacing along the length in mm",
                },
                "length_mm": {
                    "type": "number",
                    "description": "SIW length in mm",
                },
                "layer": {
                    "type": "string",
                    "description": "Layer name (e.g. 'Top')",
                },
                "epsilon_r": {
                    "type": "number",
                    "description": "Substrate relative permittivity",
                    "default": 4.4,
                },
                "height_mm": {
                    "type": "number",
                    "description": "Substrate height in mm",
                    "default": 1.5,
                },
                "x_start": {
                    "type": "number",
                    "description": "X coordinate of the SIW start in mm",
                    "default": 0,
                },
                "y_start": {
                    "type": "number",
                    "description": "Y coordinate of the SIW start in mm",
                    "default": 0,
                },
            },
            "required": [
                "name", "width_mm", "via_diameter_mm", "via_pitch_mm",
                "length_mm", "layer",
            ],
        },
    ),
]


# ---------------------------------------------------------------------------
# Impedance calculation helpers
# ---------------------------------------------------------------------------


def _microstrip_impedance(w: float, h: float, er: float, t: float = 0.035) -> float:
    """Calculate microstrip characteristic impedance using Hammerstad-Jensen.

    Parameters
    ----------
    w : float  - trace width (mm)
    h : float  - substrate height (mm)
    er : float - relative permittivity
    t : float  - conductor thickness (mm)

    Returns
    -------
    float - characteristic impedance in ohms
    """
    # Effective width correction for finite conductor thickness
    if t > 0 and w > 0:
        dw = (t / math.pi) * (1.0 + math.log(2.0 * h / t))
        we = w + dw
    else:
        we = w

    u = we / h

    # Hammerstad-Jensen effective dielectric constant
    eps_eff = 0.5 * (er + 1.0) + 0.5 * (er - 1.0) * (1.0 + 10.0 / u) ** (-0.5)  # noqa: E501

    # Hammerstad-Jensen impedance
    f = 6.0 + (2.0 * math.pi - 6.0) * math.exp(-(30.666 / u) ** 0.7528)
    z0 = (60.0 / math.sqrt(eps_eff)) * math.log(f / u + math.sqrt(1.0 + (2.0 / u) ** 2))  # noqa: E501

    return z0


def _microstrip_width_for_impedance(
    z_target: float, h: float, er: float, t: float = 0.035
) -> float:
    """Calculate microstrip width for a target impedance (iterative).

    Uses Newton-Raphson iteration starting from the Wheeler approximation.

    Parameters
    ----------
    z_target : float - target impedance (ohms)
    h : float        - substrate height (mm)
    er : float       - relative permittivity
    t : float        - conductor thickness (mm)

    Returns
    -------
    float - trace width in mm
    """
    # Wheeler initial estimate
    a = (z_target / 60.0) * math.sqrt((er + 1.0) / 2.0) + \
        ((er - 1.0) / (er + 1.0)) * (0.23 + 0.11 / er)
    b = 377.0 * math.pi / (2.0 * z_target * math.sqrt(er))

    if a > 1.52:
        w_h = 8.0 * math.exp(a) / (math.exp(2.0 * a) - 2.0)
    else:
        w_h = (2.0 / math.pi) * (
            b - 1.0 - math.log(2.0 * b - 1.0)
            + ((er - 1.0) / (2.0 * er)) * (math.log(b - 1.0) + 0.39 - 0.61 / er)
        )

    w = w_h * h

    # Refine with Newton-Raphson (up to 20 iterations)
    for _ in range(20):
        z_calc = _microstrip_impedance(w, h, er, t)
        error = z_calc - z_target
        if abs(error) < 0.01:
            break
        # Numerical derivative
        dw = w * 0.001
        z_plus = _microstrip_impedance(w + dw, h, er, t)
        dz_dw = (z_plus - z_calc) / dw
        if abs(dz_dw) < 1e-12:
            break
        w = w - error / dz_dw
        w = max(w, 0.001)  # Prevent negative width

    return w


def _stripline_impedance(w: float, h: float, er: float, t: float = 0.035) -> float:
    """Calculate stripline characteristic impedance using Cohn's formula.

    Parameters
    ----------
    w : float  - trace width (mm)
    h : float  - total distance between ground planes (mm)
    er : float - relative permittivity
    t : float  - conductor thickness (mm)

    Returns
    -------
    float - characteristic impedance in ohms
    """
    b = h  # distance between ground planes
    # Effective width correction (Cohn)
    if t > 0 and t < b:
        m = 2.0 / (1.0 + t / b)
        we = w + (t / math.pi) * (1.0 + math.log(4.0 * math.pi * w / t)) * (m / 2.0)
    else:
        we = w

    # Cohn formula for centered stripline
    if we / b < 0.35:
        z0 = (60.0 / math.sqrt(er)) * math.log(
            4.0 * b / (math.pi * we)
        )
    else:
        cf = 2.0 * math.pi
        z0 = (94.25 / math.sqrt(er)) / (
            we / b + cf * math.log(1.0 + 1.0 / math.tanh(cf * we / (2.0 * b)))  # noqa: E501
            / math.pi
        )

    return z0


def _stripline_width_for_impedance(
    z_target: float, h: float, er: float, t: float = 0.035
) -> float:
    """Calculate stripline width for a target impedance (iterative).

    Parameters
    ----------
    z_target : float - target impedance (ohms)
    h : float        - total distance between ground planes (mm)
    er : float       - relative permittivity
    t : float        - conductor thickness (mm)

    Returns
    -------
    float - trace width in mm
    """
    # Initial estimate from inverted Cohn narrow-strip formula
    x = math.exp(z_target * math.sqrt(er) / 60.0)
    w = 4.0 * h / (math.pi * x) if x > 0 else h * 0.5

    # Newton-Raphson refinement
    for _ in range(20):
        z_calc = _stripline_impedance(w, h, er, t)
        error = z_calc - z_target
        if abs(error) < 0.01:
            break
        dw = w * 0.001
        z_plus = _stripline_impedance(w + dw, h, er, t)
        dz_dw = (z_plus - z_calc) / dw
        if abs(dz_dw) < 1e-12:
            break
        w = w - error / dz_dw
        w = max(w, 0.001)

    return w


# ---------------------------------------------------------------------------
# Coupled-line impedance helpers
# ---------------------------------------------------------------------------


def _coupled_microstrip_impedances(
    w: float, s: float, h: float, er: float, t: float = 0.035
) -> tuple[float, float]:
    """Calculate even/odd mode impedances for coupled microstrips.

    Uses Kirschning & Jansen approximation for edge-coupled microstrip lines.

    Parameters
    ----------
    w : float  - trace width (mm)
    s : float  - edge-to-edge separation (mm)
    h : float  - substrate height (mm)
    er : float - relative permittivity
    t : float  - conductor thickness (mm)

    Returns
    -------
    tuple[float, float] - (Ze, Zo) even and odd mode impedances in ohms
    """
    z0_single = _microstrip_impedance(w, h, er, t)

    u = w / h
    g = s / h

    # Even-mode effective permittivity correction
    ae = 1.0 + (1.0 / 49.0) * math.log(
        (u ** 4 + (u / 52.0) ** 2) / (u ** 4 + 0.432)
    ) + (1.0 / 18.7) * math.log(1.0 + (u / 18.1) ** 3)
    be = 0.564 * ((er - 0.9) / (er + 3.0)) ** 0.053

    eps_eff_single = 0.5 * (er + 1.0) + 0.5 * (er - 1.0) * (1.0 + 10.0 / u) ** (-ae * be)

    # Even-mode impedance (approximate)
    # Ze increases relative to Z0 due to increased capacitance symmetry
    qe = 0.0
    if g > 0:
        qe = math.exp(-1.86 * g) * (1.0 - math.exp(-0.588 * (er - 1.0) ** 0.578))
    eps_eff_even = 0.5 * (er + 1.0) + 0.5 * (er - 1.0) * (
        (1.0 + 10.0 / u) ** (-ae * be)
    ) * (1.0 - qe)

    # Odd-mode effective permittivity correction
    ao = 0.7287 * (eps_eff_single - 0.5 * (er + 1.0)) * (1.0 - math.exp(-0.179 * g))
    eps_eff_odd = (0.5 * (er + 1.0) + ao + eps_eff_single) / 2.0

    # Capacitive coupling ratio
    if g > 0:
        cf_even = (1.0 / (1.0 + 0.6 * g)) * (0.02 * math.sqrt(er) * g + 1.0 - math.exp(-g))
        cf_odd = (1.0 / (1.0 + 0.6 * g)) * (0.02 * math.sqrt(er) * g + 1.0 - math.exp(-g))
    else:
        cf_even = 1.0
        cf_odd = 1.0

    # Even mode: impedance increases (less coupling to ground)
    ze = z0_single * math.sqrt(eps_eff_single / eps_eff_even) / (1.0 - z0_single * cf_even / (377.0 / math.sqrt(eps_eff_single)))
    # Odd mode: impedance decreases (more coupling to ground)
    zo = z0_single * math.sqrt(eps_eff_single / eps_eff_odd) * (1.0 - z0_single * cf_odd / (377.0 / math.sqrt(eps_eff_single)))

    # Ensure physical validity
    ze = max(ze, z0_single * 0.8)
    zo = min(zo, z0_single * 1.2)
    zo = max(zo, 10.0)  # Minimum physical value

    return ze, zo


def _cpw_impedance(w: float, gap: float, h: float, er: float) -> float:
    """Calculate coplanar waveguide impedance.

    Uses the conformal mapping approach for CPW on a dielectric substrate.

    Parameters
    ----------
    w : float   - center conductor width (mm)
    gap : float - gap width on each side (mm)
    h : float   - substrate height (mm)
    er : float  - relative permittivity

    Returns
    -------
    float - characteristic impedance in ohms
    """
    a = w / 2.0
    b = w / 2.0 + gap
    k0 = a / b
    k0p = math.sqrt(1.0 - k0 ** 2)

    # Complete elliptic integral ratio K(k)/K(k') approximation
    if k0 >= 1.0:
        return 30.0  # Degenerate case
    if k0 <= 0.0:
        return 300.0  # Degenerate case

    if k0 <= 1.0 / math.sqrt(2.0):
        kk0 = math.pi / math.log(2.0 * (1.0 + math.sqrt(k0p)) / (1.0 - math.sqrt(k0p)))
    else:
        kk0 = math.log(2.0 * (1.0 + math.sqrt(k0)) / (1.0 - math.sqrt(k0))) / math.pi

    # Substrate effect
    k1 = math.tanh(math.pi * a / (2.0 * h)) / math.tanh(math.pi * b / (2.0 * h))
    k1p = math.sqrt(1.0 - k1 ** 2)

    if k1 <= 1.0 / math.sqrt(2.0):
        kk1 = math.pi / math.log(2.0 * (1.0 + math.sqrt(k1p)) / (1.0 - math.sqrt(k1p)))
    else:
        kk1 = math.log(2.0 * (1.0 + math.sqrt(k1)) / (1.0 - math.sqrt(k1))) / math.pi

    eps_eff = 1.0 + (er - 1.0) / 2.0 * kk1 / kk0
    z0 = 30.0 * math.pi / (math.sqrt(eps_eff) * kk0)

    return z0


# ---------------------------------------------------------------------------
# VBA generation handlers
# ---------------------------------------------------------------------------


async def _handle_create_stackup(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Create a PCB layer stackup as stacked bricks in CST."""
    layers: list[dict] = arguments["layers"]
    board_w = validate_positive(float(arguments["board_width_mm"]), "board_width_mm")
    board_l = validate_positive(float(arguments["board_length_mm"]), "board_length_mm")

    script = VBAScript()
    script.add_comment("PCB Layer Stackup")

    half_w = board_w / 2.0
    half_l = board_l / 2.0
    z_current = 0.0
    layer_info: list[dict] = []

    for layer in layers:
        name = validate_name(layer["name"], "layer name")
        layer_type = layer["type"]
        thickness = validate_positive(float(layer["thickness_mm"]), "thickness_mm")
        material = layer["material"]

        z_bottom = z_current
        z_top = z_current + thickness

        # Determine component name based on layer type
        if layer_type == "dielectric":
            component = "PCB_Dielectric"
        elif layer_type in ("ground", "power"):
            component = "PCB_Planes"
        else:
            component = "PCB_Signal"

        vba = (
            VBABuilder("Brick")
            .call("Reset")
            .set("Name", name)
            .set("Component", component)
            .set("Material", material)
            .set_double("Xrange", -half_w, half_w)
            .set_double("Yrange", -half_l, half_l)
            .set_double("Zrange", z_bottom, z_top)
            .call("Create")
        )
        script.add_block(vba)

        layer_info.append({
            "name": name,
            "type": layer_type,
            "material": material,
            "z_bottom": round(z_bottom, 6),
            "z_top": round(z_top, 6),
            "thickness_mm": thickness,
        })

        z_current = z_top

    total_thickness = round(z_current, 6)
    vba_code = script.build()
    result = client.execute_vba(vba_code)
    result["total_thickness_mm"] = total_thickness
    result["layer_count"] = len(layers)
    result["layers"] = layer_info
    result["board_dimensions"] = {
        "width_mm": board_w,
        "length_mm": board_l,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_create_trace(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Create a PCB trace with optional impedance-based width calculation."""
    trace_type = arguments["trace_type"]
    length_mm = validate_positive(float(arguments["length_mm"]), "length_mm")
    layer = validate_name(arguments["layer"], "layer")
    x_start = float(arguments.get("x_start", 0))
    y_start = float(arguments.get("y_start", 0))
    direction = str(arguments.get("direction", "x"))
    copper_t = float(arguments.get("copper_thickness_mm", 0.035))
    z_pos = float(arguments.get("z_position", 0))

    impedance_target = arguments.get("impedance_target")
    width_mm = arguments.get("width_mm")
    impedance_info: dict = {}

    if impedance_target is not None:
        z_target = validate_positive(float(impedance_target), "impedance_target")
        sub_h = validate_positive(
            float(arguments["substrate_height_mm"]), "substrate_height_mm"
        )
        er = validate_positive(float(arguments["epsilon_r"]), "epsilon_r")

        if trace_type == "microstrip":
            width_mm = _microstrip_width_for_impedance(z_target, sub_h, er, copper_t)
            z_actual = _microstrip_impedance(width_mm, sub_h, er, copper_t)
        elif trace_type == "stripline":
            width_mm = _stripline_width_for_impedance(z_target, sub_h, er, copper_t)
            z_actual = _stripline_impedance(width_mm, sub_h, er, copper_t)
        elif trace_type in ("coplanar_waveguide", "grounded_cpw"):
            # For CPW, fall back to microstrip approximation with a note
            width_mm = _microstrip_width_for_impedance(z_target, sub_h, er, copper_t)
            z_actual = _microstrip_impedance(width_mm, sub_h, er, copper_t)
            impedance_info["note"] = (
                "CPW impedance depends on gap width (not modeled here). "
                "The width is estimated using microstrip formulas as a starting point. "
                "Use a 2D field solver for accurate CPW impedance."
            )
        else:
            width_mm = _microstrip_width_for_impedance(z_target, sub_h, er, copper_t)
            z_actual = _microstrip_impedance(width_mm, sub_h, er, copper_t)

        impedance_info.update({
            "target_ohms": z_target,
            "calculated_ohms": round(z_actual, 2),
            "calculated_width_mm": round(width_mm, 4),
            "substrate_height_mm": sub_h,
            "epsilon_r": er,
            "formula": "Hammerstad-Jensen" if trace_type == "microstrip" else "Cohn",
        })
    elif width_mm is None:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": (
                "Either width_mm or impedance_target must be specified. "
                "Provide width_mm for a fixed-width trace, or impedance_target "
                "with substrate_height_mm and epsilon_r for auto-calculation."
            ),
        }))]

    width_mm = validate_positive(float(width_mm), "width_mm")

    # Calculate trace end coordinates based on direction
    if direction.lower() == "x":
        angle_rad = 0.0
    elif direction.lower() == "y":
        angle_rad = math.pi / 2.0
    else:
        try:
            angle_rad = math.radians(float(direction))
        except ValueError:
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "message": f"Invalid direction '{direction}'. Use 'x', 'y', or angle in degrees.",
            }))]

    dx = length_mm * math.cos(angle_rad)
    dy = length_mm * math.sin(angle_rad)

    # The trace is a rectangle along the direction vector
    # Calculate perpendicular offset for width
    perp_x = -math.sin(angle_rad) * width_mm / 2.0
    perp_y = math.cos(angle_rad) * width_mm / 2.0

    # Four corners of the trace polygon
    x0, y0 = x_start + perp_x, y_start + perp_y
    x1, y1 = x_start - perp_x, y_start - perp_y
    x2, y2 = x_start + dx - perp_x, y_start + dy - perp_y
    x3, y3 = x_start + dx + perp_x, y_start + dy + perp_y

    trace_name = f"Trace_{layer}"
    component = "PCB_Traces"

    if abs(angle_rad) < 1e-9 or abs(angle_rad - math.pi / 2.0) < 1e-9:
        # Axis-aligned trace: use a simple brick for efficiency
        if abs(angle_rad) < 1e-9:
            # X-direction
            x_min = x_start
            x_max = x_start + length_mm
            y_min = y_start - width_mm / 2.0
            y_max = y_start + width_mm / 2.0
        else:
            # Y-direction
            x_min = x_start - width_mm / 2.0
            x_max = x_start + width_mm / 2.0
            y_min = y_start
            y_max = y_start + length_mm

        vba = (
            VBABuilder("Brick")
            .call("Reset")
            .set("Name", trace_name)
            .set("Component", component)
            .set("Material", "Copper (annealed)")
            .set_double("Xrange", x_min, x_max)
            .set_double("Yrange", y_min, y_max)
            .set_double("Zrange", z_pos, z_pos + copper_t)
            .call("Create")
        )
        vba_code = vba.build()
    else:
        # Angled trace: use extrude with polygon profile
        script = VBAScript()
        script.add_comment(f"Angled PCB trace on {layer}")

        poly_vba = (
            VBABuilder("Polygon")
            .call("Reset")
            .set("Name", f"{trace_name}_profile")
            .set("Curve", f"{trace_name}_curves")
        )
        for px, py in [(x0, y0), (x1, y1), (x2, y2), (x3, y3), (x0, y0)]:
            poly_vba.set_double("Point", px, py)
        poly_vba.call("Create")
        script.add_block(poly_vba)

        extrude_vba = (
            VBABuilder("ExtrudeCurve")
            .call("Reset")
            .set("Name", trace_name)
            .set("Component", component)
            .set("Material", "Copper (annealed)")
            .set_number("Thickness", copper_t)
            .set_double("Twistangle", 0, 0)
            .set_double("Taperangle", 0, 0)
            .set("Curve", f"{trace_name}_curves:{trace_name}_profile")
            .set("Axis", "z")
            .call("Create")
        )
        script.add_block(extrude_vba)
        vba_code = script.build()

    result = client.execute_vba(vba_code)
    result["trace_type"] = trace_type
    result["layer"] = layer
    result["width_mm"] = round(width_mm, 4)
    result["length_mm"] = length_mm
    result["direction_deg"] = round(math.degrees(angle_rad), 2)
    result["start"] = {"x": x_start, "y": y_start, "z": z_pos}
    result["end"] = {
        "x": round(x_start + dx, 4),
        "y": round(y_start + dy, 4),
        "z": z_pos,
    }
    if impedance_info:
        result["impedance"] = impedance_info

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_create_via(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Create a PCB via with barrel, pads, and antipads."""
    x = float(arguments["x"])
    y = float(arguments["y"])
    drill_d = float(arguments.get("drill_diameter_mm", 0.3))
    pad_d = float(arguments.get("pad_diameter_mm", 0.6))
    antipad_d = float(arguments.get("antipad_diameter_mm", 0.8))
    start_layer = validate_name(arguments["start_layer"], "start_layer")
    end_layer = validate_name(arguments["end_layer"], "end_layer")
    start_z = float(arguments["start_z"])
    end_z = float(arguments["end_z"])
    via_type = arguments.get("via_type", "through")
    via_name = arguments.get("name", f"Via_{start_layer}_{end_layer}")
    via_name = validate_name(via_name, "via name")

    validate_positive(drill_d, "drill_diameter_mm")
    validate_positive(pad_d, "pad_diameter_mm")
    validate_positive(antipad_d, "antipad_diameter_mm")

    if pad_d <= drill_d:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": (
                f"pad_diameter_mm ({pad_d}) must be larger than "
                f"drill_diameter_mm ({drill_d})"
            ),
        }))]

    if antipad_d <= pad_d:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": (
                f"antipad_diameter_mm ({antipad_d}) must be larger than "
                f"pad_diameter_mm ({pad_d})"
            ),
        }))]

    # Ensure start_z > end_z (top to bottom)
    z_top = max(start_z, end_z)
    z_bot = min(start_z, end_z)

    drill_r = drill_d / 2.0
    pad_r = pad_d / 2.0

    script = VBAScript()
    script.add_comment(f"PCB Via: {via_name} ({via_type})")

    # Via barrel (hollow cylinder: outer = pad, inner = drill)
    barrel_vba = (
        VBABuilder("Cylinder")
        .call("Reset")
        .set("Name", f"{via_name}_barrel")
        .set("Component", "PCB_Vias")
        .set("Material", "Copper (annealed)")
        .set("Axis", "z")
        .set_number("Outerradius", pad_r)
        .set_number("Innerradius", drill_r)
        .set_number("Xcenter", x)
        .set_number("Ycenter", y)
        .set_number("Zcenter", 0)
        .set_double("Zrange", z_bot, z_top)
        .call("Create")
    )
    script.add_block(barrel_vba)

    vba_code = script.build()
    result = client.execute_vba(vba_code)
    result["via_name"] = via_name
    result["via_type"] = via_type
    result["position"] = {"x": x, "y": y}
    result["z_range"] = {"top": z_top, "bottom": z_bot}
    result["dimensions"] = {
        "drill_diameter_mm": drill_d,
        "pad_diameter_mm": pad_d,
        "antipad_diameter_mm": antipad_d,
        "annular_ring_mm": round((pad_d - drill_d) / 2.0, 4),
    }
    result["layers"] = {
        "start": start_layer,
        "end": end_layer,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_create_ground_plane(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Create a ground/power plane with optional cutouts."""
    layer = validate_name(arguments["layer"], "layer")
    width_mm = validate_positive(float(arguments["width_mm"]), "width_mm")
    length_mm = validate_positive(float(arguments["length_mm"]), "length_mm")
    z_pos = float(arguments.get("z_position", 0))
    thickness = float(arguments.get("thickness_mm", 0.035))
    cutouts: list[dict] = arguments.get("cutouts", [])

    half_w = width_mm / 2.0
    half_l = length_mm / 2.0
    plane_name = f"Plane_{layer}"

    script = VBAScript()
    script.add_comment(f"PCB Plane: {layer}")

    # Main plane brick
    plane_vba = (
        VBABuilder("Brick")
        .call("Reset")
        .set("Name", plane_name)
        .set("Component", "PCB_Planes")
        .set("Material", "Copper (annealed)")
        .set_double("Xrange", -half_w, half_w)
        .set_double("Yrange", -half_l, half_l)
        .set_double("Zrange", z_pos, z_pos + thickness)
        .call("Create")
    )
    script.add_block(plane_vba)

    # Subtract cutouts
    cutout_info: list[dict] = []
    for i, cutout in enumerate(cutouts):
        cutout_name = f"{plane_name}_cutout{i}"
        x_min = float(cutout["x_min"])
        x_max = float(cutout["x_max"])
        y_min = float(cutout["y_min"])
        y_max = float(cutout["y_max"])

        # Create the cutout brick
        cutout_vba = (
            VBABuilder("Brick")
            .call("Reset")
            .set("Name", cutout_name)
            .set("Component", "PCB_Planes")
            .set("Material", "Copper (annealed)")
            .set_double("Xrange", x_min, x_max)
            .set_double("Yrange", y_min, y_max)
            .set_double("Zrange", z_pos, z_pos + thickness)
            .call("Create")
        )
        script.add_block(cutout_vba)

        # Boolean subtract the cutout from the plane
        subtract_vba = VBABuilder("Solid")
        subtract_vba.raw_line(
            f'Solid.Subtract "PCB_Planes:{plane_name}", '
            f'"PCB_Planes:{cutout_name}"'
        )
        script.add_block(subtract_vba)

        cutout_info.append({
            "index": i,
            "x_range": [x_min, x_max],
            "y_range": [y_min, y_max],
        })

    vba_code = script.build()
    result = client.execute_vba(vba_code)
    result["layer"] = layer
    result["dimensions"] = {
        "width_mm": width_mm,
        "length_mm": length_mm,
        "thickness_mm": thickness,
    }
    result["z_position"] = z_pos
    result["cutout_count"] = len(cutouts)
    if cutout_info:
        result["cutouts"] = cutout_info

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_import_gerber(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Import a Gerber file into CST Studio."""
    file_path = validate_file_path(arguments["file_path"])
    layer_name = validate_name(arguments["layer_name"], "layer_name")
    file_type = arguments.get("file_type", "gerber")

    if file_type == "gerber":
        # CST VBA Gerber import
        vba = (
            VBABuilder("EDAImport")
            .call("Reset")
            .set("FileName", file_path)
            .set("ImportAs", "2D")
            .set("LayerName", layer_name)
            .set("Type", "Gerber")
            .set_bool("UseUnits", True)
            .set("Units", "mm")
            .call("Import")
        )
    elif file_type == "odb++":
        vba = (
            VBABuilder("EDAImport")
            .call("Reset")
            .set("FileName", file_path)
            .set("ImportAs", "3D")
            .set("LayerName", layer_name)
            .set("Type", "ODB++")
            .set_bool("UseUnits", True)
            .set("Units", "mm")
            .call("Import")
        )
    elif file_type == "dxf":
        vba = (
            VBABuilder("DXF")
            .call("Reset")
            .set("FileName", file_path)
            .set("ScaleToUnit", "mm")
            .set_number("ImportLineWidth", 0)
            .set("AddAllShapes", "True")
            .call("Read")
        )
    else:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Unsupported file type: {file_type}. Use 'gerber', 'odb++', or 'dxf'.",
        }))]

    vba_code = vba.build()
    result = client.execute_vba(vba_code)
    result["file_path"] = file_path
    result["layer_name"] = layer_name
    result["file_type"] = file_type

    if result.get("status") == "offline":
        result["import_notes"] = (
            "To import Gerber files in CST Studio:\n"
            "1. Open CST Studio Suite on Windows\n"
            "2. Use Modeling > Import > EDA/Layout to open the import wizard\n"
            "3. Select the Gerber file and assign it to the correct layer\n"
            "4. Set the units to mm and configure layer stackup\n"
            "5. Click Import to generate the 3D PCB model\n\n"
            "Alternatively, use the generated VBA script in the CST macro editor."
        )

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_list_stackup_templates(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """List predefined PCB stackup templates from the data file."""
    stackup_file = DATA_DIR / "pcb_stackups.json"

    try:
        data = json.loads(stackup_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Stackup templates file not found: {stackup_file}",
        }))]

    stackups = data.get("stackups", [])

    # Apply optional filter
    filter_str = arguments.get("filter", "")
    if filter_str:
        filter_lower = filter_str.lower()
        stackups = [
            s for s in stackups
            if filter_lower in s["name"].lower()
            or filter_lower in s.get("description", "").lower()
        ]

    result = {
        "status": "ok",
        "template_count": len(stackups),
        "templates": stackups,
        "usage_hint": (
            "Pass the 'layers' array from any template directly to "
            "cst_pcb_create_stackup along with board_width_mm and board_length_mm."
        ),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ---------------------------------------------------------------------------
# New PCB tool handlers (Phase 8)
# ---------------------------------------------------------------------------


async def _handle_differential_pair(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Create a differential pair of traces with impedance calculation."""
    name = validate_name(arguments["name"], "name")
    component = validate_name(arguments.get("component", "PCB"), "component")
    trace_w = validate_positive(float(arguments["trace_width_mm"]), "trace_width_mm")
    gap = validate_positive(float(arguments["gap_mm"]), "gap_mm")
    length = validate_positive(float(arguments["length_mm"]), "length_mm")
    layer = validate_name(arguments["layer"], "layer")
    target_zdiff = float(arguments.get("target_impedance_diff", 100))
    er = validate_positive(float(arguments.get("epsilon_r", 4.4)), "epsilon_r")
    h = validate_positive(float(arguments.get("height_mm", 1.5)), "height_mm")
    x_start = float(arguments.get("x_start", 0))
    y_start = float(arguments.get("y_start", 0))

    copper_t = 0.035  # 1oz copper default

    # Calculate even/odd mode impedances
    ze, zo = _coupled_microstrip_impedances(trace_w, gap, h, er, copper_t)

    # Coupling coefficient and differential impedance
    k = (ze - zo) / (ze + zo)
    z0_single = _microstrip_impedance(trace_w, h, er, copper_t)
    z_diff = 2.0 * z0_single * (1.0 - k)

    # Generate VBA: two parallel bricks (positive and negative trace)
    # Traces run along X, separated in Y by gap_mm
    center_to_center = trace_w + gap
    y_pos = y_start + center_to_center / 2.0
    y_neg = y_start - center_to_center / 2.0

    script = VBAScript()
    script.add_comment(f"Differential Pair: {name} on {layer}")

    # Positive trace
    pos_vba = (
        VBABuilder("Brick")
        .call("Reset")
        .set("Name", f"{name}_P")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set_double("Xrange", x_start, x_start + length)
        .set_double("Yrange", y_pos - trace_w / 2.0, y_pos + trace_w / 2.0)
        .set_double("Zrange", 0, copper_t)
        .call("Create")
    )
    script.add_block(pos_vba)

    # Negative trace
    neg_vba = (
        VBABuilder("Brick")
        .call("Reset")
        .set("Name", f"{name}_N")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set_double("Xrange", x_start, x_start + length)
        .set_double("Yrange", y_neg - trace_w / 2.0, y_neg + trace_w / 2.0)
        .set_double("Zrange", 0, copper_t)
        .call("Create")
    )
    script.add_block(neg_vba)

    vba_code = script.build()
    result = client.execute_vba(vba_code)
    result["name"] = name
    result["layer"] = layer
    result["trace_width_mm"] = trace_w
    result["gap_mm"] = gap
    result["length_mm"] = length
    result["impedance"] = {
        "single_ended_z0_ohms": round(z0_single, 2),
        "even_mode_z0_ohms": round(ze, 2),
        "odd_mode_z0_ohms": round(zo, 2),
        "coupling_coefficient": round(k, 4),
        "differential_impedance_ohms": round(z_diff, 2),
        "target_impedance_ohms": target_zdiff,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_via_model(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Create a detailed via model with parasitic estimates."""
    name = validate_name(arguments["name"], "name")
    component = validate_name(arguments.get("component", "PCB"), "component")
    drill_d = validate_positive(float(arguments["drill_diameter_mm"]), "drill_diameter_mm")
    pad_d = validate_positive(float(arguments["pad_diameter_mm"]), "pad_diameter_mm")
    antipad_d = validate_positive(float(arguments["antipad_diameter_mm"]), "antipad_diameter_mm")
    plating_um = float(arguments.get("barrel_plating_um", 25))
    start_layer = validate_name(arguments["start_layer"], "start_layer")
    end_layer = validate_name(arguments["end_layer"], "end_layer")
    x = float(arguments["x"])
    y = float(arguments["y"])
    board_t = validate_positive(float(arguments.get("board_thickness_mm", 1.6)), "board_thickness_mm")
    er = validate_positive(float(arguments.get("epsilon_r", 4.4)), "epsilon_r")
    copper_t = 0.035  # 1oz copper default

    if pad_d <= drill_d:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"pad_diameter_mm ({pad_d}) must be larger than drill_diameter_mm ({drill_d})",
        }))]

    if antipad_d <= pad_d:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"antipad_diameter_mm ({antipad_d}) must be larger than pad_diameter_mm ({pad_d})",
        }))]

    plating_mm = plating_um / 1000.0
    drill_r = drill_d / 2.0
    pad_r = pad_d / 2.0

    # Via height = board thickness
    z_top = board_t
    z_bot = 0.0

    script = VBAScript()
    script.add_comment(f"Detailed Via Model: {name}")

    # Via barrel (hollow cylinder with plating thickness)
    outer_r = drill_r
    inner_r = drill_r - plating_mm
    if inner_r <= 0:
        inner_r = 0  # Filled via

    barrel_vba = (
        VBABuilder("Cylinder")
        .call("Reset")
        .set("Name", f"{name}_barrel")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set("Axis", "z")
        .set_number("Outerradius", outer_r)
        .set_number("Innerradius", inner_r)
        .set_number("Xcenter", x)
        .set_number("Ycenter", y)
        .set_number("Zcenter", 0)
        .set_double("Zrange", z_bot, z_top)
        .call("Create")
    )
    script.add_block(barrel_vba)

    # Top pad (brick)
    top_pad_vba = (
        VBABuilder("Brick")
        .call("Reset")
        .set("Name", f"{name}_pad_top")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set_double("Xrange", x - pad_r, x + pad_r)
        .set_double("Yrange", y - pad_r, y + pad_r)
        .set_double("Zrange", z_top, z_top + copper_t)
        .call("Create")
    )
    script.add_block(top_pad_vba)

    # Bottom pad (brick)
    bot_pad_vba = (
        VBABuilder("Brick")
        .call("Reset")
        .set("Name", f"{name}_pad_bot")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set_double("Xrange", x - pad_r, x + pad_r)
        .set_double("Yrange", y - pad_r, y + pad_r)
        .set_double("Zrange", z_bot - copper_t, z_bot)
        .call("Create")
    )
    script.add_block(bot_pad_vba)

    vba_code = script.build()

    # Parasitic calculations (Goldfarb model)
    # Inductance: L = (mu_0 * h) / (2*pi) * ln(d_antipad / d_drill)
    mu_0 = 4.0 * math.pi * 1e-7  # H/m
    h_m = board_t * 1e-3  # Convert mm to m
    d_antipad_m = antipad_d * 1e-3
    d_drill_m = drill_d * 1e-3

    l_henries = (mu_0 * h_m) / (2.0 * math.pi) * math.log(d_antipad_m / d_drill_m)
    l_nh = l_henries * 1e9  # Convert to nH

    # Capacitance: C = 1.41 * epsilon_r * t * d_pad (simplified Goldfarb)
    # t in inches, d_pad in inches => result in pF
    t_inches = board_t / 25.4
    d_pad_inches = pad_d / 25.4
    c_pf = 1.41 * er * t_inches * d_pad_inches

    result = client.execute_vba(vba_code)
    result["name"] = name
    result["layers"] = {"start": start_layer, "end": end_layer}
    result["dimensions"] = {
        "drill_diameter_mm": drill_d,
        "pad_diameter_mm": pad_d,
        "antipad_diameter_mm": antipad_d,
        "barrel_plating_um": plating_um,
        "board_thickness_mm": board_t,
    }
    result["parasitics"] = {
        "estimated_inductance_nh": round(l_nh, 3),
        "estimated_capacitance_pf": round(c_pf, 3),
        "model": "Goldfarb (1991)",
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_via_fence(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Create a row of vias along a path."""
    name = validate_name(arguments["name"], "name")
    component = validate_name(arguments.get("component", "PCB"), "component")
    x_start = float(arguments["x_start"])
    y_start = float(arguments["y_start"])
    x_end = float(arguments["x_end"])
    y_end = float(arguments["y_end"])
    spacing = validate_positive(float(arguments["via_spacing_mm"]), "via_spacing_mm")
    via_d = validate_positive(float(arguments["via_diameter_mm"]), "via_diameter_mm")
    pad_d = validate_positive(float(arguments["pad_diameter_mm"]), "pad_diameter_mm")
    rows = int(arguments.get("rows", 1))
    rows = int(validate_range(float(rows), 1, 3, "rows"))
    row_offset = float(arguments.get("row_offset_mm", 0))

    # Calculate path length and direction
    dx = x_end - x_start
    dy = y_end - y_start
    total_length = math.sqrt(dx ** 2 + dy ** 2)

    if total_length < 1e-6:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": "Start and end points are the same; fence length must be > 0.",
        }))]

    # Unit vectors along and perpendicular to path
    ux = dx / total_length
    uy = dy / total_length
    # Perpendicular (rotated 90 degrees)
    px = -uy
    py = ux

    # Number of vias along the path
    num_vias_per_row = max(1, int(total_length / spacing) + 1)
    actual_spacing = total_length / max(1, num_vias_per_row - 1) if num_vias_per_row > 1 else 0

    via_r = via_d / 2.0
    pad_r = pad_d / 2.0
    total_vias = 0

    script = VBAScript()
    script.add_comment(f"Via Fence: {name} ({rows} row(s), {num_vias_per_row} vias/row)")

    for row_idx in range(rows):
        # Row lateral offset from center line
        if rows == 1:
            lat_offset = 0.0
        else:
            lat_offset = (row_idx - (rows - 1) / 2.0) * pad_d * 1.5

        # Stagger offset along path direction
        stagger = row_offset * row_idx

        for via_idx in range(num_vias_per_row):
            dist_along = via_idx * actual_spacing + stagger if num_vias_per_row > 1 else 0
            # Wrap stagger if it exceeds total length
            if dist_along > total_length:
                dist_along = dist_along % total_length if total_length > 0 else 0

            vx = x_start + ux * dist_along + px * lat_offset
            vy = y_start + uy * dist_along + py * lat_offset

            via_name = f"{name}_r{row_idx}_v{via_idx}"

            via_vba = (
                VBABuilder("Cylinder")
                .call("Reset")
                .set("Name", via_name)
                .set("Component", component)
                .set("Material", "Copper (annealed)")
                .set("Axis", "z")
                .set_number("Outerradius", pad_r)
                .set_number("Innerradius", via_r)
                .set_number("Xcenter", round(vx, 4))
                .set_number("Ycenter", round(vy, 4))
                .set_number("Zcenter", 0)
                .set_double("Zrange", 0, 1.6)
                .call("Create")
            )
            script.add_block(via_vba)
            total_vias += 1

    vba_code = script.build()
    result = client.execute_vba(vba_code)
    result["name"] = name
    result["num_vias"] = total_vias
    result["num_rows"] = rows
    result["vias_per_row"] = num_vias_per_row
    result["total_length_mm"] = round(total_length, 4)
    result["actual_spacing_mm"] = round(actual_spacing, 4)

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_cpw_transition(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Create a CPW to microstrip transition with tapered geometry."""
    name = validate_name(arguments["name"], "name")
    component = validate_name(arguments.get("component", "PCB"), "component")
    trans_type = arguments.get("transition_type", "cpw_to_microstrip")
    cpw_w = validate_positive(float(arguments["cpw_width_mm"]), "cpw_width_mm")
    cpw_gap = validate_positive(float(arguments["cpw_gap_mm"]), "cpw_gap_mm")
    ms_w = validate_positive(float(arguments["microstrip_width_mm"]), "microstrip_width_mm")
    trans_len = validate_positive(float(arguments["transition_length_mm"]), "transition_length_mm")
    layer = validate_name(arguments["layer"], "layer")
    h = validate_positive(float(arguments["height_mm"]), "height_mm")
    er = validate_positive(float(arguments.get("epsilon_r", 4.4)), "epsilon_r")

    copper_t = 0.035

    # Calculate impedances
    cpw_z0 = _cpw_impedance(cpw_w, cpw_gap, h, er)
    ms_z0 = _microstrip_impedance(ms_w, h, er, copper_t)

    # Generate tapered geometry using polygon extrusion
    # The center conductor tapers from cpw_w to ms_w
    # The ground planes taper away (gap widens to infinity)
    # We approximate with N segments for the center conductor taper
    n_segments = 10

    script = VBAScript()
    script.add_comment(f"CPW to Microstrip Transition: {name} on {layer}")

    # Create the tapered center conductor as a polygon
    # Points go along +X direction
    # Bottom edge (y-negative side) then top edge (y-positive side) in reverse
    poly_points_bottom: list[tuple[float, float]] = []
    poly_points_top: list[tuple[float, float]] = []

    for i in range(n_segments + 1):
        frac = i / n_segments
        x_pos = frac * trans_len
        # Linear taper of conductor width
        w_at_x = cpw_w + (ms_w - cpw_w) * frac
        poly_points_bottom.append((x_pos, -w_at_x / 2.0))
        poly_points_top.append((x_pos, w_at_x / 2.0))

    # Build polygon: bottom edge left-to-right, then top edge right-to-left
    all_points = poly_points_bottom + list(reversed(poly_points_top))

    # Create as an extruded polygon
    poly_vba = (
        VBABuilder("Polygon")
        .call("Reset")
        .set("Name", f"{name}_profile")
        .set("Curve", f"{name}_curves")
    )
    for px, py in all_points:
        poly_vba.set_double("Point", round(px, 6), round(py, 6))
    # Close the polygon
    poly_vba.set_double("Point", round(all_points[0][0], 6), round(all_points[0][1], 6))
    poly_vba.call("Create")
    script.add_block(poly_vba)

    extrude_vba = (
        VBABuilder("ExtrudeCurve")
        .call("Reset")
        .set("Name", f"{name}_conductor")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set_number("Thickness", copper_t)
        .set_double("Twistangle", 0, 0)
        .set_double("Taperangle", 0, 0)
        .set("Curve", f"{name}_curves:{name}_profile")
        .set("Axis", "z")
        .call("Create")
    )
    script.add_block(extrude_vba)

    # For CPW: also create ground plane strips on each side at x=0 (CPW end)
    # The gap tapers from cpw_gap to a large value (effectively infinite for microstrip)
    gnd_width = cpw_w * 3.0  # Ground plane width (3x conductor width)

    # Left ground plane (y-negative side)
    left_gnd_points_inner: list[tuple[float, float]] = []
    left_gnd_points_outer: list[tuple[float, float]] = []
    for i in range(n_segments + 1):
        frac = i / n_segments
        x_pos = frac * trans_len
        w_at_x = cpw_w + (ms_w - cpw_w) * frac
        gap_at_x = cpw_gap * (1.0 - frac) + (cpw_gap + gnd_width) * frac
        y_inner = -w_at_x / 2.0 - gap_at_x
        y_outer = y_inner - gnd_width
        left_gnd_points_inner.append((x_pos, y_inner))
        left_gnd_points_outer.append((x_pos, y_outer))

    left_all = left_gnd_points_inner + list(reversed(left_gnd_points_outer))

    left_poly = (
        VBABuilder("Polygon")
        .call("Reset")
        .set("Name", f"{name}_gnd_left_profile")
        .set("Curve", f"{name}_gnd_left_curves")
    )
    for px, py in left_all:
        left_poly.set_double("Point", round(px, 6), round(py, 6))
    left_poly.set_double("Point", round(left_all[0][0], 6), round(left_all[0][1], 6))
    left_poly.call("Create")
    script.add_block(left_poly)

    left_extrude = (
        VBABuilder("ExtrudeCurve")
        .call("Reset")
        .set("Name", f"{name}_gnd_left")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set_number("Thickness", copper_t)
        .set_double("Twistangle", 0, 0)
        .set_double("Taperangle", 0, 0)
        .set("Curve", f"{name}_gnd_left_curves:{name}_gnd_left_profile")
        .set("Axis", "z")
        .call("Create")
    )
    script.add_block(left_extrude)

    # Right ground plane (y-positive side, mirror of left)
    right_gnd_points_inner: list[tuple[float, float]] = []
    right_gnd_points_outer: list[tuple[float, float]] = []
    for i in range(n_segments + 1):
        frac = i / n_segments
        x_pos = frac * trans_len
        w_at_x = cpw_w + (ms_w - cpw_w) * frac
        gap_at_x = cpw_gap * (1.0 - frac) + (cpw_gap + gnd_width) * frac
        y_inner = w_at_x / 2.0 + gap_at_x
        y_outer = y_inner + gnd_width
        right_gnd_points_inner.append((x_pos, y_inner))
        right_gnd_points_outer.append((x_pos, y_outer))

    right_all = right_gnd_points_inner + list(reversed(right_gnd_points_outer))

    right_poly = (
        VBABuilder("Polygon")
        .call("Reset")
        .set("Name", f"{name}_gnd_right_profile")
        .set("Curve", f"{name}_gnd_right_curves")
    )
    for px, py in right_all:
        right_poly.set_double("Point", round(px, 6), round(py, 6))
    right_poly.set_double("Point", round(right_all[0][0], 6), round(right_all[0][1], 6))
    right_poly.call("Create")
    script.add_block(right_poly)

    right_extrude = (
        VBABuilder("ExtrudeCurve")
        .call("Reset")
        .set("Name", f"{name}_gnd_right")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set_number("Thickness", copper_t)
        .set_double("Twistangle", 0, 0)
        .set_double("Taperangle", 0, 0)
        .set("Curve", f"{name}_gnd_right_curves:{name}_gnd_right_profile")
        .set("Axis", "z")
        .call("Create")
    )
    script.add_block(right_extrude)

    vba_code = script.build()
    result = client.execute_vba(vba_code)
    result["name"] = name
    result["transition_type"] = trans_type
    result["layer"] = layer
    result["cpw_impedance_ohms"] = round(cpw_z0, 2)
    result["microstrip_impedance_ohms"] = round(ms_z0, 2)
    result["dimensions"] = {
        "cpw_width_mm": cpw_w,
        "cpw_gap_mm": cpw_gap,
        "microstrip_width_mm": ms_w,
        "transition_length_mm": trans_len,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_calculate_coupling(
    arguments: dict, _client: CSTClient
) -> list[TextContent]:
    """Calculate coupling between parallel traces (pure Python, no VBA)."""
    w = validate_positive(float(arguments["trace_width_mm"]), "trace_width_mm")
    s = validate_positive(float(arguments["separation_mm"]), "separation_mm")
    h = validate_positive(float(arguments["height_mm"]), "height_mm")
    er = validate_positive(float(arguments["epsilon_r"]), "epsilon_r")
    coupling_len = validate_positive(float(arguments["coupling_length_mm"]), "coupling_length_mm")
    freq_ghz = validate_positive(float(arguments["frequency_ghz"]), "frequency_ghz")

    copper_t = 0.035

    # Even/odd mode impedances
    ze, zo = _coupled_microstrip_impedances(w, s, h, er, copper_t)

    # Coupling coefficient
    k = (ze - zo) / (ze + zo)

    # Electrical length
    c0 = 299792458.0  # m/s
    freq_hz = freq_ghz * 1e9
    wavelength_mm = (c0 / freq_hz) * 1000.0

    # Effective permittivity (approximate)
    u = w / h
    eps_eff = 0.5 * (er + 1.0) + 0.5 * (er - 1.0) * (1.0 + 10.0 / u) ** (-0.5)
    wavelength_eff = wavelength_mm / math.sqrt(eps_eff)
    electrical_length_deg = (coupling_len / wavelength_eff) * 360.0
    beta_l = math.radians(electrical_length_deg)

    # Near-end crosstalk (NEXT)
    # NEXT = k/2 * (1 - cos(2*beta*l)) for weak coupling
    if abs(k) > 1e-12:
        next_linear = abs(k) / 2.0
        next_db = 20.0 * math.log10(max(next_linear, 1e-15))
    else:
        next_db = -200.0

    # Far-end crosstalk (FEXT)
    # FEXT = k/2 * sin(2*beta*l) * j for weak coupling (magnitude)
    if abs(k) > 1e-12:
        fext_linear = abs(k) / 2.0 * abs(math.sin(beta_l))
        fext_db = 20.0 * math.log10(max(fext_linear, 1e-15))
    else:
        fext_db = -200.0

    result = {
        "status": "ok",
        "even_mode_z0_ohms": round(ze, 2),
        "odd_mode_z0_ohms": round(zo, 2),
        "coupling_coefficient": round(k, 6),
        "near_end_crosstalk_db": round(next_db, 2),
        "far_end_crosstalk_db": round(fext_db, 2),
        "electrical_length_deg": round(electrical_length_deg, 2),
        "effective_permittivity": round(eps_eff, 3),
        "parameters": {
            "trace_width_mm": w,
            "separation_mm": s,
            "height_mm": h,
            "epsilon_r": er,
            "coupling_length_mm": coupling_len,
            "frequency_ghz": freq_ghz,
        },
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_siw_waveguide(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Create a Substrate Integrated Waveguide."""
    name = validate_name(arguments["name"], "name")
    component = validate_name(arguments.get("component", "PCB"), "component")
    width = validate_positive(float(arguments["width_mm"]), "width_mm")
    via_d = validate_positive(float(arguments["via_diameter_mm"]), "via_diameter_mm")
    via_pitch = validate_positive(float(arguments["via_pitch_mm"]), "via_pitch_mm")
    length = validate_positive(float(arguments["length_mm"]), "length_mm")
    layer = validate_name(arguments["layer"], "layer")
    er = validate_positive(float(arguments.get("epsilon_r", 4.4)), "epsilon_r")
    h = validate_positive(float(arguments.get("height_mm", 1.5)), "height_mm")
    x_start = float(arguments.get("x_start", 0))
    y_start = float(arguments.get("y_start", 0))

    copper_t = 0.035

    # SIW equivalent width: w_eff = w - d^2 / (0.95 * p)  [Cassivi et al.]
    w_eff = width - (via_d ** 2) / (0.95 * via_pitch)

    if w_eff <= 0:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": (
                f"Effective SIW width is non-positive ({w_eff:.4f} mm). "
                "Increase via spacing or reduce via diameter."
            ),
        }))]

    # Cutoff frequency: fc = c / (2 * w_eff * sqrt(eps_r))
    c0 = 299792458.0  # m/s
    w_eff_m = w_eff * 1e-3
    fc_hz = c0 / (2.0 * w_eff_m * math.sqrt(er))
    fc_ghz = fc_hz / 1e9

    # Guided wavelength at 1.5 * fc (well above cutoff)
    f_op = 1.5 * fc_hz
    lambda_0 = c0 / f_op
    lambda_c = 2.0 * w_eff_m
    if lambda_0 < lambda_c:
        lambda_g = lambda_0 / math.sqrt(1.0 - (lambda_0 / lambda_c) ** 2)
    else:
        lambda_g = lambda_0  # At or below cutoff, approximate

    lambda_g_mm = lambda_g * 1000.0

    # Number of vias along each side
    num_vias = max(2, int(length / via_pitch) + 1)

    script = VBAScript()
    script.add_comment(f"Substrate Integrated Waveguide: {name}")

    # Top copper plane
    top_vba = (
        VBABuilder("Brick")
        .call("Reset")
        .set("Name", f"{name}_top")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set_double("Xrange", x_start, x_start + length)
        .set_double("Yrange", y_start - width / 2.0, y_start + width / 2.0)
        .set_double("Zrange", h, h + copper_t)
        .call("Create")
    )
    script.add_block(top_vba)

    # Bottom copper plane
    bot_vba = (
        VBABuilder("Brick")
        .call("Reset")
        .set("Name", f"{name}_bottom")
        .set("Component", component)
        .set("Material", "Copper (annealed)")
        .set_double("Xrange", x_start, x_start + length)
        .set_double("Yrange", y_start - width / 2.0, y_start + width / 2.0)
        .set_double("Zrange", -copper_t, 0)
        .call("Create")
    )
    script.add_block(bot_vba)

    # Via fences on both sides
    pad_r = via_d * 0.8  # Pad slightly larger than via

    for side_label, y_offset in [("left", -width / 2.0), ("right", width / 2.0)]:
        script.add_comment(f"Via fence: {side_label} side")
        for i in range(num_vias):
            vx = x_start + i * via_pitch
            if vx > x_start + length:
                break
            vy = y_start + y_offset

            via_vba = (
                VBABuilder("Cylinder")
                .call("Reset")
                .set("Name", f"{name}_via_{side_label}_{i}")
                .set("Component", component)
                .set("Material", "Copper (annealed)")
                .set("Axis", "z")
                .set_number("Outerradius", pad_r)
                .set_number("Innerradius", 0)
                .set_number("Xcenter", round(vx, 4))
                .set_number("Ycenter", round(vy, 4))
                .set_number("Zcenter", 0)
                .set_double("Zrange", 0, h)
                .call("Create")
            )
            script.add_block(via_vba)

    vba_code = script.build()
    result = client.execute_vba(vba_code)
    result["name"] = name
    result["layer"] = layer
    result["dimensions"] = {
        "width_mm": width,
        "length_mm": length,
        "height_mm": h,
        "via_diameter_mm": via_d,
        "via_pitch_mm": via_pitch,
    }
    result["analysis"] = {
        "effective_width_mm": round(w_eff, 4),
        "cutoff_frequency_ghz": round(fc_ghz, 4),
        "guided_wavelength_mm": round(lambda_g_mm, 4),
        "num_vias_per_side": num_vias,
        "formula": "Cassivi et al. (2002)",
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a PCB tool call."""
    try:
        if name == "cst_pcb_create_stackup":
            return await _handle_create_stackup(arguments, client)
        if name == "cst_pcb_create_trace":
            return await _handle_create_trace(arguments, client)
        if name == "cst_pcb_create_via":
            return await _handle_create_via(arguments, client)
        if name == "cst_pcb_create_ground_plane":
            return await _handle_create_ground_plane(arguments, client)
        if name == "cst_pcb_import_gerber":
            return await _handle_import_gerber(arguments, client)
        if name == "cst_pcb_list_stackup_templates":
            return await _handle_list_stackup_templates(arguments, client)
        if name == "cst_pcb_differential_pair":
            return await _handle_differential_pair(arguments, client)
        if name == "cst_pcb_via_model":
            return await _handle_via_model(arguments, client)
        if name == "cst_pcb_via_fence":
            return await _handle_via_fence(arguments, client)
        if name == "cst_pcb_cpw_transition":
            return await _handle_cpw_transition(arguments, client)
        if name == "cst_pcb_calculate_coupling":
            return await _handle_calculate_coupling(arguments, client)
        if name == "cst_pcb_siw_waveguide":
            return await _handle_siw_waveguide(arguments, client)

        return [TextContent(type="text", text=json.dumps({
            "status": "error", "message": f"Unknown PCB tool: {name}",
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error", "message": str(e),
        }))]


def register_pcb_tools(server: Server, client: CSTClient) -> None:
    """Register PCB tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
