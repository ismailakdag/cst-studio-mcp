"""
Compact CP UHF RFID reader antenna @ 867 MHz — CST automation.
Rogers RO4003C, rounded-octagon patch, diagonal dumbbell + unequal arc slots,
offset discrete (coax-like) feed. Limited parameter sweep + report.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\cst_mcp_update\src")
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.execution.farfield import farfield_monitor_vba
from cst_mcp.execution.results_api import antenna_metrics_from_results, read_1d_item
from cst_mcp.execution.vba_builder import fmt_num, vba_str
from cst_mcp.vba_builder import VBABuilder

PROJ = Path(r"E:\cstprojects\rfid_cp_867_octagon.cst")
OUT = Path(r"E:\cstprojects\exports\rfid_cp_867_report.json")
F0 = 0.867
FMIN, FMAX = 0.75, 1.00
H = 1.524  # RO4003C thickness mm
METAL = 0.035
EPS_R = 3.55
TAN_D = 0.0027  # typical RO4003C


def brick(comp, name, mat, x0, x1, y0, y1, z0, z1):
    return "\n".join(
        [
            "With Brick",
            "  .Reset",
            f'  .Name "{vba_str(name)}"',
            f'  .Component "{vba_str(comp)}"',
            f'  .Material "{vba_str(mat)}"',
            f'  .Xrange "{fmt_num(x0)}", "{fmt_num(x1)}"',
            f'  .Yrange "{fmt_num(y0)}", "{fmt_num(y1)}"',
            f'  .Zrange "{fmt_num(z0)}", "{fmt_num(z1)}"',
            "  .Create",
            "End With",
        ]
    )


def cylinder_z(comp, name, mat, r_outer, r_inner, z0, z1, xc=0.0, yc=0.0):
    return "\n".join(
        [
            "With Cylinder",
            "  .Reset",
            f'  .Name "{vba_str(name)}"',
            f'  .Component "{vba_str(comp)}"',
            f'  .Material "{vba_str(mat)}"',
            '  .Axis "z"',
            f'  .Outerradius "{fmt_num(r_outer)}"',
            f'  .Innerradius "{fmt_num(r_inner)}"',
            f'  .Zrange "{fmt_num(z0)}", "{fmt_num(z1)}"',
            f'  .Xcenter "{fmt_num(xc)}"',
            f'  .Ycenter "{fmt_num(yc)}"',
            "  .Segments \"0\"",
            "  .Create",
            "End With",
        ]
    )


def solid_add(a, b):
    return f'Solid.Add "{a}", "{b}"'


def solid_sub(a, b):
    return f'Solid.Subtract "{a}", "{b}"'


def octagon_extrude(comp, name, mat, R, z0, z1, corner_round=0.0):
    """Regular octagon extruded along +Z (official Extrude pointlist + LineTo).

    CST Extrude does **not** support .Top / .Bottom / Origin vectors in pointlist
    mode (those caused ActiveX "no such property"). Profile is in XY; Height is
    metal thickness. Substrate top is at z0 — we create at z=0 then translate
    in Z if needed, or set Height only with profile on z=0 plane and move solid.
    """
    n = 8
    pts: list[tuple[float, float]] = []
    if corner_round and corner_round > 0.05:
        for k in range(n):
            a0 = math.pi / 8 + k * math.pi / 4
            a1 = math.pi / 8 + (k + 1) * math.pi / 4
            for t in (0.0, 0.4, 0.7):
                a = a0 + t * (a1 - a0)
                scale = R * (1.0 - 0.015 * math.sin(t * math.pi) ** 2)
                pts.append((scale * math.cos(a), scale * math.sin(a)))
    else:
        for k in range(n):
            a = math.pi / 8 + k * math.pi / 4
            pts.append((R * math.cos(a), R * math.sin(a)))

    # Official example: Mode "pointlist", first .Point then .LineTo..., close loop
    h = z1 - z0
    lines = [
        "With Extrude",
        "  .Reset",
        f'  .Name "{vba_str(name)}"',
        f'  .Component "{vba_str(comp)}"',
        f'  .Material "{vba_str(mat)}"',
        '  .Mode "pointlist"',
        f'  .Height "{fmt_num(h)}"',
        '  .Twist "0.0"',
        '  .Taper "0.0"',
    ]
    x0, y0 = pts[0]
    lines.append(f'  .Point "{fmt_num(x0)}", "{fmt_num(y0)}"')
    for x, y in pts[1:]:
        lines.append(f'  .LineTo "{fmt_num(x)}", "{fmt_num(y)}"')
    lines.append(f'  .LineTo "{fmt_num(x0)}", "{fmt_num(y0)}"')
    lines += ["  .Create", "End With"]
    # Extrude typically builds from z=0; translate patch up onto substrate
    if abs(z0) > 1e-9:
        lines += [
            "With Transform",
            "  .Reset",
            f'  .Name "{comp}:{name}"',
            '  .Vector "0", "0", "' + fmt_num(z0) + '"',
            '  .MultipleObjects "False"',
            '  .GroupObjects "False"',
            '  .Repetitions "1"',
            '  .Transform "Shape", "Translate"',
            "End With",
        ]
    return "\n".join(lines)


def rotate_shape(solid, angle_deg, axis="z"):
    return "\n".join(
        [
            "With Transform",
            "  .Reset",
            f'  .Name "{solid}"',
            '  .Origin "Free"',
            '  .Center "0", "0", "0"',
            f'  .Angle "0", "0", "{fmt_num(angle_deg)}"' if axis == "z" else f'  .Angle "{fmt_num(angle_deg)}", "0", "0"',
            '  .MultipleObjects "False"',
            '  .GroupObjects "False"',
            '  .Repetitions "1"',
            '  .MultipleSelection "False"',
            '  .Transform "Shape", "Rotate"',
            "End With",
        ]
    )


def discrete_port(pn, x, y, z1, z2, r=0.3):
    return "\n".join(
        [
            "With DiscretePort",
            "  .Reset",
            f'  .PortNumber "{pn}"',
            '  .Type "Sparameter"',
            '  .Label ""',
            '  .Folder ""',
            '  .Impedance "50.0"',
            '  .VoltagePortImpedance "0.0"',
            '  .Voltage "1.0"',
            '  .Current "1.0"',
            f'  .SetP1 "False", "{fmt_num(x)}", "{fmt_num(y)}", "{fmt_num(z1)}"',
            f'  .SetP2 "False", "{fmt_num(x)}", "{fmt_num(y)}", "{fmt_num(z2)}"',
            '  .InvertDirection "False"',
            '  .LocalCoordinates "False"',
            '  .Monitor "True"',
            f'  .Radius "{fmt_num(r)}"',
            "  .Create",
            "End With",
        ]
    )


def store_params(params: dict) -> str:
    return "\n".join(f'StoreParameter "{k}", "{fmt_num(float(v))}"' for k, v in params.items())


def build_model(c: CSTClient, p: dict) -> list[dict]:
    """Build complete antenna with numeric geometry from parameter dict."""
    R = float(p["patch_R"])
    gnd = float(p["gnd_size"])
    h = H
    mt = METAL
    z0, z1 = h, h + mt

    # Slot params
    dumb_len = float(p["dumb_len"])  # total half-length along diagonal
    dumb_w = float(p["dumb_w"])
    dumb_r = float(p["dumb_r"])  # end disk radius
    arc1_span = float(p["arc1_span_deg"])  # degrees of arc
    arc2_span = float(p["arc2_span_deg"])
    arc1_w = float(p["arc1_w"])
    arc2_w = float(p["arc2_w"])
    arc_rmid = float(p["arc_rmid"])  # mid radius of curved slots
    feed_x = float(p["feed_x"])
    feed_y = float(p["feed_y"])
    corner_soft = float(p.get("corner_soft", 1.0))

    log = []
    steps = []

    steps.append(
        (
            "units",
            'With Units\n  .SetUnit "Length", "mm"\n  .SetUnit "Frequency", "GHz"\n  .SetUnit "Time", "ns"\nEnd With',
        )
    )
    steps.append(("params", store_params(p)))
    steps.append(
        (
            "mat_ro4003c",
            VBABuilder("Material")
            .call("Reset")
            .set("Name", "RO4003C")
            .set("Type", "Normal")
            .set_triple("Colour", 0.85, 0.75, 0.35)
            .set_number("Transparency", 0.25)
            .set_number("Epsilon", EPS_R)
            .set_number("Mu", 1.0)
            .set_number("TanD", TAN_D)
            .set_number("TanDFreq", F0)
            .set("TanDGiven", "True")
            .set("TanDModel", "ConstTanD")
            .call("Create")
            .build(),
        )
    )
    # Copper as lossy-ish metal (PEC ok for speed; use PEC for mesh stability)
    steps.append(
        (
            "gnd",
            brick("Antenna", "Ground", "PEC", -gnd / 2, gnd / 2, -gnd / 2, gnd / 2, -mt, 0),
        )
    )
    steps.append(
        (
            "sub",
            brick("Antenna", "Substrate", "RO4003C", -gnd / 2, gnd / 2, -gnd / 2, gnd / 2, 0, h),
        )
    )
    # Rounded octagon patch
    steps.append(
        (
            "patch",
            octagon_extrude("Antenna", "Patch", "PEC", R, z0, z1, corner_round=corner_soft),
        )
    )

    # --- Diagonal dumbbell slot (along 45°) ---
    # Build dumbbell along X then rotate 45°
    half = dumb_len / 2
    steps.append(
        (
            "db_bar",
            brick(
                "Slots",
                "DumbBar",
                "PEC",
                -half,
                half,
                -dumb_w / 2,
                dumb_w / 2,
                z0 - 0.001,
                z1 + 0.001,
            ),
        )
    )
    steps.append(
        (
            "db_c1",
            cylinder_z("Slots", "DumbC1", "PEC", dumb_r, 0, z0 - 0.001, z1 + 0.001, -half, 0),
        )
    )
    steps.append(
        (
            "db_c2",
            cylinder_z("Slots", "DumbC2", "PEC", dumb_r, 0, z0 - 0.001, z1 + 0.001, half, 0),
        )
    )
    steps.append(("db_add1", solid_add("Slots:DumbBar", "Slots:DumbC1")))
    steps.append(("db_add2", solid_add("Slots:DumbBar", "Slots:DumbC2")))
    steps.append(("db_rot", rotate_shape("Slots:DumbBar", 45.0)))
    steps.append(("db_cut", solid_sub("Antenna:Patch", "Slots:DumbBar")))

    # --- Unequal curved (arc) slots near opposite edges ---
    # Arc = annular sector via full ring then subtract wedges (bricks)
    def arc_slot(name: str, r_mid: float, width: float, span_deg: float, rot_deg: float, y_sign: float):
        r_out = r_mid + width / 2
        r_in = max(r_mid - width / 2, 0.2)
        # Place arc centered at angle rot_deg, span span_deg
        # Build ring then keep only sector using two cutting planes approximated by large bricks
        parts = []
        ring = f"{name}Ring"
        parts.append(
            (
                f"{name}_ring",
                cylinder_z("Slots", ring, "PEC", r_out, r_in, z0 - 0.001, z1 + 0.001, 0, 0),
            )
        )
        # Cut away most of ring: keep sector around +Y or -Y side, then rotate
        # Use a large brick covering half-plane opposite to desired sector
        # Sector from -span/2 to +span/2 around +Y after rotation
        # Subtract two bricks rotated to form a V keep region
        cut1, cut2 = f"{name}Cut1", f"{name}Cut2"
        # Simple approach: rectangular chord slot at r_mid with length = r_mid*span_rad
        # More reliable for meshing than thin annular sector
        span_rad = math.radians(span_deg)
        chord = r_mid * span_rad
        # Chord-aligned rectangle, then rotate
        parts.append(
            (
                f"{name}_chord",
                brick(
                    "Slots",
                    name + "Ch",
                    "PEC",
                    -chord / 2,
                    chord / 2,
                    r_mid - width / 2,
                    r_mid + width / 2,
                    z0 - 0.001,
                    z1 + 0.001,
                ),
            )
        )
        # Slight arc approximation: three offset bricks
        for i, da in enumerate((-span_deg / 4, span_deg / 4)):
            a = math.radians(da)
            cx = r_mid * math.sin(a)
            cy = r_mid * math.cos(a)
            # small tangential bricks
            parts.append(
                (
                    f"{name}_seg{i}",
                    brick(
                        "Slots",
                        f"{name}S{i}",
                        "PEC",
                        cx - chord / 6,
                        cx + chord / 6,
                        cy - width / 2,
                        cy + width / 2,
                        z0 - 0.001,
                        z1 + 0.001,
                    ),
                )
            )
            parts.append((f"{name}_add{i}", solid_add(f"Slots:{name}Ch", f"Slots:{name}S{i}")))
        parts.append((f"{name}_rot", rotate_shape(f"Slots:{name}Ch", rot_deg)))
        parts.append((f"{name}_cut", solid_sub("Antenna:Patch", f"Slots:{name}Ch")))
        # delete unused ring attempt - skip ring if using chord
        return [x for x in parts if "ring" not in x[0]]

    # Arc1 near +Y edge, shorter; Arc2 near -Y, longer — opposite edges, unequal
    steps.extend(arc_slot("Arc1", arc_rmid, arc1_w, arc1_span, 0.0, 1.0))
    steps.extend(arc_slot("Arc2", arc_rmid * 0.98, arc2_w, arc2_span, 180.0, -1.0))
    # Rotate arc pair slightly off-axis for CP (common design trick)
    # already at 0 and 180; add small asymmetry via different spans

    # --- Coax / probe feed ---
    # Discrete edge must run in NON-metal (dielectric/air). Do NOT place a PEC via
    # on the same line as the port — that triggers:
    #   "Staircasing failed ... completely inside metal material"
    # Clear a hole in ground so the probe is not shorted into the ground plane.
    # Port: ground-top z=0 → patch-bottom z=h through substrate (CST models the pin).
    hole_r = float(p.get("hole_r", 1.0))
    port_r = float(p.get("via_r", 0.25))  # discrete-port radius only
    steps.append(
        (
            "hole_gnd",
            cylinder_z(
                "Antenna", "GndHole", "Vacuum", hole_r, 0, -mt - 0.02, 0.02, feed_x, feed_y
            ),
        )
    )
    steps.append(("sub_gnd_hole", solid_sub("Antenna:Ground", "Antenna:GndHole")))
    # Port endpoint z1 just above ground hole (z=0+), z2 just below patch metal bottom
    steps.append(
        (
            "port",
            discrete_port(1, feed_x, feed_y, 0.0, h - 1e-3, r=port_r),
        )
    )

    steps.append(
        (
            "freq",
            f'With Solver\n  .FrequencyRange "{fmt_num(FMIN)}", "{fmt_num(FMAX)}"\nEnd With',
        )
    )
    # Open BC: reference frequency must be <= lowest monitor (0.867). Mid-band 0.875 was wrong.
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
                    'Boundary.MinimumDistanceType "Fraction"',
                    'Boundary.MinimumDistanceReferenceFrequencyType "User"',
                    f'Boundary.FrequencyForMinimumDistance "{fmt_num(FMIN)}"',
                    'Boundary.MinimumDistancePerWavelength "8"',
                ]
            ),
        )
    )
    steps.append(("ff", farfield_monitor_vba(f"farfield (f={fmt_num(F0)})", F0)))
    steps.append(("solver", 'ChangeSolverType "HF Time Domain"'))
    # Steady state
    steps.append(
        (
            "solver_acc",
            'With Solver\n  .SteadyStateLimit "-40"\n  .StimulationPort "All"\n  .StimulationMode "All"\nEnd With',
        )
    )

    for label, vba in steps:
        r = c.run_history(vba, label=label)
        st = r.get("status")
        msg = str(r.get("message") or r.get("result") or "")[:120]
        log.append({"label": label, "status": st, "message": msg})
        if st == "error":
            print(f"  ERR {label}: {msg}")
        else:
            print(f"  ok  {label}")
    return log


def s11_at(project: str, f_ghz: float) -> dict:
    r = read_1d_item(project, r"1D Results\S-Parameters\S1,1")
    if r.get("status") != "ok":
        return {"status": "error", "message": r.get("message")}
    xs, ys = r["x"], r["y"]
    i = min(range(len(xs)), key=lambda j: abs(xs[j] - f_ghz))
    i_min = min(range(len(ys)), key=lambda j: ys[j])
    return {
        "status": "ok",
        "s11_at_f_db": ys[i],
        "f_sample_ghz": xs[i],
        "s11_min_db": ys[i_min],
        "s11_min_freq_ghz": xs[i_min],
        "n": len(xs),
    }



def axial_ratio_boresight(c: CSTClient, f_ghz: float) -> dict:
    """FarfieldPlot axial-ratio mode: GetMin~best purity on sphere, GetMax~worst."""
    out = Path(r"E:/cstprojects/exports/rfid_ar.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    tree = rf"Farfields\farfield (f={fmt_num(f_ghz)}) [1]"
    path = out.as_posix()
    vba = "\n".join(
        [
            "Dim ok As Boolean",
            f'Open "{path}" For Output As #1',
            "On Error Resume Next",
            f'ok = SelectTreeItem("{tree}")',
            'Print #1, "select=" & CStr(ok)',
            "If Not ok Then",
            f'  ok = SelectTreeItem("Farfields\\farfield (f={fmt_num(f_ghz)})")',
            '  Print #1, "select2=" & CStr(ok)',
            "End If",
            "With FarfieldPlot",
            "  .Reset",
            '  .Plottype ("3d")',
            "  .Step (5)",
            "  .Step2 (5)",
            "  .SetLockSteps (True)",
            '  .SetPlotMode ("axial ratio")',
            "  .SetScaleLinear (False)",
            '  .Origin ("bbox")',
            "  .Plot",
            "End With",
            'Print #1, "AR_GetMax_dB=" & CStr(FarfieldPlot.GetMax)',
            'Print #1, "AR_GetMin_dB=" & CStr(FarfieldPlot.GetMin)',
            'Print #1, "mode=" & CStr(FarfieldPlot.GetPlotMode)',
            "Close #1",
        ]
    )
    try:
        res = c.execute_vba_silent(vba)
    except Exception as e:
        res = {"status": "error", "message": str(e)[:300]}
    text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            parsed[k.strip()] = v.strip()
    return {"status": "ok" if text else "error", "raw": text[:800], "parsed": parsed, "vba": res}


def evaluate(c: CSTClient, p: dict) -> dict:
    t0 = time.time()
    # rebuild path: for first design we full build; for sweep rebuild project fresh is safer
    c.delete_results()
    # For sweep we'll rebuild whole model from new project
    sol = c.run_solver(timeout_s=1200)
    dt = round(time.time() - t0, 1)
    path = c.project_path or str(PROJ)
    s11 = s11_at(path, F0)
    am = antenna_metrics_from_results(path, F0)
    ff = c.get_farfield_metrics(F0, try_farfield_plot=True)
    ar = axial_ratio_boresight(c, F0)
    m = ff.get("metrics") or {}
    # efficiency: prefer total from API
    tot = m.get("total_efficiency") or m.get("tot_efficiency_linear")
    if tot is None and m.get("total_efficiency_db") is not None:
        tot = 10 ** (float(m["total_efficiency_db"]) / 10.0)
    if tot is None:
        tot = (am.get("metrics") or {}).get("tot_efficiency_linear")
    rad = m.get("radiation_efficiency") or (am.get("metrics") or {}).get("rad_efficiency_linear")
    gain = m.get("max_realized_gain_dbi")
    # AR: GetMax in axial ratio mode is often max AR (worst) — GetMin better for best polarization purity on sphere
    ar_p = ar.get("parsed") or {}
    try:
        ar_min = float(ar_p.get("AR_GetMin_dB", "nan"))
        ar_max = float(ar_p.get("AR_GetMax_dB", "nan"))
    except ValueError:
        ar_min, ar_max = float("nan"), float("nan")
    # For boresight CP, min AR on sphere can be optimistic; use min as best-case indicator
    out = {
        "params": p,
        "solve": sol,
        "solve_s": dt,
        "s11": s11,
        "gain_realized_dbi": gain,
        "total_efficiency": tot,
        "rad_efficiency": rad,
        "ar_min_db": ar_min,
        "ar_max_db": ar_max,
        "ar_detail": ar,
        "ff_status": ff.get("status"),
        "goals": {
            "s11_ok": (s11.get("s11_at_f_db") is not None and s11["s11_at_f_db"] <= -15),
            "ar_ok": (ar_min == ar_min and ar_min < 3.0),  # not NaN and <3
            "gain_ok": (gain is not None and gain >= 4.5),
            "eff_ok": (tot is not None and tot >= 0.70),
        },
    }
    g = out["goals"]
    out["score"] = sum(1 for v in g.values() if v)
    print(
        f"  R={p['patch_R']:.2f} feed=({p['feed_x']:.2f},{p['feed_y']:.2f}) "
        f"dumb={p['dumb_len']:.1f} a1={p['arc1_span_deg']:.0f}/a2={p['arc2_span_deg']:.0f} | "
        f"S11@867={s11.get('s11_at_f_db')} min={s11.get('s11_min_db')}@{s11.get('s11_min_freq_ghz')} | "
        f"G={gain} ηtot={tot} AR_min={ar_min} score={out['score']}/4 t={dt}s"
    )
    return out


def default_params() -> dict:
    # Circular patch radius estimate for RO4003C @867 MHz ~ 50-55 mm
    R = 51.0
    return {
        "freq_GHz": F0,
        "eps_r": EPS_R,
        "tan_d": TAN_D,
        "sub_h": H,
        "metal_t": METAL,
        "patch_R": R,
        "gnd_size": R * 2 * 2.2,
        "dumb_len": 28.0,
        "dumb_w": 1.2,
        "dumb_r": 2.4,
        "arc1_span_deg": 55.0,
        "arc2_span_deg": 75.0,
        "arc1_w": 1.0,
        "arc2_w": 1.2,
        "arc_rmid": R * 0.62,
        "feed_x": 8.0,
        "feed_y": 6.0,
        "via_r": 0.45,
        "corner_soft": 1.0,
        "fmin_GHz": FMIN,
        "fmax_GHz": FMAX,
    }


def fresh_project(c: CSTClient, p: dict) -> list:
    print("NEW", c.new_project(str(PROJ)))
    log = build_model(c, p)
    c.save_project()
    return log


def main():
    cfg = CSTConfig.from_env()
    cfg.work_dir = Path(r"E:\cstprojects")
    c = CSTClient(cfg)
    print("CONNECT", c.connect())

    base = default_params()
    trials = []

    # --- Design 0: baseline ---
    print("=== BUILD baseline ===")
    fresh_project(c, base)
    trials.append(evaluate(c, base))

    # Limited sweep: patch size (frequency), feed offset (match/CP), dumbbell length (mode split)
    print("=== SWEEP patch_R ===")
    for dR in (-4.0, -2.0, 2.0, 4.0):
        p = dict(base)
        p["patch_R"] = base["patch_R"] + dR
        p["gnd_size"] = p["patch_R"] * 2 * 2.2
        p["arc_rmid"] = p["patch_R"] * 0.62
        fresh_project(c, p)
        trials.append(evaluate(c, p))

    best = max(trials, key=lambda t: (t["score"], -(t["s11"].get("s11_at_f_db") or 0)))
    base2 = dict(best["params"])
    print("best after R", best["score"], base2["patch_R"])

    print("=== SWEEP feed offset ===")
    for fx, fy in [(5, 5), (8, 4), (10, 8), (12, 6), (6, 10)]:
        p = dict(base2)
        p["feed_x"], p["feed_y"] = float(fx), float(fy)
        fresh_project(c, p)
        trials.append(evaluate(c, p))

    best = max(trials, key=lambda t: (t["score"], -(t["s11"].get("s11_at_f_db") or 0)))
    base3 = dict(best["params"])

    print("=== SWEEP dumb_len / arc asymmetry ===")
    for dl, a1, a2 in [(24, 50, 80), (28, 55, 75), (32, 45, 85), (30, 60, 70)]:
        p = dict(base3)
        p["dumb_len"] = float(dl)
        p["arc1_span_deg"] = float(a1)
        p["arc2_span_deg"] = float(a2)
        fresh_project(c, p)
        trials.append(evaluate(c, p))

    best = max(
        trials,
        key=lambda t: (
            t["score"],
            -(t["s11"].get("s11_at_f_db") or 0),
            t.get("gain_realized_dbi") or -99,
        ),
    )

    # Final re-run
    print("=== FINAL ===")
    fresh_project(c, best["params"])
    final = evaluate(c, best["params"])
    c.save_project(str(PROJ))

    report = {
        "project": str(PROJ),
        "description": (
            "Compact CP UHF RFID reader antenna: RO4003C, full ground, rounded octagonal "
            "patch, diagonal dumbbell slot, two unequal edge arc/chord slots, offset coax (discrete) feed."
        ),
        "substrate": {"material": "Rogers RO4003C", "eps_r": EPS_R, "h_mm": H, "tan_d": TAN_D},
        "freq_range_ghz": [FMIN, FMAX],
        "targets": {
            "s11_db_at_867": -15,
            "axial_ratio_db": 3,
            "realized_gain_dbi": 4.5,
            "total_efficiency": 0.70,
            "pattern": "broadside CP",
        },
        "n_trials": len(trials),
        "final_dimensions_mm": {
            "patch_circumradius_R": final["params"]["patch_R"],
            "ground_size": final["params"]["gnd_size"],
            "substrate_thickness": H,
            "metal_thickness": METAL,
            "dumbbell_length": final["params"]["dumb_len"],
            "dumbbell_bar_width": final["params"]["dumb_w"],
            "dumbbell_end_radius": final["params"]["dumb_r"],
            "arc1_span_deg": final["params"]["arc1_span_deg"],
            "arc2_span_deg": final["params"]["arc2_span_deg"],
            "arc1_width": final["params"]["arc1_w"],
            "arc2_width": final["params"]["arc2_w"],
            "arc_mid_radius": final["params"]["arc_rmid"],
            "feed_x": final["params"]["feed_x"],
            "feed_y": final["params"]["feed_y"],
            "via_radius": final["params"]["via_r"],
        },
        "final_results": {
            "s11": final.get("s11"),
            "realized_gain_dbi": final.get("gain_realized_dbi"),
            "total_efficiency": final.get("total_efficiency"),
            "rad_efficiency": final.get("rad_efficiency"),
            "ar_min_db": final.get("ar_min_db"),
            "ar_max_db": final.get("ar_max_db"),
            "goals": final.get("goals"),
            "score": final.get("score"),
            "solve_s": final.get("solve_s"),
        },
        "all_trials_summary": [
            {
                "R": t["params"]["patch_R"],
                "feed": [t["params"]["feed_x"], t["params"]["feed_y"]],
                "dumb_len": t["params"]["dumb_len"],
                "arcs": [t["params"]["arc1_span_deg"], t["params"]["arc2_span_deg"]],
                "s11_867": (t.get("s11") or {}).get("s11_at_f_db"),
                "s11_min": (t.get("s11") or {}).get("s11_min_db"),
                "f_min": (t.get("s11") or {}).get("s11_min_freq_ghz"),
                "gain": t.get("gain_realized_dbi"),
                "eff": t.get("total_efficiency"),
                "ar_min": t.get("ar_min_db"),
                "score": t.get("score"),
            }
            for t in trials
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["final_dimensions_mm"], indent=2))
    print(json.dumps(report["final_results"], indent=2, default=str))
    print("wrote", OUT)
    print("project", PROJ)
    return 0


if __name__ == "__main__":
    # Fix axial_ratio to use client properly
    raise SystemExit(main())
