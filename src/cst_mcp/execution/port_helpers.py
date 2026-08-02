"""Reliable CST waveguide port VBA for microstrip-type feeds.

Common failure mode (old mcp-cst-studio and early workflows):
port appears "floating in air" because:

1. ``PortOnBound True`` (default in some templates) snaps the port to the
   *calculation domain* boundary after open BCs expand — far from the feed.
2. Oversized free-box apertures look detached from the strip.
3. Port plane Y does not match the outer end face of the feed line.

For a feed along −Y ending at ``y_edge``, orientation is ``ymin`` and the
transverse aperture is in the XZ plane at ``Y = y_edge``.
"""

from __future__ import annotations

from cst_mcp.vba_builder import _format_number as fmt


def microstrip_waveguide_port_vba(
    *,
    port_number: int = 1,
    y_edge: float,
    feed_width: float,
    substrate_height: float,
    ground_bottom: float = -0.035,
    metal_thickness: float = 0.035,
    x_center: float = 0.0,
) -> str:
    """Waveguide port flush with microstrip feed outer face at ``y_edge``.

    Geometry convention (patch workflow / templates):
    - Substrate: z = 0 .. h
    - Ground: z = ground_bottom .. 0
    - Strip/feed metal: z = h .. h+metal_thickness
    - Feed runs parallel to Y and ends at y = y_edge (structure ymin side)
    """
    h = float(substrate_height)
    fw = max(float(feed_width), 1e-6)
    y = float(y_edge)
    xc = float(x_center)

    # Transverse size (XZ). Keep tight around the strip so the port is not a
    # huge free-space plate, but wide/tall enough for the microstrip mode.
    # X: at least ~5× strip width or ~4× h
    half_x = max(fw * 2.5, h * 2.0, fw + 2.0 * h)
    x_min = xc - half_x
    x_max = xc + half_x

    # Z: from bottom of ground plane up through substrate + strip + ~4h air
    # (standard open microstrip WG-port aperture)
    z_min = float(ground_bottom)
    z_max = h + metal_thickness + max(4.0 * h, 2.0)

    pn = int(port_number)
    return "\n".join(
        [
            "With Port",
            "  .Reset",
            f'  .PortNumber "{pn}"',
            '  .NumberOfModes "1"',
            '  .AdjustPolarization "False"',
            '  .PolarizationAngle "0.0"',
            '  .ReferencePlaneDistance "0"',
            '  .TextSize "50"',
            '  .Coordinates "Free"',
            '  .Orientation "ymin"',
            # Critical: do NOT snap to expanded open domain boundary
            '  .PortOnBound "False"',
            '  .ClipPickedPortToBound "False"',
            f'  .Xrange "{fmt(x_min)}", "{fmt(x_max)}"',
            # Planar face at feed outer end (both ends equal)
            f'  .Yrange "{fmt(y)}", "{fmt(y)}"',
            f'  .Zrange "{fmt(z_min)}", "{fmt(z_max)}"',
            "  .Create",
            "End With",
        ]
    )


def feed_line_y_range(
    *,
    ground_y: float,
    patch_length: float,
    inset: float = 0.0,
    feed_type: str = "inset",
) -> tuple[float, float]:
    """Return (y_outer, y_inner) for a −Y edge microstrip feed.

    y_outer is the port plane (substrate/ground ymin edge).
    y_inner is toward the patch (touching or entering the patch for inset).
    """
    y_outer = -abs(ground_y) / 2.0
    y_patch_edge = -abs(patch_length) / 2.0
    if feed_type == "inset":
        y_inner = y_patch_edge + max(float(inset), 0.0)
    else:
        y_inner = y_patch_edge
    # Ensure outer is more negative than inner
    if y_outer > y_inner:
        y_outer, y_inner = y_inner, y_outer
    return y_outer, y_inner
