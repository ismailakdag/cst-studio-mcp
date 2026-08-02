"""867 MHz Minkowski fractal microstrip patch — build, solve, metrics."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.domain.antennas.patch import design_patch
from cst_mcp.execution.farfield import farfield_monitor_vba
from cst_mcp.execution.port_helpers import microstrip_waveguide_port_vba
from cst_mcp.execution.vba_builder import fmt_num, vba_str
from cst_mcp.vba_builder import VBABuilder


PROJ = Path(r"E:\cstprojects\fractal_patch_867.cst")
OUT = Path(r"E:\cstprojects\exports\fractal_867_report.json")
F0 = 0.867  # GHz


def brick(component: str, name: str, material: str, x0, x1, y0, y1, z0, z1) -> str:
    def f(v):
        return fmt_num(float(v)) if not isinstance(v, str) else v

    return "\n".join(
        [
            "With Brick",
            "  .Reset",
            f'  .Name "{vba_str(name)}"',
            f'  .Component "{vba_str(component)}"',
            f'  .Material "{vba_str(material)}"',
            f'  .Xrange "{f(x0)}", "{f(x1)}"',
            f'  .Yrange "{f(y0)}", "{f(y1)}"',
            f'  .Zrange "{f(z0)}", "{f(z1)}"',
            "  .Create",
            "End With",
        ]
    )


def solid_add(dst: str, src: str) -> str:
    return f'Solid.Add "{vba_str(dst)}", "{vba_str(src)}"'


def minkowski_patch_bricks(
    *,
    s: float,
    depth: float,
    z0: float,
    z1: float,
    order: int = 1,
) -> list[tuple[str, str]]:
    """Order-1 (+ optional order-2 corner nubs) Minkowski island as bricks.

    Geometry (top view, mm, center origin):
      - Core square: [-s/2, s/2]^2
      - Mid-side outward bumps of size ~s/3 x depth on N/S/E/W
      - order>=2: small secondary nubs on each bump face
    """
    steps: list[tuple[str, str]] = []
    half = s / 2.0
    mid = s / 6.0  # half-width of primary bump (~s/3 total)
    d1 = depth

    # Core
    steps.append(
        (
            "frac_core",
            brick("Antenna", "FracCore", "PEC", -half, half, -half, half, z0, z1),
        )
    )
    # Primary Minkowski bumps (outward rectangles on mid-sides)
    bumps = [
        ("BumpN", -mid, mid, half, half + d1),
        ("BumpS", -mid, mid, -half - d1, -half),
        ("BumpE", half, half + d1, -mid, mid),
        ("BumpW", -half - d1, -half, -mid, mid),
    ]
    for name, x0, x1, y0, y1 in bumps:
        steps.append(
            (f"frac_{name}", brick("Antenna", name, "PEC", x0, x1, y0, y1, z0, z1))
        )
        steps.append((f"add_{name}", solid_add("Antenna:FracCore", f"Antenna:{name}")))

    if order >= 2:
        # Secondary nubs: smaller steps at ends of each primary bump (Koch-ish)
        d2 = d1 * 0.45
        w2 = mid * 0.55
        # North face of BumpN: two small protrusions left/right of center
        nubs = [
            ("NubN1", -mid - w2, -mid + w2 * 0.2, half + d1, half + d1 + d2),
            ("NubN2", mid - w2 * 0.2, mid + w2, half + d1, half + d1 + d2),
            ("NubS1", -mid - w2, -mid + w2 * 0.2, -half - d1 - d2, -half - d1),
            ("NubS2", mid - w2 * 0.2, mid + w2, -half - d1 - d2, -half - d1),
            ("NubE1", half + d1, half + d1 + d2, -mid - w2, -mid + w2 * 0.2),
            ("NubE2", half + d1, half + d1 + d2, mid - w2 * 0.2, mid + w2),
            ("NubW1", -half - d1 - d2, -half - d1, -mid - w2, -mid + w2 * 0.2),
            ("NubW2", -half - d1 - d2, -half - d1, mid - w2 * 0.2, mid + w2),
        ]
        for name, x0, x1, y0, y1 in nubs:
            steps.append(
                (f"frac_{name}", brick("Antenna", name, "PEC", x0, x1, y0, y1, z0, z1))
            )
            steps.append((f"add_{name}", solid_add("Antenna:FracCore", f"Antenna:{name}")))

    # Rename final solid to Patch for clarity
    steps.append(
        (
            "rename_patch",
            'Solid.Rename "Antenna:FracCore", "Patch"',
        )
    )
    return steps


def store_params_vba(params: dict[str, float]) -> str:
    lines = ["' Store design parameters"]
    for k, v in params.items():
        lines.append(f'MakeSureParameterExists "{vba_str(k)}", "{fmt_num(v)}"')
        lines.append(f'StoreParameter "{vba_str(k)}", "{fmt_num(v)}"')
    return "\n".join(lines)


def main() -> int:
    cfg = CSTConfig.from_env()
    c = CSTClient(cfg)
    print("CONNECT", c.connect())

    # Baseline sizing at 867 MHz — use length-ish square for fractal island
    d = design_patch(F0, epsilon_r=4.4, height_mm=1.6, tan_delta=0.02, feed_type="microstrip")
    # Square side ~ geometric mean of W,L then slightly reduced (fractal perimeter longer)
    s = (d.width_mm * d.length_mm) ** 0.5 * 0.92  # slightly smaller due to longer path
    depth = s / 3.0
    extent = s / 2.0 + depth + depth * 0.45  # order-2 extent
    gx = max(d.ground_x_mm, extent * 2.4)
    gy = max(d.ground_y_mm, extent * 2.4 + 40.0)  # extra for feed
    h = d.height_mm
    metal_t = 0.035
    fw = max(d.feed_width_mm, 3.0)
    fmin, fmax = F0 * 0.65, F0 * 1.35

    # Feed from ground south edge to fractal south tip
    y_patch_s = -(s / 2.0 + depth)  # south of primary bump (order-1)
    # with order-2 nubs south goes further
    y_patch_s = -(s / 2.0 + depth + depth * 0.45)
    y_feed0 = -gy / 2.0
    y_feed1 = y_patch_s + 0.5  # slight overlap onto south nub

    design_info = {
        "type": "minkowski_fractal_patch",
        "order": 2,
        "frequency_ghz": F0,
        "square_side_mm": s,
        "bump_depth_mm": depth,
        "ground_x_mm": gx,
        "ground_y_mm": gy,
        "feed_width_mm": fw,
        "substrate": {"eps_r": 4.4, "h_mm": h, "tan_d": 0.02},
        "baseline_rect": d.to_dict(),
        "notes": (
            "Minkowski island order-2: square core + mid-side bumps + secondary nubs. "
            "Microstrip feed on -Y edge. Farfield monitor at 0.867 GHz."
        ),
    }
    print("DESIGN", json.dumps(design_info, indent=2, default=str)[:1200])

    print("NEW PROJECT", c.new_project(str(PROJ)))

    params = {
        "freq_GHz": F0,
        "eps_r": 4.4,
        "tan_d": 0.02,
        "sub_h": h,
        "frac_S": s,
        "frac_depth": depth,
        "gnd_x": gx,
        "gnd_y": gy,
        "feed_w": fw,
        "metal_t": metal_t,
        "fmin_GHz": fmin,
        "fmax_GHz": fmax,
    }

    steps: list[tuple[str, str]] = []
    steps.append(
        (
            "units",
            "\n".join(
                [
                    "With Units",
                    '  .SetUnit "Length", "mm"',
                    '  .SetUnit "Frequency", "GHz"',
                    '  .SetUnit "Time", "ns"',
                    "End With",
                ]
            ),
        )
    )
    steps.append(("store_parameters", store_params_vba(params)))
    steps.append(
        (
            "material_substrate",
            (
                VBABuilder("Material")
                .call("Reset")
                .set("Name", "Substrate")
                .set("Type", "Normal")
                .set_triple("Colour", 0.15, 0.45, 0.2)
                .set_number("Transparency", 0.35)
                .set_number("Epsilon", 4.4)
                .set_number("Mu", 1.0)
                .set_number("TanD", 0.02)
                .set_number("TanDFreq", 0.0)
                .set("TanDGiven", "True")
                .set("TanDModel", "ConstTanD")
                .call("Create")
                .build()
            ),
        )
    )
    steps.append(
        (
            "brick_ground",
            brick("Antenna", "Ground", "PEC", -gx / 2, gx / 2, -gy / 2, gy / 2, -metal_t, 0),
        )
    )
    steps.append(
        (
            "brick_substrate",
            brick(
                "Antenna",
                "Substrate",
                "Substrate",
                -gx / 2,
                gx / 2,
                -gy / 2,
                gy / 2,
                0,
                h,
            ),
        )
    )
    steps.extend(
        minkowski_patch_bricks(
            s=s, depth=depth, z0=h, z1=h + metal_t, order=2
        )
    )
    steps.append(
        (
            "brick_feed",
            brick(
                "Antenna",
                "Feed",
                "PEC",
                -fw / 2,
                fw / 2,
                y_feed0,
                y_feed1,
                h,
                h + metal_t,
            ),
        )
    )
    # Join feed to fractal patch
    steps.append(("add_feed", solid_add("Antenna:Patch", "Antenna:Feed")))
    steps.append(
        (
            "freq_range",
            "\n".join(
                [
                    "With Solver",
                    f'  .FrequencyRange "{fmt_num(fmin)}", "{fmt_num(fmax)}"',
                    "End With",
                ]
            ),
        )
    )
    steps.append(
        (
            "boundaries",
            "\n".join(
                [
                    'Boundary.Xmin "expanded open"',
                    'Boundary.Xmax "expanded open"',
                    'Boundary.Ymin "expanded open"',
                    'Boundary.Ymax "expanded open"',
                    'Boundary.Zmin "expanded open"',
                    'Boundary.Zmax "expanded open"',
                ]
            ),
        )
    )
    steps.append(
        (
            "port_wg_1",
            microstrip_waveguide_port_vba(
                port_number=1,
                y_edge=y_feed0,
                feed_width=fw,
                substrate_height=h,
                ground_bottom=-metal_t,
                metal_thickness=metal_t,
                x_center=0.0,
            ),
        )
    )
    steps.append(("monitor_farfield", farfield_monitor_vba(f"farfield (f={fmt_num(F0)})", F0)))
    steps.append(("solver_type", 'ChangeSolverType "HF Time Domain"'))

    results_steps = []
    for label, vba in steps:
        r = c.run_history(vba, label=label)
        st = r.get("status")
        msg = (r.get("message") or r.get("result") or "")
        print(f"  {label:22} {st} {str(msg)[:80]}")
        results_steps.append({"label": label, "status": st, "message": str(msg)[:200]})
        if st == "error" and label not in {"units", "rename_patch"}:
            # rename might fail if already named; continue
            if label.startswith("add_") or label.startswith("frac_"):
                print("    WARN continuing after", label)

    print("SAVE", c.save_project())
    print("SOLVE...")
    t0 = time.time()
    solve = c.run_solver(timeout_s=1800)
    dt = round(time.time() - t0, 1)
    print("SOLVE", solve, "t=", dt)
    c.save_project()

    s11 = c.get_s_parameters(1, 1, max_points=80)
    ff = c.get_farfield_metrics(F0)
    disk = c.discover_farfield_monitors()
    params_list = c.list_parameters()

    report = {
        "project": str(PROJ),
        "design": design_info,
        "steps": results_steps,
        "solve": solve,
        "solve_time_s": dt,
        "parameters": params_list,
        "s11": {
            "status": s11.get("status"),
            "metrics": s11.get("metrics"),
            "n_points": s11.get("n") or len(s11.get("frequency") or []),
        },
        "farfield": ff,
        "disk_monitors": disk,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("==== REPORT ====")
    print(json.dumps({
        "s11": report["s11"],
        "farfield_status": ff.get("status"),
        "farfield_available": ff.get("available"),
        "farfield_metrics": ff.get("metrics"),
        "method": ff.get("method"),
        "disk": disk.get("count"),
        "solve_s": dt,
    }, indent=2, default=str))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
