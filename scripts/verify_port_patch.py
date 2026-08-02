"""Quick live check: patch build with fixed microstrip port."""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.domain.antennas.patch import design_patch
from cst_mcp.tools import workflows
from cst_mcp.tools.workflows import _patch_vba_steps


async def main() -> None:
    d = design_patch(2.4)
    steps = dict(_patch_vba_steps(d))
    port = steps["port_wg_1"]
    feed = steps["brick_feed"]
    print("=== PORT ===")
    print(port)
    print("=== FEED ===")
    print(feed)
    assert 'PortOnBound "False"' in port
    assert 'Orientation "ymin"' in port
    # feed outer Y should appear in port Yrange
    assert "Yrange" in port

    c = CSTClient(CSTConfig.from_env())
    print("connect", c.connect())
    r = await workflows.handle(
        "cst_workflow_patch_antenna",
        {
            "frequency_ghz": 2.4,
            "create_project": True,
            "project_path": r"E:\cstprojects\patch_2p4_portfix.cst",
        },
        c,
    )
    data = json.loads(r[0].text)
    print("status", data.get("status"))
    for s in data.get("steps") or []:
        if not isinstance(s, dict):
            continue
        lab = s.get("label") or ""
        if lab:
            print(f"  {lab:20} {s.get('status')}")
    print("save", c.save_project())
    print("path", c.project_path)


if __name__ == "__main__":
    asyncio.run(main())
