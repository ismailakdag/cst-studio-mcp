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
    lambda0_mm: float
    eps_eff: float

    def to_dict(self) -> dict:
        return asdict(self)


def design_patch(
    frequency_ghz: float,
    *,
    epsilon_r: float = 4.4,
    height_mm: float = 1.6,
    tan_delta: float = 0.02,
    feed_type: str = "inset",
    ground_factor: float = 2.0,
) -> PatchDesign:
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
    # Inset for ~50 ohm (empirical)
    inset_mm = 0.0
    if feed_type == "inset":
        inset_mm = max(0.1, length_mm * 0.3)

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
        lambda0_mm=lambda0_mm,
        eps_eff=eps_eff,
    )
