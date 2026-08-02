"""End-to-end: 2.4 GHz parametric patch → solve → report.

Usage (PowerShell):
  $env:CST_PATH="E:\\CST Studio Suite 2026"
  $env:CST_WORK_DIR="E:\\cstprojects"
  $env:PYTHONPATH="E:\\CST Studio Suite 2026\\AMD64\\python_cst_libraries"
  python scripts/run_patch_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import workflows


def _trim(obj, max_list=8):
    if isinstance(obj, dict):
        return {k: _trim(v, max_list) for k, v in obj.items()}
    if isinstance(obj, list) and len(obj) > max_list:
        return obj[:max_list] + [f"...({len(obj)} total)"]
    return obj


async def main() -> int:
    work = Path(os.environ.get("CST_WORK_DIR", str(Path.home() / "cst_projects")))
    out_dir = work / "exports" / f"patch_2p4_e2e_{int(time.time())}"
    out_dir.mkdir(parents=True, exist_ok=True)
    project = work / "patch_2p4_e2e.cst"

    client = CSTClient(CSTConfig.from_env())
    report: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "out_dir": str(out_dir)}

    print("=== CONNECT ===", flush=True)
    conn = client.connect()
    report["connect"] = conn
    print(json.dumps(conn, indent=2, default=str), flush=True)
    if conn.get("status") != "connected":
        (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return 1

    print("=== BUILD PATCH 2.4 GHz ===", flush=True)
    build = await workflows.handle(
        "cst_workflow_patch_antenna",
        {
            "frequency_ghz": 2.4,
            "create_project": True,
            "project_path": str(project),
            "epsilon_r": 4.4,
            "height_mm": 1.6,
            "tan_delta": 0.02,
            "feed_type": "inset",
        },
        client,
    )
    build_data = json.loads(build[0].text)
    report["build"] = _trim(build_data)
    print("build status:", build_data.get("status"), flush=True)
    print("parameters:", json.dumps(build_data.get("parameters_in_project"), indent=2, default=str)[:2000], flush=True)
    for s in build_data.get("steps") or []:
        if isinstance(s, dict) and s.get("label"):
            print(f"  {s.get('label'):20} {s.get('status')}", flush=True)

    if build_data.get("status") not in {"executed", "ok"}:
        (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print("BUILD FAILED", flush=True)
        return 2

    print("=== LIST PARAMETERS ===", flush=True)
    params = client.list_parameters()
    report["parameters"] = params
    print(json.dumps(params, indent=2, default=str)[:2000], flush=True)

    print("=== SOLVE (may take a while) ===", flush=True)
    t0 = time.time()
    solve = client.run_solver(timeout_s=float(os.environ.get("CST_SOLVE_TIMEOUT", "1800")))
    report["solve"] = solve
    report["solve_seconds"] = round(time.time() - t0, 1)
    print(json.dumps(solve, indent=2, default=str), flush=True)
    print(f"solve wall time: {report['solve_seconds']}s", flush=True)

    print("=== S-PARAMETERS ===", flush=True)
    s11 = client.get_s_parameters(1, 1, max_points=120)
    report["s11"] = _trim(s11)
    print("s11 status", s11.get("status"), "metrics", s11.get("metrics"), flush=True)

    print("=== FARFIELD METRICS ===", flush=True)
    ff = client.get_farfield_metrics(frequency_ghz=2.4)
    report["farfield"] = _trim(ff)
    print("ff status", ff.get("status"), "metrics", ff.get("metrics"), flush=True)

    print("=== VIEWS ===", flush=True)
    views = client.export_plot_images(out_dir / "views", width=1024, height=768)
    report["views"] = views
    print(json.dumps(views, indent=2, default=str)[:2000], flush=True)

    print("=== DESIGN REPORT PACKAGE ===", flush=True)
    full = client.design_report(
        port=1,
        frequency_ghz=2.4,
        include_images=True,
        include_sparams=True,
        include_farfield=True,
        include_parameters=True,
        out_dir=out_dir / "package",
    )
    report["design_report"] = _trim(full)

    client.save_project()
    report["project_path"] = client.project_path
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["success"] = (
        build_data.get("status") in {"executed", "ok"}
        and solve.get("status") in {"executed", "ok"}
    )

    json_path = out_dir / "report.json"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    md = [
        "# 2.4 GHz Patch E2E Report",
        "",
        f"- Project: `{client.project_path}`",
        f"- Out: `{out_dir}`",
        f"- Build: **{build_data.get('status')}**",
        f"- Solve: **{solve.get('status')}** ({report['solve_seconds']}s)",
        f"- S11: **{s11.get('status')}** metrics=`{s11.get('metrics')}`",
        f"- Farfield: **{ff.get('status')}** metrics=`{ff.get('metrics')}`",
        f"- Parameters count: **{(params.get('count') if isinstance(params, dict) else None)}**",
        f"- Views written: **{sum(1 for i in (views.get('images') or []) if i.get('exists'))}**",
        "",
        "## Parameter list",
        "```json",
        json.dumps(params.get("parameters") if isinstance(params, dict) else params, indent=2, default=str)[:3000],
        "```",
        "",
        f"Full JSON: `{json_path}`",
    ]
    md_path = out_dir / "REPORT.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    # also copy to docs/experiments
    exp = ROOT / "docs" / "experiments"
    exp.mkdir(parents=True, exist_ok=True)
    (exp / "patch_2p4_e2e_latest.md").write_text("\n".join(md), encoding="utf-8")

    print("=== DONE ===", flush=True)
    print("report", json_path, flush=True)
    print("markdown", md_path, flush=True)
    return 0 if report.get("success") else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
