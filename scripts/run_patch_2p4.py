import asyncio
import json
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone

from cst_mcp.config import CSTConfig
from cst_mcp.cst_client import CSTClient
from cst_mcp.tools import workflows


def parse_tc(result):
    if not result:
        return {}
    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    try:
        return json.loads(text)
    except Exception:
        return {"_raw": text}


def write_reports(report, out_json, out_md):
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    d = report.get("design") or {}

    def fmt(key):
        v = d.get(key)
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v) if v is not None else "—"

    lines = [
        "# 2.4 GHz Microstrip Patch Antenna — Experiment Report",
        "",
        f"**Generated (UTC):** {report['timestamp_utc']}",
        "",
        "## Design dimensions",
        "",
    ]
    if d:
        lines += [
            "| Parameter | Value |",
            "|-----------|-------|",
            f"| Frequency | {fmt('frequency_ghz')} GHz |",
            f"| Substrate εr | {fmt('epsilon_r')} |",
            f"| Substrate height | {fmt('height_mm')} mm |",
            f"| tan δ | {fmt('tan_delta')} |",
            f"| Feed type | {fmt('feed_type')} |",
            f"| Patch width W | {fmt('width_mm')} mm |",
            f"| Patch length L | {fmt('length_mm')} mm |",
            f"| Ground X | {fmt('ground_x_mm')} mm |",
            f"| Ground Y | {fmt('ground_y_mm')} mm |",
            f"| Inset | {fmt('inset_mm')} mm |",
            f"| Feed width | {fmt('feed_width_mm')} mm |",
            f"| λ0 | {fmt('lambda0_mm')} mm |",
            f"| ε_eff | {fmt('eps_eff')} |",
            "",
        ]
    else:
        lines += ["*Design not available.*", ""]

    conn_s = json.dumps(report.get("stages", {}).get("connect", {}), default=str)[:500]
    lines += [
        "## Connection / project",
        "",
        f"- **Connect status:** `{conn_s}`",
        f"- **Project path:** `{report.get('project_path') or '(none)'}`",
        r"- **Work dir:** `E:\cstprojects`",
        r"- **CST path:** `E:\CST Studio Suite 2026`",
        f"- **Patch workflow status:** `{report.get('stages', {}).get('patch_antenna', {}).get('status')}`",
        "",
        "## Simulation status",
        "",
    ]
    if report.get("simulation"):
        lines += [
            "```json",
            json.dumps(report["simulation"], indent=2, default=str)[:6000],
            "```",
        ]
    else:
        lines.append("*Solver not run or no simulation stage recorded.*")
    lines.append("")

    lines += ["## S11 metrics", ""]
    s11 = report.get("s11")
    if s11:
        slim_s = s11
        if isinstance(s11, dict) and "points" in s11 and len(str(s11)) > 4000:
            slim_s = {k: v for k, v in s11.items() if k != "points"}
            slim_s["points_count"] = len(s11.get("points") or [])
            slim_s["points_sample"] = (s11.get("points") or [])[:5]
        lines += [
            "```json",
            json.dumps(slim_s, indent=2, default=str)[:6000],
            "```",
        ]
    else:
        lines.append("*No S-parameters available.*")
    lines.append("")

    lines += ["## Farfield", ""]
    if report.get("farfield"):
        lines += [
            "```json",
            json.dumps(report["farfield"], indent=2, default=str)[:6000],
            "```",
        ]
    else:
        lines.append("*No farfield metrics available.*")
    lines.append("")

    lines += ["## Failures / partials", ""]
    if report.get("failures"):
        for f in report["failures"]:
            lines.append(f"- {f}")
    else:
        lines.append("- None recorded.")
    if report.get("notes"):
        lines.append("")
        lines.append("### Notes")
        for n in report["notes"]:
            lines.append(f"- {n}")
    lines += [
        "",
        "## Artifacts",
        "",
        r"- JSON report: `E:\cstprojects\exports\patch_2p4_report.json`",
        r"- This markdown: `E:\cst_mcp_update\docs\experiments\patch_2p4_ghz_report.md`",
        f"- CST project: `{report.get('project_path')}`",
        "",
    ]
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print("Wrote", out_json, "and", out_md, flush=True)


async def main():
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "frequency_ghz": 2.4,
        "stages": {},
        "design": None,
        "project_path": None,
        "simulation": None,
        "s11": None,
        "farfield": None,
        "failures": [],
        "notes": [
            "Units.Apply removed for CST 2026",
            "Material uses .TanD value (not TanDValue/TanDModel)",
            "Waveguide port enlarged (~3x feed width, Z margins) for adaptive port mesh",
        ],
    }
    client = CSTClient(CSTConfig.from_env())
    out_json = Path(r"E:\cstprojects\exports\patch_2p4_report.json")
    out_md = Path(r"E:\cst_mcp_update\docs\experiments\patch_2p4_ghz_report.md")
    ts = int(time.time())
    proj = str(Path(r"E:\cstprojects") / f"patch_2p4GHz_{ts}.cst")

    try:
        print("=== CONNECT ===", flush=True)
        conn = client.connect()
        report["stages"]["connect"] = conn
        print(json.dumps(conn, indent=2, default=str), flush=True)

        print("=== PATCH ===", flush=True)
        patch_args = {
            "frequency_ghz": 2.4,
            "epsilon_r": 4.4,
            "height_mm": 1.6,
            "tan_delta": 0.02,
            "feed_type": "inset",
            "create_project": True,
            "project_path": proj,
        }
        patch_data = parse_tc(
            await workflows.handle("cst_workflow_patch_antenna", patch_args, client)
        )
        slim = {k: v for k, v in patch_data.items() if k != "vba"}
        if "steps" in slim:
            slim["steps"] = [
                {kk: vv for kk, vv in s.items() if kk != "vba"}
                if isinstance(s, dict)
                else s
                for s in slim["steps"]
            ]
        report["stages"]["patch_antenna"] = slim
        report["design"] = patch_data.get("design")
        report["project_path"] = client.project_path
        print(
            "patch status",
            patch_data.get("status"),
            "path",
            client.project_path,
            flush=True,
        )

        if patch_data.get("status") not in ("ok", "executed"):
            report["failures"].append(
                f"patch status={patch_data.get('status')}: {slim}"
            )
        else:
            try:
                report["stages"]["save"] = client.save_project()
            except Exception as e:
                report["failures"].append(f"save: {e}")

            print("=== SIMULATE AND REPORT timeout=1000s ===", flush=True)
            sim_args = {
                "port": 1,
                "frequency_ghz": 2.4,
                "timeout_s": 1000,
                "include_images": True,
                "include_farfield": True,
                "max_points": 200,
                "out_dir": str(Path(r"E:\cstprojects\exports\patch_2p4_report")),
            }
            sim_data = parse_tc(
                await workflows.handle(
                    "cst_workflow_simulate_and_report", sim_args, client
                )
            )
            report["stages"]["simulate_status"] = sim_data.get("status")
            report["simulation"] = sim_data.get("solver")
            rep = sim_data.get("report") or {}
            if isinstance(rep, dict):
                report["s11"] = (
                    rep.get("s_parameters")
                    or rep.get("sparams")
                    or rep.get("s11")
                )
                report["farfield"] = rep.get("farfield")
                report["design_report_keys"] = list(rep.keys())
                report["report_out_dir"] = rep.get("out_dir")
                report["report_images"] = rep.get("images")
                report["report_status"] = rep.get("status")
            print(
                "solver",
                json.dumps(report.get("simulation"), indent=2, default=str)[:3000],
                flush=True,
            )
            s11 = report.get("s11")
            if isinstance(s11, dict):
                slim_s = {k: v for k, v in s11.items() if k != "points"}
                if "points" in s11:
                    slim_s["points_count"] = len(s11.get("points") or [])
                print(
                    "s11",
                    json.dumps(slim_s, indent=2, default=str)[:3000],
                    flush=True,
                )
            print(
                "farfield",
                json.dumps(report.get("farfield"), indent=2, default=str)[:2000]
                if report.get("farfield")
                else None,
                flush=True,
            )
            if (report.get("simulation") or {}).get("status") == "error":
                report["failures"].append(
                    (report.get("simulation") or {}).get("message", "solver error")
                )
    except Exception as e:
        report["failures"].append(f"top_level: {e}")
        traceback.print_exc()
    finally:
        if client.connected:
            report["notes"].append("CST left connected (no force disconnect)")
        write_reports(report, out_json, out_md)

    print("=== DONE ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
