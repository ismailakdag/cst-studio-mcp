"""Exercise the real stdio server against a completed project, without CST GUI.

Usage: python scripts/verify_saved_results.py PROJECT.cst [ARCHIVE.csv.gz]
The optional archive must have the tooth-study frequency_GHz/S11_re/... schema.
"""

import argparse
import asyncio
import csv
import gzip
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("archive", type=Path, nargs="?")
    args = parser.parse_args()
    project = str(args.project.resolve(strict=True))
    env = dict(os.environ, CST_CONNECT_MODE="manual")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    config = StdioServerParameters(command=sys.executable, args=["-m", "cst_mcp.server"], env=env)
    checks = {}
    async with stdio_client(config) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            checks["tools"] = len((await session.list_tools()).tools)

            async def call(name, args):
                result = await session.call_tool(name, args)
                data = json.loads(result.content[0].text)
                assert not getattr(result, "isError", getattr(result, "is_error", False)), data
                assert data["status"] == "ok", data
                return data

            listing = await call(
                "cst_list_saved_results", {"project_path": project, "contains": "S-Parameters"}
            )
            checks["s_tree_entries"] = len(listing["entries"])
            for label in ["S1,1", "S1,2", "S2,1", "S2,2"]:
                data = await call(
                    "cst_read_saved_result",
                    {
                        "project_path": project,
                        "tree_path": "1D Results\\S-Parameters\\" + label,
                        "max_points": 0,
                    },
                )
                checks[label] = {"n": data["n"], "xlabel": data["xlabel"], "finite_complex": True}
                if args.archive:
                    with gzip.open(args.archive, "rt", encoding="utf-8") as f:
                        rows = list(csv.DictReader(f))
                    prefix = label.replace(",", "")
                    # Accept the documented study archive's re/im column names.
                    keys = rows[0].keys()
                    re_key = next(
                        k
                        for k in keys
                        if k.lower().replace(",", "")
                        in {prefix.lower() + "_re", prefix.lower() + "_real"}
                    )
                    im_key = next(
                        k
                        for k in keys
                        if k.lower().replace(",", "")
                        in {prefix.lower() + "_im", prefix.lower() + "_imag"}
                    )
                    assert len(rows) == data["n"]
                    error = max(
                        abs(complex(float(row[re_key]), float(row[im_key])) - complex(r, i))
                        for row, r, i in zip(rows, data["real"], data["imag"])
                    )
                    checks[label]["max_archive_difference"] = error
                    assert error < 1e-12
            help_result = await call("cst_search_help", {"query": "cst.results"})
            checks["official_help_found"] = bool(help_result["topics"])
            checks["no_connect_tool_called"] = True
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
