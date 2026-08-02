"""Re-read S11 + views from already-solved patch_2p4_e2e project."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient


def main() -> None:
    c = CSTClient(CSTConfig.from_env())
    print("connect", c.connect().get("status"))
    print("open", c.open_project(r"E:\cstprojects\patch_2p4_e2e.cst"))
    params = c.list_parameters()
    print("params", params.get("count"), list((params.get("parameters") or {}).keys()))
    s = c.get_s_parameters(1, 1, max_points=80)
    print("s11", s.get("status"), s.get("metrics"), "n", s.get("n_points"))
    msgs = c.get_cst_messages()
    print("msgs", msgs.get("status"), msgs.get("path"))
    out = Path(r"E:\cstprojects\exports\views_fixed")
    v = c.export_plot_images(out, width=800, height=600)
    sizes = []
    for i in v.get("images") or []:
        p = Path(i["path"]) if i.get("path") else None
        sz = p.stat().st_size if p and p.exists() else 0
        sizes.append((i["view"], i.get("exists"), sz))
        print(i["view"], i.get("exists"), sz)

    md = [
        "# Patch 2.4 GHz — post-fix results",
        "",
        f"- Project: `E:\\cstprojects\\patch_2p4_e2e.cst`",
        f"- Parameters: **{params.get('count')}** → `{list((params.get('parameters') or {}).keys())}`",
        f"- S11: **{s.get('status')}** metrics=`{s.get('metrics')}` n={s.get('n_points')}",
        f"- CST messages: `{msgs.get('path')}`",
        f"- Views: `{out}` sizes={sizes}",
        "",
        "Geometry uses Parameter List expressions (`patch_W`, `patch_L`, …).",
        "Edit parameters in CST then Rebuild / `cst_param_sweep_solve`.",
    ]
    exp = ROOT / "docs" / "experiments"
    exp.mkdir(parents=True, exist_ok=True)
    (exp / "patch_2p4_e2e_latest.md").write_text("\n".join(md), encoding="utf-8")
    summary = {
        "parameters": params,
        "s11_metrics": s.get("metrics"),
        "s11_status": s.get("status"),
        "views": sizes,
        "messages_path": msgs.get("path"),
    }
    (exp / "patch_2p4_e2e_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print("wrote docs/experiments/patch_2p4_e2e_latest.md")


if __name__ == "__main__":
    main()
