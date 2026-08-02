"""867 MHz Minkowski fractal v2 — retuned size + solid feed to south bump."""
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
F0 = 0.867


def brick(component, name, material, x0, x1, y0, y1, z0, z1):
    def f(v):
        return fmt_num(float(v))

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


def solid_add(dst, src):
    return f'Solid.Add "{vba_str(dst)}", "{vba_str(src)}"'


def store_params_vba(params):
    lines = []
    for k, v in params.items():
        lines.append(f'MakeSureParameterExists "{vba_str(k)}", "{fmt_num(v)}"')
        lines.append(f'StoreParameter "{vba_str(k)}", "{fmt_num(v)}"')
    return "\n".join(lines)


def main():
    c = CSTClient(CSTConfig.from_env())
    print(c.connect())

    d = design_patch(F0, epsilon_r=4.4, height_mm=1.6, feed_type="microstrip")
    # v1 resonated ~0.56 GHz with s~85.6 → scale by 0.56/0.867 for ~0.867
    # slightly more shrink: fractal path length still longer than rect
    s = (d.width_mm * d.length_mm) ** 0.5 * 0.58
    depth = s / 3.5  # slightly milder bumps for cleaner resonance
    d2 = depth * 0.4
    extent = s / 2 + depth + d2
    gx = max(extent * 2.3, 120.0)
    gy = max(extent * 2.3 + 50.0, 150.0)
    h, metal_t, fw = d.height_mm, 0.035, 3.2
    # Wider band to capture match
    fmin, fmax = 0.5, 1.2

    half, mid = s / 2.0, s / 6.0
    y_south_primary = -half - depth  # south face of primary bump
    y_feed0 = -gy / 2.0
    y_feed1 = y_south_primary + 1.0  # overlap into primary south bump (reliable contact)

    design = {
        "type": "minkowski_fractal_patch_v2",
        "order": 2,
        "frequency_ghz": F0,
        "square_side_mm": round(s, 3),
        "bump_depth_mm": round(depth, 3),
        "ground_mm": [round(gx, 2), round(gy, 2)],
        "freq_range_ghz": [fmin, fmax],
        "note": "Retuned after v1 resonated ~0.56 GHz; feed bonds to primary south bump",
    }
    print("DESIGN", json.dumps(design, indent=2))

    print(c.new_project(str(PROJ)))

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

    steps = []
    steps.append(("units", "With Units\n  .SetUnit \"Length\", \"mm\"\n  .SetUnit \"Frequency\", \"GHz\"\n  .SetUnit \"Time\", \"ns\"\nEnd With"))
    steps.append(("store_parameters", store_params_vba(params)))
    steps.append(
        (
            "material_substrate",
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
            .build(),
        )
    )
    steps.append(("ground", brick("Antenna", "Ground", "PEC", -gx/2, gx/2, -gy/2, gy/2, -metal_t, 0)))
    steps.append(("substrate", brick("Antenna", "Substrate", "Substrate", -gx/2, gx/2, -gy/2, gy/2, 0, h)))
    z0, z1 = h, h + metal_t
    # Core + 4 primary bumps + 8 nubs
    steps.append(("core", brick("Antenna", "FracCore", "PEC", -half, half, -half, half, z0, z1)))
    for name, x0, x1, y0, y1 in [
        ("BumpN", -mid, mid, half, half + depth),
        ("BumpS", -mid, mid, -half - depth, -half),
        ("BumpE", half, half + depth, -mid, mid),
        ("BumpW", -half - depth, -half, -mid, mid),
    ]:
        steps.append((name, brick("Antenna", name, "PEC", x0, x1, y0, y1, z0, z1)))
        steps.append((f"add_{name}", solid_add("Antenna:FracCore", f"Antenna:{name}")))

    w2 = mid * 0.5
    nubs = [
        ("NubN1", -mid - w2, -mid, half + depth, half + depth + d2),
        ("NubN2", mid, mid + w2, half + depth, half + depth + d2),
        ("NubS1", -mid - w2, -mid, -half - depth - d2, -half - depth),
        ("NubS2", mid, mid + w2, -half - depth - d2, -half - depth),
        ("NubE1", half + depth, half + depth + d2, -mid - w2, -mid),
        ("NubE2", half + depth, half + depth + d2, mid, mid + w2),
        ("NubW1", -half - depth - d2, -half - depth, -mid - w2, -mid),
        ("NubW2", -half - depth - d2, -half - depth, mid, mid + w2),
    ]
    for name, x0, x1, y0, y1 in nubs:
        steps.append((name, brick("Antenna", name, "PEC", x0, x1, y0, y1, z0, z1)))
        steps.append((f"add_{name}", solid_add("Antenna:FracCore", f"Antenna:{name}")))

    steps.append(("rename", 'Solid.Rename "Antenna:FracCore", "Patch"'))
    # Feed to primary south bump
    steps.append(("feed", brick("Antenna", "Feed", "PEC", -fw/2, fw/2, y_feed0, y_feed1, z0, z1)))
    steps.append(("add_feed", solid_add("Antenna:Patch", "Antenna:Feed")))
    steps.append(("freq", f'With Solver\n  .FrequencyRange "{fmt_num(fmin)}", "{fmt_num(fmax)}"\nEnd With'))
    steps.append(
        (
            "bc",
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
            "port",
            microstrip_waveguide_port_vba(
                port_number=1,
                y_edge=y_feed0,
                feed_width=fw,
                substrate_height=h,
                ground_bottom=-metal_t,
                metal_thickness=metal_t,
            ),
        )
    )
    steps.append(("ffmon", farfield_monitor_vba(f"farfield (f={fmt_num(F0)})", F0)))
    # extra farfield samples near expected band
    steps.append(("ffmon2", farfield_monitor_vba("farfield (f=0.8)", 0.8)))
    steps.append(("ffmon3", farfield_monitor_vba("farfield (f=0.95)", 0.95)))
    steps.append(("solver", 'ChangeSolverType "HF Time Domain"'))

    for label, vba in steps:
        r = c.run_history(vba, label=label)
        print(f"  {label:16} {r.get('status')}")

    c.save_project()
    t0 = time.time()
    solve = c.run_solver(timeout_s=1800)
    dt = round(time.time() - t0, 1)
    print("SOLVE", solve, dt)
    c.save_project()

    s11 = c.get_s_parameters(1, 1, max_points=120)
    ff = c.get_farfield_metrics(F0)
    ff2 = c.get_farfield_metrics(0.8)
    disk = c.discover_farfield_monitors()

    report = {
        "project": str(PROJ),
        "design": design,
        "solve": solve,
        "solve_s": dt,
        "s11": {"status": s11.get("status"), "metrics": s11.get("metrics")},
        "farfield_867": ff,
        "farfield_800": {
            "status": ff2.get("status"),
            "metrics": ff2.get("metrics"),
            "available": ff2.get("available"),
        },
        "disk": disk,
    }
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "s11": s11.get("metrics"),
                "ff867": ff.get("metrics"),
                "ff867_available": ff.get("available"),
                "ff867_method": ff.get("method"),
                "disk_count": disk.get("count"),
                "solve_s": dt,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
