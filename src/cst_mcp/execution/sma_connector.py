"""Parametric edge-launch SMA connector + internal waveguide port (VBA generator).

Geometry mirrors the SMA model validated in a CST 2026 CPW-monopole campaign
(power balance closed to <= 0.6 % with all boundaries "expanded open"):

* PEC body, square cross-section 2*body_half, length body_length, with a
  circular bore of radius outer_radius, standing off the board edge by gap;
* PTFE (er 2.1) coax dielectric in the bore, PEC pin (pin_radius 0.635)
  running from the back face across the gap and pin_overlap onto the signal
  strip, with a PEC solder block under the overhanging pin (Solid.Add);
* two PEC legs bonded to the coplanar grounds (CPW), or one bottom leg on the
  back-side ground (microstrip);
* waveguide port on the coax back face, PortOnBound False ("free normal
  position" / internal port), orientation pointing into the board.

The coax axis sits at z = z_cu + pin_radius where z_cu is the copper TOP face,
so pin, solder and legs touch the copper.  Getting z_cu wrong reproduces the
campaign's v1 bug: a 35 um air gap between pin/legs and copper that the mesh
resolves as an open circuit.
"""

from __future__ import annotations

import math
from typing import Any

from cst_mcp.vba_builder import _format_number as _fmt
from cst_mcp.vba_safety import vba_escape, vba_number

EDGES = ("xmin", "xmax", "ymin", "ymax")
Z_CONVENTIONS = ("copper_below_top", "copper_above_top")

DEFAULTS: dict[str, Any] = {
    "pin_radius": 0.635,
    "outer_radius": 2.1,
    "dielectric_epsilon": 2.1,
    "dielectric_tand": 0.0002,
    "body_half": 4.75,
    "body_length": 6.0,
    "gap": 0.3,
    "pin_overlap": 1.5,
    "solder_width": 1.0,
    "leg_inner": 2.9,
    "leg_outer": 4.4,
    "leg_thickness": 0.5,
    "leg_on_board": 1.5,
    "copper_thickness": 0.035,
    "substrate_thickness": 1.6,
    "substrate_top_z": 0.0,
    "feed_center": 0.0,
    "edge_position": 0.0,
    "ground_type": "cpw",
    "component": "sma",
    "dielectric_material": "PTFE_er2.1",
    "metal_material": "PEC",
    "port_number": 1,
}


def coax_impedance(pin_radius: float, outer_radius: float, epsilon_r: float) -> float:
    """TEM coax impedance Z0 = 59.96/sqrt(er) * ln(b/a)."""
    return 59.958 / math.sqrt(epsilon_r) * math.log(outer_radius / pin_radius)


def outer_radius_for(z0: float, pin_radius: float, epsilon_r: float) -> float:
    return pin_radius * math.exp(z0 * math.sqrt(epsilon_r) / 59.958)


def _n(v: float) -> str:
    return _fmt(float(v))


class _Frame:
    """Map (s = outward distance from the board edge, u = along-edge, z) to world."""

    def __init__(self, edge: str, edge_position: float, feed_center: float) -> None:
        self.edge = edge
        self.e = float(edge_position)
        self.c = float(feed_center)
        self.normal_axis = "y" if edge in ("ymin", "ymax") else "x"
        self.sign = -1.0 if edge.endswith("min") else 1.0  # outward direction

    def n(self, s: float) -> float:
        return self.e + self.sign * s

    def ranges(self, s0: float, s1: float, u0: float, u1: float) -> dict[str, tuple[float, float]]:
        n = sorted((self.n(s0), self.n(s1)))
        t = sorted((self.c + u0, self.c + u1))
        if self.normal_axis == "y":
            return {"X": (t[0], t[1]), "Y": (n[0], n[1])}
        return {"X": (n[0], n[1]), "Y": (t[0], t[1])}


def _brick(name: str, comp: str, mat: str, r: dict[str, tuple[float, float]], z: tuple[float, float]) -> str:
    z0, z1 = sorted(z)
    return "\n".join([
        "With Brick", "  .Reset", f'  .Name "{name}"', f'  .Component "{comp}"', f'  .Material "{mat}"',
        f'  .Xrange "{_n(r["X"][0])}", "{_n(r["X"][1])}"',
        f'  .Yrange "{_n(r["Y"][0])}", "{_n(r["Y"][1])}"',
        f'  .Zrange "{_n(z0)}", "{_n(z1)}"',
        "  .Create", "End With",
    ])


def _cylinder(fr: _Frame, name: str, comp: str, mat: str, ro: float, ri: float,
              s0: float, s1: float, zc: float) -> str:
    a, b = sorted((fr.n(s0), fr.n(s1)))
    ax = fr.normal_axis
    rng = "Yrange" if ax == "y" else "Xrange"
    centers = ([f'  .Xcenter "{_n(fr.c)}"', f'  .Zcenter "{_n(zc)}"'] if ax == "y"
               else [f'  .Ycenter "{_n(fr.c)}"', f'  .Zcenter "{_n(zc)}"'])
    return "\n".join([
        "With Cylinder", "  .Reset", f'  .Name "{name}"', f'  .Component "{comp}"', f'  .Material "{mat}"',
        f'  .OuterRadius "{_n(ro)}"', f'  .InnerRadius "{_n(ri)}"', f'  .Axis "{ax}"',
        f'  .{rng} "{_n(a)}", "{_n(b)}"', *centers, '  .Segments "0"', "  .Create", "End With",
    ])


def resolve(args: dict[str, Any]) -> dict[str, Any]:
    """Validate/coerce arguments (numbers through vba_number, names escaped)."""
    p = dict(DEFAULTS)
    p.update({k: v for k, v in args.items() if v is not None})
    edge = str(p.get("edge", "")).lower()
    if edge not in EDGES:
        raise ValueError(f"edge must be one of {EDGES}")
    conv = p.get("copper_z_convention")
    if conv not in Z_CONVENTIONS:
        raise ValueError(
            f"copper_z_convention must be one of {Z_CONVENTIONS}: 'copper_below_top' = copper occupies "
            "substrate_top_z - t .. substrate_top_z (raw clockwise Polygon + ExtrudeCurve, the campaign case); "
            "'copper_above_top' = substrate_top_z .. substrate_top_z + t (cst_create_polygon_extrude "
            "extrude_direction='up' with z_offset=substrate_top_z)."
        )
    num_keys = [k for k, v in DEFAULTS.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    for k in num_keys:
        p[k] = float(vba_number(p[k], k))
    if p.get("target_impedance") is not None:
        z0 = float(vba_number(p["target_impedance"], "target_impedance"))
        if z0 <= 0:
            raise ValueError("target_impedance must be > 0")
        p["outer_radius"] = outer_radius_for(z0, p["pin_radius"], p["dielectric_epsilon"])
    for k in ("pin_radius", "outer_radius", "dielectric_epsilon", "body_half", "body_length",
              "copper_thickness", "substrate_thickness", "solder_width", "leg_thickness"):
        if p[k] <= 0:
            raise ValueError(f"{k} must be > 0")
    for k in ("gap", "pin_overlap", "leg_on_board", "dielectric_tand"):
        if p[k] < 0:
            raise ValueError(f"{k} must be >= 0")
    if p["outer_radius"] <= p["pin_radius"]:
        raise ValueError("outer_radius must exceed pin_radius")
    if p["body_half"] <= p["outer_radius"]:
        raise ValueError("body_half must exceed outer_radius (the bore must fit in the body)")
    if not 0 <= p["leg_inner"] < p["leg_outer"]:
        raise ValueError("need 0 <= leg_inner < leg_outer (leg offsets from the feed centre)")
    if p["ground_type"] not in ("cpw", "microstrip"):
        raise ValueError("ground_type must be 'cpw' or 'microstrip'")
    p["port_number"] = int(p["port_number"])
    if p["port_number"] < 1:
        raise ValueError("port_number must be >= 1")
    for k in ("component", "dielectric_material", "metal_material"):
        p[k] = vba_escape(str(p[k]), k)
        if not p[k] or ":" in p[k] or "/" in p[k]:
            raise ValueError(f"{k} must be a plain CST name")
    p["edge"] = edge
    t = p["copper_thickness"]
    top = p["substrate_top_z"]
    p["z_cu_top"] = top if conv == "copper_below_top" else top + t
    # Microstrip back-side ground assumed under the substrate: top-h-t .. top-h.
    p["z_cu_bottom_ground"] = top - p["substrate_thickness"] - t
    return p


def build_sma_vba(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (VBA, summary) for the connector, its PTFE material and its port."""
    p = resolve(args)
    fr = _Frame(p["edge"], p["edge_position"], p["feed_center"])
    comp, pec, ptfe = p["component"], p["metal_material"], p["dielectric_material"]
    zc = p["z_cu_top"] + p["pin_radius"]
    a = p["body_half"]
    s_front, s_back = p["gap"], p["gap"] + p["body_length"]
    blocks: list[str] = []
    blocks.append("\n".join([
        "With Material", "  .Reset", f'  .Name "{ptfe}"', '  .Folder ""', '  .FrqType "all"', '  .Type "Normal"',
        f'  .Epsilon "{_n(p["dielectric_epsilon"])}"', '  .Mu "1.0"', f'  .TanD "{_n(p["dielectric_tand"])}"',
        '  .TanDFreq "1.0"', '  .TanDGiven "True"', '  .TanDModel "ConstTanD"', '  .Colour "0.9", "0.9", "0.9"',
        "  .Create", "End With",
    ]))
    blocks.append(_brick("body", comp, pec, fr.ranges(s_front, s_back, -a, a), (zc - a, zc + a)))
    blocks.append(_cylinder(fr, "bore", comp, pec, p["outer_radius"], 0.0, s_front, s_back, zc))
    blocks.append(f'Solid.Subtract "{comp}:body", "{comp}:bore"')
    blocks.append(_cylinder(fr, "ptfe", comp, ptfe, p["outer_radius"], p["pin_radius"], s_front, s_back, zc))
    blocks.append(_cylinder(fr, "pin", comp, pec, p["pin_radius"], 0.0, s_back, -p["pin_overlap"], zc))
    hw = p["solder_width"] / 2
    blocks.append(_brick("solder", comp, pec, fr.ranges(s_front, -p["pin_overlap"], -hw, hw),
                         (p["z_cu_top"], zc)))
    blocks.append(f'Solid.Add "{comp}:pin", "{comp}:solder"')
    legs = []
    if p["ground_type"] == "cpw":
        for k, sg in enumerate((1.0, -1.0)):
            u0, u1 = sorted((sg * p["leg_inner"], sg * p["leg_outer"]))
            blocks.append(_brick(f"leg{k}", comp, pec, fr.ranges(s_front, -p["leg_on_board"], u0, u1),
                                 (p["z_cu_top"], p["z_cu_top"] + p["leg_thickness"])))
            legs.append(f"{comp}:leg{k}")
    else:
        zb = p["z_cu_bottom_ground"]
        blocks.append(_brick("leg0", comp, pec, fr.ranges(s_front, -p["leg_on_board"], -p["leg_outer"],
                                                         p["leg_outer"]),
                             (zb - p["leg_thickness"], zb)))
        legs.append(f"{comp}:leg0")
    # Internal waveguide port on the coax back face, feeding towards the board.
    ap = a - 0.25
    plane = fr.n(s_back)
    if fr.normal_axis == "y":
        xr, yr = (fr.c - ap, fr.c + ap), (plane, plane)
    else:
        xr, yr = (plane, plane), (fr.c - ap, fr.c + ap)
    blocks.append("\n".join([
        "With Port", "  .Reset", f'  .PortNumber "{p["port_number"]}"', '  .Label ""', '  .NumberOfModes "1"',
        '  .AdjustPolarization "False"', '  .PolarizationAngle "0.0"', '  .ReferencePlaneDistance "0"',
        '  .TextSize "50"', '  .Coordinates "Free"', f'  .Orientation "{p["edge"]}"', '  .PortOnBound "False"',
        '  .ClipPickedPortToBound "False"', f'  .Xrange "{_n(xr[0])}", "{_n(xr[1])}"',
        f'  .Yrange "{_n(yr[0])}", "{_n(yr[1])}"', f'  .Zrange "{_n(zc - ap)}", "{_n(zc + ap)}"',
        '  .XrangeAdd "0.0", "0.0"', '  .YrangeAdd "0.0", "0.0"', '  .ZrangeAdd "0.0", "0.0"',
        '  .SingleEnded "False"', "  .Create", "End With",
    ]))
    z0 = coax_impedance(p["pin_radius"], p["outer_radius"], p["dielectric_epsilon"])
    summary = {
        "component": comp,
        "solids": [f"{comp}:body", f"{comp}:ptfe", f"{comp}:pin", *legs],
        "coax": {"pin_radius": p["pin_radius"], "outer_radius": round(p["outer_radius"], 4),
                 "epsilon_r": p["dielectric_epsilon"], "z0_ohm": round(z0, 2)},
        "axis_z": round(zc, 6),
        "copper_top_z": p["z_cu_top"],
        "port": {"number": p["port_number"], "orientation": p["edge"], "plane": round(plane, 6),
                 "normal_axis": fr.normal_axis, "port_on_bound": False},
        "board_edge": {"edge": p["edge"], "position": p["edge_position"], "feed_center": p["feed_center"]},
        "boundary_advice": ("Set ALL boundaries to 'expanded open' (cst_set_boundary) so nothing touches "
                            "the PML; the internal port stays on the coax face (PortOnBound False)."),
    }
    return "\n".join(blocks), summary
