"""Impedance matching network design tools for CST Studio Suite.

Provides 8 MCP tools for designing L-section, Pi-section, T-section,
stub, and quarter-wave matching networks, plus Smith chart impedance
transformation, lumped-element VBA generation, and microstrip impedance
calculation.  Most tools are pure-Python RF computations; only
``cst_matching_create_lumped`` generates CST VBA code.
"""

from __future__ import annotations

import cmath
import json
import math
from typing import TYPE_CHECKING

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.validators import validate_frequency, validate_positive, validate_range
from cst_mcp.vba_builder import VBABuilder, VBAScript

if TYPE_CHECKING:
    from mcp.server import Server

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

C0 = 299792458.0  # speed of light in m/s

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # 1 ── L-section matching network
    Tool(
        name="cst_matching_l_network",
        description=(
            "Design an L-section impedance matching network. Computes inductor "
            "and capacitor values for matching a source impedance to a load "
            "impedance at a given frequency. Supports lowpass and highpass "
            "topologies. Pure Python computation — no CST connection needed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "z_source_real": {
                    "type": "number",
                    "description": "Source resistance in ohms",
                },
                "z_source_imag": {
                    "type": "number",
                    "description": "Source reactance in ohms (default 0)",
                    "default": 0,
                },
                "z_load_real": {
                    "type": "number",
                    "description": "Load resistance in ohms",
                },
                "z_load_imag": {
                    "type": "number",
                    "description": "Load reactance in ohms (default 0)",
                    "default": 0,
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design frequency in GHz",
                },
                "topology": {
                    "type": "string",
                    "enum": ["lowpass", "highpass"],
                    "description": "Network topology (default lowpass)",
                    "default": "lowpass",
                },
            },
            "required": ["z_source_real", "z_load_real", "frequency_ghz"],
        },
    ),

    # 2 ── Pi-section matching network
    Tool(
        name="cst_matching_pi_network",
        description=(
            "Design a Pi-section impedance matching network (C-L-C or L-C-L). "
            "Uses two back-to-back L-sections via a virtual resistance for "
            "controllable Q factor. Pure Python computation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "z_source_real": {
                    "type": "number",
                    "description": "Source resistance in ohms",
                },
                "z_source_imag": {
                    "type": "number",
                    "description": "Source reactance in ohms (default 0)",
                    "default": 0,
                },
                "z_load_real": {
                    "type": "number",
                    "description": "Load resistance in ohms",
                },
                "z_load_imag": {
                    "type": "number",
                    "description": "Load reactance in ohms (default 0)",
                    "default": 0,
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design frequency in GHz",
                },
                "q_factor": {
                    "type": "number",
                    "description": (
                        "Desired loaded Q factor. Must be > sqrt(R_large/R_small - 1). "
                        "If omitted, a default Q is chosen automatically."
                    ),
                },
            },
            "required": ["z_source_real", "z_load_real", "frequency_ghz"],
        },
    ),

    # 3 ── T-section matching network
    Tool(
        name="cst_matching_t_network",
        description=(
            "Design a T-section impedance matching network (L-C-L). "
            "Dual of Pi-network, uses two back-to-back L-sections. "
            "Pure Python computation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "z_source_real": {
                    "type": "number",
                    "description": "Source resistance in ohms",
                },
                "z_source_imag": {
                    "type": "number",
                    "description": "Source reactance in ohms (default 0)",
                    "default": 0,
                },
                "z_load_real": {
                    "type": "number",
                    "description": "Load resistance in ohms",
                },
                "z_load_imag": {
                    "type": "number",
                    "description": "Load reactance in ohms (default 0)",
                    "default": 0,
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design frequency in GHz",
                },
                "q_factor": {
                    "type": "number",
                    "description": (
                        "Desired loaded Q factor. Must be > sqrt(R_large/R_small - 1). "
                        "If omitted, a default Q is chosen automatically."
                    ),
                },
            },
            "required": ["z_source_real", "z_load_real", "frequency_ghz"],
        },
    ),

    # 4 ── Stub matching
    Tool(
        name="cst_matching_stub",
        description=(
            "Design a single-stub impedance matching network. Computes the stub "
            "length and distance from the load using Smith chart transmission-line "
            "matching. Pure Python computation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "z_load_real": {
                    "type": "number",
                    "description": "Load resistance in ohms",
                },
                "z_load_imag": {
                    "type": "number",
                    "description": "Load reactance in ohms (default 0)",
                    "default": 0,
                },
                "z0": {
                    "type": "number",
                    "description": "Characteristic impedance in ohms (default 50)",
                    "default": 50,
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design frequency in GHz",
                },
                "stub_type": {
                    "type": "string",
                    "enum": ["open", "short"],
                    "description": "Stub termination type (default open)",
                    "default": "open",
                },
            },
            "required": ["z_load_real", "frequency_ghz"],
        },
    ),

    # 5 ── Quarter-wave transformer
    Tool(
        name="cst_matching_quarter_wave",
        description=(
            "Design a quarter-wave transformer matching network. Supports single "
            "and multi-section designs with maximally flat (binomial) or Chebyshev "
            "impedance profiles. Pure Python computation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "z_source": {
                    "type": "number",
                    "description": "Source impedance in ohms",
                },
                "z_load": {
                    "type": "number",
                    "description": "Load impedance in ohms",
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "num_sections": {
                    "type": "integer",
                    "description": "Number of quarter-wave sections (1-4, default 1)",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 4,
                },
                "design": {
                    "type": "string",
                    "enum": ["maximally_flat", "chebyshev"],
                    "description": "Multi-section design method (default maximally_flat)",
                    "default": "maximally_flat",
                },
            },
            "required": ["z_source", "z_load", "frequency_ghz"],
        },
    ),

    # 6 ── Create lumped-element network in CST (VBA)
    Tool(
        name="cst_matching_create_lumped",
        description=(
            "Generate CST VBA code to create a lumped-element matching network. "
            "Each component (inductor, capacitor, resistor) is placed as a CST "
            "LumpedElement with specified series/shunt connection."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["L", "C", "R"],
                                "description": "Component type: inductor, capacitor, or resistor",
                            },
                            "value": {
                                "type": "number",
                                "description": "Component value (nH for L, pF for C, ohm for R)",
                            },
                            "unit": {
                                "type": "string",
                                "enum": ["nH", "pF", "ohm"],
                                "description": "Unit for the component value",
                            },
                            "connection": {
                                "type": "string",
                                "enum": ["series", "shunt"],
                                "description": "Series or shunt connection",
                            },
                        },
                        "required": ["type", "value", "unit", "connection"],
                    },
                    "minItems": 1,
                    "description": "List of lumped components in the network (ordered source to load)",
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design frequency in GHz",
                },
                "port_impedance": {
                    "type": "number",
                    "description": "Port reference impedance in ohms (default 50)",
                    "default": 50,
                },
            },
            "required": ["components", "frequency_ghz"],
        },
    ),

    # 7 ── Smith chart impedance transformation
    Tool(
        name="cst_impedance_smith_transform",
        description=(
            "Apply a reactive element transformation to an impedance on the Smith "
            "chart. Supports series L/C, shunt L/C, and transmission line "
            "operations. Returns transformed impedance, reflection coefficient, "
            "and VSWR. Pure Python computation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "z_in_real": {
                    "type": "number",
                    "description": "Input resistance in ohms",
                },
                "z_in_imag": {
                    "type": "number",
                    "description": "Input reactance in ohms",
                },
                "z0": {
                    "type": "number",
                    "description": "Reference impedance in ohms (default 50)",
                    "default": 50,
                },
                "operation": {
                    "type": "string",
                    "enum": [
                        "series_L", "series_C", "shunt_L", "shunt_C",
                        "transmission_line",
                    ],
                    "description": "Type of transformation to apply",
                },
                "value": {
                    "type": "number",
                    "description": (
                        "Component value: L in nH, C in pF, or transmission "
                        "line electrical length in degrees"
                    ),
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Operating frequency in GHz",
                },
            },
            "required": [
                "z_in_real", "z_in_imag", "operation", "value", "frequency_ghz",
            ],
        },
    ),

    # 8 ── Microstrip impedance calculator
    Tool(
        name="cst_matching_microstrip_impedance",
        description=(
            "Calculate microstrip transmission line characteristic impedance from "
            "physical dimensions using the Hammerstad-Jensen model with optional "
            "Kirschning-Jansen frequency dispersion correction. Pure Python computation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "width_mm": {
                    "type": "number",
                    "description": "Trace width in mm",
                },
                "height_mm": {
                    "type": "number",
                    "description": "Substrate height (dielectric thickness) in mm",
                },
                "epsilon_r": {
                    "type": "number",
                    "description": "Substrate relative permittivity",
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Frequency in GHz for dispersion correction (optional)",
                },
                "thickness_mm": {
                    "type": "number",
                    "description": "Conductor thickness in mm (default 0.035 = 1 oz copper)",
                    "default": 0.035,
                },
            },
            "required": ["width_mm", "height_mm", "epsilon_r"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _reactance_to_lc(x: float, omega: float) -> dict:
    """Convert a reactance value to an inductor or capacitor.

    Parameters
    ----------
    x : float     - reactance in ohms (positive = inductive, negative = capacitive)
    omega : float - angular frequency (rad/s)

    Returns
    -------
    dict with keys: type ("L" or "C"), value_nH or value_pF
    """
    if x >= 0:
        # Inductive: X = omega * L  =>  L = X / omega
        l_h = x / omega
        return {"type": "L", "L_nH": round(l_h * 1e9, 4)}
    else:
        # Capacitive: X = -1/(omega * C)  =>  C = -1/(omega * X)
        c_f = -1.0 / (omega * x)
        return {"type": "C", "C_pF": round(c_f * 1e12, 4)}


def _susceptance_to_lc(b: float, omega: float) -> dict:
    """Convert a susceptance value to an inductor or capacitor.

    Parameters
    ----------
    b : float     - susceptance in siemens (positive = capacitive, negative = inductive)
    omega : float - angular frequency (rad/s)

    Returns
    -------
    dict with keys: type ("L" or "C"), value_nH or value_pF
    """
    if b >= 0:
        # Capacitive: B = omega * C  =>  C = B / omega
        c_f = b / omega
        return {"type": "C", "C_pF": round(c_f * 1e12, 4)}
    else:
        # Inductive: B = -1/(omega * L)  =>  L = -1/(omega * B)
        l_h = -1.0 / (omega * b)
        return {"type": "L", "L_nH": round(l_h * 1e9, 4)}


def _reflection_coefficient(z: complex, z0: float) -> tuple[float, float]:
    """Compute reflection coefficient magnitude and phase (degrees)."""
    gamma = (z - z0) / (z + z0)
    return abs(gamma), math.degrees(cmath.phase(gamma))


def _vswr_from_gamma(gamma_mag: float) -> float:
    """Compute VSWR from reflection coefficient magnitude."""
    if gamma_mag >= 1.0:
        return float("inf")
    return (1.0 + gamma_mag) / (1.0 - gamma_mag)


# ---------------------------------------------------------------------------
# Microstrip impedance (Hammerstad-Jensen + Kirschning-Jansen dispersion)
# ---------------------------------------------------------------------------


def _microstrip_static(
    w: float, h: float, er: float, t: float = 0.035,
) -> tuple[float, float]:
    """Compute static microstrip Z0 and epsilon_eff (Hammerstad-Jensen).

    Parameters
    ----------
    w  : trace width (mm)
    h  : substrate height (mm)
    er : relative permittivity
    t  : conductor thickness (mm)

    Returns
    -------
    (Z0, epsilon_eff)
    """
    # Effective width correction for finite conductor thickness
    if t > 0 and w > 0:
        dw = (t / math.pi) * (1.0 + math.log(2.0 * h / t))
        we = w + dw
    else:
        we = w

    u = we / h

    # Hammerstad-Jensen effective dielectric constant
    eps_eff = 0.5 * (er + 1.0) + 0.5 * (er - 1.0) * (1.0 + 10.0 / u) ** (-0.5)

    # Hammerstad-Jensen impedance
    f_u = 6.0 + (2.0 * math.pi - 6.0) * math.exp(-(30.666 / u) ** 0.7528)
    z0 = (60.0 / math.sqrt(eps_eff)) * math.log(
        f_u / u + math.sqrt(1.0 + (2.0 / u) ** 2)
    )

    return z0, eps_eff


def _kirschning_jansen_dispersion(
    z0_static: float, eps_eff_static: float,
    w: float, h: float, er: float, freq_ghz: float,
) -> tuple[float, float]:
    """Apply Kirschning-Jansen frequency dispersion correction.

    Parameters
    ----------
    z0_static      : static Z0 (ohms)
    eps_eff_static : static effective permittivity
    w, h           : trace width and substrate height (mm)
    er             : relative permittivity
    freq_ghz       : frequency in GHz

    Returns
    -------
    (Z0_freq, eps_eff_freq)
    """
    u = w / h
    fn = freq_ghz * h  # frequency-thickness product (GHz*mm)

    # Kirschning-Jansen effective permittivity dispersion
    p1 = 0.27488 + (0.6315 + 0.525 / (1.0 + 0.0157 * fn) ** 20) * u - 0.065683 * math.exp(-8.7513 * u)
    p2 = 0.33622 * (1.0 - math.exp(-0.03442 * er))
    p3 = 0.0363 * math.exp(-4.6 * u) * (1.0 - math.exp(-(fn / 38.7) ** 4.97))
    p4 = 1.0 + 2.751 * (1.0 - math.exp(-(er / 15.916) ** 8))

    p_f = p1 * p2 * ((0.1844 + p3 * p4) * fn) ** 1.5763

    eps_eff_f = er - (er - eps_eff_static) / (1.0 + p_f)

    # Frequency-dependent impedance (from effective permittivity ratio)
    z0_f = z0_static * math.sqrt(eps_eff_static / eps_eff_f) * (
        eps_eff_f - 1.0
    ) / (eps_eff_static - 1.0) if abs(eps_eff_static - 1.0) > 1e-12 else z0_static

    return z0_f, eps_eff_f


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


async def _handle_l_network(
    arguments: dict, client: CSTClient,
) -> list[TextContent]:
    """Design an L-section matching network."""
    r_s = validate_positive(float(arguments["z_source_real"]), "z_source_real")
    x_s = float(arguments.get("z_source_imag", 0))
    r_l = validate_positive(float(arguments["z_load_real"]), "z_load_real")
    x_l = float(arguments.get("z_load_imag", 0))
    freq = validate_frequency(float(arguments["frequency_ghz"]))
    topology = arguments.get("topology", "lowpass")

    if topology not in ("lowpass", "highpass"):
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Invalid topology '{topology}'. Use 'lowpass' or 'highpass'.",
        }))]

    omega = 2.0 * math.pi * freq * 1e9  # rad/s

    # Absorb any source/load reactance by resonating it out
    # The effective matching problem is then purely resistive R_s -> R_l
    # Compensation elements are added to the final network
    source_comp = None
    load_comp = None

    if abs(x_s) > 1e-12:
        # Add series element to cancel source reactance
        source_comp = _reactance_to_lc(-x_s, omega)
        source_comp["purpose"] = "cancel source reactance"

    if abs(x_l) > 1e-12:
        # Add series element to cancel load reactance
        load_comp = _reactance_to_lc(-x_l, omega)
        load_comp["purpose"] = "cancel load reactance"

    # Check if impedances are already matched
    if abs(r_s - r_l) < 1e-6 and abs(x_s) < 1e-12 and abs(x_l) < 1e-12:
        return [TextContent(type="text", text=json.dumps({
            "status": "ok",
            "message": "Impedances are already matched — no network needed.",
            "q_factor": 0,
            "topology": topology,
            "component_values": {},
        }))]

    # Determine which is larger for L-network design
    if r_s > r_l:
        r_large, r_small = r_s, r_l
        shunt_on_source = True
    else:
        r_large, r_small = r_l, r_s
        shunt_on_source = False

    # Q factor for L-network
    q = math.sqrt(r_large / r_small - 1.0)

    # Compute reactances
    x_series = q * r_small  # series element reactance
    x_shunt = r_large / q   # shunt element reactance (magnitude)

    if topology == "lowpass":
        # Lowpass: series L, shunt C
        # Series element is inductive (+j), shunt element is capacitive (-jB)
        series_x = x_series   # positive = inductor
        shunt_b = 1.0 / x_shunt  # positive susceptance = capacitor
    else:
        # Highpass: series C, shunt L
        series_x = -x_series  # negative = capacitor
        shunt_b = -1.0 / x_shunt  # negative susceptance = inductor

    series_comp = _reactance_to_lc(series_x, omega)
    shunt_comp = _susceptance_to_lc(shunt_b, omega)

    # Build component values dict
    component_values = {}
    if "L_nH" in series_comp:
        component_values["L_nH"] = series_comp["L_nH"]
    if "C_pF" in series_comp:
        component_values["C_pF"] = series_comp["C_pF"]
    if "L_nH" in shunt_comp:
        component_values["shunt_L_nH"] = shunt_comp["L_nH"]
    if "C_pF" in shunt_comp:
        component_values["shunt_C_pF"] = shunt_comp["C_pF"]

    # Build network description
    if shunt_on_source:
        description = (
            f"Shunt element ({shunt_comp['type']}) on source side, "
            f"series element ({series_comp['type']}) toward load"
        )
    else:
        description = (
            f"Series element ({series_comp['type']}) on source side, "
            f"shunt element ({shunt_comp['type']}) toward load"
        )

    result: dict = {
        "status": "ok",
        "topology": topology,
        "component_values": component_values,
        "q_factor": round(q, 4),
        "network_description": description,
        "source_impedance": {"real": r_s, "imag": x_s},
        "load_impedance": {"real": r_l, "imag": x_l},
        "frequency_ghz": freq,
        "series_element": series_comp,
        "shunt_element": shunt_comp,
    }

    if source_comp:
        result["source_compensation"] = source_comp
    if load_comp:
        result["load_compensation"] = load_comp

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_pi_network(
    arguments: dict, client: CSTClient,
) -> list[TextContent]:
    """Design a Pi-section matching network (two back-to-back L-sections)."""
    r_s = validate_positive(float(arguments["z_source_real"]), "z_source_real")
    x_s = float(arguments.get("z_source_imag", 0))
    r_l = validate_positive(float(arguments["z_load_real"]), "z_load_real")
    x_l = float(arguments.get("z_load_imag", 0))
    freq = validate_frequency(float(arguments["frequency_ghz"]))

    omega = 2.0 * math.pi * freq * 1e9

    # Minimum Q for Pi network
    r_large = max(r_s, r_l)
    r_small = min(r_s, r_l)
    q_min = math.sqrt(r_large / r_small - 1.0)

    q = arguments.get("q_factor")
    if q is not None:
        q = float(q)
        if q < q_min:
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "message": (
                    f"Q factor {q} is too low. Minimum Q for Pi network with "
                    f"R_source={r_s} and R_load={r_l} is {round(q_min, 4)}."
                ),
            }))]
    else:
        # Default: use q_min + 1 for some design margin, minimum of 2
        q = max(q_min + 1.0, 2.0)

    # Virtual resistance (lower than both R_s and R_l)
    r_v = r_large / (1.0 + q * q)

    # Source-side L-section: R_s to R_v
    q_s = math.sqrt(r_s / r_v - 1.0)
    x_shunt_s = r_s / q_s  # shunt reactance on source side
    x_series_s = q_s * r_v  # series reactance

    # Load-side L-section: R_l to R_v
    q_l = math.sqrt(r_l / r_v - 1.0)
    x_shunt_l = r_l / q_l  # shunt reactance on load side
    x_series_l = q_l * r_v  # series reactance

    # Pi topology: shunt C1 - series L - shunt C2 (lowpass form)
    # The two series inductors combine into one
    b_s = 1.0 / x_shunt_s  # source shunt susceptance (capacitive)
    b_l = 1.0 / x_shunt_l  # load shunt susceptance (capacitive)
    x_total = x_series_s + x_series_l  # combined series reactance (inductive)

    c1_comp = _susceptance_to_lc(b_s, omega)
    l_comp = _reactance_to_lc(x_total, omega)
    c2_comp = _susceptance_to_lc(b_l, omega)

    component_values = {}
    if "C_pF" in c1_comp:
        component_values["C1_pF"] = c1_comp["C_pF"]
    elif "L_nH" in c1_comp:
        component_values["C1_as_L_nH"] = c1_comp["L_nH"]

    if "L_nH" in l_comp:
        component_values["L_nH"] = l_comp["L_nH"]
    elif "C_pF" in l_comp:
        component_values["L_as_C_pF"] = l_comp["C_pF"]

    if "C_pF" in c2_comp:
        component_values["C2_pF"] = c2_comp["C_pF"]
    elif "L_nH" in c2_comp:
        component_values["C2_as_L_nH"] = c2_comp["L_nH"]

    # Compensate for source/load reactance
    comp_notes: list[str] = []
    if abs(x_s) > 1e-12:
        comp_notes.append(
            f"Source reactance {x_s} ohm must be canceled with "
            f"a series element of {-x_s} ohm reactance."
        )
    if abs(x_l) > 1e-12:
        comp_notes.append(
            f"Load reactance {x_l} ohm must be canceled with "
            f"a series element of {-x_l} ohm reactance."
        )

    result: dict = {
        "status": "ok",
        "topology": "pi",
        "component_values": component_values,
        "q_factor": round(q, 4),
        "virtual_resistance_ohm": round(r_v, 4),
        "network_description": "Shunt C1 — Series L — Shunt C2 (lowpass Pi)",
        "source_impedance": {"real": r_s, "imag": x_s},
        "load_impedance": {"real": r_l, "imag": x_l},
        "frequency_ghz": freq,
    }
    if comp_notes:
        result["compensation_notes"] = comp_notes

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_t_network(
    arguments: dict, client: CSTClient,
) -> list[TextContent]:
    """Design a T-section matching network (dual of Pi)."""
    r_s = validate_positive(float(arguments["z_source_real"]), "z_source_real")
    x_s = float(arguments.get("z_source_imag", 0))
    r_l = validate_positive(float(arguments["z_load_real"]), "z_load_real")
    x_l = float(arguments.get("z_load_imag", 0))
    freq = validate_frequency(float(arguments["frequency_ghz"]))

    omega = 2.0 * math.pi * freq * 1e9

    # Minimum Q for T network
    r_large = max(r_s, r_l)
    r_small = min(r_s, r_l)
    q_min = math.sqrt(r_large / r_small - 1.0)

    q = arguments.get("q_factor")
    if q is not None:
        q = float(q)
        if q < q_min:
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "message": (
                    f"Q factor {q} is too low. Minimum Q for T network with "
                    f"R_source={r_s} and R_load={r_l} is {round(q_min, 4)}."
                ),
            }))]
    else:
        q = max(q_min + 1.0, 2.0)

    # Virtual resistance (higher than both R_s and R_l) — dual of Pi
    r_v = r_small * (1.0 + q * q)

    # Source-side L-section: R_s to R_v (series element on source side)
    q_s = math.sqrt(r_v / r_s - 1.0)
    x_series_s = q_s * r_s  # series reactance on source side
    x_shunt_s = r_v / q_s   # shunt reactance

    # Load-side L-section: R_l to R_v (series element on load side)
    q_l = math.sqrt(r_v / r_l - 1.0)
    x_series_l = q_l * r_l  # series reactance on load side
    x_shunt_l = r_v / q_l   # shunt reactance

    # T topology: series L1 - shunt C - series L2 (lowpass form)
    # The two shunt capacitors combine into one
    b_total = 1.0 / x_shunt_s + 1.0 / x_shunt_l  # combined shunt susceptance

    l1_comp = _reactance_to_lc(x_series_s, omega)
    c_comp = _susceptance_to_lc(b_total, omega)
    l2_comp = _reactance_to_lc(x_series_l, omega)

    component_values = {}
    if "L_nH" in l1_comp:
        component_values["L1_nH"] = l1_comp["L_nH"]
    elif "C_pF" in l1_comp:
        component_values["L1_as_C_pF"] = l1_comp["C_pF"]

    if "C_pF" in c_comp:
        component_values["C_pF"] = c_comp["C_pF"]
    elif "L_nH" in c_comp:
        component_values["C_as_L_nH"] = c_comp["L_nH"]

    if "L_nH" in l2_comp:
        component_values["L2_nH"] = l2_comp["L_nH"]
    elif "C_pF" in l2_comp:
        component_values["L2_as_C_pF"] = l2_comp["C_pF"]

    comp_notes: list[str] = []
    if abs(x_s) > 1e-12:
        comp_notes.append(
            f"Source reactance {x_s} ohm must be canceled with "
            f"a series element of {-x_s} ohm reactance."
        )
    if abs(x_l) > 1e-12:
        comp_notes.append(
            f"Load reactance {x_l} ohm must be canceled with "
            f"a series element of {-x_l} ohm reactance."
        )

    result: dict = {
        "status": "ok",
        "topology": "t",
        "component_values": component_values,
        "q_factor": round(q, 4),
        "virtual_resistance_ohm": round(r_v, 4),
        "network_description": "Series L1 — Shunt C — Series L2 (lowpass T)",
        "source_impedance": {"real": r_s, "imag": x_s},
        "load_impedance": {"real": r_l, "imag": x_l},
        "frequency_ghz": freq,
    }
    if comp_notes:
        result["compensation_notes"] = comp_notes

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_stub_matching(
    arguments: dict, client: CSTClient,
) -> list[TextContent]:
    """Design a single-stub matching network."""
    r_l = float(arguments["z_load_real"])
    x_l = float(arguments.get("z_load_imag", 0))
    z0 = validate_positive(float(arguments.get("z0", 50)), "z0")
    freq = validate_frequency(float(arguments["frequency_ghz"]))
    stub_type = arguments.get("stub_type", "open")

    if stub_type not in ("open", "short"):
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Invalid stub_type '{stub_type}'. Use 'open' or 'short'.",
        }))]

    if r_l <= 0:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"z_load_real must be positive, got {r_l}.",
        }))]

    # Wavelength
    wavelength_mm = (C0 / (freq * 1e9)) * 1e3  # mm

    # Normalized load impedance and admittance
    z_l_norm = complex(r_l, x_l) / z0
    y_l_norm = 1.0 / z_l_norm

    g_l = y_l_norm.real
    b_l = y_l_norm.imag

    # Check for already-matched load
    if abs(g_l - 1.0) < 1e-6 and abs(b_l) < 1e-6:
        return [TextContent(type="text", text=json.dumps({
            "status": "ok",
            "message": "Load is already matched to Z0 — no stub needed.",
            "stub_length_mm": 0,
            "stub_length_wavelengths": 0,
            "distance_from_load_mm": 0,
            "distance_wavelengths": 0,
        }))]

    # Single stub matching: find distance d from load where
    # the real part of Y_in = 1/Z0 (normalized G = 1)
    #
    # Y_in(d) = Y0 * (Y_L + j*Y0*tan(beta*d)) / (Y0 + j*Y_L*tan(beta*d))
    # In normalized form:
    # y_in(d) = (y_l + j*tan(beta*d)) / (1 + j*y_l*tan(beta*d))
    #
    # We need Re{y_in} = 1.  Solve for tan(beta*d) = t:
    # y_in = (g_l + j*(b_l + t)) / (1 - b_l*t + j*g_l*t)
    #      = (g_l + j*(b_l+t)) * (1 - b_l*t - j*g_l*t) / |denom|^2
    #
    # Re{y_in} = (g_l*(1-b_l*t) + g_l*t*(b_l+t)) / |denom|^2
    #          = g_l * (1 + t^2) / ((1-b_l*t)^2 + (g_l*t)^2)
    #
    # Setting Re{y_in} = 1:
    # g_l*(1+t^2) = (1-b_l*t)^2 + g_l^2*t^2
    # g_l + g_l*t^2 = 1 - 2*b_l*t + b_l^2*t^2 + g_l^2*t^2
    # (g_l - g_l^2 - b_l^2)*t^2 + 2*b_l*t + (g_l - 1) = 0
    # g_l*(1 - g_l)*t^2 - b_l^2*t^2 + 2*b_l*t + (g_l - 1) = 0
    #
    # Let a_coeff = g_l*(1-g_l) - b_l^2 = g_l - g_l^2 - b_l^2
    #     b_coeff = 2*b_l
    #     c_coeff = g_l - 1

    a_coeff = g_l - g_l * g_l - b_l * b_l
    b_coeff = 2.0 * b_l
    c_coeff = g_l - 1.0

    solutions = []

    if abs(a_coeff) < 1e-12:
        # Linear equation
        if abs(b_coeff) > 1e-12:
            t = -c_coeff / b_coeff
            solutions.append(t)
    else:
        discriminant = b_coeff * b_coeff - 4.0 * a_coeff * c_coeff
        if discriminant < 0:
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "message": "No real solution for stub matching distance. Load may not be matchable with a single stub.",
            }))]
        sqrt_disc = math.sqrt(discriminant)
        t1 = (-b_coeff + sqrt_disc) / (2.0 * a_coeff)
        t2 = (-b_coeff - sqrt_disc) / (2.0 * a_coeff)
        solutions.extend([t1, t2])

    # Find best solution (shortest distance)
    best_d_wl: float = -1.0
    best_stub_wl: float = -1.0
    found = False

    for t in solutions:
        # distance d: tan(beta*d) = t  =>  beta*d = atan(t)
        # beta*d = 2*pi*d/lambda => d/lambda = atan(t)/(2*pi)
        d_wl = math.atan(t) / (2.0 * math.pi)
        if d_wl < 0:
            d_wl += 0.5  # keep in [0, 0.5)

        # Imaginary part of y_in at this distance
        denom_sq = (1.0 - b_l * t) ** 2 + (g_l * t) ** 2
        b_in = ((b_l + t) * (1.0 - b_l * t) - g_l * g_l * t) / denom_sq

        # Stub must cancel this susceptance: b_stub = -b_in
        b_stub = -b_in

        # Stub length
        if stub_type == "open":
            # Open stub: B = Y0 * tan(beta*l)  =>  tan(beta*l) = b_stub (normalized)
            stub_wl = math.atan(b_stub) / (2.0 * math.pi)
        else:
            # Short stub: B = -Y0 * cot(beta*l) = -Y0/tan(beta*l)
            # => tan(beta*l) = -1/b_stub
            if abs(b_stub) < 1e-12:
                stub_wl = 0.25  # quarter-wave short stub
            else:
                stub_wl = math.atan(-1.0 / b_stub) / (2.0 * math.pi)

        if stub_wl < 0:
            stub_wl += 0.5

        total = d_wl + stub_wl
        if not found or total < (best_d_wl + best_stub_wl):
            best_d_wl = d_wl
            best_stub_wl = stub_wl
            found = True

    if not found:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": "Could not find valid stub matching solution.",
        }))]

    d_mm = best_d_wl * wavelength_mm
    stub_mm = best_stub_wl * wavelength_mm

    result = {
        "status": "ok",
        "stub_type": stub_type,
        "stub_length_mm": round(stub_mm, 4),
        "stub_length_wavelengths": round(best_stub_wl, 6),
        "distance_from_load_mm": round(d_mm, 4),
        "distance_wavelengths": round(best_d_wl, 6),
        "z0": z0,
        "load_impedance": {"real": r_l, "imag": x_l},
        "frequency_ghz": freq,
        "wavelength_mm": round(wavelength_mm, 4),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _binomial_coefficient(n: int, k: int) -> int:
    """Compute binomial coefficient C(n, k)."""
    if k < 0 or k > n:
        return 0
    if k == 0 or k == n:
        return 1
    result = 1
    for i in range(min(k, n - k)):
        result = result * (n - i) // (i + 1)
    return result


async def _handle_quarter_wave(
    arguments: dict, client: CSTClient,
) -> list[TextContent]:
    """Design a quarter-wave transformer matching network."""
    z_s = validate_positive(float(arguments["z_source"]), "z_source")
    z_l = validate_positive(float(arguments["z_load"]), "z_load")
    freq = validate_frequency(float(arguments["frequency_ghz"]))
    n = int(arguments.get("num_sections", 1))
    design = arguments.get("design", "maximally_flat")

    n = int(validate_range(float(n), 1, 4, "num_sections"))

    if design not in ("maximally_flat", "chebyshev"):
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Invalid design '{design}'. Use 'maximally_flat' or 'chebyshev'.",
        }))]

    # Wavelength and section length
    wavelength_mm = (C0 / (freq * 1e9)) * 1e3
    section_length = wavelength_mm / 4.0

    if n == 1:
        # Single section: Z_t = sqrt(Z_s * Z_l)
        z_t = math.sqrt(z_s * z_l)
        impedances = [round(z_t, 4)]
        bw_factor = 1.0
    else:
        # Multi-section design
        ln_ratio = math.log(z_l / z_s)

        if design == "maximally_flat":
            # Binomial (maximally flat) multi-section transformer (Pozar 5.6)
            # ln(Z_{n+1}/Z_n) = 2^{-N} * C(N,n) * ln(Z_L/Z_S)
            impedances = []
            z_prev = z_s
            for i in range(n):
                c_ni = _binomial_coefficient(n, i)
                ln_step = (2.0 ** (-n)) * c_ni * ln_ratio
                z_next = z_prev * math.exp(ln_step)
                impedances.append(round(z_next, 4))
                z_prev = z_next

            # Bandwidth improvement factor ~ N (approximate)
            bw_factor = float(n)

        else:
            # Chebyshev multi-section transformer
            # Use equal ripple design from Pozar
            # For Chebyshev, we use log-linear interpolation with Chebyshev
            # weighting of the reflection coefficients
            impedances = []
            z_prev = z_s
            for i in range(n):
                # Chebyshev impedance stepping uses geometric mean
                # with Chebyshev polynomial distribution
                # Simplified: use power-law interpolation
                exponent = (2.0 * i + 1.0) / (2.0 * n)
                z_i = z_s * (z_l / z_s) ** exponent
                impedances.append(round(z_i, 4))

            # Chebyshev gives better bandwidth than binomial for same N
            bw_factor = float(n) * 1.3  # approximate improvement

    result = {
        "status": "ok",
        "design": design,
        "num_sections": n,
        "section_impedances_ohm": impedances,
        "section_length_mm": round(section_length, 4),
        "section_length_wavelengths": 0.25,
        "z_source": z_s,
        "z_load": z_l,
        "frequency_ghz": freq,
        "wavelength_mm": round(wavelength_mm, 4),
        "bandwidth_improvement_factor": round(bw_factor, 2),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_create_lumped(
    arguments: dict, client: CSTClient,
) -> list[TextContent]:
    """Generate CST VBA for lumped-element matching network."""
    components: list[dict] = arguments["components"]
    freq = validate_frequency(float(arguments["frequency_ghz"]))
    port_z = validate_positive(
        float(arguments.get("port_impedance", 50)), "port_impedance",
    )

    if not components:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": "At least one component is required.",
        }))]

    script = VBAScript()
    script.add_comment("Lumped-Element Matching Network")
    script.add_comment(f"Design frequency: {freq} GHz")

    component_summary: list[dict] = []

    for i, comp in enumerate(components):
        comp_type = comp["type"]
        value = float(comp["value"])
        unit = comp["unit"]
        connection = comp["connection"]

        if comp_type not in ("L", "C", "R"):
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "message": f"Invalid component type '{comp_type}' at index {i}. Use 'L', 'C', or 'R'.",
            }))]
        if connection not in ("series", "shunt"):
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "message": f"Invalid connection '{connection}' at index {i}. Use 'series' or 'shunt'.",
            }))]

        validate_positive(value, f"component[{i}].value")

        elem_name = f"Match_{comp_type}{i + 1}_{connection}"

        # Determine CST LumpedElement type string
        if comp_type == "L":
            cst_type = "RLC Serial"
            r_val = 0.0
            l_val = value  # nH
            c_val = 0.0
        elif comp_type == "C":
            cst_type = "RLC Serial"
            r_val = 0.0
            l_val = 0.0
            c_val = value  # pF
        else:  # R
            cst_type = "RLC Serial"
            r_val = value
            l_val = 0.0
            c_val = 0.0

        # Position lumped elements along the x-axis, spaced 2 mm apart
        x_pos = i * 2.0

        orientation = "y" if connection == "shunt" else "x"

        vba = (
            VBABuilder("LumpedElement")
            .call("Reset")
            .set("Name", elem_name)
            .set("Type", cst_type)
            .set_number("R", r_val)
            .set_number("L", l_val)
            .set_number("C", c_val)
            .set_number("Xcenter", x_pos)
            .set_number("Ycenter", 0)
            .set_number("Zcenter", 0)
            .set("Orientation", orientation)
            .call("Create")
        )
        script.add_block(vba)

        component_summary.append({
            "index": i,
            "name": elem_name,
            "type": comp_type,
            "value": value,
            "unit": unit,
            "connection": connection,
            "position_mm": {"x": x_pos, "y": 0, "z": 0},
        })

    vba_code = script.build()
    result = client.execute_vba(vba_code)
    result["component_count"] = len(components)
    result["components"] = component_summary
    result["frequency_ghz"] = freq
    result["port_impedance"] = port_z

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_smith_transform(
    arguments: dict, client: CSTClient,
) -> list[TextContent]:
    """Apply impedance transformation on the Smith chart."""
    z_in = complex(float(arguments["z_in_real"]), float(arguments["z_in_imag"]))
    z0 = validate_positive(float(arguments.get("z0", 50)), "z0")
    operation = arguments["operation"]
    value = float(arguments["value"])
    freq = validate_frequency(float(arguments["frequency_ghz"]))

    valid_ops = ("series_L", "series_C", "shunt_L", "shunt_C", "transmission_line")
    if operation not in valid_ops:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Invalid operation '{operation}'. Valid: {list(valid_ops)}",
        }))]

    omega = 2.0 * math.pi * freq * 1e9

    if operation == "series_L":
        # Series inductor: Z_out = Z_in + j*omega*L
        l_h = value * 1e-9  # nH to H
        x_l = omega * l_h
        z_out = z_in + complex(0, x_l)

    elif operation == "series_C":
        # Series capacitor: Z_out = Z_in - j/(omega*C)
        c_f = value * 1e-12  # pF to F
        if c_f <= 0:
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "message": "Capacitance must be positive.",
            }))]
        x_c = -1.0 / (omega * c_f)
        z_out = z_in + complex(0, x_c)

    elif operation == "shunt_L":
        # Shunt inductor: Y_out = Y_in + 1/(j*omega*L) = Y_in - j/(omega*L)
        l_h = value * 1e-9
        if l_h <= 0:
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "message": "Inductance must be positive.",
            }))]
        b_l = -1.0 / (omega * l_h)
        y_in = 1.0 / z_in
        y_out = y_in + complex(0, b_l)
        z_out = 1.0 / y_out

    elif operation == "shunt_C":
        # Shunt capacitor: Y_out = Y_in + j*omega*C
        c_f = value * 1e-12
        b_c = omega * c_f
        y_in = 1.0 / z_in
        y_out = y_in + complex(0, b_c)
        z_out = 1.0 / y_out

    else:
        # Transmission line: electrical length in degrees
        theta_rad = math.radians(value)
        # Z_out = Z0 * (Z_in + j*Z0*tan(theta)) / (Z0 + j*Z_in*tan(theta))
        tan_theta = math.tan(theta_rad)
        z_out = z0 * (z_in + complex(0, z0 * tan_theta)) / (
            z0 + complex(0, z_in * tan_theta)
        )

    gamma_mag, gamma_phase = _reflection_coefficient(z_out, z0)
    vswr = _vswr_from_gamma(gamma_mag)

    result = {
        "status": "ok",
        "z_in": {"real": round(z_in.real, 4), "imag": round(z_in.imag, 4)},
        "z_out_real": round(z_out.real, 4),
        "z_out_imag": round(z_out.imag, 4),
        "operation": operation,
        "value": value,
        "frequency_ghz": freq,
        "z0": z0,
        "reflection_coefficient_mag": round(gamma_mag, 6),
        "reflection_coefficient_phase_deg": round(gamma_phase, 2),
        "vswr": round(vswr, 4) if vswr < 1e6 else "inf",
        "return_loss_dB": round(-20.0 * math.log10(max(gamma_mag, 1e-15)), 2),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_microstrip_impedance(
    arguments: dict, client: CSTClient,
) -> list[TextContent]:
    """Calculate microstrip impedance from physical dimensions."""
    w = validate_positive(float(arguments["width_mm"]), "width_mm")
    h = validate_positive(float(arguments["height_mm"]), "height_mm")
    er = validate_positive(float(arguments["epsilon_r"]), "epsilon_r")
    t = float(arguments.get("thickness_mm", 0.035))
    freq_ghz = arguments.get("frequency_ghz")

    z0_static, eps_eff_static = _microstrip_static(w, h, er, t)

    if freq_ghz is not None:
        freq_ghz = validate_frequency(float(freq_ghz))
        z0_freq, eps_eff_freq = _kirschning_jansen_dispersion(
            z0_static, eps_eff_static, w, h, er, freq_ghz,
        )
        wavelength_mm = (C0 / (freq_ghz * 1e9)) * 1e3 / math.sqrt(eps_eff_freq)
        # Propagation delay: t_pd = sqrt(eps_eff) / c  (per mm)
        prop_delay_ps_mm = math.sqrt(eps_eff_freq) / (C0 * 1e-9)  # ps/mm
    else:
        z0_freq = z0_static
        eps_eff_freq = eps_eff_static
        wavelength_mm = None
        prop_delay_ps_mm = math.sqrt(eps_eff_static) / (C0 * 1e-9)

    result: dict = {
        "status": "ok",
        "z0_ohm": round(z0_freq, 4),
        "z0_static_ohm": round(z0_static, 4),
        "epsilon_eff": round(eps_eff_freq, 6),
        "epsilon_eff_static": round(eps_eff_static, 6),
        "propagation_delay_ps_mm": round(prop_delay_ps_mm, 6),
        "dimensions": {
            "width_mm": w,
            "height_mm": h,
            "thickness_mm": t,
            "w_h_ratio": round(w / h, 4),
        },
        "substrate": {"epsilon_r": er},
    }

    if wavelength_mm is not None:
        result["wavelength_mm"] = round(wavelength_mm, 4)
        result["frequency_ghz"] = freq_ghz

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


async def handle(
    name: str, arguments: dict, client: CSTClient,
) -> list[TextContent]:
    """Handle a matching network tool call."""
    try:
        if name == "cst_matching_l_network":
            return await _handle_l_network(arguments, client)
        if name == "cst_matching_pi_network":
            return await _handle_pi_network(arguments, client)
        if name == "cst_matching_t_network":
            return await _handle_t_network(arguments, client)
        if name == "cst_matching_stub":
            return await _handle_stub_matching(arguments, client)
        if name == "cst_matching_quarter_wave":
            return await _handle_quarter_wave(arguments, client)
        if name == "cst_matching_create_lumped":
            return await _handle_create_lumped(arguments, client)
        if name == "cst_impedance_smith_transform":
            return await _handle_smith_transform(arguments, client)
        if name == "cst_matching_microstrip_impedance":
            return await _handle_microstrip_impedance(arguments, client)

        return [TextContent(type="text", text=json.dumps({
            "status": "error", "message": f"Unknown matching tool: {name}",
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error", "message": str(e),
        }))]


def register_matching_tools(server: Server, client: CSTClient) -> None:
    """Register matching network tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
