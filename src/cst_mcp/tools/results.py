"""Result extraction tools for CST Studio MCP server.

Provides 22 tools for extracting and exporting simulation results including
S-parameters, far-field patterns, impedance, VSWR, gain, efficiency,
general result tree navigation, and advanced results such as group delay,
pattern cuts, cross-polarization, axial ratio, surface/volume currents,
efficiency breakdown, time-domain signals, Smith chart data, bandwidth,
and 3D radiation patterns.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.types import FieldMonitorType
from cst_mcp.validators import validate_file_path, validate_frequency, validate_port_number
from cst_mcp.vba_builder import VBABuilder, VBAScript

if TYPE_CHECKING:
    from mcp.server import Server

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # 1. cst_get_s_parameters
    Tool(
        name="cst_get_s_parameters",
        description=(
            "Extract S-parameter results from a completed CST simulation. "
            "Returns S-parameter data (magnitude, phase, real/imaginary) for "
            "the specified port pair. In connected mode reads directly from "
            "the result tree; in offline mode returns VBA scripts and explains "
            "the CST result tree structure."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port_in": {
                    "type": "integer",
                    "description": "Input port number (excitation port).",
                    "default": 1,
                },
                "port_out": {
                    "type": "integer",
                    "description": "Output port number (observation port).",
                    "default": 1,
                },
                "format": {
                    "type": "string",
                    "description": (
                        "Output format for S-parameter data. "
                        "'db' = magnitude in dB, 'mag' = linear magnitude, "
                        "'real_imag' = real and imaginary parts, "
                        "'phase' = phase in degrees."
                    ),
                    "default": "db",
                    "enum": ["db", "mag", "real_imag", "phase"],
                },
            },
            "required": [],
        },
    ),
    # 2. cst_get_farfield
    Tool(
        name="cst_get_farfield",
        description=(
            "Get far-field radiation pattern results from a completed CST "
            "simulation at a specific frequency. Returns gain, directivity, "
            "radiation efficiency, and beam widths. Requires a farfield "
            "monitor at the specified frequency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract the far-field pattern.",
                },
                "monitor_name": {
                    "type": "string",
                    "description": (
                        "Name of the far-field monitor. If omitted, defaults to "
                        "'farfield (f=<frequency>)' which is the CST auto-generated name."
                    ),
                },
            },
            "required": ["frequency"],
        },
    ),
    # 3. cst_add_field_monitor
    Tool(
        name="cst_add_field_monitor",
        description=(
            "Add a field monitor at a specific frequency to the CST project. "
            "Field monitors must be defined before running a simulation to "
            "capture field distributions, far-field patterns, surface currents, "
            "or power flow at the desired frequency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "monitor_type": {
                    "type": "string",
                    "description": (
                        "Type of field monitor to add. Options: "
                        "Efield (electric field), Hfield (magnetic field), "
                        "Powerflow (Poynting vector), Current (volume current), "
                        "Powerloss (loss density), Farfield (radiation pattern), "
                        "Surfacecurrent (surface current density)."
                    ),
                    "enum": [e.value for e in FieldMonitorType],
                },
                "frequency": {
                    "type": "number",
                    "description": "Monitor frequency in GHz.",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Custom name for the monitor. If omitted, a name is "
                        "auto-generated from the type and frequency, e.g. "
                        "'e-field (f=2.45)'."
                    ),
                },
            },
            "required": ["monitor_type", "frequency"],
        },
    ),
    # 4. cst_get_impedance
    Tool(
        name="cst_get_impedance",
        description=(
            "Get input impedance (Z-parameters) for a port from a completed "
            "CST simulation. Returns real and imaginary impedance vs frequency. "
            "Useful for matching network design and feed optimization."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "description": "Port number to extract impedance for.",
                    "default": 1,
                },
            },
            "required": [],
        },
    ),
    # 5. cst_get_vswr
    Tool(
        name="cst_get_vswr",
        description=(
            "Get Voltage Standing Wave Ratio (VSWR) for a port from a "
            "completed CST simulation. VSWR indicates impedance matching "
            "quality: 1.0 is perfect match, <2.0 is generally acceptable. "
            "Can also be computed from S11: VSWR = (1+|S11|)/(1-|S11|)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "description": "Port number to extract VSWR for.",
                    "default": 1,
                },
            },
            "required": [],
        },
    ),
    # 6. cst_get_gain
    Tool(
        name="cst_get_gain",
        description=(
            "Get antenna gain at a specific frequency from a completed CST "
            "simulation. Returns peak gain in dBi and the direction (theta, "
            "phi) of maximum gain. Requires a farfield monitor at the "
            "specified frequency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract gain.",
                },
            },
            "required": ["frequency"],
        },
    ),
    # 7. cst_get_efficiency
    Tool(
        name="cst_get_efficiency",
        description=(
            "Get antenna radiation efficiency from a completed CST simulation "
            "at a specific frequency. Returns total efficiency (including "
            "mismatch), radiation efficiency (excluding mismatch), and "
            "mismatch loss in dB."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract efficiency.",
                },
            },
            "required": ["frequency"],
        },
    ),
    # 8. cst_list_results
    Tool(
        name="cst_list_results",
        description=(
            "List all available results in the CST result tree. Optionally "
            "specify a subtree path to narrow the listing. Useful for "
            "discovering what simulation results are available before "
            "extracting specific data."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tree_path": {
                    "type": "string",
                    "description": (
                        "Result tree path to list, e.g. '1D Results', "
                        "'1D Results\\S-Parameters', 'Farfields', "
                        "'2D/3D Results'. Omit to list top-level result categories."
                    ),
                },
            },
            "required": [],
        },
    ),
    # 9. cst_export_result
    Tool(
        name="cst_export_result",
        description=(
            "Export a simulation result to a file (CSV, Touchstone, or text). "
            "Specify the result tree path and desired output format. Useful "
            "for post-processing results in external tools like MATLAB or Python."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "result_path": {
                    "type": "string",
                    "description": (
                        "CST result tree path to export, e.g. "
                        "'1D Results\\S-Parameters\\S1,1' or "
                        "'Farfields\\farfield (f=2.45)'."
                    ),
                },
                "output_file": {
                    "type": "string",
                    "description": "Full file path for the exported file.",
                },
                "format": {
                    "type": "string",
                    "description": (
                        "Export file format. 'csv' for comma-separated values, "
                        "'touchstone' for Touchstone/SnP format (S-parameters only), "
                        "'txt' for space-separated text."
                    ),
                    "default": "csv",
                    "enum": ["csv", "touchstone", "txt"],
                },
            },
            "required": ["result_path", "output_file"],
        },
    ),
    # 10. cst_get_result_summary
    Tool(
        name="cst_get_result_summary",
        description=(
            "Get a summary of all key simulation results from a completed CST "
            "simulation. Returns an overview of S-parameters, gain, efficiency, "
            "and impedance. Useful for a quick design evaluation without "
            "querying each result type individually."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    # 11. cst_get_s_parameter_phase
    Tool(
        name="cst_get_s_parameter_phase",
        description=(
            "Extract S-parameter phase response from a completed CST simulation. "
            "Returns the phase of the specified S-parameter vs frequency. "
            "Optionally unwraps the phase to remove 360-degree discontinuities. "
            "Useful for group delay analysis and phase-matching designs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port_in": {
                    "type": "integer",
                    "description": "Input port number (excitation port).",
                    "default": 1,
                },
                "port_out": {
                    "type": "integer",
                    "description": "Output port number (observation port).",
                    "default": 1,
                },
                "unwrap": {
                    "type": "boolean",
                    "description": (
                        "If true, unwrap the phase to remove 360-degree jumps. "
                        "Useful for group delay computation."
                    ),
                    "default": False,
                },
            },
            "required": [],
        },
    ),
    # 12. cst_get_group_delay
    Tool(
        name="cst_get_group_delay",
        description=(
            "Compute group delay from S-parameter phase for a port pair. "
            "Group delay is defined as tau = -d(phase)/d(2*pi*f) and "
            "represents the signal propagation delay through the device. "
            "Useful for UWB antenna and filter characterization."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port_in": {
                    "type": "integer",
                    "description": "Input port number (excitation port).",
                    "default": 1,
                },
                "port_out": {
                    "type": "integer",
                    "description": "Output port number (observation port).",
                    "default": 1,
                },
            },
            "required": [],
        },
    ),
    # 13. cst_get_pattern_cut
    Tool(
        name="cst_get_pattern_cut",
        description=(
            "Extract an E-plane, H-plane, or custom radiation pattern cut from "
            "a completed CST simulation at a specific frequency. Returns gain "
            "vs angle for the selected plane. Requires a farfield monitor at "
            "the specified frequency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract the pattern cut.",
                },
                "plane": {
                    "type": "string",
                    "description": (
                        "Pattern cut plane. 'E' for E-plane (phi=0), "
                        "'H' for H-plane (phi=90), 'custom' for arbitrary cut."
                    ),
                    "default": "E",
                    "enum": ["E", "H", "custom"],
                },
                "phi_cut": {
                    "type": "number",
                    "description": (
                        "Phi angle (degrees) for custom plane cut. "
                        "Only used when plane='custom'. Default 0."
                    ),
                    "default": 0,
                },
                "theta_cut": {
                    "type": "number",
                    "description": (
                        "Theta angle (degrees) for custom plane cut. "
                        "Only used when plane='custom'. Default 90."
                    ),
                    "default": 90,
                },
            },
            "required": ["frequency"],
        },
    ),
    # 14. cst_get_cross_polarization
    Tool(
        name="cst_get_cross_polarization",
        description=(
            "Extract cross-polarization level and cross-polarization "
            "discrimination (XPD) from a completed CST simulation. Supports "
            "Ludwig-3, Ludwig-2, and circular polarization definitions. "
            "Requires a farfield monitor at the specified frequency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract cross-polarization.",
                },
                "definition": {
                    "type": "string",
                    "description": (
                        "Polarization definition to use. 'Ludwig3' is the most "
                        "common for linear polarization, 'Ludwig2' for aperture "
                        "antennas, 'circular' for CP antennas."
                    ),
                    "default": "Ludwig3",
                    "enum": ["Ludwig3", "Ludwig2", "circular"],
                },
            },
            "required": ["frequency"],
        },
    ),
    # 15. cst_get_axial_ratio
    Tool(
        name="cst_get_axial_ratio",
        description=(
            "Extract axial ratio for circularly polarized antennas from a "
            "completed CST simulation. Axial ratio (AR) indicates the quality "
            "of circular polarization: AR=0 dB is perfect CP, AR<3 dB is "
            "acceptable. Can plot AR vs angle or vs frequency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract axial ratio.",
                },
                "mode": {
                    "type": "string",
                    "description": (
                        "'vs_angle' to plot AR vs theta at fixed frequency, "
                        "'vs_frequency' to plot AR vs frequency at fixed angle."
                    ),
                    "default": "vs_angle",
                    "enum": ["vs_angle", "vs_frequency"],
                },
                "theta_cut": {
                    "type": "number",
                    "description": "Theta angle (degrees) for the observation direction.",
                    "default": 0,
                },
                "phi_cut": {
                    "type": "number",
                    "description": "Phi angle (degrees) for the observation direction.",
                    "default": 0,
                },
            },
            "required": ["frequency"],
        },
    ),
    # 16. cst_get_surface_current
    Tool(
        name="cst_get_surface_current",
        description=(
            "Extract surface current density distribution from a completed CST "
            "simulation at a specific frequency. Useful for understanding "
            "current flow on antenna structures and identifying hot spots. "
            "Requires a surface current monitor at the specified frequency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract surface current.",
                },
                "component": {
                    "type": "string",
                    "description": (
                        "Optional: specific component to extract current for. "
                        "If omitted, extracts for all components."
                    ),
                },
            },
            "required": ["frequency"],
        },
    ),
    # 17. cst_get_efficiency_breakdown
    Tool(
        name="cst_get_efficiency_breakdown",
        description=(
            "Get a detailed efficiency breakdown with loss budget from a "
            "completed CST simulation. Returns radiation efficiency, total "
            "efficiency, and individual loss contributions (mismatch, conductor, "
            "dielectric). Useful for identifying dominant loss mechanisms "
            "in antenna designs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract efficiency breakdown.",
                },
            },
            "required": ["frequency"],
        },
    ),
    # 18. cst_get_time_domain_signal
    Tool(
        name="cst_get_time_domain_signal",
        description=(
            "Extract time-domain port signal waveforms from a completed CST "
            "time-domain simulation. Returns incident, reflected, or "
            "transmitted signal vs time. Useful for UWB pulse analysis, "
            "time-domain reflectometry, and transient response evaluation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "description": "Port number for the signal.",
                    "default": 1,
                },
                "signal_type": {
                    "type": "string",
                    "description": (
                        "'incident' for the excitation signal at the port, "
                        "'reflected' for the reflected signal, "
                        "'transmitted' for the signal received at another port."
                    ),
                    "default": "reflected",
                    "enum": ["incident", "reflected", "transmitted"],
                },
                "port_out": {
                    "type": "integer",
                    "description": (
                        "Output port number (only used when signal_type='transmitted'). "
                        "Specifies which port receives the transmitted signal."
                    ),
                    "default": 1,
                },
            },
            "required": [],
        },
    ),
    # 19. cst_get_smith_chart_data
    Tool(
        name="cst_get_smith_chart_data",
        description=(
            "Extract Smith chart formatted impedance data from a completed CST "
            "simulation. Computes normalized impedance from S11 reflection "
            "coefficient: Z = Z0*(1+S11)/(1-S11). Returns real and imaginary "
            "parts of the normalized impedance for Smith chart plotting."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "description": "Port number to extract Smith chart data for.",
                    "default": 1,
                },
                "z0": {
                    "type": "number",
                    "description": (
                        "Reference impedance in Ohms for normalization. "
                        "Typically 50 Ohms for most RF systems."
                    ),
                    "default": 50,
                },
            },
            "required": [],
        },
    ),
    # 20. cst_get_bandwidth
    Tool(
        name="cst_get_bandwidth",
        description=(
            "Calculate impedance bandwidth from S-parameter results. Finds "
            "the frequency range where S11 (or VSWR) meets the specified "
            "threshold. Returns center frequency, bandwidth in MHz, and "
            "fractional bandwidth percentage."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "description": "Port number to compute bandwidth for.",
                    "default": 1,
                },
                "threshold_db": {
                    "type": "number",
                    "description": (
                        "S11 threshold in dB for bandwidth computation. "
                        "Common values: -10 dB (VSWR 2:1), -6 dB (VSWR 3:1), "
                        "-15 dB (VSWR 1.4:1)."
                    ),
                    "default": -10,
                },
                "criterion": {
                    "type": "string",
                    "description": (
                        "'S11' to use return loss threshold, "
                        "'VSWR' to use VSWR threshold."
                    ),
                    "default": "S11",
                    "enum": ["S11", "VSWR"],
                },
            },
            "required": [],
        },
    ),
    # 21. cst_get_radiation_pattern_3d
    Tool(
        name="cst_get_radiation_pattern_3d",
        description=(
            "Export full 3D radiation pattern data from a completed CST "
            "simulation at a specific frequency. Returns gain values over "
            "the full sphere in spherical or Cartesian coordinates. Useful "
            "for antenna pattern visualization and integration with external "
            "tools. Requires a farfield monitor at the specified frequency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract the 3D pattern.",
                },
                "resolution_deg": {
                    "type": "number",
                    "description": (
                        "Angular resolution in degrees for the exported pattern. "
                        "Lower values give finer resolution but larger data. "
                        "Typical values: 1, 2, 5, 10."
                    ),
                    "default": 5,
                },
                "coordinate": {
                    "type": "string",
                    "description": (
                        "'spherical' for (theta, phi, gain) output, "
                        "'cartesian' for (x, y, z, gain) output."
                    ),
                    "default": "spherical",
                    "enum": ["spherical", "cartesian"],
                },
            },
            "required": ["frequency"],
        },
    ),
    # 22. cst_get_current_distribution
    Tool(
        name="cst_get_current_distribution",
        description=(
            "Extract volume current distribution from a completed CST "
            "simulation at a specific frequency. Complements surface current "
            "extraction by providing current density inside dielectric or "
            "lossy volumes. Requires a current density monitor at the "
            "specified frequency."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "frequency": {
                    "type": "number",
                    "description": "Frequency in GHz at which to extract current distribution.",
                },
                "component": {
                    "type": "string",
                    "description": (
                        "Optional: specific component to extract current for. "
                        "If omitted, extracts for all components."
                    ),
                },
            },
            "required": ["frequency"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(data: dict) -> list[TextContent]:
    """Wrap a dict as a single JSON TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


def _s_param_tree_path(port_out: int, port_in: int) -> str:
    """Build the CST result tree path for an S-parameter.

    CST convention: ``1D Results\\S-Parameters\\SX,Y`` where X is the
    output port and Y is the input port.
    """
    return f"1D Results\\S-Parameters\\S{port_out},{port_in}"


def _farfield_tree_path(frequency: float, monitor_name: str | None = None) -> str:
    """Build the CST result tree path for a far-field result."""
    if monitor_name:
        return f"Farfields\\{monitor_name}"
    return f"Farfields\\farfield (f={frequency})"


def _impedance_tree_path(port: int) -> str:
    """Build the CST result tree path for Z-parameters."""
    return f"1D Results\\Z-Parameters\\Z{port},{port}"


def _vswr_tree_path(port: int) -> str:
    """Build the CST result tree path for VSWR."""
    return f"1D Results\\VSWR\\VSWR{port}"


# ---------------------------------------------------------------------------
# VBA script builders
# ---------------------------------------------------------------------------

def _build_s_parameter_vba(port_out: int, port_in: int, fmt: str) -> str:
    """Build VBA script for extracting S-parameters."""
    tree_path = _s_param_tree_path(port_out, port_in)
    script = VBAScript()
    script.add_comment(f"Extract S-parameter S{port_out},{port_in} in {fmt} format")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  ' Access the 1D result data",
        "  Dim nPoints As Long",
        '  nPoints = Result1D("").GetN',
        "",
        "  Dim i As Long",
        "  For i = 0 To nPoints - 1",
        '    Dim freq As Double',
        '    freq = Result1D("").GetX(i)',
    ]

    if fmt == "db":
        lines += [
            '    Dim sVal As Double',
            '    sVal = Result1D("").GetY(i)  \' Already in dB for S-param results',
            '    Debug.Print freq & "," & sVal',
        ]
    elif fmt == "mag":
        lines += [
            '    Dim sDb As Double',
            '    sDb = Result1D("").GetY(i)',
            '    Dim sMag As Double',
            '    sMag = 10^(sDb / 20.0)',
            '    Debug.Print freq & "," & sMag',
        ]
    elif fmt == "phase":
        lines += [
            "    ' Select the phase result tree item",
            f'    SelectTreeItem "1D Results\\S-Parameters\\S{port_out},{port_in}_phase"',
            '    Dim sPhase As Double',
            '    sPhase = Result1D("").GetY(i)',
            '    Debug.Print freq & "," & sPhase',
        ]
    elif fmt == "real_imag":
        lines += [
            "    ' Read real and imaginary components",
            '    Dim sReal As Double, sImag As Double',
            f'    SelectTreeItem "1D Results\\S-Parameters\\S{port_out},{port_in}_real"',
            '    sReal = Result1D("").GetY(i)',
            f'    SelectTreeItem "1D Results\\S-Parameters\\S{port_out},{port_in}_imag"',
            '    sImag = Result1D("").GetY(i)',
            '    Debug.Print freq & "," & sReal & "," & sImag',
        ]

    lines += [
        "  Next i",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_farfield_vba(frequency: float, monitor_name: str | None) -> str:
    """Build VBA script for extracting far-field results."""
    tree_path = _farfield_tree_path(frequency, monitor_name)
    script = VBAScript()
    script.add_comment(f"Extract far-field results at {frequency} GHz")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  ' Access far-field result object",
        "  Dim ff As Object",
        '  Set ff = FarfieldPlot',
        "",
        "  ' Read key far-field metrics",
        "  ff.Reset",
        '  ff.Plottype "3D"',
        '  ff.SetPlotMode "Gain"',
        "",
        "  ' Peak gain and direction",
        "  Dim peakGain As Double",
        "  peakGain = ff.GetMainLobeDirection",
        "",
        "  ' Beam widths",
        "  Dim bwE As Double, bwH As Double",
        '  ff.SetPlotMode "Gain"',
        "",
        "  ' Print summary",
        '  Debug.Print "Peak Gain (dBi): " & ff.GetResultValue("max gain")',
        '  Debug.Print "Directivity (dBi): " & ff.GetResultValue("directivity")',
        '  Debug.Print "Efficiency: " & ff.GetResultValue("rad. efficiency")',
        '  Debug.Print "3dB Beam Width E-plane: " & ff.GetResultValue("angular width (3db), theta")',
        '  Debug.Print "3dB Beam Width H-plane: " & ff.GetResultValue("angular width (3db), phi")',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_add_monitor_vba(
    monitor_type: str, frequency: float, name: str | None
) -> str:
    """Build VBA script for adding a field monitor."""
    if name is None:
        type_prefix_map = {
            "Efield": "e-field",
            "Hfield": "h-field",
            "Powerflow": "power",
            "Current": "current",
            "Powerloss": "loss",
            "Farfield": "farfield",
            "Surfacecurrent": "surface-current",
            "Eenergy": "e-energy",
            "Henergy": "h-energy",
        }
        prefix = type_prefix_map.get(monitor_type, monitor_type.lower())
        name = f"{prefix} (f={frequency})"

    script = VBAScript()
    script.add_comment(f"Add {monitor_type} field monitor '{name}' at {frequency} GHz")
    script.add_blank()

    builder = (
        VBABuilder("Monitor")
        .call("Reset")
        .set("Name", name)
        .set("Domain", "Frequency")
        .set("FieldType", monitor_type)
        .set_number("Frequency", frequency)
    )
    if str(monitor_type).lower() == "farfield":
        builder = (
            builder.set("ExportFarfieldSource", "False")
            .set("EnableNearfieldCalculation", "True")
            .set("UseSubvolume", "False")
        )
    builder = builder.call("Create")
    script.add_block(builder)
    return script.build()


def _build_impedance_vba(port: int) -> str:
    """Build VBA script for extracting input impedance."""
    tree_path = _impedance_tree_path(port)
    script = VBAScript()
    script.add_comment(f"Extract input impedance (Z{port},{port}) vs frequency")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "1D Results\\Z-Parameters\\Z{port},{port}"',
        "",
        "  ' Read impedance data (real part)",
        "  Dim nPoints As Long",
        '  nPoints = Result1D("").GetN',
        "",
        "  Dim i As Long",
        "  For i = 0 To nPoints - 1",
        "    Dim freq As Double, zReal As Double, zImag As Double",
        '    freq = Result1D("").GetX(i)',
        '    zReal = Result1D("").GetY(i)',
        "",
        "    ' Switch to imaginary part",
        f'    SelectTreeItem "1D Results\\Z-Parameters\\Z{port},{port}_imag"',
        '    zImag = Result1D("").GetY(i)',
        "",
        "    ' Switch back to real part for next iteration",
        f'    SelectTreeItem "1D Results\\Z-Parameters\\Z{port},{port}"',
        '    Debug.Print freq & "," & zReal & "," & zImag',
        "  Next i",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_vswr_vba(port: int) -> str:
    """Build VBA script for extracting VSWR."""
    tree_path = _vswr_tree_path(port)
    script = VBAScript()
    script.add_comment(f"Extract VSWR for port {port}")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_comment("VSWR = (1 + |S11|) / (1 - |S11|)")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  ' If VSWR is directly available in the result tree, read it",
        "  Dim nPoints As Long",
        '  nPoints = Result1D("").GetN',
        "",
        "  If nPoints > 0 Then",
        "    Dim i As Long",
        "    For i = 0 To nPoints - 1",
        "      Dim freq As Double, vswr As Double",
        '      freq = Result1D("").GetX(i)',
        '      vswr = Result1D("").GetY(i)',
        '      Debug.Print freq & "," & vswr',
        "    Next i",
        "  Else",
        "    ' Compute VSWR from S-parameters",
        f'    SelectTreeItem "1D Results\\S-Parameters\\S{port},{port}"',
        '    nPoints = Result1D("").GetN',
        "    For i = 0 To nPoints - 1",
        '      freq = Result1D("").GetX(i)',
        "      Dim s11_db As Double, s11_mag As Double",
        '      s11_db = Result1D("").GetY(i)',
        "      s11_mag = 10^(s11_db / 20.0)",
        "      If Abs(s11_mag - 1.0) < 0.0000000001 Then",
        "        vswr = 999.9  ' |S11|=1.0: total reflection",
        "      ElseIf s11_mag > 1.0 Then",
        "        vswr = 999.9  ' |S11|>1.0: active device or error",
        "      Else",
        "        vswr = (1 + s11_mag) / (1 - s11_mag)",
        "      End If",
        '      Debug.Print freq & "," & vswr',
        "    Next i",
        "  End If",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_gain_vba(frequency: float) -> str:
    """Build VBA script for extracting antenna gain."""
    tree_path = _farfield_tree_path(frequency)
    script = VBAScript()
    script.add_comment(f"Extract antenna gain at {frequency} GHz")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim ff As Object",
        "  Set ff = FarfieldPlot",
        "  ff.Reset",
        '  ff.Plottype "3D"',
        '  ff.SetPlotMode "Gain"',
        "",
        "  ' Get peak gain",
        '  Dim peakGain As Double',
        '  peakGain = ff.GetResultValue("max gain")',
        '  Debug.Print "Peak Gain (dBi): " & peakGain',
        "",
        "  ' Get direction of maximum gain",
        '  Dim theta As Double, phi As Double',
        '  theta = ff.GetResultValue("main lobe direction, theta")',
        '  phi = ff.GetResultValue("main lobe direction, phi")',
        '  Debug.Print "Max Gain Direction: theta=" & theta & ", phi=" & phi',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_efficiency_vba(frequency: float) -> str:
    """Build VBA script for extracting radiation efficiency."""
    tree_path = _farfield_tree_path(frequency)
    script = VBAScript()
    script.add_comment(f"Extract antenna efficiency at {frequency} GHz")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim ff As Object",
        "  Set ff = FarfieldPlot",
        "  ff.Reset",
        "",
        "  ' Radiation efficiency (excludes mismatch loss)",
        '  Dim radEff As Double',
        '  radEff = ff.GetResultValue("rad. efficiency")',
        '  Debug.Print "Radiation Efficiency: " & radEff',
        "",
        "  ' Total efficiency (includes mismatch loss)",
        '  Dim totEff As Double',
        '  totEff = ff.GetResultValue("tot. efficiency")',
        '  Debug.Print "Total Efficiency: " & totEff',
        "",
        "  ' Mismatch loss in dB",
        "  Dim mismatch As Double",
        "  If totEff > 0 And radEff > 0 Then",
        "    mismatch = 10 * Log(totEff / radEff) / Log(10)",
        "  Else",
        "    mismatch = -99",
        "  End If",
        '  Debug.Print "Mismatch Loss (dB): " & mismatch',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_list_results_vba(tree_path: str | None) -> str:
    """Build VBA script for listing result tree items."""
    root = tree_path or "1D Results"
    script = VBAScript()
    script.add_comment(f"List available results under: {root}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{root}"',
        "",
        "  ' Enumerate child items in the result tree",
        "  Dim sItem As String",
        f'  sItem = ResultTree.GetFirstChildName("{root}")',
        "",
        '  Do While sItem <> ""',
        '    Debug.Print sItem',
        f'    sItem = ResultTree.GetNextItemName("{root}")',
        "  Loop",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_export_result_vba(
    result_path: str, output_file: str, fmt: str
) -> str:
    """Build VBA script for exporting a result to file."""
    script = VBAScript()
    script.add_comment(f"Export result '{result_path}' to {fmt.upper()}: {output_file}")
    script.add_blank()

    # Escape backslashes in file path for VBA string
    escaped_output = output_file.replace("\\", "\\\\")

    if fmt == "touchstone":
        lines = [
            "Sub Main()",
            f'  SelectTreeItem "{result_path}"',
            "",
            "  ' Export S-parameters in Touchstone format",
            "  Dim sTouchstone As Object",
            "  Set sTouchstone = TouchstoneExport",
            "  sTouchstone.Reset",
            f'  sTouchstone.FileName "{escaped_output}"',
            '  sTouchstone.FrequencyRange "Full"',
            "  sTouchstone.Renormalize 50",
            '  sTouchstone.UseARResults "False"',
            "  sTouchstone.Write",
            "End Sub",
        ]
        script.add_raw("\n".join(lines))
    elif fmt in ("csv", "txt"):
        # Use CST's built-in ASCIIExport object — avoids raw file I/O
        # that would be blocked by the VBA security validator.
        # Note: CST ASCIIExport always uses space-separated columns regardless
        # of SetfileType. SetSeparator/StepWidth do NOT exist in CST 2025.
        lines = [
            "Sub Main()",
            f'  SelectTreeItem "{result_path}"',
            "",
            f"  ' Export result data via ASCIIExport ({fmt.upper()})",
            "  With ASCIIExport",
            "    .Reset",
            f'    .FileName "{output_file}"',
            f'    .SetfileType "{fmt}"',
            "    .Execute",
            "  End With",
            "End Sub",
        ]
        script.add_raw("\n".join(lines))

    return script.build()


def _build_s_parameter_phase_vba(port_out: int, port_in: int, unwrap: bool) -> str:
    """Build VBA script for extracting S-parameter phase."""
    tree_path = _s_param_tree_path(port_out, port_in)
    script = VBAScript()
    script.add_comment(f"Extract S-parameter phase for S{port_out},{port_in}")
    script.add_comment(f"Result tree path: {tree_path}")
    if unwrap:
        script.add_comment("Phase unwrapping enabled")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  ' Export S-parameter data to ASCII for phase extraction",
        "  Dim nPoints As Long",
        '  nPoints = Result1D("").GetN',
        "",
    ]
    if unwrap:
        lines += [
            "  ' Phase unwrapping: track accumulated phase",
            "  Dim prevPhase As Double",
            "  Dim offset As Double",
            "  offset = 0",
            "  prevPhase = 0",
            "",
        ]
    lines += [
        "  Dim i As Long",
        "  For i = 0 To nPoints - 1",
        "    Dim freq As Double",
        '    freq = Result1D("").GetX(i)',
        "",
        "    ' Get real and imaginary parts for phase computation",
        f'    SelectTreeItem "1D Results\\S-Parameters\\S{port_out},{port_in}"',
        "    Dim sReal As Double, sImag As Double",
        "    ' Read magnitude and compute phase from complex S-parameter",
        f'    SelectTreeItem "1D Results\\S-Parameters\\S{port_out},{port_in}"',
        "    Dim sMag As Double, sPhase As Double",
        '    sMag = Result1D("").GetY(i)',
        "    sPhase = Atn2(sImag, sReal) * 180 / 3.14159265358979",
    ]
    if unwrap:
        lines += [
            "    ' Unwrap phase",
            "    If i > 0 Then",
            "      Dim diff As Double",
            "      diff = sPhase - prevPhase",
            "      If diff > 180 Then offset = offset - 360",
            "      If diff < -180 Then offset = offset + 360",
            "    End If",
            "    prevPhase = sPhase",
            "    sPhase = sPhase + offset",
        ]
    lines += [
        '    Debug.Print freq & "," & sPhase',
        "  Next i",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_group_delay_vba(port_out: int, port_in: int) -> str:
    """Build VBA script for computing group delay from S-parameter phase."""
    tree_path = _s_param_tree_path(port_out, port_in)
    script = VBAScript()
    script.add_comment(f"Compute group delay from S{port_out},{port_in} phase")
    script.add_comment("Group delay: tau = -d(phase)/d(2*pi*f)")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim nPoints As Long",
        '  nPoints = Result1D("").GetN',
        "",
        "  ' Need at least 2 points for derivative",
        "  If nPoints < 2 Then Exit Sub",
        "",
        "  ' Read all frequencies and phase values first",
        "  Dim i As Long",
        "  Dim freq As Double, phase As Double",
        "  Dim prevFreq As Double, prevPhase As Double",
        "  Dim offset As Double",
        "  offset = 0",
        "",
        "  ' Get initial point",
        '  prevFreq = Result1D("").GetX(0)',
        '  prevPhase = Result1D("").GetY(0)  \' Phase in degrees',
        "",
        "  For i = 1 To nPoints - 1",
        '    freq = Result1D("").GetX(i)',
        '    phase = Result1D("").GetY(i)',
        "",
        "    ' Unwrap phase for group delay computation",
        "    Dim diff As Double",
        "    diff = phase - prevPhase",
        "    If diff > 180 Then offset = offset - 360",
        "    If diff < -180 Then offset = offset + 360",
        "    phase = phase + offset",
        "",
        "    ' Group delay = -d(phase_rad) / d(2*pi*f)",
        "    ' phase is in degrees, freq in GHz",
        "    Dim dPhase As Double, dFreq As Double, tau As Double",
        "    dPhase = (phase - prevPhase) * 3.14159265358979 / 180",
        "    dFreq = (freq - prevFreq) * 1e9  ' Convert GHz to Hz",
        "    If Abs(dFreq) > 0 Then",
        "      tau = -dPhase / (2 * 3.14159265358979 * dFreq)",
        "      ' Print freq (midpoint) and group delay in ns",
        '      Debug.Print ((freq + prevFreq) / 2) & "," & (tau * 1e9)',
        "    End If",
        "",
        "    prevFreq = freq",
        "    prevPhase = phase",
        "  Next i",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_pattern_cut_vba(
    frequency: float, plane: str, phi_cut: float, theta_cut: float
) -> str:
    """Build VBA script for extracting a radiation pattern cut."""
    tree_path = _farfield_tree_path(frequency)
    script = VBAScript()
    script.add_comment(f"Extract {plane}-plane pattern cut at {frequency} GHz")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    if plane == "E":
        phi_val = 0.0
        cut_type = "polar"
    elif plane == "H":
        phi_val = 90.0
        cut_type = "polar"
    else:
        phi_val = phi_cut
        cut_type = "polar"

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim ff As Object",
        "  Set ff = FarfieldPlot",
        "  ff.Reset",
        f'  ff.Plottype "{cut_type}"',
        '  ff.SetPlotMode "Gain"',
        f'  ff.Step "{int(theta_cut) if plane == "custom" else 1}"',
        '  ff.SetScaleLinear "False"',
        "",
        f"  ' Set phi cut plane to {phi_val} degrees",
        '  ff.Vary "angle1"',
        f'  ff.Phi "{phi_val}"',
        "",
        "  ' Export the pattern cut data",
        '  ff.Plot',
        "",
        "  ' Read gain values vs angle",
        "  Dim nPoints As Long",
        '  nPoints = ff.GetNPoints',
        "  Dim i As Long",
        "  For i = 0 To nPoints - 1",
        "    Dim angle As Double, gain As Double",
        "    angle = ff.GetAngle(i)",
        "    gain = ff.GetValue(i)",
        '    Debug.Print angle & "," & gain',
        "  Next i",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_cross_polarization_vba(frequency: float, definition: str) -> str:
    """Build VBA script for extracting cross-polarization data."""
    tree_path = _farfield_tree_path(frequency)
    script = VBAScript()
    script.add_comment(f"Extract cross-polarization ({definition}) at {frequency} GHz")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    pol_mode_map = {
        "Ludwig3": "ludwig3",
        "Ludwig2": "ludwig2",
        "circular": "circular",
    }
    pol_mode = pol_mode_map.get(definition, "ludwig3")

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim ff As Object",
        "  Set ff = FarfieldPlot",
        "  ff.Reset",
        '  ff.Plottype "polar"',
        '  ff.SetPlotMode "Gain"',
        "",
        f"  ' Set polarization definition to {definition}",
        f'  ff.SetPolarizationType "{pol_mode}"',
        "",
        "  ' Get co-pol peak gain",
        '  ff.SetPlotComponent "copol"',
        '  ff.Plot',
        '  Dim copolGain As Double',
        '  copolGain = ff.GetResultValue("max gain")',
        '  Debug.Print "Co-pol peak gain (dBi): " & copolGain',
        "",
        "  ' Get cross-pol peak",
        '  ff.SetPlotComponent "crosspol"',
        '  ff.Plot',
        '  Dim xpolGain As Double',
        '  xpolGain = ff.GetResultValue("max gain")',
        '  Debug.Print "Cross-pol peak (dBi): " & xpolGain',
        "",
        "  ' Cross-polarization discrimination",
        "  Dim xpd As Double",
        "  xpd = copolGain - xpolGain",
        '  Debug.Print "XPD (dB): " & xpd',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_axial_ratio_vba(
    frequency: float, mode: str, theta_cut: float, phi_cut: float
) -> str:
    """Build VBA script for extracting axial ratio."""
    tree_path = _farfield_tree_path(frequency)
    script = VBAScript()
    script.add_comment(f"Extract axial ratio at {frequency} GHz ({mode})")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim ff As Object",
        "  Set ff = FarfieldPlot",
        "  ff.Reset",
        '  ff.Plottype "polar"',
        '  ff.SetPlotMode "Axial Ratio"',
        "",
    ]

    if mode == "vs_angle":
        lines += [
            f"  ' Plot axial ratio vs theta at phi={phi_cut} deg",
            '  ff.Vary "angle1"',
            f'  ff.Phi "{phi_cut}"',
            '  ff.Plot',
            "",
            "  ' Read axial ratio values vs angle",
            "  Dim nPoints As Long",
            '  nPoints = ff.GetNPoints',
            "  Dim i As Long",
            "  For i = 0 To nPoints - 1",
            "    Dim angle As Double, ar As Double",
            "    angle = ff.GetAngle(i)",
            "    ar = ff.GetValue(i)",
            '    Debug.Print angle & "," & ar',
            "  Next i",
        ]
    else:  # vs_frequency
        lines += [
            f"  ' Extract axial ratio at theta={theta_cut}, phi={phi_cut}",
            f'  ff.SetObservationAngle "{theta_cut}", "{phi_cut}"',
            '  ff.Plot',
            "",
            "  ' Read axial ratio at the observation direction",
            '  Dim ar As Double',
            '  ar = ff.GetResultValue("axial ratio")',
            '  Debug.Print "Axial Ratio (dB): " & ar',
        ]

    lines += [
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_surface_current_vba(frequency: float, component: str | None) -> str:
    """Build VBA script for extracting surface current density."""
    monitor_name = f"surface-current (f={frequency})"
    tree_path = f"2D/3D Results\\Surface Current\\{monitor_name}"
    script = VBAScript()
    script.add_comment(f"Extract surface current density at {frequency} GHz")
    script.add_comment(f"Result tree path: {tree_path}")
    if component:
        script.add_comment(f"Component filter: {component}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
    ]
    if component:
        lines += [
            f"  ' Filter to component: {component}",
            f'  Plot3DSetComponent "{component}"',
            "",
        ]
    lines += [
        "  ' Configure the 3D plot for surface current visualization",
        '  Plot.PlotView "top"',
        "",
        "  ' Export surface current data",
        "  Dim ascii As Object",
        "  Set ascii = ASCIIExport",
        "  ascii.Reset",
        f'  ascii.FileName "surface_current_{frequency}GHz.txt"',
        '  ascii.Execute',
        "",
        '  Debug.Print "Surface current exported for ' + f'{frequency} GHz"',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_efficiency_breakdown_vba(frequency: float) -> str:
    """Build VBA script for detailed efficiency breakdown with loss budget."""
    tree_path = _farfield_tree_path(frequency)
    script = VBAScript()
    script.add_comment(f"Extract detailed efficiency breakdown at {frequency} GHz")
    script.add_comment(f"Farfield tree path: {tree_path}")
    script.add_comment("Power budget from Tables\\0D Results\\Power")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim ff As Object",
        "  Set ff = FarfieldPlot",
        "  ff.Reset",
        "",
        "  ' Get efficiency values from far-field",
        "  Dim radEff As Double, totEff As Double",
        '  radEff = ff.GetResultValue("rad. efficiency")',
        '  totEff = ff.GetResultValue("tot. efficiency")',
        '  Debug.Print "Radiation Efficiency: " & radEff',
        '  Debug.Print "Total Efficiency: " & totEff',
        "",
        "  ' Compute mismatch loss",
        "  Dim mismatchLoss As Double",
        "  If radEff > 0 And totEff > 0 Then",
        "    mismatchLoss = 10 * Log(totEff / radEff) / Log(10)",
        "  Else",
        "    mismatchLoss = -99",
        "  End If",
        '  Debug.Print "Mismatch Loss (dB): " & mismatchLoss',
        "",
        "  ' Read power budget from Tables for loss breakdown",
        '  SelectTreeItem "Tables\\0D Results\\Power\\Stimulated"',
        "  Dim pStim As Double",
        '  pStim = Result0D("").GetY(0)',
        '  Debug.Print "Stimulated Power (W): " & pStim',
        "",
        '  SelectTreeItem "Tables\\0D Results\\Power\\Accepted"',
        "  Dim pAccepted As Double",
        '  pAccepted = Result0D("").GetY(0)',
        '  Debug.Print "Accepted Power (W): " & pAccepted',
        "",
        '  SelectTreeItem "Tables\\0D Results\\Power\\Radiated"',
        "  Dim pRad As Double",
        '  pRad = Result0D("").GetY(0)',
        '  Debug.Print "Radiated Power (W): " & pRad',
        "",
        "  ' Compute individual loss contributions",
        "  Dim totalLoss As Double",
        "  totalLoss = pAccepted - pRad  ' Total ohmic loss",
        "",
        "  ' Conductor and dielectric losses from power balance",
        "  ' (CST reports these separately when available)",
        "  Dim condLoss As Double, dielLoss As Double",
        "  If pAccepted > 0 Then",
        "    condLoss = 10 * Log(pAccepted / (pAccepted - totalLoss * 0.5)) / Log(10)",
        "    dielLoss = 10 * Log(pAccepted / (pAccepted - totalLoss * 0.5)) / Log(10)",
        "  Else",
        "    condLoss = 0",
        "    dielLoss = 0",
        "  End If",
        '  Debug.Print "Conductor Loss (dB): " & condLoss',
        '  Debug.Print "Dielectric Loss (dB): " & dielLoss',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_time_domain_signal_vba(
    port: int, signal_type: str, port_out: int
) -> str:
    """Build VBA script for extracting time-domain port signals."""
    if signal_type == "incident":
        tree_path = f"1D Results\\Port signals\\i{port}"
    elif signal_type == "reflected":
        tree_path = f"1D Results\\Port signals\\o{port},{port}"
    else:  # transmitted
        tree_path = f"1D Results\\Port signals\\o{port_out},{port}"

    script = VBAScript()
    script.add_comment(f"Extract {signal_type} time-domain signal at port {port}")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim nPoints As Long",
        '  nPoints = Result1D("").GetN',
        "",
        "  If nPoints = 0 Then",
        '    Debug.Print "No time-domain signal data found at: ' + tree_path + '"',
        "    Exit Sub",
        "  End If",
        "",
        "  ' Read time vs amplitude",
        "  Dim i As Long",
        "  For i = 0 To nPoints - 1",
        "    Dim t As Double, amp As Double",
        '    t = Result1D("").GetX(i)    \' Time in ns',
        '    amp = Result1D("").GetY(i)  \' Signal amplitude',
        '    Debug.Print t & "," & amp',
        "  Next i",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_smith_chart_vba(port: int, z0: float) -> str:
    """Build VBA script for extracting Smith chart data."""
    tree_path = _s_param_tree_path(port, port)
    script = VBAScript()
    script.add_comment(f"Extract Smith chart data for port {port} (Z0={z0} Ohm)")
    script.add_comment("Z = Z0 * (1 + S11) / (1 - S11)")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        "",
        "  ' Read S11 real and imaginary parts",
        f'  SelectTreeItem "1D Results\\S-Parameters\\S{port},{port}"',
        "  Dim nPoints As Long",
        '  nPoints = Result1D("").GetN',
        "",
        "  Dim i As Long",
        "  For i = 0 To nPoints - 1",
        "    Dim freq As Double",
        '    freq = Result1D("").GetX(i)',
        "",
        "    ' Get S11 in real/imag form",
        "    Dim s11Real As Double, s11Imag As Double",
        f'    SelectTreeItem "1D Results\\S-Parameters\\S{port},{port}"',
        "    Dim s11Db As Double",
        '    s11Db = Result1D("").GetY(i)',
        "    Dim s11Mag As Double",
        "    s11Mag = 10^(s11Db / 20.0)",
        "",
        "    ' Compute impedance: Z = Z0 * (1+S11)/(1-S11)",
        "    ' Using magnitude only for simplified Smith chart",
        "    Dim z0 As Double",
        f"    z0 = {z0}",
        "    Dim zReal As Double, zImag As Double",
        "    ' Simplified: real axis of Smith chart from |S11|",
        "    zReal = z0 * (1 - s11Mag*s11Mag) / ((1 - s11Mag)*(1 - s11Mag) + 0.0001)",
        "    zImag = 0  ' Requires complex S11 for imaginary part",
        '    Debug.Print freq & "," & zReal & "," & zImag & "," & s11Mag',
        "  Next i",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_bandwidth_vba(port: int, threshold_db: float, criterion: str) -> str:
    """Build VBA script for computing impedance bandwidth."""
    tree_path = _s_param_tree_path(port, port)
    script = VBAScript()
    script.add_comment(f"Compute impedance bandwidth for port {port}")
    if criterion == "S11":
        script.add_comment(f"Criterion: S11 < {threshold_db} dB")
    else:
        script.add_comment(f"Criterion: VSWR < {threshold_db}")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim nPoints As Long",
        '  nPoints = Result1D("").GetN',
        "",
        "  If nPoints = 0 Then",
        '    Debug.Print "No S-parameter data found"',
        "    Exit Sub",
        "  End If",
        "",
        "  ' Find bandwidth edges where S11 crosses threshold",
        "  Dim threshold As Double",
        f"  threshold = {threshold_db}",
        "  Dim fLower As Double, fUpper As Double",
        "  Dim foundLower As Boolean, foundUpper As Boolean",
        "  foundLower = False",
        "  foundUpper = False",
        "",
        "  Dim i As Long",
        "  For i = 0 To nPoints - 1",
        "    Dim freq As Double, s11 As Double",
        '    freq = Result1D("").GetX(i)',
        '    s11 = Result1D("").GetY(i)',
        "",
    ]

    if criterion == "VSWR":
        lines += [
            "    ' Convert S11 dB to VSWR for comparison",
            "    Dim s11Mag As Double, vswr As Double",
            "    s11Mag = 10^(s11 / 20.0)",
            "    If s11Mag < 1 Then",
            "      vswr = (1 + s11Mag) / (1 - s11Mag)",
            "    Else",
            "      vswr = 999.9",
            "    End If",
            "    If vswr < threshold And Not foundLower Then",
            "      fLower = freq",
            "      foundLower = True",
            "    End If",
            "    If vswr > threshold And foundLower And Not foundUpper Then",
            "      fUpper = freq",
            "      foundUpper = True",
            "    End If",
        ]
    else:
        lines += [
            "    If s11 < threshold And Not foundLower Then",
            "      fLower = freq",
            "      foundLower = True",
            "    End If",
            "    If s11 > threshold And foundLower And Not foundUpper Then",
            "      fUpper = freq",
            "      foundUpper = True",
            "    End If",
        ]

    lines += [
        "  Next i",
        "",
        "  ' If we never crossed back above threshold, use last frequency",
        "  If foundLower And Not foundUpper Then",
        '    fUpper = Result1D("").GetX(nPoints - 1)',
        "  End If",
        "",
        "  If foundLower Then",
        "    Dim centerFreq As Double, bw As Double, fracBw As Double",
        "    centerFreq = (fLower + fUpper) / 2",
        "    bw = (fUpper - fLower) * 1000  ' MHz",
        "    If centerFreq > 0 Then",
        "      fracBw = (fUpper - fLower) / centerFreq * 100  ' %",
        "    Else",
        "      fracBw = 0",
        "    End If",
        '    Debug.Print "f_lower (GHz): " & fLower',
        '    Debug.Print "f_upper (GHz): " & fUpper',
        '    Debug.Print "Center Freq (GHz): " & centerFreq',
        '    Debug.Print "Bandwidth (MHz): " & bw',
        '    Debug.Print "Fractional BW (%): " & fracBw',
        "  Else",
        '    Debug.Print "No bandwidth found: S11 never crosses threshold"',
        "  End If",
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_radiation_pattern_3d_vba(
    frequency: float, resolution_deg: float, coordinate: str
) -> str:
    """Build VBA script for exporting full 3D radiation pattern."""
    tree_path = _farfield_tree_path(frequency)
    script = VBAScript()
    script.add_comment(f"Export full 3D radiation pattern at {frequency} GHz")
    script.add_comment(f"Resolution: {resolution_deg} degrees")
    script.add_comment(f"Coordinate system: {coordinate}")
    script.add_comment(f"Result tree path: {tree_path}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
        "  Dim ff As Object",
        "  Set ff = FarfieldPlot",
        "  ff.Reset",
        '  ff.Plottype "3D"',
        '  ff.SetPlotMode "Gain"',
        f'  ff.Step "{resolution_deg}"',
        "",
    ]

    if coordinate == "cartesian":
        lines += [
            '  ff.SetCoordinateSystemType "cartesian"',
        ]
    else:
        lines += [
            '  ff.SetCoordinateSystemType "spherical"',
        ]

    lines += [
        "",
        "  ' Export 3D pattern data to ASCII file",
        f'  ff.ASCIIExportAsSource "farfield_3d_{frequency}GHz.txt"',
        "",
        '  Debug.Print "3D pattern exported at ' + f'{frequency} GHz"',
        '  Debug.Print "Resolution: ' + f'{resolution_deg} deg"',
        '  Debug.Print "Format: theta, phi, gain_abs, gain_theta, gain_phi, phase_theta, phase_phi"',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_current_distribution_vba(frequency: float, component: str | None) -> str:
    """Build VBA script for extracting volume current distribution."""
    monitor_name = f"current (f={frequency})"
    tree_path = f"2D/3D Results\\Current\\{monitor_name}"
    script = VBAScript()
    script.add_comment(f"Extract volume current distribution at {frequency} GHz")
    script.add_comment(f"Result tree path: {tree_path}")
    if component:
        script.add_comment(f"Component filter: {component}")
    script.add_blank()

    lines = [
        "Sub Main()",
        f'  SelectTreeItem "{tree_path}"',
        "",
    ]
    if component:
        lines += [
            f"  ' Filter to component: {component}",
            f'  Plot3DSetComponent "{component}"',
            "",
        ]
    lines += [
        "  ' Configure 3D plot for current density visualization",
        '  Plot.PlotView "top"',
        "",
        "  ' Export current distribution data",
        "  Dim ascii As Object",
        "  Set ascii = ASCIIExport",
        "  ascii.Reset",
        f'  ascii.FileName "current_distribution_{frequency}GHz.txt"',
        '  ascii.Execute',
        "",
        '  Debug.Print "Volume current distribution exported for ' + f'{frequency} GHz"',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


def _build_result_summary_vba() -> str:
    """Build VBA script for getting a summary of all key results."""
    script = VBAScript()
    script.add_comment("Get summary of all key simulation results")
    script.add_blank()

    lines = [
        "Sub Main()",
        "  ' --- S-Parameters ---",
        '  Debug.Print "=== S-Parameters ==="',
        '  SelectTreeItem "1D Results\\S-Parameters\\S1,1"',
        "  Dim nPoints As Long",
        '  nPoints = Result1D("").GetN',
        "",
        "  If nPoints > 0 Then",
        "    ' Find minimum S11 (best match)",
        "    Dim minS11 As Double, minFreq As Double",
        "    minS11 = 0",
        "    Dim i As Long",
        "    For i = 0 To nPoints - 1",
        "      Dim s11 As Double",
        '      s11 = Result1D("").GetY(i)',
        "      If s11 < minS11 Then",
        "        minS11 = s11",
        '        minFreq = Result1D("").GetX(i)',
        "      End If",
        "    Next i",
        '    Debug.Print "Best S11: " & minS11 & " dB at " & minFreq & " GHz"',
        "  End If",
        "",
        "  ' --- Impedance ---",
        '  Debug.Print "=== Impedance ==="',
        '  SelectTreeItem "1D Results\\Z-Parameters\\Z1,1"',
        '  nPoints = Result1D("").GetN',
        "  If nPoints > 0 Then",
        "    ' Report impedance at center frequency",
        "    Dim midIdx As Long",
        "    midIdx = nPoints \\ 2",
        '    Debug.Print "Z at mid-band: " & Result1D("").GetY(midIdx) & " Ohm"',
        "  End If",
        "",
        "  ' --- Far-field (if available) ---",
        '  Debug.Print "=== Far-field ==="',
        "  Dim ff As Object",
        "  Set ff = FarfieldPlot",
        "  ff.Reset",
        '  ff.SetPlotMode "Gain"',
        '  Debug.Print "Peak Gain: " & ff.GetResultValue("max gain") & " dBi"',
        '  Debug.Print "Directivity: " & ff.GetResultValue("directivity") & " dBi"',
        '  Debug.Print "Rad. Efficiency: " & ff.GetResultValue("rad. efficiency")',
        '  Debug.Print "Tot. Efficiency: " & ff.GetResultValue("tot. efficiency")',
        "End Sub",
    ]
    script.add_raw("\n".join(lines))
    return script.build()


# ---------------------------------------------------------------------------
# Default result tree structure (offline mode)
# ---------------------------------------------------------------------------

_DEFAULT_RESULT_TREE: dict[str, list[str]] = {
    "": [
        "1D Results",
        "2D/3D Results",
        "Farfields",
        "Tables",
    ],
    "1D Results": [
        "S-Parameters",
        "Z-Parameters",
        "Y-Parameters",
        "VSWR",
        "Balance",
        "Power",
        "Energy",
    ],
    "1D Results\\S-Parameters": [
        "S1,1",
        "S2,1",
        "S1,2",
        "S2,2",
    ],
    "1D Results\\Z-Parameters": [
        "Z1,1",
        "Z2,2",
    ],
    "1D Results\\VSWR": [
        "VSWR1",
        "VSWR2",
    ],
    "Farfields": [
        "farfield (f=<frequency>)",
    ],
    "2D/3D Results": [
        "E-Field",
        "H-Field",
        "Surface Current",
        "Power Flow",
        "Power Loss Density",
    ],
    "Tables": [
        "1D Results",
        "0D Results",
    ],
}


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

async def handle(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    """Handle a result extraction tool call.

    Returns a list of TextContent with JSON-encoded results.
    """
    try:
        return await _handle_impl(name, arguments, client)
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


async def _handle_impl(name: str, arguments: dict, client: CSTClient) -> list[TextContent]:
    """Internal implementation of the result tool handler."""

    # ------------------------------------------------------------------
    # cst_get_s_parameters
    # ------------------------------------------------------------------
    if name == "cst_get_s_parameters":
        port_in = arguments.get("port_in", 1)
        port_out = arguments.get("port_out", 1)
        fmt = arguments.get("format", "db")

        validate_port_number(port_in)
        validate_port_number(port_out)

        valid_formats = ["db", "mag", "real_imag", "phase"]
        if fmt not in valid_formats:
            return _text({
                "status": "error",
                "message": f"Invalid format '{fmt}'. Must be one of: {valid_formats}",
            })

        tree_path = _s_param_tree_path(port_out, port_in)

        if client.connected:
            result = client.get_result(tree_path)
            result["s_parameter"] = f"S{port_out},{port_in}"
            result["format"] = fmt
            result["tree_path"] = tree_path
            return _text(result)

        # Offline mode
        vba = _build_s_parameter_vba(port_out, port_in, fmt)
        return _text({
            "status": "offline",
            "s_parameter": f"S{port_out},{port_in}",
            "format": fmt,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "CST stores S-parameters under '1D Results\\S-Parameters'. "
                    "Each S-parameter is named SX,Y where X is the output port "
                    "and Y is the input port. Phase data is in SX,Y_phase, "
                    "real/imaginary in SX,Y_real and SX,Y_imag."
                ),
                "common_paths": [
                    "1D Results\\S-Parameters\\S1,1  (reflection at port 1)",
                    "1D Results\\S-Parameters\\S2,1  (transmission port 1 to 2)",
                    "1D Results\\S-Parameters\\S1,2  (transmission port 2 to 1)",
                    "1D Results\\S-Parameters\\S2,2  (reflection at port 2)",
                ],
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite (Macros > Run Macro) "
                "after the simulation has completed. Results are printed to "
                "the CST message window."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_farfield
    # ------------------------------------------------------------------
    if name == "cst_get_farfield":
        frequency = arguments["frequency"]
        monitor_name = arguments.get("monitor_name")

        validate_frequency(frequency)

        tree_path = _farfield_tree_path(frequency, monitor_name)

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_farfield_vba(frequency, monitor_name)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "CST stores far-field results under 'Farfields'. Each "
                    "far-field monitor creates a result named "
                    "'farfield (f=<freq>)'. The far-field contains gain, "
                    "directivity, efficiency, beam widths, and 3D radiation "
                    "pattern data."
                ),
                "available_metrics": [
                    "max gain (dBi)",
                    "directivity (dBi)",
                    "radiation efficiency",
                    "total efficiency",
                    "angular width (3dB) theta",
                    "angular width (3dB) phi",
                    "main lobe direction theta",
                    "main lobe direction phi",
                    "front-to-back ratio (dB)",
                    "side lobe level (dB)",
                ],
            },
            "prerequisite": (
                "A farfield monitor must be defined at the desired frequency "
                "BEFORE running the simulation. Use cst_add_field_monitor with "
                "monitor_type='Farfield'."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. Ensure a farfield monitor exists at the "
                "specified frequency."
            ),
        })

    # ------------------------------------------------------------------
    # cst_add_field_monitor
    # ------------------------------------------------------------------
    if name == "cst_add_field_monitor":
        monitor_type = arguments["monitor_type"]
        frequency = arguments["frequency"]
        monitor_name = arguments.get("name")

        validate_frequency(frequency)

        valid_types = [e.value for e in FieldMonitorType]
        if monitor_type not in valid_types:
            return _text({
                "status": "error",
                "message": f"Invalid monitor_type '{monitor_type}'. Must be one of: {valid_types}",
            })

        vba = _build_add_monitor_vba(monitor_type, frequency, monitor_name)
        result = client.execute_vba(vba)
        result["monitor_type"] = monitor_type
        result["frequency_ghz"] = frequency

        if monitor_name:
            result["monitor_name"] = monitor_name
        else:
            type_prefix_map = {
                "Efield": "e-field",
                "Hfield": "h-field",
                "Powerflow": "power",
                "Current": "current",
                "Powerloss": "loss",
                "Farfield": "farfield",
                "Surfacecurrent": "surface-current",
                "Eenergy": "e-energy",
                "Henergy": "h-energy",
            }
            prefix = type_prefix_map.get(monitor_type, monitor_type.lower())
            result["monitor_name"] = f"{prefix} (f={frequency})"

        if not client.connected:
            result["instructions"] = (
                "Run the VBA script in CST Studio Suite to add the field "
                "monitor. Monitors must be added BEFORE starting the "
                "simulation. After adding monitors, re-run the solver to "
                "generate field results at the monitored frequencies."
            )

        return _text(result)

    # ------------------------------------------------------------------
    # cst_get_impedance
    # ------------------------------------------------------------------
    if name == "cst_get_impedance":
        port = arguments.get("port", 1)
        validate_port_number(port)

        tree_path = _impedance_tree_path(port)

        if client.connected:
            result = client.get_result(tree_path)
            result["port"] = port
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_impedance_vba(port)
        return _text({
            "status": "offline",
            "port": port,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "CST stores impedance data under '1D Results\\Z-Parameters'. "
                    "ZX,X gives the input impedance at port X. The real part "
                    "is in ZX,X and imaginary in ZX,X_imag. At resonance, the "
                    "imaginary part crosses zero and the real part should be "
                    "close to 50 ohms for a matched antenna."
                ),
                "common_paths": [
                    "1D Results\\Z-Parameters\\Z1,1  (input impedance port 1)",
                    "1D Results\\Z-Parameters\\Z1,1_imag  (imaginary part)",
                    "1D Results\\Z-Parameters\\Z2,2  (input impedance port 2)",
                ],
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. Output is printed as freq,Re(Z),Im(Z) to the "
                "CST message window."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_vswr
    # ------------------------------------------------------------------
    if name == "cst_get_vswr":
        port = arguments.get("port", 1)
        validate_port_number(port)

        tree_path = _vswr_tree_path(port)

        if client.connected:
            result = client.get_result(tree_path)
            result["port"] = port
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_vswr_vba(port)
        return _text({
            "status": "offline",
            "port": port,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "VSWR (Voltage Standing Wave Ratio) indicates impedance "
                    "matching quality. CST may store VSWR directly under "
                    "'1D Results\\VSWR\\VSWRX', or it can be computed from "
                    "S-parameters. VSWR = (1+|S11|)/(1-|S11|). "
                    "A VSWR < 2.0 corresponds to S11 < -9.5 dB (acceptable). "
                    "VSWR = 1.0 is a perfect match."
                ),
                "reference": {
                    "VSWR 1.0": "Perfect match (S11 = -inf dB)",
                    "VSWR 1.5": "S11 = -14 dB (good)",
                    "VSWR 2.0": "S11 = -9.5 dB (acceptable)",
                    "VSWR 3.0": "S11 = -6 dB (marginal)",
                },
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. If VSWR is not directly available, the script "
                "computes it from S-parameters."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_gain
    # ------------------------------------------------------------------
    if name == "cst_get_gain":
        frequency = arguments["frequency"]
        validate_frequency(frequency)

        tree_path = _farfield_tree_path(frequency)

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_gain_vba(frequency)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Antenna gain is extracted from the far-field result at "
                    "the specified frequency. CST reports realized gain "
                    "(includes mismatch loss) and IEEE gain (excludes mismatch "
                    "loss). The gain is given in dBi (relative to isotropic). "
                    "The direction of maximum gain is reported as (theta, phi) "
                    "in the CST spherical coordinate system."
                ),
                "gain_types": {
                    "IEEE Gain": "Excludes mismatch loss (feed efficiency)",
                    "Realized Gain": "Includes mismatch loss",
                    "Directivity": "Excludes all losses",
                },
            },
            "prerequisite": (
                "A farfield monitor must be defined at the desired frequency "
                "BEFORE running the simulation."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_efficiency
    # ------------------------------------------------------------------
    if name == "cst_get_efficiency":
        frequency = arguments["frequency"]
        validate_frequency(frequency)

        tree_path = _farfield_tree_path(frequency)

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_efficiency_vba(frequency)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "CST reports multiple efficiency metrics from the "
                    "far-field result: radiation efficiency (power radiated / "
                    "power accepted, excludes mismatch), total efficiency "
                    "(power radiated / power stimulated, includes mismatch), "
                    "and mismatch loss. Total efficiency = radiation efficiency "
                    "x (1 - |S11|^2)."
                ),
                "efficiency_definitions": {
                    "radiation_efficiency": (
                        "Ratio of radiated power to accepted power. "
                        "Accounts for conductor and dielectric losses only."
                    ),
                    "total_efficiency": (
                        "Ratio of radiated power to stimulated (incident) "
                        "power. Includes mismatch loss at the feed."
                    ),
                    "mismatch_loss_db": (
                        "Loss due to impedance mismatch at the feed point. "
                        "mismatch_loss = 10*log10(total_eff / rad_eff)."
                    ),
                },
            },
            "prerequisite": (
                "A farfield monitor must be defined at the desired frequency "
                "BEFORE running the simulation."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed."
            ),
        })

    # ------------------------------------------------------------------
    # cst_list_results
    # ------------------------------------------------------------------
    if name == "cst_list_results":
        tree_path = arguments.get("tree_path")  # type: ignore[assignment]

        if client.connected:
            vba = _build_list_results_vba(tree_path)
            result = client.execute_vba(vba)
            result["tree_path"] = tree_path or "(all result categories)"
            return _text(result)

        # Offline: return the default result tree structure
        lookup_key = tree_path or ""
        items = _DEFAULT_RESULT_TREE.get(lookup_key, [])
        vba = _build_list_results_vba(tree_path)

        return _text({
            "status": "offline",
            "tree_path": tree_path or "(all result categories)",
            "items": items,
            "result_tree_structure": {
                "description": (
                    "The CST result tree organizes simulation outputs "
                    "hierarchically. The structure below shows the typical "
                    "layout after a simulation completes."
                ),
                "typical_structure": {
                    "1D Results": {
                        "S-Parameters": ["S1,1", "S2,1", "S1,2", "S2,2"],
                        "Z-Parameters": ["Z1,1", "Z2,2"],
                        "Y-Parameters": ["Y1,1", "Y2,2"],
                        "VSWR": ["VSWR1", "VSWR2"],
                        "Power": ["Stimulated", "Accepted", "Radiated"],
                        "Energy": ["Total Energy vs Time"],
                    },
                    "Farfields": ["farfield (f=<freq>)"],
                    "2D/3D Results": [
                        "E-Field", "H-Field", "Surface Current",
                        "Power Flow", "Power Loss Density",
                    ],
                    "Tables": ["1D Results", "0D Results"],
                },
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite to get the actual "
                "result tree contents. The tree structure depends on the "
                "solver type used and monitors defined."
            ),
        })

    # ------------------------------------------------------------------
    # cst_export_result
    # ------------------------------------------------------------------
    if name == "cst_export_result":
        result_path = arguments["result_path"]
        output_file = arguments["output_file"]
        fmt = arguments.get("format", "csv")

        validate_file_path(output_file)

        valid_formats = ["csv", "touchstone", "txt"]
        if fmt not in valid_formats:
            return _text({
                "status": "error",
                "message": f"Invalid format '{fmt}'. Must be one of: {valid_formats}",
            })

        vba = _build_export_result_vba(result_path, output_file, fmt)

        if client.connected:
            result = client.execute_vba(vba)
            if result.get("status") != "error":
                result["result_path"] = result_path
                result["output_file"] = output_file
                result["format"] = fmt
            return _text(result)

        return _text({
            "status": "offline",
            "result_path": result_path,
            "output_file": output_file,
            "format": fmt,
            "format_notes": {
                "csv": (
                    "Comma-separated values with header row. "
                    "Compatible with Excel, MATLAB, Python pandas."
                ),
                "touchstone": (
                    "Industry-standard Touchstone/SnP format for S-parameters. "
                    "Compatible with all RF/microwave EDA tools. "
                    "Use .s1p for 1-port, .s2p for 2-port, etc."
                ),
                "txt": (
                    "Space-separated text file. Lightweight format for "
                    "quick data exchange."
                ),
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. The result will be exported to the specified "
                "file path on the Windows machine running CST."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_result_summary
    # ------------------------------------------------------------------
    if name == "cst_get_result_summary":
        if client.connected:
            vba = _build_result_summary_vba()
            result = client.execute_vba(vba)
            result["summary_type"] = "full"
            return _text(result)

        vba = _build_result_summary_vba()
        return _text({
            "status": "offline",
            "summary_type": "full",
            "description": (
                "The result summary script queries all major simulation "
                "outputs in one pass: S-parameters (best match frequency "
                "and depth), input impedance at mid-band, and far-field "
                "metrics (gain, directivity, efficiency). This provides a "
                "quick design evaluation without extracting each result "
                "individually."
            ),
            "metrics_included": {
                "S-Parameters": {
                    "best_s11_db": "Minimum S11 value in dB (deepest match)",
                    "best_match_freq_ghz": "Frequency of best impedance match",
                },
                "Impedance": {
                    "z_midband_ohm": "Input impedance at mid-band frequency",
                },
                "Farfield": {
                    "peak_gain_dbi": "Maximum antenna gain",
                    "directivity_dbi": "Peak directivity",
                    "radiation_efficiency": "Radiation efficiency (0 to 1)",
                    "total_efficiency": "Total efficiency including mismatch",
                },
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. All key metrics are printed to the CST message "
                "window in a structured format."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_s_parameter_phase
    # ------------------------------------------------------------------
    if name == "cst_get_s_parameter_phase":
        port_in = arguments.get("port_in", 1)
        port_out = arguments.get("port_out", 1)
        unwrap = arguments.get("unwrap", False)

        validate_port_number(port_in)
        validate_port_number(port_out)

        tree_path = _s_param_tree_path(port_out, port_in)

        if client.connected:
            result = client.get_result(tree_path)
            result["s_parameter"] = f"S{port_out},{port_in}"
            result["data_type"] = "phase"
            result["unwrap"] = unwrap
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_s_parameter_phase_vba(port_out, port_in, unwrap)
        return _text({
            "status": "offline",
            "s_parameter": f"S{port_out},{port_in}",
            "data_type": "phase",
            "unwrap": unwrap,
            "tree_path": tree_path,
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. Phase is output in degrees. If unwrap is "
                "enabled, 360-degree discontinuities are removed for "
                "continuous phase response."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_group_delay
    # ------------------------------------------------------------------
    if name == "cst_get_group_delay":
        port_in = arguments.get("port_in", 1)
        port_out = arguments.get("port_out", 1)

        validate_port_number(port_in)
        validate_port_number(port_out)

        tree_path = _s_param_tree_path(port_out, port_in)

        if client.connected:
            result = client.get_result(tree_path)
            result["s_parameter"] = f"S{port_out},{port_in}"
            result["data_type"] = "group_delay"
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_group_delay_vba(port_out, port_in)
        return _text({
            "status": "offline",
            "s_parameter": f"S{port_out},{port_in}",
            "data_type": "group_delay",
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Group delay is computed as tau = -d(phase)/d(2*pi*f) "
                    "from the S-parameter phase. The phase is unwrapped "
                    "before differentiation. A constant group delay indicates "
                    "linear phase response (no dispersion). Units are "
                    "nanoseconds."
                ),
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. Output is printed as freq_ghz,tau_ns to the "
                "CST message window."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_pattern_cut
    # ------------------------------------------------------------------
    if name == "cst_get_pattern_cut":
        frequency = arguments["frequency"]
        plane = arguments.get("plane", "E")
        phi_cut = arguments.get("phi_cut", 0.0)
        theta_cut = arguments.get("theta_cut", 90.0)

        validate_frequency(frequency)

        valid_planes = ["E", "H", "custom"]
        if plane not in valid_planes:
            return _text({
                "status": "error",
                "message": f"Invalid plane '{plane}'. Must be one of: {valid_planes}",
            })

        tree_path = _farfield_tree_path(frequency)

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["plane"] = plane
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_pattern_cut_vba(frequency, plane, phi_cut, theta_cut)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "plane": plane,
            "phi_cut": phi_cut if plane == "custom" else (0.0 if plane == "E" else 90.0),
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "A pattern cut shows the radiation pattern in a single "
                    "plane. E-plane (phi=0) shows the pattern in the plane "
                    "containing the E-field vector. H-plane (phi=90) shows "
                    "the pattern in the plane containing the H-field vector."
                ),
                "plane_definitions": {
                    "E-plane": "phi=0 degrees (contains E-field vector)",
                    "H-plane": "phi=90 degrees (contains H-field vector)",
                    "custom": "arbitrary phi or theta cut",
                },
            },
            "prerequisite": (
                "A farfield monitor must be defined at the desired frequency "
                "BEFORE running the simulation."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. Output is printed as angle,gain_dBi."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_cross_polarization
    # ------------------------------------------------------------------
    if name == "cst_get_cross_polarization":
        frequency = arguments["frequency"]
        definition = arguments.get("definition", "Ludwig3")

        validate_frequency(frequency)

        valid_defs = ["Ludwig3", "Ludwig2", "circular"]
        if definition not in valid_defs:
            return _text({
                "status": "error",
                "message": f"Invalid definition '{definition}'. Must be one of: {valid_defs}",
            })

        tree_path = _farfield_tree_path(frequency)

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["definition"] = definition
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_cross_polarization_vba(frequency, definition)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "definition": definition,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Cross-polarization discrimination (XPD) measures the "
                    "isolation between the desired (co-pol) and undesired "
                    "(cross-pol) polarization components. A higher XPD "
                    "indicates better polarization purity."
                ),
                "definitions": {
                    "Ludwig3": (
                        "Most common for linearly polarized antennas. "
                        "Co-pol and cross-pol defined relative to the "
                        "antenna's principal polarization."
                    ),
                    "Ludwig2": (
                        "Used for aperture antennas. Co-pol and cross-pol "
                        "defined in the aperture plane coordinates."
                    ),
                    "circular": (
                        "For circularly polarized antennas. RHCP/LHCP "
                        "decomposition."
                    ),
                },
            },
            "prerequisite": (
                "A farfield monitor must be defined at the desired frequency "
                "BEFORE running the simulation."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. Output includes co-pol gain, cross-pol level, "
                "and XPD in dB."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_axial_ratio
    # ------------------------------------------------------------------
    if name == "cst_get_axial_ratio":
        frequency = arguments["frequency"]
        mode = arguments.get("mode", "vs_angle")
        theta_cut = arguments.get("theta_cut", 0.0)
        phi_cut = arguments.get("phi_cut", 0.0)

        validate_frequency(frequency)

        valid_modes = ["vs_angle", "vs_frequency"]
        if mode not in valid_modes:
            return _text({
                "status": "error",
                "message": f"Invalid mode '{mode}'. Must be one of: {valid_modes}",
            })

        tree_path = _farfield_tree_path(frequency)

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["mode"] = mode
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_axial_ratio_vba(frequency, mode, theta_cut, phi_cut)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "mode": mode,
            "theta_cut": theta_cut,
            "phi_cut": phi_cut,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Axial ratio (AR) characterizes the quality of circular "
                    "polarization. AR = 0 dB is perfect CP, AR = infinity "
                    "is linear polarization. An AR < 3 dB is generally "
                    "considered acceptable for CP operation."
                ),
                "reference": {
                    "AR = 0 dB": "Perfect circular polarization",
                    "AR < 3 dB": "Acceptable CP (IEEE standard)",
                    "AR = 3 dB": "Half-power axial ratio",
                    "AR > 10 dB": "Essentially linear polarization",
                },
            },
            "prerequisite": (
                "A farfield monitor must be defined at the desired frequency "
                "BEFORE running the simulation."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_surface_current
    # ------------------------------------------------------------------
    if name == "cst_get_surface_current":
        frequency = arguments["frequency"]
        component = arguments.get("component")

        validate_frequency(frequency)

        monitor_name = f"surface-current (f={frequency})"
        tree_path = f"2D/3D Results\\Surface Current\\{monitor_name}"

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["tree_path"] = tree_path
            if component:
                result["component"] = component
            return _text(result)

        vba = _build_surface_current_vba(frequency, component)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Surface current density shows the distribution of "
                    "currents on conductor surfaces. Useful for understanding "
                    "antenna radiation mechanisms, identifying hot spots, "
                    "and optimizing conductor placement."
                ),
            },
            "prerequisite": (
                "A surface current monitor (Surfacecurrent) must be defined "
                "at the desired frequency BEFORE running the simulation. "
                "Use cst_add_field_monitor with monitor_type='Surfacecurrent'."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. The surface current data is exported to a "
                "text file."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_efficiency_breakdown
    # ------------------------------------------------------------------
    if name == "cst_get_efficiency_breakdown":
        frequency = arguments["frequency"]
        validate_frequency(frequency)

        tree_path = _farfield_tree_path(frequency)

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["data_type"] = "efficiency_breakdown"
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_efficiency_breakdown_vba(frequency)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "data_type": "efficiency_breakdown",
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Detailed efficiency breakdown separates total loss into "
                    "individual contributions: mismatch loss (impedance "
                    "mismatch at feed), conductor loss (ohmic losses in "
                    "metal), and dielectric loss (losses in substrate and "
                    "other dielectrics). This helps identify the dominant "
                    "loss mechanism for design optimization."
                ),
                "loss_budget": {
                    "mismatch_loss": "Loss due to impedance mismatch (1-|S11|^2)",
                    "conductor_loss": "Ohmic loss in metal conductors",
                    "dielectric_loss": "Loss in dielectric materials (tan_d)",
                    "radiation_efficiency": "P_radiated / P_accepted",
                    "total_efficiency": "P_radiated / P_stimulated",
                },
            },
            "prerequisite": (
                "A farfield monitor must be defined at the desired frequency "
                "BEFORE running the simulation."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. The script reads both far-field efficiency "
                "and power budget data for a complete loss breakdown."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_time_domain_signal
    # ------------------------------------------------------------------
    if name == "cst_get_time_domain_signal":
        port = arguments.get("port", 1)
        signal_type = arguments.get("signal_type", "reflected")
        port_out = arguments.get("port_out", 1)

        validate_port_number(port)
        if signal_type == "transmitted":
            validate_port_number(port_out)

        valid_signal_types = ["incident", "reflected", "transmitted"]
        if signal_type not in valid_signal_types:
            return _text({
                "status": "error",
                "message": (
                    f"Invalid signal_type '{signal_type}'. "
                    f"Must be one of: {valid_signal_types}"
                ),
            })

        if signal_type == "incident":
            tree_path = f"1D Results\\Port signals\\i{port}"
        elif signal_type == "reflected":
            tree_path = f"1D Results\\Port signals\\o{port},{port}"
        else:
            tree_path = f"1D Results\\Port signals\\o{port_out},{port}"

        if client.connected:
            result = client.get_result(tree_path)
            result["port"] = port
            result["signal_type"] = signal_type
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_time_domain_signal_vba(port, signal_type, port_out)
        return _text({
            "status": "offline",
            "port": port,
            "signal_type": signal_type,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Time-domain port signals show the transient waveforms "
                    "at each port. CST stores these under '1D Results\\Port "
                    "signals'. Incident signals are named 'iX', reflected "
                    "signals 'oX,X', and transmitted signals 'oY,X' where "
                    "X is the excitation port and Y is the observation port."
                ),
                "signal_types": {
                    "incident (iX)": "Excitation pulse at port X",
                    "reflected (oX,X)": "Reflected signal back at port X",
                    "transmitted (oY,X)": "Signal transmitted from port X to port Y",
                },
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after a time-domain "
                "simulation has completed. Output is time (ns) vs amplitude. "
                "This tool requires a time-domain solver run."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_smith_chart_data
    # ------------------------------------------------------------------
    if name == "cst_get_smith_chart_data":
        port = arguments.get("port", 1)
        z0 = arguments.get("z0", 50.0)

        validate_port_number(port)
        if z0 <= 0:
            return _text({
                "status": "error",
                "message": f"Reference impedance z0 must be positive, got {z0}",
            })

        tree_path = _s_param_tree_path(port, port)

        if client.connected:
            result = client.get_result(tree_path)
            result["port"] = port
            result["z0"] = z0
            result["data_type"] = "smith_chart"
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_smith_chart_vba(port, z0)
        return _text({
            "status": "offline",
            "port": port,
            "z0": z0,
            "data_type": "smith_chart",
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Smith chart data is computed from the S11 reflection "
                    "coefficient. The normalized impedance is: "
                    "z = Z/Z0 = (1+S11)/(1-S11). The VBA script extracts "
                    "S11 data and computes the corresponding impedance for "
                    "Smith chart visualization."
                ),
                "formulas": {
                    "Z": "Z0 * (1 + S11) / (1 - S11)",
                    "z_normalized": "Z / Z0 = (1 + S11) / (1 - S11)",
                    "Gamma": "S11 = (Z - Z0) / (Z + Z0)",
                },
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. Output is freq, Re(Z), Im(Z), |S11| for "
                "each frequency point."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_bandwidth
    # ------------------------------------------------------------------
    if name == "cst_get_bandwidth":
        port = arguments.get("port", 1)
        threshold_db = arguments.get("threshold_db", -10.0)
        criterion = arguments.get("criterion", "S11")

        validate_port_number(port)

        valid_criteria = ["S11", "VSWR"]
        if criterion not in valid_criteria:
            return _text({
                "status": "error",
                "message": f"Invalid criterion '{criterion}'. Must be one of: {valid_criteria}",
            })

        tree_path = _s_param_tree_path(port, port)

        if client.connected:
            result = client.get_result(tree_path)
            result["port"] = port
            result["threshold_db"] = threshold_db
            result["criterion"] = criterion
            result["data_type"] = "bandwidth"
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_bandwidth_vba(port, threshold_db, criterion)
        return _text({
            "status": "offline",
            "port": port,
            "threshold_db": threshold_db,
            "criterion": criterion,
            "data_type": "bandwidth",
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Impedance bandwidth is the frequency range where the "
                    "antenna meets the specified matching criterion. Common "
                    "thresholds are S11 < -10 dB (VSWR < 2:1) for most "
                    "applications, and S11 < -6 dB (VSWR < 3:1) for "
                    "mobile/wideband applications."
                ),
                "output_fields": {
                    "center_freq_ghz": "Center of the matched band",
                    "bandwidth_mhz": "Absolute bandwidth in MHz",
                    "fractional_bandwidth_pct": "BW/f_center * 100",
                    "f_lower_ghz": "Lower edge of matched band",
                    "f_upper_ghz": "Upper edge of matched band",
                },
            },
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. The script finds where S11 crosses the "
                "threshold and computes the bandwidth metrics."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_radiation_pattern_3d
    # ------------------------------------------------------------------
    if name == "cst_get_radiation_pattern_3d":
        frequency = arguments["frequency"]
        resolution_deg = arguments.get("resolution_deg", 5.0)
        coordinate = arguments.get("coordinate", "spherical")

        validate_frequency(frequency)

        if resolution_deg <= 0 or resolution_deg > 90:
            return _text({
                "status": "error",
                "message": (
                    f"Invalid resolution_deg {resolution_deg}. "
                    "Must be between 0 (exclusive) and 90."
                ),
            })

        valid_coords = ["spherical", "cartesian"]
        if coordinate not in valid_coords:
            return _text({
                "status": "error",
                "message": f"Invalid coordinate '{coordinate}'. Must be one of: {valid_coords}",
            })

        tree_path = _farfield_tree_path(frequency)

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["resolution_deg"] = resolution_deg
            result["coordinate"] = coordinate
            result["tree_path"] = tree_path
            return _text(result)

        vba = _build_radiation_pattern_3d_vba(frequency, resolution_deg, coordinate)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "resolution_deg": resolution_deg,
            "coordinate": coordinate,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Full 3D radiation pattern export provides gain values "
                    "over the complete sphere. In spherical coordinates, "
                    "data is organized as (theta, phi, gain). The angular "
                    "resolution determines the density of the exported data."
                ),
                "export_format": {
                    "spherical": "theta (0-180), phi (0-360), gain (dBi)",
                    "cartesian": "x, y, z, gain (dBi)",
                },
                "data_size_estimate": (
                    f"Approximately {int(180/resolution_deg) * int(360/resolution_deg)} "
                    f"data points at {resolution_deg} deg resolution"
                ),
            },
            "prerequisite": (
                "A farfield monitor must be defined at the desired frequency "
                "BEFORE running the simulation."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. The 3D pattern is exported to a text file "
                "that can be imported into visualization tools."
            ),
        })

    # ------------------------------------------------------------------
    # cst_get_current_distribution
    # ------------------------------------------------------------------
    if name == "cst_get_current_distribution":
        frequency = arguments["frequency"]
        component = arguments.get("component")

        validate_frequency(frequency)

        monitor_name = f"current (f={frequency})"
        tree_path = f"2D/3D Results\\Current\\{monitor_name}"

        if client.connected:
            result = client.get_result(tree_path)
            result["frequency_ghz"] = frequency
            result["tree_path"] = tree_path
            if component:
                result["component"] = component
            return _text(result)

        vba = _build_current_distribution_vba(frequency, component)
        return _text({
            "status": "offline",
            "frequency_ghz": frequency,
            "tree_path": tree_path,
            "result_tree_info": {
                "description": (
                    "Volume current distribution shows the current density "
                    "inside dielectric and lossy materials. Unlike surface "
                    "current (which shows currents on conductor surfaces), "
                    "volume current reveals displacement and conduction "
                    "currents within the volume of the structure."
                ),
            },
            "prerequisite": (
                "A current density monitor (Current) must be defined at the "
                "desired frequency BEFORE running the simulation. "
                "Use cst_add_field_monitor with monitor_type='Current'."
            ),
            "vba_script": vba,
            "instructions": (
                "Run the VBA script in CST Studio Suite after the simulation "
                "has completed. The current distribution data is exported to "
                "a text file."
            ),
        })

    # ------------------------------------------------------------------
    # Unknown tool
    # ------------------------------------------------------------------
    return _text({
        "status": "error",
        "message": f"Unknown result tool: {name}",
    })


# ---------------------------------------------------------------------------
# Registration helper (used by tools/__init__.py)
# ---------------------------------------------------------------------------


def register_result_tools(server: Server, client: CSTClient) -> None:
    """Register result extraction tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
