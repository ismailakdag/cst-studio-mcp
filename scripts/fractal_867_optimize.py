"""Parametric Minkowski fractal @ 867 MHz — optimize frac_S (no redesign).

1) Build once with CST Parameter List expressions
2) Sweep frac_S via StoreParameter → DeleteResults → Rebuild → Solve
3) Pick best S11; refine; report
"""
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
from cst_mcp.execution.farfield import farfield_monitor_vba
from cst_mcp.execution.port_helpers import microstrip_waveguide_port_vba
from cst_mcp.execution.vba_builder import fmt_num, vba_str
from cst_mcp.vba_builder import VBABuilder

PROJ = Path(r"E:\cstprojects\fractal_867_opt.cst")
OUT = Path(r"E:\cstprojects\exports\fractal_867_opt.json")
F0 = 0.867
FMIN, FMAX = 0.55, 1.25


def brick_expr(component, name, material, x0, x1, y0, y1, z0, z1):
    return "\n".join(
        [
            "With Brick",
            "  .Reset",
            f'  .Name "{name}"',
            f'  .Component "{component}"',
            f'  .Material "{material}"',
            f'  .Xrange "{x0}", "{x1}"',
            f'  .Yrange "{y0}", "{y1}"',
            f'  .Zrange "{z0}", "{z1}"',
            "  .Create",
            "End With",
        ]
    )


def solid_add(dst, src):
    return f'Solid.Add "{dst}", "{src}"'


def store_params(params: dict[str, float]) -> str:
    return "\n".join(f'StoreParameter "{k}", "{fmt_num(v)}"' for k, v in params.items())


def build_parametric(c: CSTClient, p0: dict[str, float]) -> list[dict]:
    """Create parametric project history once."""
    steps_log = []
    # Fixed large ground so size sweeps don't break the port plane
    gx, gy = 200.0, 240.0
    h, mt, fw = 1.6, 0.035, float(p0["feed_w"])
    y_port = -gy / 2.0

    steps = []
    steps.append(
        (
            "units",
            'With Units\n  .SetUnit "Length", "mm"\n  .SetUnit "Frequency", "GHz"\n  .SetUnit "Time", "ns"\nEnd With',
        )
    )
    steps.append(("params", store_params(p0)))
    steps.append(
        (
            "mat",
            VBABuilder("Material")
            .call("Reset")
            .set("Name", "Substrate")
            .set("Type", "Normal")
            .set_triple("Colour", 0.15, 0.45, 0.2)
            .set_number("Transparency", 0.35)
            .set("Epsilon", "eps_r")
            .set_number("Mu", 1.0)
            .set("TanD", "tan_d")
            .set_number("TanDFreq", 0.0)
            .set("TanDGiven", "True")
            .set("TanDModel", "ConstTanD")
            .call("Create")
            .build(),
        )
    )
    # Ground / substrate fixed numeric extents (stable port)
    steps.append(
        (
            "gnd",
            brick_expr(
                "Antenna", "Ground", "PEC",
                f"{-gx/2}", f"{gx/2}", f"{-gy/2}", f"{gy/2}", "-metal_t", "0",
            ),
        )
    )
    steps.append(
        (
            "sub",
            brick_expr(
                "Antenna", "Substrate", "Substrate",
                f"{-gx/2}", f"{gx/2}", f"{-gy/2}", f"{gy/2}", "0", "sub_h",
            ),
        )
    )
    # Parametric fractal metal (frac_S, frac_depth drive everything)
    # mid half-width of bump = frac_S/6 ; secondary d2 = frac_depth*0.4 ; w2 = frac_S/12
    z0, z1 = "sub_h", "sub_h+metal_t"
    steps.append(
        (
            "core",
            brick_expr(
                "Antenna", "FracCore", "PEC",
                "-frac_S/2", "frac_S/2", "-frac_S/2", "frac_S/2", z0, z1,
            ),
        )
    )
    bumps = [
        ("BumpN", "-frac_S/6", "frac_S/6", "frac_S/2", "frac_S/2+frac_depth"),
        ("BumpS", "-frac_S/6", "frac_S/6", "-frac_S/2-frac_depth", "-frac_S/2"),
        ("BumpE", "frac_S/2", "frac_S/2+frac_depth", "-frac_S/6", "frac_S/6"),
        ("BumpW", "-frac_S/2-frac_depth", "-frac_S/2", "-frac_S/6", "frac_S/6"),
    ]
    for name, x0, x1, y0, y1 in bumps:
        steps.append((name, brick_expr("Antenna", name, "PEC", x0, x1, y0, y1, z0, z1)))
        steps.append((f"add_{name}", solid_add("Antenna:FracCore", f"Antenna:{name}")))

    nubs = [
        ("NubN1", "-frac_S/6-frac_S/12", "-frac_S/6", "frac_S/2+frac_depth", "frac_S/2+frac_depth+0.4*frac_depth"),
        ("NubN2", "frac_S/6", "frac_S/6+frac_S/12", "frac_S/2+frac_depth", "frac_S/2+frac_depth+0.4*frac_depth"),
        ("NubS1", "-frac_S/6-frac_S/12", "-frac_S/6", "-frac_S/2-frac_depth-0.4*frac_depth", "-frac_S/2-frac_depth"),
        ("NubS2", "frac_S/6", "frac_S/6+frac_S/12", "-frac_S/2-frac_depth-0.4*frac_depth", "-frac_S/2-frac_depth"),
        ("NubE1", "frac_S/2+frac_depth", "frac_S/2+frac_depth+0.4*frac_depth", "-frac_S/6-frac_S/12", "-frac_S/6"),
        ("NubE2", "frac_S/2+frac_depth", "frac_S/2+frac_depth+0.4*frac_depth", "frac_S/6", "frac_S/6+frac_S/12"),
        ("NubW1", "-frac_S/2-frac_depth-0.4*frac_depth", "-frac_S/2-frac_depth", "-frac_S/6-frac_S/12", "-frac_S/6"),
        ("NubW2", "-frac_S/2-frac_depth-0.4*frac_depth", "-frac_S/2-frac_depth", "frac_S/6", "frac_S/6+frac_S/12"),
    ]
    for name, x0, x1, y0, y1 in nubs:
        steps.append((name, brick_expr("Antenna", name, "PEC", x0, x1, y0, y1, z0, z1)))
        steps.append((f"add_{name}", solid_add("Antenna:FracCore", f"Antenna:{name}")))

    steps.append(("rename", 'Solid.Rename "Antenna:FracCore", "Patch"'))
    # Feed overlaps primary south bump (expression)
    steps.append(
        (
            "feed",
            brick_expr(
                "Antenna", "Feed", "PEC",
                "-feed_w/2", "feed_w/2",
                f"{y_port}", "-frac_S/2-frac_depth+1",
                z0, z1,
            ),
        )
    )
    steps.append(("add_feed", solid_add("Antenna:Patch", "Antenna:Feed")))
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
    steps.append(
        (
            "port",
            microstrip_waveguide_port_vba(
                port_number=1,
                y_edge=y_port,
                feed_width=fw,
                substrate_height=h,
                ground_bottom=-mt,
                metal_thickness=mt,
            ),
        )
    )
    steps.append(("ff", farfield_monitor_vba(f"farfield (f={fmt_num(F0)})", F0)))
    steps.append(("solver", 'ChangeSolverType "HF Time Domain"'))

    for label, vba in steps:
        r = c.run_history(vba, label=label)
        steps_log.append({"label": label, "status": r.get("status")})
        if r.get("status") == "error":
            print("ERR", label, r)
    c.save_project()
    return steps_log


def eval_params(c: CSTClient, params: dict[str, float], timeout_s: float = 600) -> dict:
    """StoreParameter → DeleteResults → Rebuild → Solve → S11 metrics."""
    t0 = time.time()
    # Keep depth linked to S unless overridden
    p = dict(params)
    if "frac_depth" not in p and "frac_S" in p:
        p["frac_depth"] = p["frac_S"] / 3.5
    r = c.set_params_rebuild_solve(p, export_s11=True, port=1, timeout_s=timeout_s)
    dt = round(time.time() - t0, 1)
    s11 = (r.get("s_parameters") or {}) if isinstance(r, dict) else {}
    metrics = s11.get("metrics") or {}
    out = {
        "params": p,
        "status": r.get("status"),
        "s11_min_db": metrics.get("min_db"),
        "s11_freq_ghz": metrics.get("freq_at_min_ghz"),
        "solve_s": dt,
        "message": r.get("message"),
    }
    # sample S11 near 867 MHz if curve available
    try:
        xs = s11.get("frequency") or s11.get("x") or []
        ys = s11.get("s_db") or s11.get("y") or []
        if xs and ys and len(xs) == len(ys):
            i = min(range(len(xs)), key=lambda j: abs(float(xs[j]) - F0))
            out["s11_at_867_db"] = float(ys[i])
            out["s11_at_867_freq"] = float(xs[i])
    except Exception:
        pass
    print(
        f"  S={p.get('frac_S'):.2f} d={p.get('frac_depth'):.2f} fw={p.get('feed_w', 3.2):.2f} "
        f"→ minS11={out.get('s11_min_db')} @{out.get('s11_freq_ghz')} GHz "
        f"@867={out.get('s11_at_867_db')}  t={dt}s  st={out['status']}"
    )
    return out


def main() -> int:
    c = CSTClient(CSTConfig.from_env())
    print(c.connect())

    # Predicted resonance: previous S=53.95 → 1.181 GHz ⇒ S≈73.5 for 0.867
    s0 = 73.5
    p0 = {
        "freq_GHz": F0,
        "eps_r": 4.4,
        "tan_d": 0.02,
        "sub_h": 1.6,
        "metal_t": 0.035,
        "frac_S": s0,
        "frac_depth": s0 / 3.5,
        "feed_w": 3.2,
        "fmin_GHz": FMIN,
        "fmax_GHz": FMAX,
    }

    print("NEW parametric project", c.new_project(str(PROJ)))
    blog = build_parametric(c, p0)
    print("build steps", sum(1 for s in blog if s["status"] == "executed"), "/", len(blog))

    trials: list[dict] = []

    # --- Coarse sweep on frac_S ---
    print("=== COARSE frac_S sweep ===")
    for s in [66.0, 70.0, 73.5, 77.0, 81.0, 85.0]:
        trials.append(eval_params(c, {"frac_S": s, "feed_w": 3.2}))

    def score(t):
        """Prefer S11 < -10 near 867 MHz; else best min_db close to 867."""
        mn = t.get("s11_min_db")
        fr = t.get("s11_freq_ghz")
        at = t.get("s11_at_867_db")
        if mn is None:
            return 1e9
        # primary: value at 867 if available
        if at is not None:
            # lower is better; bonus if freq of min close to 0.867
            pen = abs((fr or F0) - F0) * 3.0
            return float(at) + pen * 0.1
        pen = abs((fr or F0) - F0) * 5.0
        return float(mn) + pen

    best = min(trials, key=score)
    print("best coarse", best)

    # --- Fine sweep around best S ---
    print("=== FINE frac_S ===")
    bs = float(best["params"]["frac_S"])
    fine_s = sorted({round(bs + d, 2) for d in [-4, -2, -1, 0, 1, 2, 4]})
    for s in fine_s:
        if any(abs(t["params"]["frac_S"] - s) < 0.05 for t in trials):
            continue
        trials.append(eval_params(c, {"frac_S": s, "feed_w": 3.2}))

    best = min(trials, key=score)
    print("best after fine S", best)

    # --- If still not < -10, try feed_w at best S ---
    if (best.get("s11_min_db") is None) or (best["s11_min_db"] > -10):
        print("=== feed_w tweak ===")
        bs = float(best["params"]["frac_S"])
        for fw in [2.4, 2.8, 3.2, 4.0, 5.0, 6.0]:
            trials.append(eval_params(c, {"frac_S": bs, "feed_w": fw, "frac_depth": bs / 3.5}))
        best = min(trials, key=score)

    # --- Optional depth ratio tweak ---
    if best.get("s11_min_db") is not None and best["s11_min_db"] > -10:
        print("=== frac_depth ratio tweak ===")
        bs = float(best["params"]["frac_S"])
        fw = float(best["params"].get("feed_w", 3.2))
        for ratio in [3.0, 3.5, 4.0, 4.5]:
            trials.append(
                eval_params(
                    c,
                    {"frac_S": bs, "feed_w": fw, "frac_depth": bs / ratio},
                )
            )
        best = min(trials, key=score)

    # Final solve already at best if last trial is best; else re-run best
    bp = best["params"]
    print("=== FINAL at best params ===", bp)
    final = eval_params(c, bp)
    ff = c.get_farfield_metrics(F0)
    c.save_project(str(PROJ))

    report = {
        "project": str(PROJ),
        "target": {"s11_db": -10, "freq_ghz": F0},
        "trials": trials,
        "best": best,
        "final": final,
        "farfield": {
            "status": ff.get("status"),
            "available": ff.get("available"),
            "metrics": ff.get("metrics"),
            "method": ff.get("method"),
        },
        "success": (final.get("s11_min_db") is not None and final["s11_min_db"] <= -10),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("==== RESULT ====")
    print(json.dumps({
        "success": report["success"],
        "final": final,
        "ff_available": ff.get("available"),
        "ff_gain": (ff.get("metrics") or {}).get("max_realized_gain_dbi"),
        "n_trials": len(trials),
        "project": str(PROJ),
    }, indent=2, default=str))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
