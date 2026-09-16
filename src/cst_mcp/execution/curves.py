"""View-independent curves from the official CST results API (2025/2026).

Raw complex samples are always retained. No GUI selection or History write.
"""

from __future__ import annotations

import math
from typing import Any


def read_curve(
    project_path: str, tree_path: str, run_id: int = 0, *, allow_interactive: bool = False
) -> dict[str, Any]:
    try:
        import cst.results

        project = cst.results.ProjectFile(project_path, allow_interactive=allow_interactive)
        module = project.get_3d()
        item = module.get_result_item(tree_path, run_id)
        x = [float(v) for v in item.get_xdata()]
        values = [complex(v) for v in item.get_ydata()]
        if not x or len(x) != len(values):
            raise ValueError("Empty or mismatched result axes")
        if not all(math.isfinite(v) for v in x):
            raise ValueError("Non-finite x samples")
        if not all(math.isfinite(v.real) and math.isfinite(v.imag) for v in values):
            raise ValueError("Non-finite complex samples")
        return {
            "status": "ok",
            "source": "cst.results",
            "project_path": project_path,
            "tree_path": tree_path,
            "run_id": run_id,
            "n": len(x),
            "x": x,
            "real": [v.real for v in values],
            "imag": [v.imag for v in values],
            "xlabel": str(item.xlabel),
            "ylabel": str(item.ylabel),
            "title": str(item.title),
            "snapshot": "Last saved project results; unsaved GUI changes are not included",
        }
    except Exception as exc:
        return {
            "status": "error",
            "tree_path": tree_path,
            "run_id": run_id,
            "message": str(exc),
            "hint": "Use a saved, unpacked completed project and an exact 1D result tree path; check run_id. 3D fields need a dedicated export.",
        }


def format_curve(data: dict, fmt: str = "real_imag", unwrap: bool = False) -> dict:
    if data.get("status") != "ok":
        return data
    out = dict(data)
    values = [complex(r, i) for r, i in zip(data["real"], data["imag"])]
    if fmt == "real_imag":
        out.update(format=fmt, y=[[v.real, v.imag] for v in values])
    elif fmt == "mag":
        out.update(format=fmt, y=[abs(v) for v in values])
    elif fmt == "db":
        # JSON has no -Infinity; null explicitly represents zero amplitude.
        out.update(
            format=fmt,
            unit="dB",
            y=[20 * math.log10(abs(v)) if v else None for v in values],
            zero_amplitude="null represents -infinity dB",
        )
    elif fmt == "phase":
        phase = [math.atan2(v.imag, v.real) for v in values]
        if unwrap:
            for j in range(1, len(phase)):
                phase[j] = (
                    phase[j - 1] + (phase[j] - phase[j - 1] + math.pi) % (2 * math.pi) - math.pi
                )
        out.update(
            format=fmt,
            unit="degrees",
            y=[math.degrees(v) if values[j] else None for j, v in enumerate(phase)],
            unwrap=unwrap,
        )
    else:
        return {"status": "error", "message": f"Unsupported curve format: {fmt}"}
    return out


def frequency_scale(label: str) -> float:
    """CST xlabel includes the physical unit; never silently assume GHz."""
    import re

    units = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12}
    match = re.search(r"\b([kKmMgGtT]?[hH][zZ])\b", label)
    if not match:
        raise ValueError(f"Cannot determine frequency unit from xlabel={label!r}")
    return units[match.group(1).lower()]


def sample_curve(data: dict, maximum: int = 200) -> dict:
    """Explicit preview, after all metrics were calculated on the full curve."""
    if data.get("status") != "ok":
        return data
    if maximum < 0:
        raise ValueError("max_points must be non-negative")
    out = dict(data)
    n = data["n"]
    if maximum and maximum < n:
        indices = sorted({round(j*(n-1)/(maximum-1)) for j in range(maximum)}) if maximum > 1 else [0]
        for key in ["x", "y", "real", "imag", "impedance_real", "impedance_imag"]:
            if key in data:
                out[key] = [data[key][j] for j in indices]
        out.update(n=len(indices), total_points=n, sampled=True, sample_indices=indices)
    else:
        out.update(total_points=n, sampled=False)
    return out


def derived_s(data: dict, kind: str, arguments: dict) -> dict:
    if data.get("status") != "ok":
        return data
    out = dict(data)
    values = [complex(r, i) for r, i in zip(data["real"], data["imag"])]
    if kind == "cst_get_vswr":
        out.update(
            y=[(1 + abs(v)) / (1 - abs(v)) if abs(v) < 1 else None for v in values],
            data_type="vswr",
            singular_value="null for |Gamma| >= 1",
        )
    elif kind == "cst_get_smith_chart_data":
        z0 = float(arguments.get("z0", 50))
        if not math.isfinite(z0) or z0 <= 0:
            raise ValueError("z0 must be finite and positive")
        zs = [z0 * (1 + v) / (1 - v) if abs(1 - v) > 1e-15 else None for v in values]
        out.update(
            z0=z0,
            impedance_real=[v.real if v is not None else None for v in zs],
            impedance_imag=[v.imag if v is not None else None for v in zs],
            unit="ohm",
            data_type="smith_chart",
            assumption="Scalar real reference impedance z0 supplied by caller",
        )
    else:
        scale = frequency_scale(data["xlabel"])
        x = [v * scale for v in data["x"]]
        if len(x) < 2 or any(b <= a for a, b in zip(x, x[1:])):
            raise ValueError("Requires at least two strictly increasing frequency samples")
        if kind == "cst_get_group_delay":
            if any(v == 0 for v in values):
                raise ValueError("Group delay is undefined at zero amplitude")
            phase = format_curve(data, "phase", True)["y"]
            delay = []
            for j in range(len(x)):
                a, b = max(0, j - 1), min(len(x) - 1, j + 1)
                delay.append(-(phase[b] - phase[a]) / 360 / (x[b] - x[a]))
            out.update(
                y=delay,
                unit="seconds",
                data_type="group_delay",
                method="Unwrapped phase finite difference; one-sided endpoints",
            )
        elif kind == "cst_get_bandwidth":
            threshold = float(arguments.get("threshold_db", -10))
            if not math.isfinite(threshold) or threshold >= 0:
                raise ValueError("threshold_db must be finite and negative (reflection dB)")
            if arguments.get("criterion", "S11") not in {"S11", "VSWR"}:
                raise ValueError("criterion must be S11 or VSWR")
            mags = [abs(v) for v in values]
            limit = 10 ** (threshold / 20)
            bands = []
            start = x[0] if mags[0] <= limit else None
            for j in range(1, len(x)):
                inside_a, inside_b = mags[j - 1] <= limit, mags[j] <= limit
                if inside_a != inside_b:
                    edge = x[j - 1] + (x[j] - x[j - 1]) * (limit - mags[j - 1]) / (
                        mags[j] - mags[j - 1]
                    )
                    if inside_b:
                        start = edge
                    else:
                        bands.append((start, edge, start == x[0], False))
                        start = None
            if start is not None:
                bands.append((start, x[-1], start == x[0], True))
            out.update(
                data_type="bandwidth",
                threshold_db=threshold,
                equivalent_vswr=(1 + limit) / (1 - limit),
                method="Linear interpolation of reflection magnitude; all contiguous bands",
                bands=[
                    {
                        "f_lower_ghz": a / 1e9,
                        "f_upper_ghz": b / 1e9,
                        "center_freq_ghz": (a + b) / 2e9,
                        "bandwidth_mhz": (b - a) / 1e6,
                        "fractional_bandwidth_pct": 200 * (b - a) / (a + b),
                        "lower_truncated": low,
                        "upper_truncated": high,
                    }
                    for a, b, low, high in bands
                ],
            )
        else:
            raise ValueError(f"Unsupported derived quantity: {kind}")
    return out
