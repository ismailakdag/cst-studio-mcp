"""Phased array antenna design tools for CST Studio Suite.

Provides 8 MCP tools for array synthesis:
  - Linear, planar, and circular array generation (VBA)
  - Array factor computation (pure Python)
  - Beam steering phase calculation
  - Amplitude taper design for sidelobe control
  - Grating lobe analysis
  - Mutual coupling extraction setup (VBA)

All VBA is generated through ``VBABuilder`` / ``VBAScript`` — no raw
f-strings.  Pure-Python tools use only ``math`` and ``cmath`` (no numpy).
"""

from __future__ import annotations

import cmath
import json
import math
from typing import TYPE_CHECKING, Callable

from mcp.types import TextContent, Tool

from cst_mcp.validators import (
    validate_frequency,
    validate_name,
    validate_positive,
    validate_range,
)
from cst_mcp.vba_builder import VBABuilder, VBAScript

if TYPE_CHECKING:
    from mcp.server import Server

    from cst_mcp.cst_client import CSTClient

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

C0 = 299792458.0  # speed of light in m/s

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # 1 -- Linear array
    Tool(
        name="cst_array_linear",
        description=(
            "Create a linear antenna array by replicating an element along "
            "a chosen axis. Uses Transform.Translate to produce copies named "
            "Element_1 through Element_N."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_elements": {
                    "type": "integer",
                    "description": "Number of elements (2-64)",
                    "minimum": 2,
                    "maximum": 64,
                },
                "spacing_mm": {
                    "type": "number",
                    "description": "Inter-element spacing in mm",
                },
                "axis": {
                    "type": "string",
                    "enum": ["x", "y"],
                    "description": "Array axis (default x)",
                    "default": "x",
                },
                "element_component": {
                    "type": "string",
                    "description": "Component name of the element to replicate (default Antenna)",
                    "default": "Antenna",
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design frequency in GHz (for wavelength reference)",
                },
            },
            "required": ["num_elements", "spacing_mm", "frequency_ghz"],
        },
    ),

    # 2 -- Planar array
    Tool(
        name="cst_array_planar",
        description=(
            "Create a 2D planar antenna array with rectangular or triangular "
            "lattice. Replicates an element in X and Y using "
            "Transform.Translate."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_x": {
                    "type": "integer",
                    "description": "Number of elements along X",
                    "minimum": 1,
                    "maximum": 64,
                },
                "num_y": {
                    "type": "integer",
                    "description": "Number of elements along Y",
                    "minimum": 1,
                    "maximum": 64,
                },
                "spacing_x_mm": {
                    "type": "number",
                    "description": "Inter-element spacing along X in mm",
                },
                "spacing_y_mm": {
                    "type": "number",
                    "description": "Inter-element spacing along Y in mm",
                },
                "lattice": {
                    "type": "string",
                    "enum": ["rectangular", "triangular"],
                    "description": "Lattice type (default rectangular)",
                    "default": "rectangular",
                },
                "element_component": {
                    "type": "string",
                    "description": "Component name of the element to replicate (default Antenna)",
                    "default": "Antenna",
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design frequency in GHz (for wavelength reference)",
                },
            },
            "required": ["num_x", "num_y", "spacing_x_mm", "spacing_y_mm", "frequency_ghz"],
        },
    ),

    # 3 -- Circular array
    Tool(
        name="cst_array_circular",
        description=(
            "Create a circular antenna array by placing elements at equal "
            "angular intervals around a circle of given radius."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_elements": {
                    "type": "integer",
                    "description": "Number of elements (2-64)",
                    "minimum": 2,
                    "maximum": 64,
                },
                "radius_mm": {
                    "type": "number",
                    "description": "Array circle radius in mm",
                },
                "element_component": {
                    "type": "string",
                    "description": "Component name of the element to replicate (default Antenna)",
                    "default": "Antenna",
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design frequency in GHz (for wavelength reference)",
                },
            },
            "required": ["num_elements", "radius_mm", "frequency_ghz"],
        },
    ),

    # 4 -- Array factor computation (pure Python)
    Tool(
        name="cst_array_compute_factor",
        description=(
            "Compute the array factor analytically for a linear or planar "
            "array. Returns AF(theta) in dB, half-power beamwidth, first "
            "null beamwidth, peak sidelobe level, and directivity."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_elements": {
                    "type": "integer",
                    "description": "Number of elements",
                    "minimum": 2,
                },
                "spacing_wavelengths": {
                    "type": "number",
                    "description": "Inter-element spacing in wavelengths (d/lambda)",
                },
                "scan_angle_deg": {
                    "type": "number",
                    "description": "Scan angle in degrees from broadside (default 0)",
                    "default": 0,
                },
                "amplitude_weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Amplitude weights per element (default uniform)",
                },
                "array_type": {
                    "type": "string",
                    "enum": ["linear", "planar"],
                    "description": "Array type (default linear)",
                    "default": "linear",
                },
            },
            "required": ["num_elements", "spacing_wavelengths"],
        },
    ),

    # 5 -- Beam steering phase computation
    Tool(
        name="cst_array_beam_steering",
        description=(
            "Calculate progressive phase weights to steer the main beam to "
            "a specified angle. Returns phase weights and VBA to set port "
            "phases in CST."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_elements": {
                    "type": "integer",
                    "description": "Number of elements",
                    "minimum": 2,
                },
                "spacing_mm": {
                    "type": "number",
                    "description": "Inter-element spacing in mm",
                },
                "frequency_ghz": {
                    "type": "number",
                    "description": "Operating frequency in GHz",
                },
                "scan_theta_deg": {
                    "type": "number",
                    "description": "Desired scan angle theta in degrees from broadside",
                },
                "scan_phi_deg": {
                    "type": "number",
                    "description": "Desired scan angle phi in degrees (default 0)",
                    "default": 0,
                },
            },
            "required": ["num_elements", "spacing_mm", "frequency_ghz", "scan_theta_deg"],
        },
    ),

    # 6 -- Amplitude taper design (pure Python)
    Tool(
        name="cst_array_taper_design",
        description=(
            "Design amplitude taper weights for sidelobe control. Supports "
            "uniform, cosine, Hamming, Hanning, Blackman, Taylor, and "
            "Chebyshev window functions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_elements": {
                    "type": "integer",
                    "description": "Number of elements",
                    "minimum": 2,
                },
                "taper_type": {
                    "type": "string",
                    "enum": [
                        "uniform", "cosine", "hamming", "hanning",
                        "blackman", "taylor", "chebyshev",
                    ],
                    "description": "Window/taper type",
                },
                "sidelobe_level_db": {
                    "type": "number",
                    "description": "Desired peak sidelobe level in dB (negative, default -25). Used for Taylor and Chebyshev only.",
                    "default": -25,
                },
            },
            "required": ["num_elements", "taper_type"],
        },
    ),

    # 7 -- Grating lobe analysis (pure Python)
    Tool(
        name="cst_array_grating_lobe_analysis",
        description=(
            "Analyse whether grating lobes exist for a given element spacing "
            "and maximum scan angle. Returns safe spacing and grating lobe "
            "angles."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "spacing_wavelengths": {
                    "type": "number",
                    "description": "Inter-element spacing in wavelengths (d/lambda)",
                },
                "max_scan_angle_deg": {
                    "type": "number",
                    "description": "Maximum scan angle from broadside in degrees (default 60)",
                    "default": 60,
                },
            },
            "required": ["spacing_wavelengths"],
        },
    ),

    # 8 -- Mutual coupling extraction setup
    Tool(
        name="cst_array_mutual_coupling",
        description=(
            "Set up a multi-port S-parameter simulation in CST for mutual "
            "coupling extraction between array elements."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "num_ports": {
                    "type": "integer",
                    "description": "Total number of ports in the array",
                    "minimum": 2,
                },
                "port_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Explicit port numbers to include (default 1..num_ports)",
                },
            },
            "required": ["num_ports"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _result_json(calculated: dict, vba_script: str, notes: list[str]) -> str:
    """Format the standard return payload (matches antenna_templates pattern)."""
    return json.dumps({
        "calculated_parameters": calculated,
        "vba_script": vba_script,
        "notes": notes,
    }, indent=2)


def _wavelength_mm(freq_ghz: float) -> float:
    """Free-space wavelength in mm for a given frequency in GHz."""
    return (C0 / (freq_ghz * 1e9)) * 1000.0


# ---------------------------------------------------------------------------
# 1. Linear array
# ---------------------------------------------------------------------------


def _build_linear_array(args: dict) -> str:
    num = int(args["num_elements"])
    spacing = float(args["spacing_mm"])
    axis = args.get("axis", "x").lower()
    component = args.get("element_component", "Antenna")
    freq = float(args["frequency_ghz"])

    validate_range(num, 2, 64, "num_elements")
    validate_positive(spacing, "spacing_mm")
    validate_frequency(freq)
    validate_name(component, "element_component")
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y'")

    lam = _wavelength_mm(freq)

    script = VBAScript()
    script.add_comment(f"Linear array: {num} elements, spacing={spacing:.2f} mm, axis={axis}")
    script.add_comment(f"Frequency: {freq} GHz, wavelength: {lam:.2f} mm")
    script.add_comment(f"Spacing = {spacing / lam:.3f} wavelengths")

    # Element 1 is the original — copy for elements 2..N
    for i in range(1, num):
        dx = spacing * i if axis == "x" else 0.0
        dy = spacing * i if axis == "y" else 0.0
        solid_ref = f"{component}:Element_1"

        vba = VBABuilder("Transform")
        vba.call("Reset")
        vba.set("Name", solid_ref)
        vba.set_number("TranslateX", dx)
        vba.set_number("TranslateY", dy)
        vba.set_number("TranslateZ", 0)
        vba.set("Copy", "True")
        vba.set("Destination", f"Element_{i + 1}")
        vba.call_with_args("Transform", "Shape", "Translate")
        script.add_block(vba)

    return _result_json(
        calculated={
            "num_elements": num,
            "spacing_mm": spacing,
            "spacing_wavelengths": spacing / lam,
            "wavelength_mm": round(lam, 3),
            "total_length_mm": round(spacing * (num - 1), 3),
            "axis": axis,
        },
        vba_script=script.build(),
        notes=[
            f"Element_1 must already exist in component '{component}'.",
            f"Array spans {spacing * (num - 1):.1f} mm along {axis}-axis.",
            f"Element spacing is {spacing / lam:.3f} wavelengths at {freq} GHz.",
        ],
    )


# ---------------------------------------------------------------------------
# 2. Planar array
# ---------------------------------------------------------------------------


def _build_planar_array(args: dict) -> str:
    num_x = int(args["num_x"])
    num_y = int(args["num_y"])
    dx = float(args["spacing_x_mm"])
    dy = float(args["spacing_y_mm"])
    lattice = args.get("lattice", "rectangular").lower()
    component = args.get("element_component", "Antenna")
    freq = float(args["frequency_ghz"])

    validate_range(num_x, 1, 64, "num_x")
    validate_range(num_y, 1, 64, "num_y")
    validate_positive(dx, "spacing_x_mm")
    validate_positive(dy, "spacing_y_mm")
    validate_frequency(freq)
    validate_name(component, "element_component")
    if lattice not in ("rectangular", "triangular"):
        raise ValueError("lattice must be 'rectangular' or 'triangular'")

    lam = _wavelength_mm(freq)
    total = num_x * num_y

    script = VBAScript()
    script.add_comment(
        f"Planar array: {num_x}x{num_y} ({total} elements), "
        f"dx={dx:.2f} mm, dy={dy:.2f} mm, lattice={lattice}"
    )
    script.add_comment(f"Frequency: {freq} GHz, wavelength: {lam:.2f} mm")

    idx = 1
    for iy in range(num_y):
        for ix in range(num_x):
            if ix == 0 and iy == 0:
                # Element_1 is the original
                idx += 1
                continue
            x_offset = dx * ix
            y_offset = dy * iy
            # Triangular lattice: offset odd rows by dx/2
            if lattice == "triangular" and iy % 2 == 1:
                x_offset += dx / 2.0

            solid_ref = f"{component}:Element_1"
            vba = VBABuilder("Transform")
            vba.call("Reset")
            vba.set("Name", solid_ref)
            vba.set_number("TranslateX", x_offset)
            vba.set_number("TranslateY", y_offset)
            vba.set_number("TranslateZ", 0)
            vba.set("Copy", "True")
            vba.set("Destination", f"Element_{idx}")
            vba.call_with_args("Transform", "Shape", "Translate")
            script.add_block(vba)
            idx += 1

    return _result_json(
        calculated={
            "num_x": num_x,
            "num_y": num_y,
            "total_elements": total,
            "spacing_x_mm": dx,
            "spacing_y_mm": dy,
            "spacing_x_wavelengths": dx / lam,
            "spacing_y_wavelengths": dy / lam,
            "wavelength_mm": round(lam, 3),
            "lattice": lattice,
            "array_size_x_mm": round(dx * (num_x - 1), 3),
            "array_size_y_mm": round(dy * (num_y - 1), 3),
        },
        vba_script=script.build(),
        notes=[
            f"Element_1 must already exist in component '{component}'.",
            f"Array has {total} elements in a {lattice} lattice.",
            f"X-spacing = {dx / lam:.3f} lambda, Y-spacing = {dy / lam:.3f} lambda.",
        ],
    )


# ---------------------------------------------------------------------------
# 3. Circular array
# ---------------------------------------------------------------------------


def _build_circular_array(args: dict) -> str:
    num = int(args["num_elements"])
    radius = float(args["radius_mm"])
    component = args.get("element_component", "Antenna")
    freq = float(args["frequency_ghz"])

    validate_range(num, 2, 64, "num_elements")
    validate_positive(radius, "radius_mm")
    validate_frequency(freq)
    validate_name(component, "element_component")

    lam = _wavelength_mm(freq)
    angle_step = 360.0 / num

    script = VBAScript()
    script.add_comment(
        f"Circular array: {num} elements, radius={radius:.2f} mm, "
        f"angular step={angle_step:.1f} deg"
    )
    script.add_comment(f"Frequency: {freq} GHz, wavelength: {lam:.2f} mm")

    # Element_1 is assumed at (radius, 0). Copy and rotate for elements 2..N
    for i in range(1, num):
        angle = angle_step * i
        # Translate to radius, then rotate
        vba = VBABuilder("Transform")
        vba.call("Reset")
        vba.set("Name", f"{component}:Element_1")
        vba.set_number("OriginX", 0)
        vba.set_number("OriginY", 0)
        vba.set_number("OriginZ", 0)
        vba.set_number("Angle", angle)
        vba.set("PlaneNormal", "z")
        vba.set("Copy", "True")
        vba.set("Destination", f"Element_{i + 1}")
        vba.call_with_args("Transform", "Shape", "Rotate")
        script.add_block(vba)

    # Element inter-spacing along the arc
    arc_spacing = 2.0 * radius * math.sin(math.pi / num)

    return _result_json(
        calculated={
            "num_elements": num,
            "radius_mm": radius,
            "angular_step_deg": round(angle_step, 3),
            "arc_spacing_mm": round(arc_spacing, 3),
            "arc_spacing_wavelengths": round(arc_spacing / lam, 3),
            "wavelength_mm": round(lam, 3),
            "circumference_mm": round(2 * math.pi * radius, 3),
        },
        vba_script=script.build(),
        notes=[
            f"Element_1 must already exist in component '{component}' at radius={radius} mm on the +X axis.",
            f"Elements are rotated about the Z-axis at {angle_step:.1f} deg intervals.",
            f"Arc spacing between adjacent elements is {arc_spacing:.2f} mm "
            f"({arc_spacing / lam:.3f} wavelengths).",
        ],
    )


# ---------------------------------------------------------------------------
# 4. Array factor computation (pure Python, no VBA)
# ---------------------------------------------------------------------------


def _build_array_factor(args: dict) -> str:
    num = int(args["num_elements"])
    d_lam = float(args["spacing_wavelengths"])
    scan_deg = float(args.get("scan_angle_deg", 0))
    weights = args.get("amplitude_weights", None)
    array_type = args.get("array_type", "linear")

    if num < 2:
        raise ValueError("num_elements must be >= 2")
    validate_positive(d_lam, "spacing_wavelengths")
    if array_type not in ("linear", "planar"):
        raise ValueError("array_type must be 'linear' or 'planar'")

    # Default uniform weights
    if weights is None:
        weights = [1.0] * num
    elif len(weights) != num:
        raise ValueError(
            f"amplitude_weights length ({len(weights)}) must match num_elements ({num})"
        )

    k = 2.0 * math.pi  # k*d = 2*pi*d/lambda, d in wavelengths so k = 2pi
    d = d_lam  # spacing in wavelengths
    beta = -k * d * math.sin(math.radians(scan_deg))  # progressive phase for steering

    # Compute AF(theta) over -90..+90 degrees in 0.5-degree steps
    theta_deg_list: list[float] = []
    af_linear: list[float] = []  # |AF| (linear)

    step = 0.5
    n_points = int(180.0 / step) + 1
    for idx in range(n_points):
        theta = -90.0 + idx * step
        theta_rad = math.radians(theta)
        psi = k * d * math.sin(theta_rad) + beta

        # AF = sum( a_n * exp(j * n * psi) )
        af = complex(0.0, 0.0)
        for n in range(num):
            af += weights[n] * cmath.exp(1j * n * psi)

        theta_deg_list.append(theta)
        af_linear.append(abs(af))

    # Normalise and convert to dB
    peak = max(af_linear)
    if peak == 0:
        raise ValueError("Array factor is identically zero — check weights")

    af_db: list[float] = []
    for val in af_linear:
        ratio = val / peak
        if ratio < 1e-15:
            af_db.append(-300.0)
        else:
            af_db.append(20.0 * math.log10(ratio))

    # --- Derived metrics ---

    # Half-power beamwidth (HPBW): find -3 dB crossings around the main beam
    peak_idx = af_db.index(max(af_db))
    hpbw = _find_beamwidth(af_db, theta_deg_list, peak_idx, -3.0)

    # First null beamwidth (FNBW)
    fnbw = _find_null_beamwidth(af_db, theta_deg_list, peak_idx)

    # Peak sidelobe level
    psll = _find_peak_sidelobe(af_db, theta_deg_list, peak_idx)

    # Directivity estimate: D = 2 * |AF_max|^2 / integral(|AF|^2 sin(theta) dtheta)
    directivity_db = _estimate_directivity(af_linear, theta_deg_list, step)

    # Subsample for output (every 1 degree)
    out_theta: list[float] = []
    out_af: list[float] = []
    for i in range(0, len(theta_deg_list), 2):  # step=0.5, take every 2 => 1 deg
        out_theta.append(round(theta_deg_list[i], 1))
        out_af.append(round(af_db[i], 2))

    return json.dumps({
        "theta_deg": out_theta,
        "af_db": out_af,
        "half_power_beamwidth_deg": round(hpbw, 2),
        "first_null_beamwidth_deg": round(fnbw, 2),
        "peak_sidelobe_level_db": round(psll, 2),
        "directivity_db": round(directivity_db, 2),
        "scan_angle_deg": scan_deg,
        "num_elements": num,
        "spacing_wavelengths": d_lam,
    }, indent=2)


def _find_beamwidth(
    af_db: list[float], theta: list[float], peak_idx: int, level_db: float
) -> float:
    """Find the beamwidth at a given dB level around the main beam."""
    # Search left from peak
    left_theta = theta[0]
    for i in range(peak_idx, -1, -1):
        if af_db[i] <= level_db:
            # Linear interpolation
            if i + 1 <= peak_idx:
                frac = (level_db - af_db[i]) / (af_db[i + 1] - af_db[i]) if af_db[i + 1] != af_db[i] else 0
                left_theta = theta[i] + frac * (theta[i + 1] - theta[i])
            else:
                left_theta = theta[i]
            break

    # Search right from peak
    right_theta = theta[-1]
    for i in range(peak_idx, len(af_db)):
        if af_db[i] <= level_db:
            if i - 1 >= peak_idx:
                frac = (level_db - af_db[i - 1]) / (af_db[i] - af_db[i - 1]) if af_db[i] != af_db[i - 1] else 0
                right_theta = theta[i - 1] + frac * (theta[i] - theta[i - 1])
            else:
                right_theta = theta[i]
            break

    return abs(right_theta - left_theta)


def _find_null_beamwidth(
    af_db: list[float], theta: list[float], peak_idx: int
) -> float:
    """Find the first-null beamwidth (angle between first nulls on each side)."""
    # A null is a local minimum that is significantly below the peak
    null_threshold = -30.0  # consider anything below -30 dB a null

    # Search left
    left_null = theta[0]
    prev_val = af_db[peak_idx]
    for i in range(peak_idx - 1, -1, -1):
        if af_db[i] <= null_threshold or (af_db[i] > prev_val and prev_val < -10.0):
            # Found a null or passed through a minimum
            left_null = theta[i + 1] if af_db[i] > prev_val else theta[i]
            break
        prev_val = af_db[i]

    # Search right
    right_null = theta[-1]
    prev_val = af_db[peak_idx]
    for i in range(peak_idx + 1, len(af_db)):
        if af_db[i] <= null_threshold or (af_db[i] > prev_val and prev_val < -10.0):
            right_null = theta[i - 1] if af_db[i] > prev_val else theta[i]
            break
        prev_val = af_db[i]

    return abs(right_null - left_null)


def _find_peak_sidelobe(
    af_db: list[float], theta: list[float], peak_idx: int
) -> float:
    """Find the peak sidelobe level relative to the main beam.

    Searches outward from the main-beam peak for the first local minimum
    on each side (the first null), then finds the highest value beyond
    those nulls.
    """
    n = len(af_db)

    # Search left from peak for the first local minimum
    null_left = 0
    for i in range(peak_idx - 1, 0, -1):
        if af_db[i] <= af_db[i - 1]:
            # af_db started rising again — previous index was the minimum
            null_left = i
            break

    # Search right from peak for the first local minimum
    null_right = n - 1
    for i in range(peak_idx + 1, n - 1):
        if af_db[i] <= af_db[i + 1]:
            null_right = i
            break

    sidelobe_max = -300.0

    # Check left sidelobe region (everything to the left of the first null)
    for i in range(0, null_left + 1):
        if af_db[i] > sidelobe_max:
            sidelobe_max = af_db[i]

    # Check right sidelobe region (everything to the right of the first null)
    for i in range(null_right, n):
        if af_db[i] > sidelobe_max:
            sidelobe_max = af_db[i]

    return sidelobe_max


def _estimate_directivity(
    af_linear: list[float], theta_deg: list[float], step_deg: float
) -> float:
    """Estimate directivity from the AF pattern using numerical integration."""
    step_rad = math.radians(step_deg)
    peak_sq = max(v * v for v in af_linear)
    if peak_sq == 0:
        return 0.0

    # Integrate |AF|^2 * cos(theta) over theta from -90 to +90
    # (using cos(theta) as the element of solid angle in the visible region)
    integral = 0.0
    for i, val in enumerate(af_linear):
        theta_rad = math.radians(theta_deg[i])
        cos_theta = math.cos(theta_rad)
        if cos_theta > 0:
            integral += val * val * cos_theta * step_rad

    if integral <= 0:
        return 0.0

    directivity = 2.0 * peak_sq / integral
    return 10.0 * math.log10(directivity) if directivity > 0 else 0.0


# ---------------------------------------------------------------------------
# 5. Beam steering phase calculation
# ---------------------------------------------------------------------------


def _build_beam_steering(args: dict) -> str:
    num = int(args["num_elements"])
    spacing = float(args["spacing_mm"])
    freq = float(args["frequency_ghz"])
    scan_theta = float(args["scan_theta_deg"])
    scan_phi = float(args.get("scan_phi_deg", 0))

    if num < 2:
        raise ValueError("num_elements must be >= 2")
    validate_positive(spacing, "spacing_mm")
    validate_frequency(freq)

    lam = _wavelength_mm(freq)
    k = 2.0 * math.pi / lam  # wave number in 1/mm

    # Progressive phase: beta_n = k * d * n * sin(theta_scan)
    # Negative sign for steering toward scan_theta
    beta = -k * spacing * math.sin(math.radians(scan_theta))

    phase_weights: list[float] = []
    for n in range(num):
        phase = math.degrees(beta * n)
        # Normalise to [0, 360)
        phase = phase % 360.0
        phase_weights.append(round(phase, 2))

    # Generate VBA to set port phases
    script = VBAScript()
    script.add_comment(
        f"Beam steering: scan_theta={scan_theta} deg, scan_phi={scan_phi} deg"
    )
    script.add_comment(
        f"Progressive phase shift: {math.degrees(beta):.2f} deg/element"
    )

    for n in range(num):
        port_num = n + 1
        vba = VBABuilder("Port")
        vba.call("Reset")
        vba.set_number("PortNumber", port_num)
        vba.set_number("PhaseShift", phase_weights[n])
        vba.call("Modify")
        script.add_block(vba)

    return json.dumps({
        "phase_weights_deg": phase_weights,
        "progressive_phase_deg": round(math.degrees(beta), 2),
        "scan_theta_deg": scan_theta,
        "scan_phi_deg": scan_phi,
        "spacing_mm": spacing,
        "spacing_wavelengths": round(spacing / lam, 4),
        "frequency_ghz": freq,
        "wavelength_mm": round(lam, 3),
        "vba_script": script.build(),
        "notes": [
            f"Phase weights calculated for {num}-element array.",
            f"Progressive phase shift: {math.degrees(beta):.2f} deg per element.",
            f"Beam steered to theta={scan_theta} deg from broadside.",
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# 6. Amplitude taper design (pure Python)
# ---------------------------------------------------------------------------


def _build_taper_design(args: dict) -> str:
    num = int(args["num_elements"])
    taper = args["taper_type"].lower()
    sll_db = float(args.get("sidelobe_level_db", -25))

    if num < 2:
        raise ValueError("num_elements must be >= 2")
    valid_tapers = ("uniform", "cosine", "hamming", "hanning", "blackman", "taylor", "chebyshev")
    if taper not in valid_tapers:
        raise ValueError(f"taper_type must be one of {valid_tapers}")

    weights: list[float]
    expected_sll: float
    N = num

    if taper == "uniform":
        weights = [1.0] * N
        expected_sll = -13.26  # uniform linear array SLL

    elif taper == "cosine":
        weights = [
            math.cos(math.pi * (n - (N - 1) / 2.0) / N)
            for n in range(N)
        ]
        expected_sll = -23.0

    elif taper == "hamming":
        weights = [
            0.54 - 0.46 * math.cos(2.0 * math.pi * n / (N - 1))
            for n in range(N)
        ]
        expected_sll = -42.7

    elif taper == "hanning":
        weights = [
            0.5 * (1.0 - math.cos(2.0 * math.pi * n / (N - 1)))
            for n in range(N)
        ]
        expected_sll = -31.5

    elif taper == "blackman":
        weights = [
            0.42 - 0.5 * math.cos(2.0 * math.pi * n / (N - 1))
            + 0.08 * math.cos(4.0 * math.pi * n / (N - 1))
            for n in range(N)
        ]
        expected_sll = -58.1

    elif taper == "taylor":
        weights = _taylor_weights(N, sll_db)
        expected_sll = sll_db

    elif taper == "chebyshev":
        weights = _chebyshev_weights(N, sll_db)
        expected_sll = sll_db

    else:
        weights = [1.0] * N
        expected_sll = -13.26

    # Normalise to peak = 1.0
    peak = max(abs(w) for w in weights)
    if peak > 0:
        weights = [w / peak for w in weights]

    # Taper efficiency = (sum(w))^2 / (N * sum(w^2))
    sum_w = sum(weights)
    sum_w2 = sum(w * w for w in weights)
    taper_eff = (sum_w * sum_w) / (N * sum_w2) if sum_w2 > 0 else 1.0

    return json.dumps({
        "amplitude_weights": [round(w, 6) for w in weights],
        "expected_sll_db": round(expected_sll, 1),
        "taper_efficiency": round(taper_eff, 4),
        "taper_type": taper,
        "num_elements": N,
        "notes": [
            f"{taper.capitalize()} taper for {N} elements.",
            f"Expected peak sidelobe level: {expected_sll:.1f} dB.",
            f"Taper efficiency: {taper_eff:.4f} ({taper_eff * 100:.1f}%).",
        ],
    }, indent=2)


def _taylor_weights(n: int, sll_db: float) -> list[float]:
    """Compute Taylor window weights (one-parameter approximation).

    Uses the Taylor distribution with nbar chosen from the desired SLL.
    Reference: Taylor, IEEE AP-3, 1955.
    """
    # Convert SLL to linear ratio
    sll_linear = 10.0 ** (-abs(sll_db) / 20.0)
    # A parameter from Dolph-Chebyshev
    a = (1.0 / math.pi) * math.acosh(1.0 / sll_linear)
    # nbar: number of nearly-equal sidelobes
    nbar = max(2, int(2.0 * a * a + 0.5) + 1)
    nbar = min(nbar, n)

    # Sigma squared
    sigma2 = nbar * nbar / (a * a + (nbar - 0.5) * (nbar - 0.5))

    # Compute coefficients F_m
    weights = [0.0] * n
    for i in range(n):
        x = (i - (n - 1) / 2.0) / n
        w = 1.0
        for m in range(1, nbar):
            # Numerator product
            num = 1.0
            for p in range(1, nbar):
                num *= 1.0 - (m * m) / (sigma2 * (a * a + (p - 0.5) * (p - 0.5)))
            # Denominator product
            den = 1.0
            for p in range(1, nbar):
                if p != m:
                    den *= 1.0 - (m * m) / (p * p)
            coeff = num / den if den != 0 else 0.0
            w += 2.0 * coeff * math.cos(2.0 * math.pi * m * x)
        weights[i] = w

    return weights


def _chebyshev_weights(n: int, sll_db: float) -> list[float]:
    """Compute Dolph-Chebyshev array weights.

    Uses the direct computation via Chebyshev polynomials.
    """
    r = 10.0 ** (abs(sll_db) / 20.0)  # voltage ratio

    # x0 parameter
    x0 = math.cosh(math.acosh(r) / (n - 1))

    weights = [0.0] * n
    for i in range(n):
        xi = (i - (n - 1) / 2.0)
        w = 0.0
        for k in range(n):
            # Chebyshev polynomial evaluation
            arg = x0 * math.cos(math.pi * k / n)
            # T_{n-1}(arg) via recursive or direct formula
            tn = _chebyshev_poly(n - 1, arg)
            w += tn * math.cos(2.0 * math.pi * k * xi / n)
        weights[i] = abs(w) / n

    return weights


def _chebyshev_poly(order: int, x: float) -> float:
    """Evaluate Chebyshev polynomial T_n(x) of the first kind."""
    if order == 0:
        return 1.0
    if order == 1:
        return x
    t_prev2 = 1.0
    t_prev1 = x
    for _ in range(2, order + 1):
        t_curr = 2.0 * x * t_prev1 - t_prev2
        t_prev2 = t_prev1
        t_prev1 = t_curr
    return t_prev1


# ---------------------------------------------------------------------------
# 7. Grating lobe analysis (pure Python)
# ---------------------------------------------------------------------------


def _build_grating_lobe_analysis(args: dict) -> str:
    d_lam = float(args["spacing_wavelengths"])
    max_scan = float(args.get("max_scan_angle_deg", 60))

    validate_positive(d_lam, "spacing_wavelengths")
    validate_range(max_scan, 0, 90, "max_scan_angle_deg")

    # Grating lobe condition: d/lambda >= 1 / (1 + |sin(theta_max)|)
    sin_scan = abs(math.sin(math.radians(max_scan)))
    max_safe_spacing = 1.0 / (1.0 + sin_scan)

    has_grating_lobes = d_lam >= max_safe_spacing

    # Find grating lobe angles if they exist
    # Grating lobes appear at sin(theta_gl) = sin(theta_scan) + m*lambda/d
    # where m is a non-zero integer
    grating_angles: list[float] = []
    if has_grating_lobes:
        for m in [-3, -2, -1, 1, 2, 3]:
            for scan_sign in [1, -1]:
                sin_gl = scan_sign * math.sin(math.radians(max_scan)) + m / d_lam
                if -1.0 <= sin_gl <= 1.0:
                    angle = math.degrees(math.asin(sin_gl))
                    # Only include if in visible space and not the main beam
                    if abs(angle - scan_sign * max_scan) > 1.0:
                        angle_rounded = round(angle, 2)
                        if angle_rounded not in grating_angles:
                            grating_angles.append(angle_rounded)
        grating_angles.sort()

    return json.dumps({
        "has_grating_lobes": has_grating_lobes,
        "max_safe_spacing_wavelengths": round(max_safe_spacing, 4),
        "spacing_wavelengths": d_lam,
        "max_scan_angle_deg": max_scan,
        "grating_lobe_angles_deg": grating_angles,
        "notes": [
            f"Element spacing: {d_lam} wavelengths.",
            f"Maximum scan angle: {max_scan} degrees.",
            f"Safe spacing for no grating lobes: < {max_safe_spacing:.4f} wavelengths.",
            "Grating lobes present!" if has_grating_lobes else "No grating lobes in visible space.",
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# 8. Mutual coupling extraction setup
# ---------------------------------------------------------------------------


def _build_mutual_coupling(args: dict) -> str:
    num_ports = int(args["num_ports"])
    port_numbers = args.get("port_numbers", None)

    if num_ports < 2:
        raise ValueError("num_ports must be >= 2")

    if port_numbers is None:
        port_numbers = list(range(1, num_ports + 1))
    else:
        port_numbers = [int(p) for p in port_numbers]
        if len(port_numbers) != num_ports:
            raise ValueError(
                f"port_numbers length ({len(port_numbers)}) must match num_ports ({num_ports})"
            )

    script = VBAScript()
    script.add_comment(f"Mutual coupling extraction: {num_ports} ports")
    script.add_comment("Configure frequency-domain solver for S-parameter matrix")

    # Set up frequency-domain solver with all ports
    solver = VBABuilder("FDSolver")
    solver.call("Reset")
    solver.set("ResetSampleIntervals", "all")
    solver.set("StimulationMode", "All")
    solver.set("AutoNormImpedance", "True")
    solver.set_number("NormalizingImpedance", 50)
    solver.set("ModesOnly", "False")
    script.add_block(solver)

    # Enable S-parameter calculation for all port pairs
    for p in port_numbers:
        port_vba = VBABuilder("Port")
        port_vba.call("Reset")
        port_vba.set_number("PortNumber", p)
        port_vba.set_number("Impedance", 50)
        port_vba.set("Active", "True")
        port_vba.call("Modify")
        script.add_block(port_vba)

    # Build coupling matrix description
    coupling_pairs: list[str] = []
    for i in range(len(port_numbers)):
        for j in range(i, len(port_numbers)):
            p1 = port_numbers[i]
            p2 = port_numbers[j]
            if i == j:
                coupling_pairs.append(f"S({p1},{p2}) - reflection")
            else:
                coupling_pairs.append(f"S({p1},{p2}) - coupling")

    return json.dumps({
        "vba_script": script.build(),
        "num_ports": num_ports,
        "port_numbers": port_numbers,
        "coupling_matrix_entries": coupling_pairs,
        "total_s_parameters": len(coupling_pairs),
        "notes": [
            f"Configured {num_ports}-port S-parameter simulation.",
            "Run frequency-domain solver to extract the coupling matrix.",
            "S(i,j) with i!=j gives mutual coupling between ports i and j.",
            "All ports normalised to 50 ohms.",
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[[dict], str]] = {
    "cst_array_linear": _build_linear_array,
    "cst_array_planar": _build_planar_array,
    "cst_array_circular": _build_circular_array,
    "cst_array_compute_factor": _build_array_factor,
    "cst_array_beam_steering": _build_beam_steering,
    "cst_array_taper_design": _build_taper_design,
    "cst_array_grating_lobe_analysis": _build_grating_lobe_analysis,
    "cst_array_mutual_coupling": _build_mutual_coupling,
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle an array synthesis tool call."""
    handler_fn = _HANDLERS.get(name)
    if handler_fn is None:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Unknown array tool: {name}",
        }))]

    try:
        result_text = handler_fn(arguments)
        return [TextContent(type="text", text=result_text)]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": str(e),
        }))]


def register_array_tools(server: Server, client: CSTClient) -> None:
    """Register array synthesis tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
