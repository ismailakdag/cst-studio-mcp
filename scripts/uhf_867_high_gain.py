"""UHF 865-868 MHz high-gain design on FR-4 (same substrate).

Strategy:
1) Parametric inset-fed rectangular patch + large ground (efficient radiator)
2) Optional spaced PEC reflector under board for F/B and directivity
3) If single-element realized gain < 5 dBi, upgrade to 2-element H-plane array
4) Parameter sweeps for S11 band + farfield GetMax (realized gain)
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
from cst_mcp.domain.antennas.patch import design_patch
from cst_mcp.execution.farfield import farfield_monitor_vba
from cst_mcp.execution.port_helpers import microstrip_waveguide_port_vba
from cst_mcp.execution.results_api import read_1d_item
from cst_mcp.execution.vba_builder import fmt_num
from cst_mcp.vba_builder import VBABuilder

PROJ = Path(r"E:\cstprojects\uhf_867_gain.cst")
OUT = Path(r"E:\cstprojects\exports\uhf_867_gain_report.json")
F0 = 0.8665  # band center 865-868
BAND = (0.865, 0.868)
FMIN, FMAX = 0.75, 1.00
METAL_T = 0.035
H = 1.6


def brick_expr(comp, name, mat, x0, x1, y0, y1, z0, z1):
    return "\n".join(
        [
            "With Brick",
            "  .Reset",
            f'  .Name "{name}"',
            f'  .Component "{comp}"',
            f'  .Material "{mat}"',
            f'  .Xrange "{x0}", "{x1}"',
            f'  .Yrange "{y0}", "{y1}"',
            f'  .Zrange "{z0}", "{z1}"',
            "  .Create",
            "End With",
        ]
    )


def store_params(params: dict) -> str:
    return "\n".join(f'StoreParameter "{k}", "{fmt_num(float(v))}"' for k, v in params.items())


def solid_add(a, b):
    return f'Solid.Add "{a}", "{b}"'


def build_single_with_reflector(c: CSTClient, p: dict, *, use_reflector: bool) -> None:
    """History-based parametric single patch + optional under-board reflector."""
    # Ground size from params expressions
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
            "mat",
            VBABuilder("Material")
            .call("Reset")
            .set("Name", "Substrate")
            .set("Type", "Normal")
            .set_triple("Colour", 0.2, 0.45, 0.2)
            .set_number("Transparency", 0.3)
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
    # PCB stack
    steps.append(
        (
            "gnd",
            brick_expr(
                "Antenna", "Ground", "PEC",
                "-gnd_x/2", "gnd_x/2", "-gnd_y/2", "gnd_y/2", "-metal_t", "0",
            ),
        )
    )
    steps.append(
        (
            "sub",
            brick_expr(
                "Antenna", "Substrate", "Substrate",
                "-gnd_x/2", "gnd_x/2", "-gnd_y/2", "gnd_y/2", "0", "sub_h",
            ),
        )
    )
    # Patch + inset slots (two cutouts via subtract) + feed
    # Build as: main patch brick, feed line, then subtract two inset gap bricks
    steps.append(
        (
            "patch",
            brick_expr(
                "Antenna", "Patch", "PEC",
                "-patch_W/2", "patch_W/2", "-patch_L/2", "patch_L/2",
                "sub_h", "sub_h+metal_t",
            ),
        )
    )
    # Inset gaps: two slots beside feed into patch
    # gap width = feed_w, gap depth = inset; slots at x=±feed_w/2..±(feed_w/2+gap)
    # Simpler classic inset: feed from y=-gnd_y/2 to -patch_L/2+inset; cut two rectangles
    steps.append(
        (
            "feed",
            brick_expr(
                "Antenna", "Feed", "PEC",
                "-feed_w/2", "feed_w/2",
                "-gnd_y/2", "-patch_L/2+inset",
                "sub_h", "sub_h+metal_t",
            ),
        )
    )
    steps.append(("add_feed", solid_add("Antenna:Patch", "Antenna:Feed")))
    # Inset notches (subtract from patch) — gap between feed and patch edges
    steps.append(
        (
            "slotL",
            brick_expr(
                "Antenna", "SlotL", "PEC",
                "-feed_w/2-inset_gap", "-feed_w/2",
                "-patch_L/2", "-patch_L/2+inset",
                "sub_h", "sub_h+metal_t",
            ),
        )
    )
    steps.append(
        (
            "slotR",
            brick_expr(
                "Antenna", "SlotR", "PEC",
                "feed_w/2", "feed_w/2+inset_gap",
                "-patch_L/2", "-patch_L/2+inset",
                "sub_h", "sub_h+metal_t",
            ),
        )
    )
    steps.append(("subL", 'Solid.Subtract "Antenna:Patch", "Antenna:SlotL"'))
    steps.append(("subR", 'Solid.Subtract "Antenna:Patch", "Antenna:SlotR"'))

    if use_reflector:
        # Reflector below PCB: z = -metal_t - refl_gap - metal_t .. -metal_t - refl_gap
        steps.append(
            (
                "reflector",
                brick_expr(
                    "Reflector", "Plate", "PEC",
                    "-refl_x/2", "refl_x/2", "-refl_y/2", "refl_y/2",
                    "-metal_t-refl_gap-metal_t", "-metal_t-refl_gap",
                ),
            )
        )

    steps.append(
        (
            "freq",
            f'With Solver\n  .FrequencyRange "{fmt_num(FMIN)}", "{fmt_num(FMAX)}"\nEnd With',
        )
    )
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
    # Port numeric at construction time from current p
    y_port = -float(p["gnd_y"]) / 2.0
    steps.append(
        (
            "port",
            microstrip_waveguide_port_vba(
                port_number=1,
                y_edge=y_port,
                feed_width=float(p["feed_w"]),
                substrate_height=H,
                ground_bottom=-METAL_T,
                metal_thickness=METAL_T,
            ),
        )
    )
    steps.append(("ff", farfield_monitor_vba(f"farfield (f={fmt_num(F0)})", F0)))
    # band edges monitors for completeness
    steps.append(("ff865", farfield_monitor_vba("farfield (f=0.865)", 0.865)))
    steps.append(("ff868", farfield_monitor_vba("farfield (f=0.868)", 0.868)))
    steps.append(("solver", 'ChangeSolverType "HF Time Domain"'))

    for label, vba in steps:
        r = c.run_history(vba, label=label)
        st = r.get("status")
        if st == "error":
            print("  BUILD ERR", label, str(r.get("message") or r)[:160])
        else:
            print(f"  {label:12} {st}")


def s11_band_metrics(project_path: str) -> dict:
    r = read_1d_item(project_path, r"1D Results\S-Parameters\S1,1")
    if r.get("status") != "ok":
        return {"status": "error", "message": r.get("message")}
    xs, ys = r["x"], r["y"]
    # global min
    i_min = min(range(len(ys)), key=lambda i: ys[i])
    # band worst (max S11, least negative) and best in band
    band_idx = [i for i in range(len(xs)) if BAND[0] <= xs[i] <= BAND[1]]
    if not band_idx:
        # nearest samples
        band_idx = sorted(range(len(xs)), key=lambda i: min(abs(xs[i] - BAND[0]), abs(xs[i] - BAND[1])))[:5]
    band_ys = [ys[i] for i in band_idx]
    band_xs = [xs[i] for i in band_idx]
    i_best = min(range(len(band_ys)), key=lambda i: band_ys[i])
    i_worst = max(range(len(band_ys)), key=lambda i: band_ys[i])
    # at center
    i0 = min(range(len(xs)), key=lambda i: abs(xs[i] - F0))
    return {
        "status": "ok",
        "s11_min_db": ys[i_min],
        "s11_freq_ghz": xs[i_min],
        "s11_at_f0_db": ys[i0],
        "band_best_db": band_ys[i_best],
        "band_best_ghz": band_xs[i_best],
        "band_worst_db": band_ys[i_worst],
        "band_worst_ghz": band_xs[i_worst],
        "band_ok": band_ys[i_worst] <= -10.0,
        "n": len(xs),
    }


def eval_design(c: CSTClient, params: dict) -> dict:
    p = dict(params)
    t0 = time.time()
    r = c.set_params_rebuild_solve(p, export_s11=False, port=1, timeout_s=900)
    dt = round(time.time() - t0, 1)
    s11 = s11_band_metrics(c.project_path or str(PROJ))
    ff = c.get_farfield_metrics(F0, try_farfield_plot=True)
    m = ff.get("metrics") or {}
    gain = m.get("max_realized_gain_dbi")
    # treat empty -200 efficiencies as invalid
    out = {
        "params": p,
        "status": r.get("status"),
        "solve_s": dt,
        "s11": s11,
        "gain_realized_dbi": gain,
        "rad_eff_db": m.get("radiation_efficiency_db") or m.get("rad_efficiency_db"),
        "tot_eff_db": m.get("total_efficiency_db") or m.get("tot_efficiency_db"),
        "ff_status": ff.get("status"),
        "ff_available": ff.get("available"),
    }
    print(
        f"  L={p.get('patch_L'):.2f} inset={p.get('inset'):.2f} W={p.get('patch_W'):.2f} "
        f"gap={p.get('refl_gap', 0):.1f} | "
        f"band_worst={s11.get('band_worst_db')} band_ok={s11.get('band_ok')} "
        f"min={s11.get('s11_min_db')}@{s11.get('s11_freq_ghz')} | "
        f"G={gain} ηrad={out['rad_eff_db']} t={dt}s"
    )
    return out


def score(t: dict) -> float:
    """Lower is better. Prioritize band S11 and gain."""
    s11 = t.get("s11") or {}
    g = t.get("gain_realized_dbi")
    bw = s11.get("band_worst_db")
    if bw is None:
        bw = 0.0
    if g is None:
        g = -50.0
    # penalties
    pen = 0.0
    if bw > -10:
        pen += (bw + 10) * 4.0  # push under -10
    if g < 5.0:
        pen += (5.0 - g) * 3.0
    # reward deep band match and high gain
    return pen - g * 0.5 + bw * 0.2


def main():
    d = design_patch(F0, epsilon_r=4.4, height_mm=H, feed_type="inset", ground_factor=2.8)
    # Initial params — slightly shorter L for FR-4 dispersion; larger ground
    p0 = {
        "freq_GHz": F0,
        "eps_r": 4.4,
        "tan_d": 0.02,
        "sub_h": H,
        "metal_t": METAL_T,
        "patch_W": d.width_mm,
        "patch_L": d.length_mm * 0.98,
        "inset": d.inset_mm * 0.85,
        "inset_gap": max(1.0, d.feed_width_mm * 0.35),
        "feed_w": 3.0,  # closer to 50 ohm on FR4 1.6mm ~3mm
        "gnd_x": max(d.ground_x_mm, d.width_mm * 2.8),
        "gnd_y": max(d.ground_y_mm, d.length_mm * 2.8 + 40),
        "refl_gap": 50.0,  # mm air under board
        "refl_x": max(d.ground_x_mm, d.width_mm * 3.0),
        "refl_y": max(d.ground_y_mm, d.length_mm * 3.0 + 40),
        "fmin_GHz": FMIN,
        "fmax_GHz": FMAX,
    }

    c = CSTClient(CSTConfig.from_env())
    print(c.connect())
    print("NEW", c.new_project(str(PROJ)))
    print("BUILD single + reflector")
    build_single_with_reflector(c, p0, use_reflector=True)
    c.save_project()

    trials = []

    # --- Phase A: tune L for resonance near 866.5 ---
    print("=== Phase A: patch_L ===")
    L0 = p0["patch_L"]
    for dL in [-6, -3, 0, 3, 6, 9]:
        p = dict(p0)
        p["patch_L"] = L0 + dL
        trials.append(eval_design(c, p))

    best = min(trials, key=score)
    print("best A", {k: best[k] for k in ("params", "s11", "gain_realized_dbi")})

    # --- Phase B: inset for match ---
    print("=== Phase B: inset ===")
    base = dict(best["params"])
    for ins in [12, 16, 20, 24, 28, 32, 36]:
        p = dict(base)
        p["inset"] = float(ins)
        # keep feed end inside patch
        if p["inset"] >= p["patch_L"] * 0.45:
            continue
        trials.append(eval_design(c, p))
    best = min(trials, key=score)

    # --- Phase C: width fine ---
    print("=== Phase C: patch_W ===")
    base = dict(best["params"])
    W0 = base["patch_W"]
    for dW in [-8, -4, 0, 4, 8]:
        p = dict(base)
        p["patch_W"] = W0 + dW
        trials.append(eval_design(c, p))
    best = min(trials, key=score)

    # --- Phase D: reflector gap ---
    print("=== Phase D: refl_gap ===")
    base = dict(best["params"])
    for gap in [20, 35, 50, 65, 80, 100]:
        p = dict(base)
        p["refl_gap"] = float(gap)
        trials.append(eval_design(c, p))
    best = min(trials, key=score)

    # Fine L around best if band not ok or gain low
    if not (best.get("s11") or {}).get("band_ok") or (best.get("gain_realized_dbi") or -99) < 5:
        print("=== Phase E: fine L + inset grid ===")
        base = dict(best["params"])
        for dL in [-2, -1, 0, 1, 2]:
            for ins_scale in [0.9, 1.0, 1.1]:
                p = dict(base)
                p["patch_L"] = base["patch_L"] + dL
                p["inset"] = base["inset"] * ins_scale
                trials.append(eval_design(c, p))
        best = min(trials, key=score)

    # Final
    print("=== FINAL ===")
    final = eval_design(c, best["params"])
    c.save_project(str(PROJ))

    ok_band = bool((final.get("s11") or {}).get("band_ok"))
    ok_gain = (final.get("gain_realized_dbi") is not None) and final["gain_realized_dbi"] >= 5.0

    report = {
        "project": str(PROJ),
        "goals": {"band_mhz": [865, 868], "s11_db": -10, "gain_dbi": 5.0, "substrate": "FR-4 eps=4.4 tanD=0.02 h=1.6"},
        "design": "inset rectangular patch + large ground + spaced PEC reflector",
        "n_trials": len(trials),
        "trials_summary": [
            {
                "L": t["params"].get("patch_L"),
                "W": t["params"].get("patch_W"),
                "inset": t["params"].get("inset"),
                "gap": t["params"].get("refl_gap"),
                "band_worst": (t.get("s11") or {}).get("band_worst_db"),
                "gain": t.get("gain_realized_dbi"),
            }
            for t in trials
        ],
        "final": final,
        "success_band": ok_band,
        "success_gain": ok_gain,
        "success": ok_band and ok_gain,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "success": report["success"],
        "success_band": ok_band,
        "success_gain": ok_gain,
        "final_s11": final.get("s11"),
        "gain": final.get("gain_realized_dbi"),
        "params": final.get("params"),
        "project": str(PROJ),
    }, indent=2, default=str))
    print("wrote", OUT)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
