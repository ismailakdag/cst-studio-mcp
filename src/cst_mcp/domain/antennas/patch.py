"""Rectangular microstrip patch sizing (Balanis / Hammerstad–Jensen)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

C0 = 299_792_458.0  # m/s


@dataclass
class PatchDesign:
    frequency_ghz: float
    epsilon_r: float
    height_mm: float
    tan_delta: float
    feed_type: str
    # computed (mm)
    width_mm: float
    length_mm: float
    ground_x_mm: float
    ground_y_mm: float
    inset_mm: float
    feed_width_mm: float
    notch_gap_mm: float
    edge_resistance_ohm: float
    # coaxial probe feed (feed_type == "probe"; zero otherwise)
    probe_offset_mm: float
    probe_radius_mm: float
    coax_outer_radius_mm: float
    coax_epsilon_r: float
    lambda0_mm: float
    eps_eff: float

    def to_dict(self) -> dict:
        return asdict(self)


def _bessel_j0(x: float) -> float:
    """J0(x) by its power series (accurate for the |x| < ~20 used here)."""
    term, total, m = 1.0, 1.0, 0
    q = -(x * x) / 4.0
    while abs(term) > 1e-17 * max(1.0, abs(total)) and m < 200:
        m += 1
        term *= q / (m * m)
        total += term
    return total


def _simpson(f, a: float, b: float, n: int = 400) -> float:
    n += n % 2
    step = (b - a) / n
    acc = f(a) + f(b)
    for i in range(1, n):
        acc += (4 if i % 2 else 2) * f(a + i * step)
    return acc * step / 3.0


def edge_resistance(width_m: float, length_m: float, lambda0_m: float) -> float:
    """Resonant input resistance at the radiating edge (Balanis 14.2.1).

    Two-slot transmission-line model: R_in = 1 / (2 (G1 + G12)) with

    * G1  = 1/(120 pi^2) int_0^pi [sin(k0 W cos t / 2) / cos t]^2 sin^3 t dt
    * G12 = 1/(120 pi^2) int_0^pi [sin(k0 W cos t / 2) / cos t]^2
      J0(k0 L sin t) sin^3 t dt   (mutual conductance of the two slots)
    """
    k0 = 2 * math.pi / lambda0_m

    def slot(t: float) -> float:
        c = math.cos(t)
        if abs(c) < 1e-12:  # limit sin(a c)/c -> a
            ratio = k0 * width_m / 2
        else:
            ratio = math.sin(k0 * width_m * c / 2) / c
        return ratio * ratio * math.sin(t) ** 3

    g1 = _simpson(slot, 0.0, math.pi) / (120 * math.pi**2)
    g12 = _simpson(
        lambda t: slot(t) * _bessel_j0(k0 * length_m * math.sin(t)), 0.0, math.pi
    ) / (120 * math.pi**2)
    return 1.0 / (2.0 * (g1 + g12))


def inset_depth(length_m: float, r_edge: float, z0: float = 50.0) -> float:
    """Inset depth y0 with R_in(y0) = R_edge cos^2(pi y0 / L) = z0."""
    if r_edge <= z0:
        return 0.0
    return length_m / math.pi * math.acos(math.sqrt(z0 / r_edge))


PTFE_EPSILON_R = 2.1
SMA_PIN_RADIUS_MM = 0.635


def coax_outer_radius(inner_radius: float, epsilon_r: float, z0: float = 50.0) -> float:
    """Outer radius b of a coax with Z0 = 60/sqrt(eps_r) ln(b/a)."""
    return inner_radius * math.exp(z0 * math.sqrt(epsilon_r) / 60.0)


def probe_offset(length_m: float, r_edge: float, z0: float = 50.0) -> float:
    """Probe offset from the patch centre along L for R_in = z0.

    Same cos^2 rule as the inset feed: the feed point sits y0 inside the
    radiating edge with R_edge cos^2(pi y0 / L) = z0, i.e. L/2 - y0 from the
    centre.
    """
    return length_m / 2.0 - inset_depth(length_m, r_edge, z0)


def design_patch(
    frequency_ghz: float,
    *,
    epsilon_r: float = 4.4,
    height_mm: float = 1.6,
    tan_delta: float = 0.02,
    feed_type: str = "inset",
    ground_factor: float = 2.0,
    notch_gap_mm: float | None = None,
) -> PatchDesign:
    """Size a rectangular patch.

    Inset feed: depth y0 = (L/pi) arccos(sqrt(50/R_edge)) with R_edge from the
    Balanis G1/G12 slot model (2.4 GHz, FR-4 4.4/1.6 mm: R_edge ~ 321 ohm,
    y0 ~ 10.9 mm; the former fixed 0.3 L gave 8.8 mm).  The notch gap on each
    side of the feed defaults to 1 mm: Matin & Sayeed's empirical g = c 4.65e-12 / (sqrt(2 eps_eff) f_GHz) gives
    only ~0.2 mm at 2.4 GHz on FR-4, which is hard to etch and to mesh, while
    ~1 mm (about feed_w/3) is the usual practical choice and barely changes the
    resonance.  Both are starting points; refine inset/notch_g in the solver.

    Probe feed: the coax pin sits at the same cos^2 point, L/2 - y0 from the
    patch centre toward the -Y edge (2.4 GHz FR-4: ~3.8 mm).  Pin radius
    0.635 mm (SMA); PTFE (eps_r 2.1) outer radius a exp(50 sqrt(eps_r)/60)
    ~2.12 mm for 50 ohm.
    """
    if frequency_ghz <= 0:
        raise ValueError("frequency_ghz must be positive")
    if epsilon_r < 1.0:
        raise ValueError("epsilon_r must be >= 1")
    if height_mm <= 0:
        raise ValueError("height_mm must be positive")

    f_hz = frequency_ghz * 1e9
    lambda0_m = C0 / f_hz
    lambda0_mm = lambda0_m * 1e3
    h_m = height_mm * 1e-3

    # Width (Balanis)
    width_m = C0 / (2 * f_hz) * math.sqrt(2 / (epsilon_r + 1))
    # Effective permittivity
    eps_eff = (epsilon_r + 1) / 2 + (epsilon_r - 1) / 2 * (
        1 + 12 * h_m / width_m
    ) ** -0.5
    # Extension
    delta_l = (
        0.412
        * h_m
        * (eps_eff + 0.3)
        * (width_m / h_m + 0.264)
        / ((eps_eff - 0.258) * (width_m / h_m + 0.8))
    )
    length_m = C0 / (2 * f_hz * math.sqrt(eps_eff)) - 2 * delta_l

    width_mm = width_m * 1e3
    length_mm = length_m * 1e3
    gx = width_mm * ground_factor
    gy = length_mm * ground_factor

    # ~50 ohm microstrip width (Wheeler rough estimate)
    # Simplified: for FR4 1.6mm ~3mm; scale with h
    feed_width_mm = max(0.5, min(height_mm * 2.0, width_mm * 0.2))
    r_edge = edge_resistance(width_m, length_m, lambda0_m)
    inset_mm = 0.0
    if feed_type == "inset":
        inset_mm = max(0.1, inset_depth(length_m, r_edge) * 1e3)
    gap = 1.0 if notch_gap_mm is None else float(notch_gap_mm)
    if not math.isfinite(gap) or gap <= 0:
        raise ValueError("notch_gap_mm must be positive")
    if feed_type == "inset" and feed_width_mm + 2 * gap >= width_mm:
        raise ValueError("notch_gap_mm too large for the patch width")

    probe_mm = probe_r = coax_r = coax_er = 0.0
    if feed_type == "probe":
        probe_r = SMA_PIN_RADIUS_MM
        coax_er = PTFE_EPSILON_R
        coax_r = coax_outer_radius(probe_r, coax_er)
        # Keep the pin (and its ground clearance) on the patch
        probe_mm = min(probe_offset(length_m, r_edge) * 1e3, length_mm / 2 - probe_r)

    return PatchDesign(
        frequency_ghz=frequency_ghz,
        epsilon_r=epsilon_r,
        height_mm=height_mm,
        tan_delta=tan_delta,
        feed_type=feed_type,
        width_mm=width_mm,
        length_mm=length_mm,
        ground_x_mm=gx,
        ground_y_mm=gy,
        inset_mm=inset_mm,
        feed_width_mm=feed_width_mm,
        notch_gap_mm=gap if feed_type == "inset" else 0.0,
        edge_resistance_ohm=r_edge,
        probe_offset_mm=probe_mm,
        probe_radius_mm=probe_r,
        coax_outer_radius_mm=coax_r,
        coax_epsilon_r=coax_er,
        lambda0_mm=lambda0_mm,
        eps_eff=eps_eff,
    )
