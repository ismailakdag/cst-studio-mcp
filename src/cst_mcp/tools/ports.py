"""Port and excitation tools for CST Studio Suite."""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent, Tool

from cst_mcp.cst_client import CSTClient
from cst_mcp.validators import validate_name, validate_port_number, validate_positive, validate_range
from cst_mcp.vba_builder import VBABuilder

_ORIENTATION_ENUM = ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"]
_FLOQUET_ORIENTATION_ENUM = ["zmin", "zmax"]
_DISCRETE_PORT_TYPE_ENUM = ["SParameter", "Voltage", "Current"]
_POLARIZATION_ENUM = ["linear", "circular"]
_ELEMENT_TYPE_ENUM = ["R", "L", "C", "RLC_serial", "RLC_parallel"]

_COORD_PROPERTY = {"type": "number"}

TOOLS: list[Tool] = [
    Tool(
        name="cst_add_waveguide_port",
        description=(
            "Add a waveguide port for S-parameter excitation. Defines a port face on "
            "the boundary of the simulation domain for guided-wave excitation. "
            "IMPORTANT: The port plane should be at or near the edge of the model "
            "geometry. Ground planes and substrates must NOT extend past the port "
            "plane in the port's orientation direction, or VBA execution may hang. "
            "For microstrip feeds: place the port at the end of the feed line where "
            "the ground/substrate terminates. Use Coordinates='Free' for ports not "
            "aligned to the bounding box. Valid orientations: xmin/xmax/ymin/ymax/zmin/zmax."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port_number": {
                    "type": "integer",
                    "description": "Port number (1-999)",
                },
                "orientation": {
                    "type": "string",
                    "enum": _ORIENTATION_ENUM,
                    "description": "Face of the bounding box where the port is placed",
                },
                "x_min": {
                    "type": "number",
                    "description": "X-axis minimum coordinate of the port aperture (mm)",
                },
                "x_max": {
                    "type": "number",
                    "description": "X-axis maximum coordinate of the port aperture (mm)",
                },
                "y_min": {
                    "type": "number",
                    "description": "Y-axis minimum coordinate of the port aperture (mm)",
                },
                "y_max": {
                    "type": "number",
                    "description": "Y-axis maximum coordinate of the port aperture (mm)",
                },
                "z_min": {
                    "type": "number",
                    "description": "Z-axis minimum coordinate of the port aperture (mm)",
                },
                "z_max": {
                    "type": "number",
                    "description": "Z-axis maximum coordinate of the port aperture (mm)",
                },
                "mode_number": {
                    "type": "integer",
                    "description": "Number of modes to consider (default 1)",
                    "default": 1,
                },
                "coordinates": {
                    "type": "string",
                    "enum": ["Free", "Full", "Picks"],
                    "description": (
                        "Coordinate mode. 'Free' allows arbitrary placement using "
                        "the specified ranges (required for microstrip/coplanar ports). "
                        "'Full' maps the port to the full bounding-box face. "
                        "'Picks' uses previously picked geometry faces. Default: 'Free'."
                    ),
                    "default": "Free",
                },
            },
            "required": [
                "port_number",
                "orientation",
                "x_min",
                "x_max",
                "y_min",
                "y_max",
                "z_min",
                "z_max",
            ],
        },
    ),
    Tool(
        name="cst_add_discrete_port",
        description=(
            "Add a discrete (lumped) port between two points. Used for circuit-level "
            "excitation with a defined impedance."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port_number": {
                    "type": "integer",
                    "description": "Port number (1-999)",
                },
                "impedance": {
                    "type": "number",
                    "description": "Port impedance in ohms (default 50)",
                    "default": 50.0,
                },
                "x1": {
                    "type": "number",
                    "description": "X coordinate of the start point (mm)",
                },
                "y1": {
                    "type": "number",
                    "description": "Y coordinate of the start point (mm)",
                },
                "z1": {
                    "type": "number",
                    "description": "Z coordinate of the start point (mm)",
                },
                "x2": {
                    "type": "number",
                    "description": "X coordinate of the end point (mm)",
                },
                "y2": {
                    "type": "number",
                    "description": "Y coordinate of the end point (mm)",
                },
                "z2": {
                    "type": "number",
                    "description": "Z coordinate of the end point (mm)",
                },
                "port_type": {
                    "type": "string",
                    "enum": _DISCRETE_PORT_TYPE_ENUM,
                    "description": "Excitation type (default SParameter)",
                    "default": "SParameter",
                },
            },
            "required": ["port_number", "x1", "y1", "z1", "x2", "y2", "z2"],
        },
    ),
    Tool(
        name="cst_add_lumped_element",
        description=(
            "Add a lumped R, L, C, or RLC element between two points. "
            "Value is in ohms for R, henries for L, farads for C."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name for the lumped element",
                },
                "element_type": {
                    "type": "string",
                    "enum": _ELEMENT_TYPE_ENUM,
                    "description": "Type of lumped element",
                },
                "value": {
                    "type": "number",
                    "description": "Element value (ohms for R, henries for L, farads for C)",
                },
                "x1": {
                    "type": "number",
                    "description": "X coordinate of the first terminal (mm)",
                },
                "y1": {
                    "type": "number",
                    "description": "Y coordinate of the first terminal (mm)",
                },
                "z1": {
                    "type": "number",
                    "description": "Z coordinate of the first terminal (mm)",
                },
                "x2": {
                    "type": "number",
                    "description": "X coordinate of the second terminal (mm)",
                },
                "y2": {
                    "type": "number",
                    "description": "Y coordinate of the second terminal (mm)",
                },
                "z2": {
                    "type": "number",
                    "description": "Z coordinate of the second terminal (mm)",
                },
            },
            "required": [
                "name",
                "element_type",
                "value",
                "x1",
                "y1",
                "z1",
                "x2",
                "y2",
                "z2",
            ],
        },
    ),
    Tool(
        name="cst_add_plane_wave",
        description=(
            "Add a plane wave excitation source. Defines an incident plane wave "
            "with given direction and polarization for scattering / RCS analysis."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "polarization": {
                    "type": "string",
                    "enum": _POLARIZATION_ENUM,
                    "description": "Polarization type",
                },
                "theta": {
                    "type": "number",
                    "description": "Elevation angle of incidence in degrees (0-180)",
                },
                "phi": {
                    "type": "number",
                    "description": "Azimuth angle of incidence in degrees (0-360)",
                },
                "e_theta": {
                    "type": "number",
                    "description": "Theta component of the polarization vector (default 1)",
                    "default": 1.0,
                },
                "e_phi": {
                    "type": "number",
                    "description": "Phi component of the polarization vector (default 0)",
                    "default": 0.0,
                },
            },
            "required": ["polarization", "theta", "phi"],
        },
    ),
    Tool(
        name="cst_add_floquet_port",
        description=(
            "Add a Floquet port for periodic structures such as frequency selective "
            "surfaces, metamaterials, and phased arrays."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port_number": {
                    "type": "integer",
                    "description": "Port number (1-999)",
                },
                "orientation": {
                    "type": "string",
                    "enum": _FLOQUET_ORIENTATION_ENUM,
                    "description": "Orientation of the Floquet port (zmin or zmax)",
                },
                "modes": {
                    "type": "integer",
                    "description": "Number of Floquet modes to include (default 2)",
                    "default": 2,
                },
            },
            "required": ["port_number", "orientation"],
        },
    ),
    Tool(
        name="cst_list_ports",
        description=(
            "List all ports defined in the current CST project. Returns VBA to "
            "query port information, or a description in offline mode."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="cst_delete_port",
        description="Delete a port by its port number.",
        inputSchema={
            "type": "object",
            "properties": {
                "port_number": {
                    "type": "integer",
                    "description": "Port number to delete (1-999)",
                },
            },
            "required": ["port_number"],
        },
    ),
    Tool(
        name="cst_add_multipin_port",
        description=(
            "Add a waveguide port with multiple mode monitoring for higher-order mode "
            "analysis. Used for multimode waveguides, mode converters, and structures "
            "where higher-order propagating modes need to be captured."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port_number": {
                    "type": "integer",
                    "description": "Port number (1-999)",
                },
                "orientation": {
                    "type": "string",
                    "enum": _ORIENTATION_ENUM,
                    "description": "Face of the bounding box where the port is placed",
                },
                "x_min": {
                    "type": "number",
                    "description": "X-axis minimum coordinate of the port aperture (mm)",
                },
                "x_max": {
                    "type": "number",
                    "description": "X-axis maximum coordinate of the port aperture (mm)",
                },
                "y_min": {
                    "type": "number",
                    "description": "Y-axis minimum coordinate of the port aperture (mm)",
                },
                "y_max": {
                    "type": "number",
                    "description": "Y-axis maximum coordinate of the port aperture (mm)",
                },
                "z_min": {
                    "type": "number",
                    "description": "Z-axis minimum coordinate of the port aperture (mm)",
                },
                "z_max": {
                    "type": "number",
                    "description": "Z-axis maximum coordinate of the port aperture (mm)",
                },
                "num_modes": {
                    "type": "integer",
                    "description": "Number of modes to monitor (1-10, default 1)",
                    "default": 1,
                },
            },
            "required": [
                "port_number",
                "orientation",
                "x_min",
                "x_max",
                "y_min",
                "y_max",
                "z_min",
                "z_max",
            ],
        },
    ),
]

async def handle(
    name: str, arguments: dict, client: CSTClient
) -> list[TextContent]:
    """Handle a port/excitation tool call."""
    try:
        if name == "cst_add_waveguide_port":
            return await _handle_waveguide_port(arguments, client)
        if name == "cst_add_discrete_port":
            return await _handle_discrete_port(arguments, client)
        if name == "cst_add_lumped_element":
            return await _handle_lumped_element(arguments, client)
        if name == "cst_add_plane_wave":
            return await _handle_plane_wave(arguments, client)
        if name == "cst_add_floquet_port":
            return await _handle_floquet_port(arguments, client)
        if name == "cst_list_ports":
            return await _handle_list_ports(arguments, client)
        if name == "cst_delete_port":
            return await _handle_delete_port(arguments, client)
        if name == "cst_add_multipin_port":
            return await _handle_multipin_port(arguments, client)

        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": f"Unknown port tool: {name}"}, indent=2),
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"tool": name, "status": "error", "message": str(e)}, indent=2),
        )]


async def _handle_waveguide_port(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    port_number = validate_port_number(arguments["port_number"])
    orientation = arguments["orientation"]
    if orientation not in _ORIENTATION_ENUM:
        raise ValueError(
            f"Invalid orientation '{orientation}'. Must be one of: {_ORIENTATION_ENUM}"
        )
    x_min = float(arguments["x_min"])
    x_max = float(arguments["x_max"])
    y_min = float(arguments["y_min"])
    y_max = float(arguments["y_max"])
    z_min = float(arguments["z_min"])
    z_max = float(arguments["z_max"])
    mode_number = int(arguments.get("mode_number", 1))
    if mode_number < 1:
        raise ValueError(f"mode_number must be >= 1, got {mode_number}")

    coordinates = arguments.get("coordinates", "Free")
    if coordinates not in ("Free", "Full", "Picks"):
        raise ValueError(
            f"Invalid coordinates '{coordinates}'. Must be Free, Full, or Picks."
        )

    vba = (
        VBABuilder("Port")
        .call("Reset")
        .set_number("PortNumber", port_number)
        .set("Label", "")
        .set("Coordinates", coordinates)
        .set("Orientation", orientation)
        .set_double("Xrange", x_min, x_max)
        .set_double("Yrange", y_min, y_max)
        .set_double("Zrange", z_min, z_max)
        .set_number("NumberOfModes", mode_number)
        .call("Create")
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["port_type"] = "waveguide"
    result["port_number"] = port_number
    result["orientation"] = orientation
    result["coordinates"] = coordinates

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_discrete_port(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    port_number = validate_port_number(arguments["port_number"])
    impedance = float(arguments.get("impedance", 50.0))
    validate_positive(impedance, "impedance")
    x1 = float(arguments["x1"])
    y1 = float(arguments["y1"])
    z1 = float(arguments["z1"])
    x2 = float(arguments["x2"])
    y2 = float(arguments["y2"])
    z2 = float(arguments["z2"])
    port_type = arguments.get("port_type", "SParameter")
    if port_type not in _DISCRETE_PORT_TYPE_ENUM:
        raise ValueError(
            f"Invalid port_type '{port_type}'. Must be one of: {_DISCRETE_PORT_TYPE_ENUM}"
        )

    # Official DiscretePort: SetP1/SetP2 (picked, x, y, z); Type "Sparameter"
    type_map = {
        "SParameter": "Sparameter",
        "Sparameter": "Sparameter",
        "Voltage": "Voltage",
        "Current": "Current",
    }
    cst_type = type_map.get(port_type, port_type)
    from cst_mcp.vba_builder import _format_number as _fn

    vba = (
        VBABuilder("DiscretePort")
        .call("Reset")
        .set_number("PortNumber", port_number)
        .set("Type", cst_type)
        .set_number("Impedance", impedance)
        .set_number("Voltage", 1.0)
        .set_number("Current", 1.0)
        .set_raw(
            "SetP1",
            f'"False", "{_fn(x1)}", "{_fn(y1)}", "{_fn(z1)}"',
        )
        .set_raw(
            "SetP2",
            f'"False", "{_fn(x2)}", "{_fn(y2)}", "{_fn(z2)}"',
        )
        .set("InvertDirection", "False")
        .set("LocalCoordinates", "False")
        .set_bool("Monitor", True)
        .set_number("Radius", 0.01)
        .call("Create")
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["port_type"] = "discrete"
    result["port_number"] = port_number
    result["impedance"] = impedance

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_lumped_element(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    elem_name = validate_name(arguments["name"], "element name")
    element_type = arguments["element_type"]
    if element_type not in _ELEMENT_TYPE_ENUM:
        raise ValueError(
            f"Invalid element_type '{element_type}'. Must be one of: {_ELEMENT_TYPE_ENUM}"
        )
    value = float(arguments["value"])
    x1 = float(arguments["x1"])
    y1 = float(arguments["y1"])
    z1 = float(arguments["z1"])
    x2 = float(arguments["x2"])
    y2 = float(arguments["y2"])
    z2 = float(arguments["z2"])

    # Map element_type to CST VBA LumpedElement type string
    cst_type_map = {
        "R": "RLC Serial",
        "L": "RLC Serial",
        "C": "RLC Serial",
        "RLC_serial": "RLC Serial",
        "RLC_parallel": "RLC Parallel",
    }
    cst_type = cst_type_map[element_type]

    vba = (
        VBABuilder("LumpedElement")
        .call("Reset")
        .set("Name", elem_name)
        .set("Type", cst_type)
    )

    # Set R, L, C values depending on element_type
    if element_type == "R":
        vba.set_number("SetR", value)
        vba.set_number("SetL", 0)
        vba.set_number("SetC", 0)
    elif element_type == "L":
        vba.set_number("SetR", 0)
        vba.set_number("SetL", value)
        vba.set_number("SetC", 0)
    elif element_type == "C":
        vba.set_number("SetR", 0)
        vba.set_number("SetL", 0)
        vba.set_number("SetC", value)
    else:
        # For RLC_serial / RLC_parallel, value is used as R and user should
        # set L/C separately; here we set R=value with L=0 and C=0 as defaults
        vba.set_number("SetR", value)
        vba.set_number("SetL", 0)
        vba.set_number("SetC", 0)

    vba = (
        vba
        .set_triple("Point1", x1, y1, z1)
        .set_triple("Point2", x2, y2, z2)
        .call("Create")
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["element_name"] = elem_name
    result["element_type"] = element_type
    result["value"] = value

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_plane_wave(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    polarization = arguments["polarization"]
    if polarization not in _POLARIZATION_ENUM:
        raise ValueError(
            f"Invalid polarization '{polarization}'. Must be one of: {_POLARIZATION_ENUM}"
        )
    theta = float(arguments["theta"])
    phi = float(arguments["phi"])
    e_theta = float(arguments.get("e_theta", 1.0))
    e_phi = float(arguments.get("e_phi", 0.0))

    vba = VBABuilder("PlaneWave").call("Reset")

    # Propagation direction defaults to z
    vba.set("Normal", "z")

    # Set polarization type and polarization-specific parameters
    vba.set("Polarization", polarization)
    if polarization == "circular":
        vba.set("CircularPolarization", "Left")
    else:
        vba.set_number("EFieldVector", e_theta)

    vba.set_number("Theta", theta)
    vba.set_number("Phi", phi)
    vba.set_number("PolarizationAngle", 0)
    vba.set_number("EFieldAmplitudeTheta", e_theta)
    vba.set_number("EFieldAmplitudePhi", e_phi)
    vba.call("Store")
    script = vba.build()
    result = client.execute_vba(script)
    result["excitation"] = "plane_wave"
    result["polarization"] = polarization
    result["theta"] = theta
    result["phi"] = phi

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_floquet_port(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    port_number = validate_port_number(arguments["port_number"])
    orientation = arguments["orientation"]
    if orientation not in _FLOQUET_ORIENTATION_ENUM:
        raise ValueError(
            f"Invalid orientation '{orientation}'. Must be one of: {_FLOQUET_ORIENTATION_ENUM}"
        )
    modes = int(arguments.get("modes", 2))
    if modes < 1:
        raise ValueError(f"modes must be >= 1, got {modes}")

    vba = (
        VBABuilder("FloquetPort")
        .call("Reset")
        .set_number("PortNumber", port_number)
        .set("Orientation", orientation)
        .set_number("NumberOfModes", modes)
        .call("Create")
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["port_type"] = "floquet"
    result["port_number"] = port_number
    result["modes"] = modes

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_list_ports(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    # Build VBA that queries port count — CST returns results via execute_vba
    vba_code = (
        'Dim n As Long\n'
        'n = Port.StartPortNumberIteration()\n'
        'Dim msg As String\n'
        'msg = "Total ports: " & n & vbCrLf\n'
        'Dim i As Long\n'
        'For i = 1 To n\n'
        '  Dim pn As Long\n'
        '  pn = Port.GetNextPortNumber()\n'
        '  msg = msg & "Port " & pn & vbCrLf\n'
        'Next i\n'
        'MsgBox msg'
    )

    result = client.execute_vba(vba_code)
    result["description"] = "Lists all defined ports in the CST project"

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_delete_port(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    port_number = validate_port_number(arguments["port_number"])

    vba = (
        VBABuilder("Port")
        .call("Reset")
        .set_number("PortNumber", port_number)
        .call("Delete")
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["action"] = "deleted"
    result["port_number"] = port_number

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_multipin_port(
    arguments: dict, client: CSTClient
) -> list[TextContent]:
    port_number = validate_port_number(arguments["port_number"])
    orientation = arguments["orientation"]
    if orientation not in _ORIENTATION_ENUM:
        raise ValueError(
            f"Invalid orientation '{orientation}'. Must be one of: {_ORIENTATION_ENUM}"
        )
    x_min = float(arguments["x_min"])
    x_max = float(arguments["x_max"])
    y_min = float(arguments["y_min"])
    y_max = float(arguments["y_max"])
    z_min = float(arguments["z_min"])
    z_max = float(arguments["z_max"])
    num_modes = int(arguments.get("num_modes", 1))
    validate_range(num_modes, 1, 10, "num_modes")

    vba = (
        VBABuilder("Port")
        .call("Reset")
        .set_number("PortNumber", port_number)
        .set("Label", "")
        .set("Orientation", orientation)
        .set_double("Xrange", x_min, x_max)
        .set_double("Yrange", y_min, y_max)
        .set_double("Zrange", z_min, z_max)
        .set_number("NumberOfModes", num_modes)
        .call("Create")
    )
    script = vba.build()
    result = client.execute_vba(script)
    result["port_type"] = "multipin"
    result["port_number"] = port_number
    result["orientation"] = orientation
    result["num_modes"] = num_modes

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def register_port_tools(server: Server, client: CSTClient) -> None:
    """Register port/excitation tools with the MCP server."""
    from cst_mcp.tools import _registry
    _registry.add_module(TOOLS, handle, client)
