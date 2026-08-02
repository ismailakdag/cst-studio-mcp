"""Parametric antenna design templates for CST Studio Suite.

Provides 13 MCP tools that generate complete antenna models from design
parameters.  Each tool calculates physical dimensions using standard RF
engineering formulas and emits production-quality VBA scripts that can be
pasted directly into CST Studio to create a simulatable model.
"""

from __future__ import annotations

import json
import math
from typing import Callable

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.vba_builder import VBABuilder, VBAScript
from cst_mcp.validators import validate_frequency, validate_positive

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

C0 = 299792458.0  # speed of light in m/s

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # 1 ── Rectangular microstrip patch antenna
    Tool(
        name="cst_antenna_patch",
        description=(
            "Create a rectangular microstrip patch antenna with calculated "
            "dimensions for a target frequency. Supports inset, microstrip, "
            "and probe feed types. Generates substrate, ground plane, patch, "
            "feed structure, waveguide port, boundaries, and field monitors."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "substrate_height_mm": {
                    "type": "number",
                    "description": "Substrate thickness in mm (default 1.6)",
                    "default": 1.6,
                },
                "epsilon_r": {
                    "type": "number",
                    "description": "Substrate relative permittivity (default 4.4 — FR-4)",
                    "default": 4.4,
                },
                "tan_d": {
                    "type": "number",
                    "description": "Substrate loss tangent (default 0.02)",
                    "default": 0.02,
                },
                "feed_type": {
                    "type": "string",
                    "enum": ["microstrip", "probe", "inset"],
                    "description": "Feed method (default inset)",
                    "default": "inset",
                },
                "ground_size_factor": {
                    "type": "number",
                    "description": "Ground plane size = factor * patch size (default 2.0)",
                    "default": 2.0,
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 2 ── Half-wave dipole
    Tool(
        name="cst_antenna_dipole",
        description=(
            "Create a half-wave dipole antenna at a target frequency. "
            "Generates two wire arms with a discrete port at the feed gap."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "wire_radius_mm": {
                    "type": "number",
                    "description": "Wire radius in mm (default 0.5)",
                    "default": 0.5,
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 3 ── Quarter-wave monopole
    Tool(
        name="cst_antenna_monopole",
        description=(
            "Create a quarter-wave monopole antenna over a ground plane. "
            "Generates a vertical wire element, ground plane, and feed port."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "wire_radius_mm": {
                    "type": "number",
                    "description": "Wire radius in mm (default 0.5)",
                    "default": 0.5,
                },
                "ground_radius_mm": {
                    "type": "number",
                    "description": "Ground plane radius in mm (auto-calculated if omitted)",
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 4 ── Pyramidal horn
    Tool(
        name="cst_antenna_horn",
        description=(
            "Create a pyramidal horn antenna for a target frequency and gain. "
            "Generates the waveguide section, flared horn, and waveguide port."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "gain_dbi": {
                    "type": "number",
                    "description": "Target gain in dBi (default 15)",
                    "default": 15,
                },
                "a": {
                    "type": "number",
                    "description": "Waveguide broad-wall dimension in mm (auto-calculated if omitted)",
                },
                "b": {
                    "type": "number",
                    "description": "Waveguide narrow-wall dimension in mm (auto-calculated if omitted)",
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 5 ── Yagi-Uda
    Tool(
        name="cst_antenna_yagi",
        description=(
            "Create a Yagi-Uda antenna with a reflector, driven element, and "
            "configurable number of directors. Generates wire elements and "
            "a discrete port feed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "num_directors": {
                    "type": "integer",
                    "description": "Number of director elements (default 3)",
                    "default": 3,
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 6 ── Axial-mode helix
    Tool(
        name="cst_antenna_helix",
        description=(
            "Create an axial-mode helical antenna for circular polarization. "
            "Generates helix coil, ground plane, and feed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "num_turns": {
                    "type": "integer",
                    "description": "Number of helix turns (default 10)",
                    "default": 10,
                },
                "ground_type": {
                    "type": "string",
                    "enum": ["circular", "square"],
                    "description": "Ground plane shape (default circular)",
                    "default": "circular",
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 7 ── Vivaldi / tapered slot
    Tool(
        name="cst_antenna_vivaldi",
        description=(
            "Create a Vivaldi (tapered slot) antenna on a dielectric substrate. "
            "Generates substrate, exponential taper metallisation, and feed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "substrate_height_mm": {
                    "type": "number",
                    "description": "Substrate thickness in mm (default 1.6)",
                    "default": 1.6,
                },
                "epsilon_r": {
                    "type": "number",
                    "description": "Substrate relative permittivity (default 2.2 — Rogers)",
                    "default": 2.2,
                },
                "taper_length_factor": {
                    "type": "number",
                    "description": "Taper length in wavelengths (default 3)",
                    "default": 3,
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 8 ── Slot antenna
    Tool(
        name="cst_antenna_slot",
        description=(
            "Create a slot antenna in a ground plane. Generates the ground "
            "plane with a resonant slot and microstrip feed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "slot_width_mm": {
                    "type": "number",
                    "description": "Slot width in mm (auto-calculated if omitted)",
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 9 ── Inverted-F antenna
    Tool(
        name="cst_antenna_ifa",
        description=(
            "Create an Inverted-F antenna (IFA) suitable for mobile devices. "
            "Generates ground plane, radiating arm, shorting pin, and feed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "ground_length_mm": {
                    "type": "number",
                    "description": "Ground plane length in mm (default 100)",
                    "default": 100,
                },
                "ground_width_mm": {
                    "type": "number",
                    "description": "Ground plane width in mm (default 40)",
                    "default": 40,
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 10 ── Planar inverted-F antenna
    Tool(
        name="cst_antenna_pifa",
        description=(
            "Create a Planar Inverted-F Antenna (PIFA) for compact wireless "
            "devices. Generates ground plane, top patch, shorting wall, and feed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "ground_length_mm": {
                    "type": "number",
                    "description": "Ground plane length in mm (default 100)",
                    "default": 100,
                },
                "ground_width_mm": {
                    "type": "number",
                    "description": "Ground plane width in mm (default 40)",
                    "default": 40,
                },
                "patch_width_mm": {
                    "type": "number",
                    "description": "Patch width in mm (auto-calculated if omitted)",
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 11 ── Archimedean spiral
    Tool(
        name="cst_antenna_spiral",
        description=(
            "Create a wideband Archimedean spiral antenna. Generates two "
            "spiral arms with a discrete port feed at the center."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "freq_low_ghz": {
                    "type": "number",
                    "description": "Low end of operating band in GHz",
                },
                "freq_high_ghz": {
                    "type": "number",
                    "description": "High end of operating band in GHz",
                },
                "num_turns": {
                    "type": "integer",
                    "description": "Number of spiral turns (default 5)",
                    "default": 5,
                },
            },
            "required": ["freq_low_ghz", "freq_high_ghz"],
        },
    ),

    # 12 ── Bowtie antenna
    Tool(
        name="cst_antenna_bowtie",
        description=(
            "Create a planar bowtie antenna. Generates two triangular arms "
            "with a discrete port at the feed gap."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency_ghz": {
                    "type": "number",
                    "description": "Design center frequency in GHz",
                },
                "flare_angle": {
                    "type": "number",
                    "description": "Flare half-angle of each arm in degrees (default 60)",
                    "default": 60,
                },
                "arm_length_mm": {
                    "type": "number",
                    "description": "Arm length in mm (auto-calculated from frequency if omitted)",
                },
            },
            "required": ["frequency_ghz"],
        },
    ),

    # 13 ── List templates
    Tool(
        name="cst_list_antenna_templates",
        description=(
            "List all available parametric antenna templates with descriptions "
            "and typical use cases. No arguments required."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]

_TOOL_NAMES = {t.name for t in TOOLS}

# ---------------------------------------------------------------------------
# VBA helper utilities
# ---------------------------------------------------------------------------


def _wavelength_mm(freq_ghz: float) -> float:
    """Free-space wavelength in mm."""
    return (C0 / (freq_ghz * 1e9)) * 1e3


def _build_units_block() -> str:
    """Standard CST units via SetUnit (CST 2024+ help). No .Apply / .Geometry."""
    return "\n".join(
        [
            "With Units",
            '  .SetUnit "Length", "mm"',
            '  .SetUnit "Frequency", "GHz"',
            '  .SetUnit "Time", "ns"',
            "End With",
        ]
    )


def _build_frequency_range(f_min: float, f_max: float) -> VBABuilder:
    """Set solver frequency range in GHz."""
    return (
        VBABuilder("Solver")
        .set_double("FrequencyRange", f_min, f_max)
    )


def _build_open_boundaries() -> str:
    """Open (add space) boundary conditions on all six faces."""
    lines = [
        "' --- Boundary conditions: open (add space) ---",
    ]
    for face in ("Xmin", "Xmax", "Ymin", "Ymax", "Zmin", "Zmax"):
        lines.append(f'Boundary.{face} "expanded open"')
    lines.append('Boundary.ApplyInAllDirections "False"')
    return "\n".join(lines)


def _build_field_monitor(freq_ghz: float, label: str = "farfield") -> VBABuilder:
    """Add a farfield monitor at design frequency (official: .Frequency).

    EnableNearfieldCalculation keeps nearfield data so FarfieldPlot.GetMax
    works after the hex mesh is discarded post-solve.
    """
    return (
        VBABuilder("Monitor")
        .call("Reset")
        .set("Name", f"{label} (f={freq_ghz})")
        .set("Domain", "Frequency")
        .set("FieldType", "Farfield")
        .set_number("Frequency", freq_ghz)
        .set("ExportFarfieldSource", "False")
        .set("EnableNearfieldCalculation", "True")
        .set("UseSubvolume", "False")
        .call("Create")
    )


def _build_efield_monitor(freq_ghz: float) -> VBABuilder:
    """Add an E-field volume monitor at design frequency."""
    return (
        VBABuilder("Monitor")
        .call("Reset")
        .set("Name", f"e-field (f={freq_ghz})")
        .set("Domain", "Frequency")
        .set("FieldType", "Efield")
        .set_number("Frequency", freq_ghz)
        .call("Create")
    )


def _build_substrate_material(name: str, eps_r: float, tan_d: float) -> VBABuilder:
    """Define a substrate material (TanD = numeric loss tangent)."""
    return (
        VBABuilder("Material")
        .call("Reset")
        .set("Name", name)
        .set("Type", "Normal")
        .set_number("Epsilon", eps_r)
        .set_number("Mu", 1)
        .set_number("TanD", tan_d)
        .set_number("TanDFreq", 0.0)
        .set("TanDGiven", "True" if tan_d > 0 else "False")
        .set("TanDModel", "ConstTanD")
        .set_triple("Colour", 0.94, 0.82, 0.64)
        .set_number("Transparency", 0.5)
        .call("Create")
    )


def _store_design_parameters(params: dict[str, float]) -> str:
    """Generate VBA StoreParameter calls for antenna design parameters.

    Stores the computed dimensions as CST project parameters, making them
    visible in CST's parameter list and available for parametric sweeps
    or optimization via StoreParameter + DeleteResults + Rebuild.
    """
    lines = ["' --- Design Parameters ---"]
    for name, value in params.items():
        # Format numbers without scientific notation for CST compatibility
        if isinstance(value, float):
            val_str = f"{value:.6g}"
        else:
            val_str = str(value)
        lines.append(f'StoreParameter "{name}", "{val_str}"')
    lines.append("")
    return "\n".join(lines)


def _build_substrate_material_block(name: str, eps_r: float, tan_d: float) -> str:
    """Build a complete material definition block for a dielectric substrate."""
    return _build_substrate_material(name, eps_r, tan_d).build()

def _build_brick(component: str, name: str, material: str,
                 x0: float, x1: float, y0: float, y1: float,
                 z0: float, z1: float) -> str:
    """Build a Brick VBA block."""
    return (
        VBABuilder("Brick")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set_double("Xrange", x0, x1)
        .set_double("Yrange", y0, y1)
        .set_double("Zrange", z0, z1)
        .call("Create")
    ).build()


def _build_cylinder(component: str, name: str, material: str,
                    axis: str, cx: float, cy: float, cz: float,
                    outer_r: float, inner_r: float,
                    range_min: float, range_max: float) -> str:
    """Build a Cylinder VBA block."""
    return (
        VBABuilder("Cylinder")
        .call("Reset")
        .set("Name", name)
        .set("Component", component)
        .set("Material", material)
        .set("Axis", axis)
        .set_number("Outerradius", outer_r)
        .set_number("Innerradius", inner_r)
        .set_number("Xcenter", cx)
        .set_number("Ycenter", cy)
        .set_number("Zcenter", cz)
        .set_double("Zrange", range_min, range_max)
        .call("Create")
    ).build()


def _result_json(calculated: dict, vba_script: str, notes: list[str]) -> str:
    """Format the standard return payload."""
    return json.dumps({
        "calculated_parameters": calculated,
        "vba_script": vba_script,
        "notes": notes,
    }, indent=2)


# ---------------------------------------------------------------------------
# 1. Rectangular microstrip patch antenna
# ---------------------------------------------------------------------------

def _build_patch_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    h = validate_positive(args.get("substrate_height_mm", 1.6), "substrate_height_mm")
    eps_r = validate_positive(args.get("epsilon_r", 4.4), "epsilon_r")
    tan_d = args.get("tan_d", 0.02)
    feed_type = args.get("feed_type", "inset")
    gsf = validate_positive(args.get("ground_size_factor", 2.0), "ground_size_factor")

    lam0 = _wavelength_mm(freq)  # free-space wavelength in mm

    # --- Patch width ---
    W = (C0 / (2 * freq * 1e9)) * math.sqrt(2 / (eps_r + 1)) * 1e3  # mm

    # --- Effective permittivity ---
    ratio = h / W
    eps_eff = ((eps_r + 1) / 2) + ((eps_r - 1) / 2) * (1 / math.sqrt(1 + 12 * ratio))

    # --- Fringing extension ---
    delta_L = 0.412 * h * (
        (eps_eff + 0.3) * (W / h + 0.264)
    ) / (
        (eps_eff - 0.258) * (W / h + 0.8)
    )

    # --- Patch length ---
    L = (C0 / (2 * freq * 1e9 * math.sqrt(eps_eff))) * 1e3 - 2 * delta_L

    # --- Ground plane ---
    gnd_x = gsf * W
    gnd_y = gsf * L

    # --- Inset depth (for 50 ohm match) ---
    # R_in(y0) = R_edge * cos^2(pi*y0/L)
    # For 50 ohm: y0 = (L/pi) * arccos(sqrt(50/R_edge))
    # R_edge ~ 90 * eps_r^2 / (eps_r - 1) * (L/W)^2  (approximate)
    R_edge = 90 * (eps_r ** 2) / (eps_r - 1) * (L / W) ** 2
    if R_edge > 50:
        inset_depth = (L / math.pi) * math.acos(math.sqrt(50 / R_edge))
    else:
        inset_depth = 0

    # Feed line width (approximate 50-ohm microstrip)
    # Use Wheeler's approximation
    A_w = (50 / 60) * math.sqrt((eps_r + 1) / 2) + (eps_r - 1) / (eps_r + 1) * (0.23 + 0.11 / eps_r)
    feed_w = h * max(
        8 * math.exp(A_w) / (math.exp(2 * A_w) - 2),
        (2 / math.pi) * (
            (eps_r - 1) / (2 * eps_r) * (math.log(2 * A_w - 1) + 0.39 - 0.61 / eps_r)
        ) if A_w > 1.52 else 1.0,
    )
    feed_w = max(feed_w, 0.5)  # minimum practical width

    # Inset gap width
    inset_gap = feed_w * 0.5

    # Frequency range margins
    f_min = freq * 0.8
    f_max = freq * 1.2

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "patch_width_mm": round(W, 3),
        "patch_length_mm": round(L, 3),
        "epsilon_eff": round(eps_eff, 4),
        "delta_L_mm": round(delta_L, 4),
        "R_edge_ohm": round(R_edge, 1),
        "inset_depth_mm": round(inset_depth, 3),
        "feed_line_width_mm": round(feed_w, 3),
        "ground_x_mm": round(gnd_x, 3),
        "ground_y_mm": round(gnd_y, 3),
        "substrate_height_mm": h,
        "epsilon_r": eps_r,
    }

    # --- Build VBA script ---
    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Rectangular Microstrip Patch Antenna at {freq} GHz")
    script.add_comment(f"Substrate: h={h} mm, eps_r={eps_r}, tan_d={tan_d}")
    script.add_comment(f"Feed type: {feed_type}")
    script.add_comment("=" * 60)

    # Units
    script.add_raw(_build_units_block())

    # Frequency range
    script.add_block(_build_frequency_range(f_min, f_max))

    # Store design parameters in CST for parametric sweeps/optimization
    script.add_raw(_store_design_parameters({
        "patch_W": round(W, 4),
        "patch_L": round(L, 4),
        "sub_h": round(h, 4),
        "eps_r": eps_r,
        "feed_w": round(feed_w, 4),
        "inset_depth": round(inset_depth, 4),
        "inset_gap": round(inset_gap, 4),
        "gnd_x": round(gnd_x, 4),
        "gnd_y": round(gnd_y, 4),
    }))

    # Substrate material
    script.add_raw(_build_substrate_material_block("Substrate_FR4", eps_r, tan_d))

    # Substrate brick
    script.add_raw(_build_brick(
        "Antenna", "Substrate", "Substrate_FR4",
        -gnd_x / 2, gnd_x / 2,
        -gnd_y / 2, gnd_y / 2,
        0, h,
    ))

    # Ground plane (bottom of substrate)
    script.add_raw(_build_brick(
        "Antenna", "Ground", "PEC",
        -gnd_x / 2, gnd_x / 2,
        -gnd_y / 2, gnd_y / 2,
        -0.035, 0,
    ))

    # Patch (top of substrate)
    script.add_raw(_build_brick(
        "Antenna", "Patch", "PEC",
        -W / 2, W / 2,
        -L / 2, L / 2,
        h, h + 0.035,
    ))

    # Feed
    if feed_type == "inset":
        # Inset notch — left slot
        script.add_raw(_build_brick(
            "Antenna", "InsetSlotL", "Vacuum",
            -feed_w / 2 - inset_gap, -feed_w / 2,
            -L / 2 - 0.1, -L / 2 + inset_depth,
            h, h + 0.035,
        ))
        # Inset notch — right slot
        script.add_raw(_build_brick(
            "Antenna", "InsetSlotR", "Vacuum",
            feed_w / 2, feed_w / 2 + inset_gap,
            -L / 2 - 0.1, -L / 2 + inset_depth,
            h, h + 0.035,
        ))
        # Feed line on top of substrate from edge to patch
        gnd_y / 2 - L / 2
        script.add_raw(_build_brick(
            "Antenna", "FeedLine", "PEC",
            -feed_w / 2, feed_w / 2,
            -gnd_y / 2, -L / 2,
            h, h + 0.035,
        ))
        # Waveguide port flush with feed outer face (PortOnBound=False)
        from cst_mcp.execution.port_helpers import microstrip_waveguide_port_vba

        script.add_raw(
            microstrip_waveguide_port_vba(
                port_number=1,
                y_edge=-gnd_y / 2,
                feed_width=feed_w,
                substrate_height=h,
                ground_bottom=-0.035,
                metal_thickness=0.035,
                x_center=0.0,
            )
        )

    elif feed_type == "microstrip":
        gnd_y / 2 - L / 2
        script.add_raw(_build_brick(
            "Antenna", "FeedLine", "PEC",
            -feed_w / 2, feed_w / 2,
            -gnd_y / 2, -L / 2,
            h, h + 0.035,
        ))
        from cst_mcp.execution.port_helpers import microstrip_waveguide_port_vba

        script.add_raw(
            microstrip_waveguide_port_vba(
                port_number=1,
                y_edge=-gnd_y / 2,
                feed_width=feed_w,
                substrate_height=h,
                ground_bottom=-0.035,
                metal_thickness=0.035,
                x_center=0.0,
            )
        )

    elif feed_type == "probe":
        # Coaxial probe — cylinder from ground to patch
        probe_x = 0.0
        probe_y = -L / 2 + inset_depth  # same position as inset would be
        script.add_raw(_build_cylinder(
            "Antenna", "Probe", "PEC",
            "z", probe_x, probe_y, 0,
            0.65, 0,  # outer 0.65 mm radius (SMA inner)
            0, h,
        ))
        # Discrete port
        port_vba = (
            VBABuilder("DiscretePort")
            .call("Reset")
            .set_number("PortNumber", 1)
            .set("Type", "SParameter")
            .set_number("Impedance", 50)
            .set_triple("Point1", probe_x, probe_y, 0)
            .set_triple("Point2", probe_x, probe_y, h)
            .set_number("Radius", 0.5)
            .set_bool("Monitor", True)
            .call("Create")
        )
        script.add_block(port_vba)

    # Boundaries
    script.add_raw(_build_open_boundaries())

    # Field monitors
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"Patch dimensions: {W:.2f} x {L:.2f} mm on {h} mm {eps_r}-permittivity substrate.",
        f"Edge impedance ~{R_edge:.0f} ohm; inset depth {inset_depth:.2f} mm for 50-ohm match.",
        "Run the Time Domain solver for S-parameter and radiation pattern results.",
        "Adjust inset depth or probe position to fine-tune input impedance.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 2. Half-wave dipole antenna
# ---------------------------------------------------------------------------

def _build_dipole_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    wire_r = validate_positive(args.get("wire_radius_mm", 0.5), "wire_radius_mm")

    lam0 = _wavelength_mm(freq)
    arm_length = 0.48 * lam0 / 2  # each arm; total = 0.48 * lambda
    gap = max(wire_r * 4, lam0 * 0.005)  # feed gap

    f_min = freq * 0.7
    f_max = freq * 1.3

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "total_length_mm": round(2 * arm_length, 3),
        "arm_length_mm": round(arm_length, 3),
        "wire_radius_mm": wire_r,
        "gap_mm": round(gap, 3),
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Half-Wave Dipole Antenna at {freq} GHz")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Upper arm (+z direction)
    upper_vba = (
        VBABuilder("Cylinder")
        .call("Reset")
        .set("Name", "UpperArm")
        .set("Component", "Dipole")
        .set("Material", "PEC")
        .set("Axis", "z")
        .set_number("Outerradius", wire_r)
        .set_number("Innerradius", 0)
        .set_number("Xcenter", 0)
        .set_number("Ycenter", 0)
        .set_number("Zcenter", 0)
        .set_double("Zrange", gap / 2, gap / 2 + arm_length)
        .call("Create")
    )
    script.add_block(upper_vba)

    # Lower arm (-z direction)
    lower_vba = (
        VBABuilder("Cylinder")
        .call("Reset")
        .set("Name", "LowerArm")
        .set("Component", "Dipole")
        .set("Material", "PEC")
        .set("Axis", "z")
        .set_number("Outerradius", wire_r)
        .set_number("Innerradius", 0)
        .set_number("Xcenter", 0)
        .set_number("Ycenter", 0)
        .set_number("Zcenter", 0)
        .set_double("Zrange", -gap / 2 - arm_length, -gap / 2)
        .call("Create")
    )
    script.add_block(lower_vba)

    # Discrete port at feed gap
    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", 0, 0, -gap / 2)
        .set_triple("Point2", 0, 0, gap / 2)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"Total dipole length {2 * arm_length:.2f} mm (0.48 * lambda for finite-diameter wire).",
        "Input impedance ~73 ohm at resonance.",
        "Use open boundaries on all sides.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 3. Quarter-wave monopole
# ---------------------------------------------------------------------------

def _build_monopole_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    wire_r = validate_positive(args.get("wire_radius_mm", 0.5), "wire_radius_mm")

    lam0 = _wavelength_mm(freq)
    arm_length = 0.24 * lam0  # quarter-wave, slightly shortened
    gnd_r = args.get("ground_radius_mm")
    if gnd_r is None:
        gnd_r = lam0 * 0.5  # half-wavelength radius
    else:
        gnd_r = validate_positive(gnd_r, "ground_radius_mm")

    f_min = freq * 0.7
    f_max = freq * 1.3

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "monopole_height_mm": round(arm_length, 3),
        "wire_radius_mm": wire_r,
        "ground_radius_mm": round(gnd_r, 3),
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Quarter-Wave Monopole Antenna at {freq} GHz")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Ground plane (circular disc at z=0)
    gnd_vba = (
        VBABuilder("Cylinder")
        .call("Reset")
        .set("Name", "GroundPlane")
        .set("Component", "Monopole")
        .set("Material", "PEC")
        .set("Axis", "z")
        .set_number("Outerradius", gnd_r)
        .set_number("Innerradius", 0)
        .set_number("Xcenter", 0)
        .set_number("Ycenter", 0)
        .set_number("Zcenter", 0)
        .set_double("Zrange", -0.5, 0)
        .call("Create")
    )
    script.add_block(gnd_vba)

    # Vertical wire
    wire_vba = (
        VBABuilder("Cylinder")
        .call("Reset")
        .set("Name", "Element")
        .set("Component", "Monopole")
        .set("Material", "PEC")
        .set("Axis", "z")
        .set_number("Outerradius", wire_r)
        .set_number("Innerradius", 0)
        .set_number("Xcenter", 0)
        .set_number("Ycenter", 0)
        .set_number("Zcenter", 0)
        .set_double("Zrange", 0, arm_length)
        .call("Create")
    )
    script.add_block(wire_vba)

    # Discrete port between ground and monopole base
    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", 0, 0, -0.5)
        .set_triple("Point2", 0, 0, 0)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"Monopole height {arm_length:.2f} mm (~quarter-wave at {freq} GHz).",
        f"Ground plane radius {gnd_r:.2f} mm.",
        "Input impedance ~36 ohm at resonance (half of dipole).",
        "Use open boundaries; ground plane acts as image plane.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 4. Pyramidal horn antenna
# ---------------------------------------------------------------------------

def _build_horn_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    gain_dbi = args.get("gain_dbi", 15)

    lam0 = _wavelength_mm(freq)

    # Waveguide dimensions (standard rectangular waveguide for frequency)
    # a > lambda/2, b ~ a/2 for dominant TE10 mode
    a_wg = args.get("a")
    b_wg = args.get("b")
    if a_wg is None:
        # Choose waveguide so that 0.6*lambda < a < 0.95*lambda (typical)
        a_wg = lam0 * 0.72
    else:
        a_wg = validate_positive(a_wg, "a")
    if b_wg is None:
        b_wg = a_wg / 2
    else:
        b_wg = validate_positive(b_wg, "b")

    # Gain in linear
    G = 10 ** (gain_dbi / 10)

    # Aperture efficiency ~ 0.51 for pyramidal horn
    eta_ap = 0.51

    # Required aperture area: G = 4*pi*A_eff / lambda^2
    # A_eff = eta_ap * A_phys
    A_phys = G * lam0 ** 2 / (4 * math.pi * eta_ap)

    # For pyramidal horn, A1 * B1 = A_phys
    # Typical aspect ratio A1/B1 ~ a/b
    aspect = a_wg / b_wg
    B1 = math.sqrt(A_phys / aspect)
    A1 = A_phys / B1

    # Horn length from Balanis — optimum horn
    # R_H (E-plane slant) = B1^2 / (2*lambda), R_E similar
    # Axial length L ~ R_H for moderate gain
    R_H = B1 ** 2 / (2 * lam0)
    R_E = A1 ** 2 / (3 * lam0)
    horn_length = max(R_H, R_E)
    horn_length = max(horn_length, 2 * lam0)  # minimum practical length

    # Waveguide section length
    wg_length = lam0 * 1.5

    f_min = freq * 0.8
    f_max = freq * 1.2

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "gain_dbi": gain_dbi,
        "waveguide_a_mm": round(a_wg, 3),
        "waveguide_b_mm": round(b_wg, 3),
        "aperture_A1_mm": round(A1, 3),
        "aperture_B1_mm": round(B1, 3),
        "horn_length_mm": round(horn_length, 3),
        "wg_section_length_mm": round(wg_length, 3),
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Pyramidal Horn Antenna at {freq} GHz, {gain_dbi} dBi")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Wall thickness
    t = max(lam0 * 0.02, 0.5)

    # Waveguide section: hollow brick from z = -wg_length to z = 0
    # Outer shell
    script.add_raw(_build_brick(
        "Horn", "WG_Outer", "PEC",
        -a_wg / 2 - t, a_wg / 2 + t,
        -b_wg / 2 - t, b_wg / 2 + t,
        -wg_length, 0,
    ))
    # Inner cavity (vacuum)
    script.add_raw(_build_brick(
        "Horn", "WG_Inner", "Vacuum",
        -a_wg / 2, a_wg / 2,
        -b_wg / 2, b_wg / 2,
        -wg_length, 0,
    ))

    # Horn flare: build as four trapezoidal walls using extrude
    # Top wall (y = +b side, tapers from b_wg/2 to B1/2)
    # Bottom wall, Left wall, Right wall
    # Simplification: build as outer and inner cones via bricks
    # Use two bricks: outer horn shell and inner vacuum cutout

    # Outer horn shell (tapered box approximation using a brick
    # at mid-cross-section — CST actually needs loft; use brick endpoints)
    # For VBA simplicity, create outer shell as a large brick
    # then subtract inner taper.  This is simplified geometry.
    script.add_raw(_build_brick(
        "Horn", "Horn_Outer", "PEC",
        -A1 / 2 - t, A1 / 2 + t,
        -B1 / 2 - t, B1 / 2 + t,
        0, horn_length,
    ))

    # Inner vacuum for horn (tapered cavity approximated via loft)
    # Use analytical VBA for loft between waveguide aperture and horn aperture

    # Rear profile curve
    rear_curve = (
        VBABuilder("Polygon")
        .call("Reset")
        .set("Name", "rear_profile")
        .set("Curve", "horn_curves")
        .set_double("Point", -a_wg / 2, -b_wg / 2)
        .set_double("LineTo", a_wg / 2, -b_wg / 2)
        .set_double("LineTo", a_wg / 2, b_wg / 2)
        .set_double("LineTo", -a_wg / 2, b_wg / 2)
        .set_double("LineTo", -a_wg / 2, -b_wg / 2)
        .call("Create")
    )
    script.add_block(rear_curve)

    # Front profile curve
    front_curve = (
        VBABuilder("Polygon")
        .call("Reset")
        .set("Name", "front_profile")
        .set("Curve", "horn_curves")
        .set_double("Point", -A1 / 2, -B1 / 2)
        .set_double("LineTo", A1 / 2, -B1 / 2)
        .set_double("LineTo", A1 / 2, B1 / 2)
        .set_double("LineTo", -A1 / 2, B1 / 2)
        .set_double("LineTo", -A1 / 2, -B1 / 2)
        .call("Create")
    )
    script.add_block(front_curve)

    # Loft between profiles
    loft = (
        VBABuilder("Loft")
        .call("Reset")
        .set("Name", "Horn_Inner")
        .set("Component", "Horn")
        .set("Material", "Vacuum")
        .set("AddCurve", "horn_curves:rear_profile")
        .set("AddCurve", "horn_curves:front_profile")
        .call("Create")
    )
    script.add_block(loft)

    # Waveguide port at rear of waveguide
    port_vba = (
        VBABuilder("Port")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Label", "")
        .set("Coordinates", "Free")
        .set("Orientation", "zmin")
        .set_double("Xrange", -a_wg / 2, a_wg / 2)
        .set_double("Yrange", -b_wg / 2, b_wg / 2)
        .set_double("Zrange", -wg_length, -wg_length)
        .set_number("NumberOfModes", 1)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"Pyramidal horn: waveguide {a_wg:.1f} x {b_wg:.1f} mm, aperture {A1:.1f} x {B1:.1f} mm.",
        f"Horn length {horn_length:.1f} mm for ~{gain_dbi} dBi gain.",
        "The horn interior uses a lofted vacuum cutout for the taper.",
        "Verify waveguide dimensions are above cutoff for TE10 mode.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 5. Yagi-Uda antenna
# ---------------------------------------------------------------------------

def _build_yagi_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    n_dir = max(int(args.get("num_directors", 3)), 0)

    lam0 = _wavelength_mm(freq)
    wire_r = lam0 * 0.003  # typical wire radius

    # Element lengths (NBS-optimised Yagi design rules)
    reflector_len = 0.495 * lam0
    driven_len = 0.473 * lam0
    director_base_len = 0.440 * lam0  # first director

    # Spacings
    refl_spacing = 0.25 * lam0  # reflector behind driven
    dir_spacing_base = 0.34 * lam0
    dir_spacing_inc = 0.0  # uniform spacing for simplicity

    # Director progressive shortening
    dir_shortening = 0.005 * lam0  # per element

    f_min = freq * 0.8
    f_max = freq * 1.2

    elements = []
    # Reflector at z = -refl_spacing
    elements.append(("Reflector", -refl_spacing, reflector_len))
    # Driven at z = 0
    elements.append(("Driven", 0, driven_len))
    # Directors
    for i in range(n_dir):
        z_pos = dir_spacing_base + i * (dir_spacing_base + dir_spacing_inc)
        d_len = director_base_len - i * dir_shortening
        elements.append((f"Director{i + 1}", z_pos, d_len))

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "wire_radius_mm": round(wire_r, 3),
        "num_elements": len(elements),
        "reflector_length_mm": round(reflector_len, 3),
        "driven_length_mm": round(driven_len, 3),
        "elements": [
            {"name": e[0], "z_position_mm": round(e[1], 3), "length_mm": round(e[2], 3)}
            for e in elements
        ],
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Yagi-Uda Antenna at {freq} GHz ({len(elements)} elements)")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Create each element as a cylinder along x-axis at position z
    for name, z_pos, length in elements:
        (
            VBABuilder("Cylinder")
            .call("Reset")
            .set("Name", name)
            .set("Component", "Yagi")
            .set("Material", "PEC")
            .set("Axis", "x")
            .set_number("Outerradius", wire_r)
            .set_number("Innerradius", 0)
            .set_number("Xcenter", 0)
            .set_number("Ycenter", 0)
            .set_number("Zcenter", z_pos)
            .set_double("Zrange", z_pos - wire_r, z_pos + wire_r)
        )
        # Cylinder axis is x, so use Xrange for the element length
        # Reset — CST Cylinder Zrange is always the axis range,
        # but we set Axis=x, so we use the range on x
        elem_vba2 = (
            VBABuilder("Cylinder")
            .call("Reset")
            .set("Name", name)
            .set("Component", "Yagi")
            .set("Material", "PEC")
            .set("Axis", "x")
            .set_number("Outerradius", wire_r)
            .set_number("Innerradius", 0)
            .set_number("Xcenter", 0)
            .set_number("Ycenter", 0)
            .set_number("Zcenter", z_pos)
            .set_double("Zrange", -length / 2, length / 2)
            .call("Create")
        )
        script.add_block(elem_vba2)

    # Discrete port at driven element center (small gap)
    gap = wire_r * 4
    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", 0, -gap / 2, 0)
        .set_triple("Point2", 0, gap / 2, 0)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"{len(elements)}-element Yagi: 1 reflector, 1 driven, {n_dir} directors.",
        f"Estimated gain ~{7.5 + 2.5 * math.log10(max(n_dir, 1)):.1f} dBi.",
        "Elements oriented along x-axis, boom along z-axis.",
        "Driven element has a discrete port feed at center.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 6. Axial-mode helical antenna
# ---------------------------------------------------------------------------

def _build_helix_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    n_turns = max(int(args.get("num_turns", 10)), 1)
    ground_type = args.get("ground_type", "circular")

    lam0 = _wavelength_mm(freq)

    # Axial-mode helix: circumference ~ lambda
    C_helix = lam0  # circumference
    radius = C_helix / (2 * math.pi)
    pitch = lam0 / 4  # spacing between turns
    total_height = n_turns * pitch
    pitch_angle = math.degrees(math.atan(pitch / C_helix))
    wire_r = lam0 * 0.005  # wire radius

    # Ground plane
    gnd_size = 0.75 * lam0  # diameter for circular, side for square

    f_min = freq * 0.7
    f_max = freq * 1.3

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "num_turns": n_turns,
        "circumference_mm": round(C_helix, 3),
        "helix_radius_mm": round(radius, 3),
        "pitch_mm": round(pitch, 3),
        "pitch_angle_deg": round(pitch_angle, 2),
        "total_height_mm": round(total_height, 3),
        "wire_radius_mm": round(wire_r, 3),
        "ground_size_mm": round(gnd_size, 3),
        "ground_type": ground_type,
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Axial-Mode Helical Antenna at {freq} GHz, {n_turns} turns")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Ground plane at z=0
    if ground_type == "circular":
        gnd_vba = (
            VBABuilder("Cylinder")
            .call("Reset")
            .set("Name", "GroundPlane")
            .set("Component", "Helix")
            .set("Material", "PEC")
            .set("Axis", "z")
            .set_number("Outerradius", gnd_size / 2)
            .set_number("Innerradius", 0)
            .set_number("Xcenter", 0)
            .set_number("Ycenter", 0)
            .set_number("Zcenter", 0)
            .set_double("Zrange", -0.5, 0)
            .call("Create")
        )
        script.add_block(gnd_vba)
    else:
        script.add_raw(_build_brick(
            "Helix", "GroundPlane", "PEC",
            -gnd_size / 2, gnd_size / 2,
            -gnd_size / 2, gnd_size / 2,
            -0.5, 0,
        ))

    # Helix coil — analytical curve
    # Parametric: x = R*cos(t), y = R*sin(t), z = pitch/(2*pi) * t
    # t from 0 to 2*pi*n_turns
    t_max_val = 2 * math.pi * n_turns
    pitch_per_rad = pitch / (2 * math.pi)

    helix_curve = (
        VBABuilder("AnalyticalCurve")
        .call("Reset")
        .set("Name", "helix_coil")
        .set("Curve", "helix_curves")
        .set("LawX", f"{radius:.6f}*cos(t)")
        .set("LawY", f"{radius:.6f}*sin(t)")
        .set("LawZ", f"{pitch_per_rad:.6f}*t")
        .set_double("ParameterRange", 0, t_max_val)
        .call("Create")
    )
    script.add_block(helix_curve)

    # Sweep a circular cross-section along the helix curve
    # Create cross-section circle
    circle_vba = (
        VBABuilder("Circle")
        .call("Reset")
        .set("Name", "wire_xsec")
        .set("Curve", "helix_curves")
        .set_number("Radius", wire_r)
        .set_number("Xcenter", radius)
        .set_number("Ycenter", 0)
        .set_number("Zcenter", 0)
        .call("Create")
    )
    script.add_block(circle_vba)

    # Sweep
    sweep_vba = (
        VBABuilder("SweepCurve")
        .call("Reset")
        .set("Name", "HelixWire")
        .set("Component", "Helix")
        .set("Material", "PEC")
        .set("Twistangle", "0.0")
        .set("Path", "helix_curves:helix_coil")
        .set("CrossSection", "helix_curves:wire_xsec")
        .call("Create")
    )
    script.add_block(sweep_vba)

    # Discrete port from ground to helix start
    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", radius, 0, 0)
        .set_triple("Point2", radius, 0, -0.5)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    # Approximate gain: G ~ 15 * C^2 * n * S / lambda^3 (Kraus formula simplified)
    approx_gain = 10 * math.log10(15 * n_turns * pitch / lam0 * (C_helix / lam0) ** 2)

    notes = [
        f"Helical antenna: {n_turns} turns, radius {radius:.2f} mm, pitch {pitch:.2f} mm.",
        f"Circumference/lambda = {C_helix / lam0:.3f} (should be ~1 for axial mode).",
        f"Approximate gain ~{approx_gain:.1f} dBi (Kraus formula).",
        "Produces circular polarization (RHCP with right-hand winding).",
        "Input impedance ~140 ohm; may need a matching section.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 7. Vivaldi / tapered slot antenna
# ---------------------------------------------------------------------------

def _build_vivaldi_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    h = validate_positive(args.get("substrate_height_mm", 1.6), "substrate_height_mm")
    eps_r = validate_positive(args.get("epsilon_r", 2.2), "epsilon_r")
    taper_factor = validate_positive(args.get("taper_length_factor", 3), "taper_length_factor")

    lam0 = _wavelength_mm(freq)
    lam_eff = lam0 / math.sqrt(eps_r)

    # Antenna dimensions
    taper_length = taper_factor * lam0
    substrate_width = lam0 * 1.5
    substrate_length = taper_length + lam0 * 0.5  # extra for feed region

    # Slot opening
    slot_opening = lam0 * 0.5
    slot_min = lam0 * 0.02  # narrow end of slot

    # Exponential taper rate
    # y(x) = c1 * exp(R*x) + c2
    # At x=0: y = slot_min/2; at x=taper_length: y = slot_opening/2
    if taper_length > 0:
        R_taper = (1.0 / taper_length) * math.log(slot_opening / max(slot_min, 0.01))
    else:
        R_taper = 0

    # Feed line (microstrip on opposite side, quarter-wave stub)

    f_min = freq * 0.5  # Vivaldi is wideband
    f_max = freq * 1.5

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "lambda_eff_mm": round(lam_eff, 3),
        "taper_length_mm": round(taper_length, 3),
        "substrate_width_mm": round(substrate_width, 3),
        "substrate_length_mm": round(substrate_length, 3),
        "slot_opening_mm": round(slot_opening, 3),
        "slot_min_mm": round(slot_min, 3),
        "taper_rate": round(R_taper, 6),
        "epsilon_r": eps_r,
        "substrate_height_mm": h,
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Vivaldi (Tapered Slot) Antenna at {freq} GHz")
    script.add_comment(f"Substrate: eps_r={eps_r}, h={h} mm")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Substrate material
    script.add_raw(_build_substrate_material_block("Vivaldi_Sub", eps_r, 0.001))

    # Substrate
    script.add_raw(_build_brick(
        "Vivaldi", "Substrate", "Vivaldi_Sub",
        0, substrate_length,
        -substrate_width / 2, substrate_width / 2,
        0, h,
    ))

    # Top metallisation (upper half above slot)
    # Build as a polygon extrusion representing the tapered edge
    # Discretise the exponential taper into segments
    n_seg = 40
    upper_points = []
    lower_points = []
    for i in range(n_seg + 1):
        x = (taper_length / n_seg) * i
        # Exponential taper
        y_half = (slot_min / 2) * math.exp(R_taper * x)
        upper_points.append((x, y_half))
        lower_points.append((x, -y_half))

    # Upper metallisation: from taper edge to substrate_width/2
    upper_poly = VBABuilder("Extrude")
    upper_poly.call("Reset")
    upper_poly.set("Name", "MetalUpper")
    upper_poly.set("Component", "Vivaldi")
    upper_poly.set("Material", "PEC")
    upper_poly.set_number("Mode", 0)
    upper_poly.set_number("Height", 0.035)
    upper_poly.set("Origin", f"0.0, 0.0, {h}")
    upper_poly.set("Uvector", "1.0, 0.0, 0.0")
    upper_poly.set("Vvector", "0.0, 1.0, 0.0")

    # Start at feed end, top of substrate, taper edge
    first_pt = upper_points[0]
    upper_poly.set_double("Point", first_pt[0], first_pt[1])
    for pt in upper_points[1:]:
        upper_poly.set_double("LineTo", pt[0], pt[1])
    # Close along top edge
    upper_poly.set_double("LineTo", substrate_length, substrate_width / 2)
    upper_poly.set_double("LineTo", 0, substrate_width / 2)
    upper_poly.set_double("LineTo", first_pt[0], first_pt[1])
    upper_poly.call("Create")
    script.add_block(upper_poly)

    # Lower metallisation
    lower_poly = VBABuilder("Extrude")
    lower_poly.call("Reset")
    lower_poly.set("Name", "MetalLower")
    lower_poly.set("Component", "Vivaldi")
    lower_poly.set("Material", "PEC")
    lower_poly.set_number("Mode", 0)
    lower_poly.set_number("Height", 0.035)
    lower_poly.set("Origin", f"0.0, 0.0, {h}")
    lower_poly.set("Uvector", "1.0, 0.0, 0.0")
    lower_poly.set("Vvector", "0.0, 1.0, 0.0")

    first_pt_l = lower_points[0]
    lower_poly.set_double("Point", first_pt_l[0], first_pt_l[1])
    for pt in lower_points[1:]:
        lower_poly.set_double("LineTo", pt[0], pt[1])
    # Close along bottom edge
    lower_poly.set_double("LineTo", substrate_length, -substrate_width / 2)
    lower_poly.set_double("LineTo", 0, -substrate_width / 2)
    lower_poly.set_double("LineTo", first_pt_l[0], first_pt_l[1])
    lower_poly.call("Create")
    script.add_block(lower_poly)

    # Discrete port at the narrow slot end
    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", 0, -slot_min / 2, h)
        .set_triple("Point2", 0, slot_min / 2, h)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"Vivaldi antenna: {taper_length:.1f} mm taper ({taper_factor} wavelengths).",
        "Wideband endfire radiation pattern.",
        "Exponential taper provides smooth impedance transition.",
        "Adjust taper_length_factor for wider bandwidth vs. higher gain.",
        "Typically fed via microstrip-to-slotline transition (add manually for full design).",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 8. Slot antenna
# ---------------------------------------------------------------------------

def _build_slot_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])

    lam0 = _wavelength_mm(freq)
    slot_length = lam0 / 2
    slot_width = args.get("slot_width_mm")
    if slot_width is None:
        slot_width = lam0 / 20
    else:
        slot_width = validate_positive(slot_width, "slot_width_mm")

    # Ground plane size
    gnd_size = lam0 * 1.5

    # Microstrip feed line (on back, crossing slot at center)
    # Approximate 50-ohm line on air (no substrate for simplicity)
    feed_w = 2.0
    feed_stub = lam0 / 4  # quarter-wave stub past slot center

    f_min = freq * 0.8
    f_max = freq * 1.2

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "slot_length_mm": round(slot_length, 3),
        "slot_width_mm": round(slot_width, 3),
        "ground_size_mm": round(gnd_size, 3),
        "feed_stub_mm": round(feed_stub, 3),
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Slot Antenna at {freq} GHz")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Ground plane
    script.add_raw(_build_brick(
        "Slot", "GroundPlane", "PEC",
        -gnd_size / 2, gnd_size / 2,
        -gnd_size / 2, gnd_size / 2,
        -0.035, 0,
    ))

    # Cut slot in ground plane (vacuum brick, removes from PEC via boolean)
    script.add_raw(_build_brick(
        "Slot", "SlotCut", "Vacuum",
        -slot_length / 2, slot_length / 2,
        -slot_width / 2, slot_width / 2,
        -0.035, 0,
    ))

    # Feed line crossing the slot (perpendicular, on z=-0.035 side)
    script.add_raw(_build_brick(
        "Slot", "FeedLine", "PEC",
        -feed_w / 2, feed_w / 2,
        -gnd_size / 2, feed_stub,
        -0.07, -0.035,
    ))

    # Discrete port at edge of feed line
    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", 0, -gnd_size / 2, -0.07)
        .set_triple("Point2", 0, -gnd_size / 2, 0)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"Resonant slot: {slot_length:.2f} x {slot_width:.2f} mm (lambda/2 x lambda/20).",
        "Slot antenna is the Babinet complement of the dipole.",
        "Impedance ~363 ohm at resonance; microstrip feed provides transformation.",
        "Adjust stub length to tune impedance match.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 9. Inverted-F antenna (IFA)
# ---------------------------------------------------------------------------

def _build_ifa_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    gnd_l = validate_positive(args.get("ground_length_mm", 100), "ground_length_mm")
    gnd_w = validate_positive(args.get("ground_width_mm", 40), "ground_width_mm")

    lam0 = _wavelength_mm(freq)

    # IFA dimensions
    arm_length = lam0 / 4  # quarter-wave horizontal arm
    ifa_height = min(lam0 * 0.05, 8)  # height above ground, max 8mm for mobile
    wire_r = 0.5  # wire radius

    # Shorting pin offset from feed
    short_offset = arm_length * 0.1  # 10% of arm from feed end

    f_min = freq * 0.8
    f_max = freq * 1.2

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "arm_length_mm": round(arm_length, 3),
        "height_mm": round(ifa_height, 3),
        "ground_length_mm": gnd_l,
        "ground_width_mm": gnd_w,
        "shorting_offset_mm": round(short_offset, 3),
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Inverted-F Antenna (IFA) at {freq} GHz")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Ground plane at z=0
    script.add_raw(_build_brick(
        "IFA", "Ground", "PEC",
        0, gnd_l,
        -gnd_w / 2, gnd_w / 2,
        -0.5, 0,
    ))

    # IFA located at one end of the ground plane (x=0 end)
    # Feed pin (vertical wire at x = short_offset)
    feed_x = short_offset

    # Shorting pin (vertical wire at x = 0)
    script.add_raw(_build_brick(
        "IFA", "ShortingPin", "PEC",
        -wire_r, wire_r,
        -wire_r, wire_r,
        0, ifa_height,
    ))

    # Horizontal arm from shorting pin to arm end
    script.add_raw(_build_brick(
        "IFA", "HorizontalArm", "PEC",
        0, arm_length,
        -wire_r, wire_r,
        ifa_height - wire_r, ifa_height + wire_r,
    ))

    # Feed pin (vertical, near shorting pin)
    script.add_raw(_build_brick(
        "IFA", "FeedPin", "PEC",
        feed_x - wire_r, feed_x + wire_r,
        -wire_r, wire_r,
        0, ifa_height,
    ))

    # Discrete port at feed pin base (between ground and arm)
    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", feed_x, 0, 0)
        .set_triple("Point2", feed_x, 0, ifa_height)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"IFA: arm length {arm_length:.2f} mm, height {ifa_height:.2f} mm.",
        "Compact antenna suitable for mobile and IoT devices.",
        "Adjust shorting pin distance from feed to tune impedance.",
        "Ground plane size strongly affects bandwidth and efficiency.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 10. Planar inverted-F antenna (PIFA)
# ---------------------------------------------------------------------------

def _build_pifa_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    gnd_l = validate_positive(args.get("ground_length_mm", 100), "ground_length_mm")
    gnd_w = validate_positive(args.get("ground_width_mm", 40), "ground_width_mm")

    lam0 = _wavelength_mm(freq)

    # PIFA: L + W ~ lambda/4 in effective medium
    pifa_height = min(lam0 * 0.04, 7)  # height above ground
    # Effective wavelength considering air medium (between patch and ground)
    lam_eff = lam0  # air-filled PIFA

    patch_w = args.get("patch_width_mm")
    if patch_w is None:
        patch_w = lam_eff / 8  # start with W = lambda/8
    else:
        patch_w = validate_positive(patch_w, "patch_width_mm")

    # L + W ~ lambda/4 => L = lambda/4 - W
    patch_l = lam_eff / 4 - patch_w
    if patch_l < 2:
        # If L is too small, redistribute
        patch_l = lam_eff / 8
        patch_w = lam_eff / 8

    # Shorting wall width (fraction of patch width)
    short_w = max(patch_w * 0.2, 1)

    # Feed position (between shorting wall and open edge)
    feed_x = patch_l * 0.3  # 30% from shorting wall

    f_min = freq * 0.8
    f_max = freq * 1.2

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "patch_length_mm": round(patch_l, 3),
        "patch_width_mm": round(patch_w, 3),
        "pifa_height_mm": round(pifa_height, 3),
        "shorting_wall_width_mm": round(short_w, 3),
        "feed_position_x_mm": round(feed_x, 3),
        "ground_length_mm": gnd_l,
        "ground_width_mm": gnd_w,
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Planar Inverted-F Antenna (PIFA) at {freq} GHz")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Ground plane at z=0
    script.add_raw(_build_brick(
        "PIFA", "Ground", "PEC",
        0, gnd_l,
        -gnd_w / 2, gnd_w / 2,
        -0.5, 0,
    ))

    # Top patch at z = pifa_height, located at corner of ground
    script.add_raw(_build_brick(
        "PIFA", "TopPatch", "PEC",
        0, patch_l,
        -patch_w / 2, patch_w / 2,
        pifa_height, pifa_height + 0.1,
    ))

    # Shorting wall at x=0 (connects patch edge to ground)
    script.add_raw(_build_brick(
        "PIFA", "ShortingWall", "PEC",
        -0.1, 0,
        -short_w / 2, short_w / 2,
        0, pifa_height,
    ))

    # Feed pin
    pin_r = 0.5
    script.add_raw(_build_brick(
        "PIFA", "FeedPin", "PEC",
        feed_x - pin_r, feed_x + pin_r,
        -pin_r, pin_r,
        0, pifa_height,
    ))

    # Discrete port
    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", feed_x, 0, 0)
        .set_triple("Point2", feed_x, 0, pifa_height)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"PIFA: patch {patch_l:.2f} x {patch_w:.2f} mm at height {pifa_height:.2f} mm.",
        f"Resonance condition: L + W ~ lambda/4 = {lam_eff / 4:.2f} mm.",
        "Adjust feed pin position to tune impedance.",
        "Adjust shorting wall width for bandwidth control.",
        "Compact design widely used in mobile phone antennas.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 11. Archimedean spiral antenna
# ---------------------------------------------------------------------------

def _build_spiral_antenna(args: dict) -> str:
    f_low = validate_frequency(args["freq_low_ghz"])
    f_high = validate_frequency(args["freq_high_ghz"])
    if f_high <= f_low:
        raise ValueError("freq_high_ghz must be greater than freq_low_ghz")
    n_turns = max(int(args.get("num_turns", 5)), 1)

    lam_low = _wavelength_mm(f_low)
    lam_high = _wavelength_mm(f_high)

    # Archimedean spiral: r = r0 + a*phi
    # Outer radius set by low frequency: circumference at outer = lambda_low
    # C = 2*pi*r_outer => r_outer = lambda_low / (2*pi)
    r_outer = lam_low / (2 * math.pi)
    # Inner radius from high frequency
    r_inner = lam_high / (2 * math.pi)
    r_inner = max(r_inner, 0.5)  # practical minimum

    # Arm width = gap width = inter-arm spacing / 2
    total_radial = r_outer - r_inner
    arm_width = total_radial / (2 * n_turns)
    arm_width = max(arm_width, 0.3)  # practical minimum

    # Spiral growth rate: a = arm_width / pi  (two arms, so pitch = 2*arm_width per turn)
    growth_rate = 2 * arm_width / (2 * math.pi)  # radial growth per radian

    f_center = (f_low + f_high) / 2
    f_min = f_low * 0.8
    f_max = f_high * 1.2

    calc = {
        "freq_low_ghz": f_low,
        "freq_high_ghz": f_high,
        "center_freq_ghz": round(f_center, 3),
        "outer_radius_mm": round(r_outer, 3),
        "inner_radius_mm": round(r_inner, 3),
        "arm_width_mm": round(arm_width, 3),
        "growth_rate_mm_per_rad": round(growth_rate, 6),
        "num_turns": n_turns,
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Archimedean Spiral Antenna: {f_low}-{f_high} GHz")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Build spiral arms using analytical curves
    # Arm 1: r(t) = r_inner + growth_rate * t, x = r*cos(t), y = r*sin(t)
    # Arm 2: offset by pi
    t_max_val = 2 * math.pi * n_turns

    for arm_idx, offset in enumerate([0, math.pi]):
        arm_name = f"spiral_arm{arm_idx + 1}"
        # Inner edge
        inner_curve = (
            VBABuilder("AnalyticalCurve")
            .call("Reset")
            .set("Name", f"{arm_name}_inner")
            .set("Curve", "spiral_curves")
            .set("LawX", f"({r_inner}+{growth_rate:.6f}*t)*cos(t+{offset:.6f})")
            .set("LawY", f"({r_inner}+{growth_rate:.6f}*t)*sin(t+{offset:.6f})")
            .set("LawZ", "0")
            .set_double("ParameterRange", 0, t_max_val)
            .call("Create")
        )
        script.add_block(inner_curve)

        # Outer edge (offset by arm_width in radial direction)
        outer_curve = (
            VBABuilder("AnalyticalCurve")
            .call("Reset")
            .set("Name", f"{arm_name}_outer")
            .set("Curve", "spiral_curves")
            .set("LawX", f"({r_inner + arm_width}+{growth_rate:.6f}*t)*cos(t+{offset:.6f})")
            .set("LawY", f"({r_inner + arm_width}+{growth_rate:.6f}*t)*sin(t+{offset:.6f})")
            .set("LawZ", "0")
            .set_double("ParameterRange", 0, t_max_val)
            .call("Create")
        )
        script.add_block(outer_curve)

    # Since building planar spiral arms from analytical curves in CST VBA
    # is complex (needs curve-based face creation), provide a polygon-based
    # discretised approach instead
    script.add_comment("Discretised spiral arm polygons (PEC, 0.035 mm thick)")

    for arm_idx, offset in enumerate([0, math.pi]):
        n_pts = max(n_turns * 36, 72)  # 36 points per turn
        inner_pts = []
        outer_pts = []
        for i in range(n_pts + 1):
            t = t_max_val * i / n_pts
            r_i = r_inner + growth_rate * t
            r_o = r_i + arm_width
            angle = t + offset
            inner_pts.append((r_i * math.cos(angle), r_i * math.sin(angle)))
            outer_pts.append((r_o * math.cos(angle), r_o * math.sin(angle)))

        # Build polygon: inner edge forward, outer edge backward, close
        arm_vba = VBABuilder("Extrude")
        arm_vba.call("Reset")
        arm_vba.set("Name", f"Arm{arm_idx + 1}")
        arm_vba.set("Component", "Spiral")
        arm_vba.set("Material", "PEC")
        arm_vba.set_number("Mode", 0)
        arm_vba.set_number("Height", 0.035)
        arm_vba.set("Origin", "0.0, 0.0, 0.0")
        arm_vba.set("Uvector", "1.0, 0.0, 0.0")
        arm_vba.set("Vvector", "0.0, 1.0, 0.0")

        # First point
        arm_vba.set_double("Point", inner_pts[0][0], inner_pts[0][1])
        # Inner edge
        for pt in inner_pts[1:]:
            arm_vba.set_double("LineTo", pt[0], pt[1])
        # Connect to outer edge (at far end)
        arm_vba.set_double("LineTo", outer_pts[-1][0], outer_pts[-1][1])
        # Outer edge reversed
        for pt in reversed(outer_pts[:-1]):
            arm_vba.set_double("LineTo", pt[0], pt[1])
        # Close
        arm_vba.set_double("LineTo", inner_pts[0][0], inner_pts[0][1])
        arm_vba.call("Create")
        script.add_block(arm_vba)

    # Discrete port between arm inner tips
    # Arm1 starts at angle=0, Arm2 at angle=pi
    p1x = r_inner * math.cos(0)
    p1y = r_inner * math.sin(0)
    p2x = r_inner * math.cos(math.pi)
    p2y = r_inner * math.sin(math.pi)

    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", p1x, p1y, 0)
        .set_triple("Point2", p2x, p2y, 0)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(f_center))
    script.add_block(_build_efield_monitor(f_center))

    notes = [
        f"Archimedean spiral: {n_turns} turns, {r_inner:.2f} to {r_outer:.2f} mm radius.",
        f"Operating band: {f_low}-{f_high} GHz ({f_high / f_low:.1f}:1 bandwidth ratio).",
        "Produces circular polarization over the operating band.",
        "Input impedance ~188 ohm (self-complementary); use a balun for 50-ohm feed.",
        "Add an absorber-backed cavity for unidirectional radiation.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 12. Bowtie antenna
# ---------------------------------------------------------------------------

def _build_bowtie_antenna(args: dict) -> str:
    freq = validate_frequency(args["frequency_ghz"])
    flare_angle = args.get("flare_angle", 60)
    if flare_angle <= 0 or flare_angle >= 180:
        raise ValueError("flare_angle must be between 0 and 180 degrees")

    lam0 = _wavelength_mm(freq)

    arm_length = args.get("arm_length_mm")
    if arm_length is None:
        arm_length = lam0 / 4
    else:
        arm_length = validate_positive(arm_length, "arm_length_mm")

    # Gap between arms
    gap = max(lam0 * 0.005, 0.5)

    # Half-width at the end of each arm
    half_width = arm_length * math.tan(math.radians(flare_angle / 2))

    f_min = freq * 0.5  # bowties are wideband
    f_max = freq * 1.5

    calc = {
        "frequency_ghz": freq,
        "wavelength_mm": round(lam0, 3),
        "arm_length_mm": round(arm_length, 3),
        "flare_angle_deg": flare_angle,
        "arm_half_width_mm": round(half_width, 3),
        "gap_mm": round(gap, 3),
    }

    script = VBAScript()
    script.add_comment("=" * 60)
    script.add_comment(f"Bowtie Antenna at {freq} GHz")
    script.add_comment("=" * 60)

    script.add_raw(_build_units_block())
    script.add_block(_build_frequency_range(f_min, f_max))

    # Upper arm (triangle pointing +x, flares in y)
    upper_vba = VBABuilder("Extrude")
    upper_vba.call("Reset")
    upper_vba.set("Name", "UpperArm")
    upper_vba.set("Component", "Bowtie")
    upper_vba.set("Material", "PEC")
    upper_vba.set_number("Mode", 0)
    upper_vba.set_number("Height", 0.035)
    upper_vba.set("Origin", "0.0, 0.0, 0.0")
    upper_vba.set("Uvector", "1.0, 0.0, 0.0")
    upper_vba.set("Vvector", "0.0, 1.0, 0.0")
    # Triangle: tip at gap edge, flares out
    upper_vba.set_double("Point", gap / 2, 0)
    upper_vba.set_double("LineTo", gap / 2 + arm_length, half_width)
    upper_vba.set_double("LineTo", gap / 2 + arm_length, -half_width)
    upper_vba.set_double("LineTo", gap / 2, 0)
    upper_vba.call("Create")
    script.add_block(upper_vba)

    # Lower arm (mirror, pointing -x)
    lower_vba = VBABuilder("Extrude")
    lower_vba.call("Reset")
    lower_vba.set("Name", "LowerArm")
    lower_vba.set("Component", "Bowtie")
    lower_vba.set("Material", "PEC")
    lower_vba.set_number("Mode", 0)
    lower_vba.set_number("Height", 0.035)
    lower_vba.set("Origin", "0.0, 0.0, 0.0")
    lower_vba.set("Uvector", "1.0, 0.0, 0.0")
    lower_vba.set("Vvector", "0.0, 1.0, 0.0")
    lower_vba.set_double("Point", -gap / 2, 0)
    lower_vba.set_double("LineTo", -gap / 2 - arm_length, half_width)
    lower_vba.set_double("LineTo", -gap / 2 - arm_length, -half_width)
    lower_vba.set_double("LineTo", -gap / 2, 0)
    lower_vba.call("Create")
    script.add_block(lower_vba)

    # Discrete port across gap
    port_vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", 1)
        .set("Type", "SParameter")
        .set_number("Impedance", 50)
        .set_triple("Point1", -gap / 2, 0, 0)
        .set_triple("Point2", gap / 2, 0, 0)
        .set_number("Radius", 0.5)
        .set_bool("Monitor", True)
        .call("Create")
    )
    script.add_block(port_vba)

    script.add_raw(_build_open_boundaries())
    script.add_block(_build_field_monitor(freq))
    script.add_block(_build_efield_monitor(freq))

    notes = [
        f"Bowtie antenna: arm length {arm_length:.2f} mm, flare {flare_angle} deg.",
        "Wideband variant of the dipole; wider flare = wider bandwidth.",
        "Input impedance depends on flare angle; ~70-100 ohm typical.",
        "Planar structure easy to fabricate on PCB.",
    ]

    return _result_json(calc, script.build(), notes)


# ---------------------------------------------------------------------------
# 13. List antenna templates
# ---------------------------------------------------------------------------

_TEMPLATE_CATALOG = [
    {
        "tool": "cst_antenna_patch",
        "name": "Rectangular Microstrip Patch",
        "description": "Rectangular patch antenna on dielectric substrate with inset/probe/microstrip feed.",
        "use_cases": ["Wi-Fi", "GPS", "5G sub-6 GHz", "ISM band"],
        "polarization": "Linear",
        "bandwidth": "Narrow (2-5%)",
        "gain_range_dbi": "5-8",
    },
    {
        "tool": "cst_antenna_dipole",
        "name": "Half-Wave Dipole",
        "description": "Classic half-wavelength dipole — fundamental reference antenna.",
        "use_cases": ["Reference measurements", "VHF/UHF", "FM radio"],
        "polarization": "Linear",
        "bandwidth": "Moderate (~10%)",
        "gain_range_dbi": "2.15",
    },
    {
        "tool": "cst_antenna_monopole",
        "name": "Quarter-Wave Monopole",
        "description": "Monopole over ground plane — half of a dipole with image theory.",
        "use_cases": ["Vehicle antennas", "base stations", "IoT"],
        "polarization": "Vertical linear",
        "bandwidth": "Moderate (~10%)",
        "gain_range_dbi": "2-5",
    },
    {
        "tool": "cst_antenna_horn",
        "name": "Pyramidal Horn",
        "description": "High-gain horn antenna fed by rectangular waveguide.",
        "use_cases": ["Gain standard", "radar", "satellite feeds", "mmWave"],
        "polarization": "Linear",
        "bandwidth": "Moderate (~40% waveguide band)",
        "gain_range_dbi": "10-25",
    },
    {
        "tool": "cst_antenna_yagi",
        "name": "Yagi-Uda",
        "description": "Directional antenna with reflector, driven element, and directors.",
        "use_cases": ["TV reception", "ham radio", "point-to-point links"],
        "polarization": "Linear",
        "bandwidth": "Narrow (3-5%)",
        "gain_range_dbi": "6-18",
    },
    {
        "tool": "cst_antenna_helix",
        "name": "Axial-Mode Helix",
        "description": "Helical antenna producing circular polarization along the axis.",
        "use_cases": ["Satellite communication", "GNSS", "telemetry"],
        "polarization": "Circular",
        "bandwidth": "Wide (~50%)",
        "gain_range_dbi": "8-18",
    },
    {
        "tool": "cst_antenna_vivaldi",
        "name": "Vivaldi / Tapered Slot",
        "description": "Wideband endfire antenna with exponential taper on substrate.",
        "use_cases": ["UWB radar", "imaging", "phased arrays"],
        "polarization": "Linear",
        "bandwidth": "Very wide (>10:1)",
        "gain_range_dbi": "4-12",
    },
    {
        "tool": "cst_antenna_slot",
        "name": "Slot Antenna",
        "description": "Resonant slot cut in a ground plane (Babinet complement of dipole).",
        "use_cases": ["Flush-mount aircraft", "conformal arrays", "waveguide slots"],
        "polarization": "Linear",
        "bandwidth": "Narrow (2-5%)",
        "gain_range_dbi": "2-5",
    },
    {
        "tool": "cst_antenna_ifa",
        "name": "Inverted-F Antenna (IFA)",
        "description": "Compact wire antenna with shorting pin, popular in mobile devices.",
        "use_cases": ["Mobile phones", "laptops", "IoT modules"],
        "polarization": "Linear (mixed in practice)",
        "bandwidth": "Moderate (5-10%)",
        "gain_range_dbi": "1-3",
    },
    {
        "tool": "cst_antenna_pifa",
        "name": "Planar Inverted-F Antenna (PIFA)",
        "description": "Compact planar antenna with top patch, shorting wall, and feed pin.",
        "use_cases": ["Smartphones", "wearables", "compact wireless"],
        "polarization": "Linear (mixed in practice)",
        "bandwidth": "Moderate (4-10%)",
        "gain_range_dbi": "2-5",
    },
    {
        "tool": "cst_antenna_spiral",
        "name": "Archimedean Spiral",
        "description": "Self-complementary wideband spiral antenna for circular polarization.",
        "use_cases": ["Direction finding", "electronic warfare", "UWB"],
        "polarization": "Circular",
        "bandwidth": "Very wide (>10:1)",
        "gain_range_dbi": "2-8",
    },
    {
        "tool": "cst_antenna_bowtie",
        "name": "Bowtie Antenna",
        "description": "Planar wideband dipole variant with triangular arms.",
        "use_cases": ["UWB", "GPR", "RFID readers"],
        "polarization": "Linear",
        "bandwidth": "Wide (30-50%)",
        "gain_range_dbi": "2-5",
    },
]


def _build_list_templates(args: dict) -> str:
    return json.dumps({
        "antenna_templates": _TEMPLATE_CATALOG,
        "total_count": len(_TEMPLATE_CATALOG),
        "notes": [
            "Use any tool name to generate a complete parametric antenna model.",
            "All dimensions are auto-calculated from the target frequency.",
            "VBA scripts include geometry, materials, ports, boundaries, and monitors.",
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[[dict], str]] = {
    "cst_antenna_patch": _build_patch_antenna,
    "cst_antenna_dipole": _build_dipole_antenna,
    "cst_antenna_monopole": _build_monopole_antenna,
    "cst_antenna_horn": _build_horn_antenna,
    "cst_antenna_yagi": _build_yagi_antenna,
    "cst_antenna_helix": _build_helix_antenna,
    "cst_antenna_vivaldi": _build_vivaldi_antenna,
    "cst_antenna_slot": _build_slot_antenna,
    "cst_antenna_ifa": _build_ifa_antenna,
    "cst_antenna_pifa": _build_pifa_antenna,
    "cst_antenna_spiral": _build_spiral_antenna,
    "cst_antenna_bowtie": _build_bowtie_antenna,
    "cst_list_antenna_templates": _build_list_templates,
}

# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle an antenna template tool call.

    For design-template tools the VBA is generated but *not* automatically
    executed — the complete script is returned so the user can review
    calculated parameters before committing to CST.
    """
    handler_fn = _HANDLERS.get(name)
    if handler_fn is None:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": f"Unknown antenna template tool: {name}",
        }))]

    try:
        result_text = handler_fn(arguments)
        return [TextContent(type="text", text=result_text)]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": str(e),
        }))]


def register_antenna_template_tools(server, client: CSTClient) -> None:
    """Register antenna template tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
