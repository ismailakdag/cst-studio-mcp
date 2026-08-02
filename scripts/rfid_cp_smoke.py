"""Single build+solve smoke test for CP RFID antenna (no sweep)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, r"E:\cst_mcp_update\src")
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient

spec = importlib.util.spec_from_file_location(
    "rfid", r"E:\cst_mcp_update\scripts\rfid_cp_867_octagon.py"
)
m = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(m)


def main() -> int:
    cfg = CSTConfig.from_env()
    cfg.work_dir = Path(r"E:\cstprojects")
    c = CSTClient(cfg)
    print("CONNECT", c.connect(), flush=True)
    p = m.default_params()
    print("NEW", c.new_project(str(m.PROJ)), flush=True)
    log = m.build_model(c, p)
    errs = [x for x in log if x["status"] == "error"]
    print("build_errors", len(errs), flush=True)
    for e in errs[:8]:
        print(" ", e, flush=True)
    c.save_project()
    if errs:
        return 1
    print("SOLVE...", flush=True)
    sol = c.run_solver(timeout_s=900)
    print("SOLVE", sol, flush=True)
    path = c.project_path or str(m.PROJ)
    s11 = m.s11_at(path, 0.867)
    print("S11", s11, flush=True)
    ff = c.get_farfield_metrics(0.867, try_farfield_plot=True)
    print("FF status", ff.get("status"), flush=True)
    print("metrics", ff.get("metrics"), flush=True)
    ar = m.axial_ratio_boresight(c, 0.867)
    print("AR", ar.get("parsed"), flush=True)
    out = {
        "project": path,
        "solve": sol,
        "s11": s11,
        "farfield": ff,
        "ar": ar.get("parsed"),
        "params": p,
    }
    rep = Path(r"E:\cstprojects\exports\rfid_cp_smoke.json")
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("wrote", rep, flush=True)
    return 0 if sol.get("status") in {"executed", "ok"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
