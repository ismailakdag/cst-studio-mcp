"""Restart-equivalent full flow: build patch → solve → S11 → farfield metrics."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import workflows


async def main() -> int:
    errors: list[str] = []
    c = CSTClient(CSTConfig.from_env())

    print("1 CONNECT")
    conn = c.connect()
    print(json.dumps(conn, indent=2, default=str))
    if conn.get("status") != "connected":
        print("FAIL connect")
        return 1

    print("2 BUILD patch 2.4 GHz")
    r = await workflows.handle(
        "cst_workflow_patch_antenna",
        {
            "frequency_ghz": 2.4,
            "create_project": True,
            "project_path": r"E:\cstprojects\patch_2p4_retry.cst",
            "epsilon_r": 4.4,
            "height_mm": 1.6,
            "tan_delta": 0.02,
            "feed_type": "inset",
        },
        c,
    )
    build = json.loads(r[0].text)
    print("build", build.get("status"), "params", (build.get("parameters_in_project") or {}).get("count"))
    for s in build.get("steps") or []:
        if not isinstance(s, dict):
            continue
        if s.get("label"):
            print(f"  {s.get('label'):20} {s.get('status')}")
        if s.get("status") == "error" and s.get("label") not in {"units", "store_parameters"}:
            if s.get("label") == "units":
                continue
            msg = s.get("message") or ""
            print("  ERR", s.get("label"), msg[:250])
            if s.get("label") not in {"units", "store_parameters"}:
                if "non-fatal" not in (s.get("note") or ""):
                    errors.append(f"{s.get('label')}: {msg[:200]}")

    if build.get("status") not in {"executed", "ok"}:
        errors.append("build status " + str(build.get("status")))

    print("3 PARAMS", c.list_parameters().get("count"), list((c.list_parameters().get("parameters") or {}).keys()))

    print("4 SOLVE")
    t0 = time.time()
    solve = c.run_solver(timeout_s=1200)
    print(solve, "t=", round(time.time() - t0, 1))
    if solve.get("status") not in {"executed", "ok"}:
        errors.append("solve " + str(solve))

    print("5 S11")
    s11 = c.get_s_parameters(1, 1, max_points=60)
    print(s11.get("status"), s11.get("metrics"))
    if s11.get("status") != "ok":
        errors.append("s11 " + str(s11.get("message")))

    print("6 FARFIELD / antenna metrics")
    ff = c.get_farfield_metrics(2.4)
    print(ff.get("status"), ff.get("method"), ff.get("metrics"))
    if ff.get("status") != "ok":
        errors.append("ff " + str(ff.get("message")))

    print("7 MESSAGE LOG scan")
    msgs = c.get_cst_messages(max_chars=4000)
    tail = msgs.get("tail") or ""
    bad_markers = [
        "Unterminated block",
        'SelectTreeItem "farfield (f=',  # bare name without Farfields\
        "TanDValue",
        '.Apply"',
        ".Apply)",
    ]
    for bad in bad_markers:
        if bad in tail:
            # only count if near recent errors
            print("  FOUND bad marker:", bad)
            errors.append("messages contain " + bad)

    # Show recent WARNING/ERROR lines
    for line in tail.splitlines():
        if any(k in line for k in ("ERROR", "WARNING", "Unable to resolve", "Unterminated")):
            print(" ", line[:140])

    print("8 SAVE", c.save_project())

    out = {
        "errors": errors,
        "build": build.get("status"),
        "params_count": c.list_parameters().get("count"),
        "solve": solve,
        "s11_metrics": s11.get("metrics"),
        "ff_metrics": ff.get("metrics"),
        "ff_method": ff.get("method"),
        "project": c.project_path,
        "message_file": msgs.get("path"),
    }
    path = Path(r"E:\cstprojects\exports\retry_summary.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    print("=== SUMMARY errors:", len(errors))
    for e in errors:
        print(" -", e[:250])
    print("wrote", path)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
