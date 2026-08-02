"""Push fractal match toward 867 MHz while keeping S11 < -10 dB if possible."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\cst_mcp_update\src")
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.execution.results_api import read_1d_item

PROJ = r"E:\cstprojects\fractal_867_opt.cst"
OUT = Path(r"E:\cstprojects\exports\fractal_867_opt.json")
F0 = 0.867


def s11_curve(c):
    # prefer results API for dense curve
    path = c.project_path or PROJ
    r = read_1d_item(path, r"1D Results\S-Parameters\S1,1")
    if r.get("status") != "ok":
        sp = c.get_s_parameters(1, 1, max_points=400)
        return sp.get("frequency") or sp.get("x") or [], sp.get("s_db") or sp.get("y") or [], sp.get("metrics")
    return r.get("x") or [], r.get("y") or [], {
        "min_db": r.get("y_at_extremum"),
        "freq_at_min_ghz": r.get("x_at_extremum"),
    }


def at_freq(xs, ys, f):
    if not xs or not ys:
        return None
    i = min(range(len(xs)), key=lambda j: abs(xs[j] - f))
    return float(ys[i]), float(xs[i])


def run(c, params):
    p = dict(params)
    if "frac_depth" not in p:
        p["frac_depth"] = p["frac_S"] / 3.5
    t0 = time.time()
    r = c.set_params_rebuild_solve(p, export_s11=True, port=1, timeout_s=600)
    dt = round(time.time() - t0, 1)
    xs, ys, metrics = s11_curve(c)
    near = at_freq(xs, ys, F0)
    # also find best in 0.8-0.95 window
    band = [(xs[i], ys[i]) for i in range(len(xs)) if 0.80 <= xs[i] <= 0.95]
    band_best = min(band, key=lambda t: t[1]) if band else None
    out = {
        "params": p,
        "status": r.get("status"),
        "s11_min_db": (metrics or {}).get("min_db"),
        "s11_freq_ghz": (metrics or {}).get("freq_at_min_ghz"),
        "s11_at_867": near[0] if near else None,
        "band_0p8_0p95_best": {"f": band_best[0], "s11": band_best[1]} if band_best else None,
        "solve_s": dt,
        "n_pts": len(xs),
    }
    print(
        f"S={p['frac_S']:.1f} d={p['frac_depth']:.2f} fw={p.get('feed_w',3.2):.1f} | "
        f"min={out['s11_min_db']}@{out['s11_freq_ghz']} | "
        f"@867={out['s11_at_867']} | band={out['band_0p8_0p95_best']} t={dt}s"
    )
    return out


def main():
    c = CSTClient(CSTConfig.from_env())
    print(c.connect())
    print(c.open_project(PROJ))

    trials = []
    # Larger sizes to pull resonance down; also mild depth/feed around candidates
    for s in [90, 95, 100, 105, 110, 115, 120]:
        trials.append(run(c, {"frac_S": s, "feed_w": 3.2}))

    # score: prefer s11_at_867, require min somewhere; want s11_at_867 <= -10 ideally
    def score(t):
        a = t.get("s11_at_867")
        if a is None:
            return 100.0
        # heavy reward for being under -10 at 867
        return float(a)

    best867 = min(trials, key=score)
    print("best @867 so far", best867)

    # fine around best S for 867
    bs = best867["params"]["frac_S"]
    for ds in [-3, -1.5, 1.5, 3]:
        trials.append(run(c, {"frac_S": bs + ds, "feed_w": 3.2}))

    best867 = min(trials, key=score)

    # if still not -10 at 867, try feed_w and depth at that S
    if best867.get("s11_at_867") is None or best867["s11_at_867"] > -10:
        print("=== match tweaks at best S for 867 ===")
        bs = best867["params"]["frac_S"]
        for fw in [2.5, 4.0, 5.5, 7.0]:
            trials.append(run(c, {"frac_S": bs, "feed_w": fw}))
        for ratio in [2.8, 3.2, 4.0, 5.0]:
            trials.append(run(c, {"frac_S": bs, "feed_w": best867["params"].get("feed_w", 3.2), "frac_depth": bs / ratio}))
        best867 = min(trials, key=score)

    # Also keep track of absolute best min_db < -10 (any freq)
    with_match = [t for t in trials if t.get("s11_min_db") is not None and t["s11_min_db"] <= -10]
    best_deep = min(with_match, key=lambda t: t["s11_min_db"]) if with_match else None

    # Choose final: prefer S11@867 <= -10; else deepest match overall
    if best867.get("s11_at_867") is not None and best867["s11_at_867"] <= -10:
        final_p = best867["params"]
        chosen = "s11_at_867"
    elif best_deep:
        final_p = best_deep["params"]
        chosen = "deepest_match"
    else:
        final_p = best867["params"]
        chosen = "best_effort_867"

    print("FINAL params", final_p, "chosen", chosen)
    final = run(c, final_p)
    ff = c.get_farfield_metrics(F0)
    c.save_project(PROJ)

    # merge with previous report
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    report = {
        **prev,
        "project": PROJ,
        "phase2_trials": trials,
        "phase2_best_867": best867,
        "phase2_best_deep": best_deep,
        "phase2_final": final,
        "phase2_chosen": chosen,
        "farfield": {
            "status": ff.get("status"),
            "available": ff.get("available"),
            "metrics": ff.get("metrics"),
        },
        "success_any_freq": final.get("s11_min_db") is not None and final["s11_min_db"] <= -10,
        "success_at_867": final.get("s11_at_867") is not None and final["s11_at_867"] <= -10,
    }
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "chosen": chosen,
        "final": final,
        "success_any_freq": report["success_any_freq"],
        "success_at_867": report["success_at_867"],
        "ff_gain": (ff.get("metrics") or {}).get("max_realized_gain_dbi"),
        "n": len(trials),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
