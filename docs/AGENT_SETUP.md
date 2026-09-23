# Agent setup and acceptance checks — 1.1.0

This is a local **stdio MCP server**, not a remote MCP URL. The website is documentation.
Use the client's supported stdio configuration; do not configure the website URL as a server endpoint.

## Install

On Windows with a licensed CST installation, use Python 3.12 (the version used for CST 2026 validation):

```powershell
git clone https://github.com/ismailakdag/cst-studio-mcp.git C:\CST-MCP
Set-Location C:\CST-MCP
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

For an existing installation, use `git pull --ff-only` and rerun installation/tests while the MCP client is stopped. Do not interrupt an active simulation to update. No external agent, launcher, or CST process is started by installing or discovering the MCP server in default manual mode.

Example for clients using the `mcpServers` JSON convention (other clients use their own equivalent configuration):

```json
{
  "mcpServers": {
    "cst-studio": {
      "command": "C:/CST-MCP/.venv/Scripts/python.exe",
      "args": ["-m", "cst_mcp.server"],
      "env": {
        "CST_CONNECT_MODE": "manual",
        "CST_PATH": "C:/Program Files (x86)/CST Studio Suite 2026",
        "CST_WORK_DIR": "C:/CST-Projects"
      }
    }
  }
}
```

For Claude Code, the equivalent one-line registration is:

```powershell
claude mcp add cst-studio --scope user -e CST_CONNECT_MODE=manual -e CST_PATH="C:/Program Files (x86)/CST Studio Suite 2026" -e CST_WORK_DIR="C:/CST-Projects" '--' "C:/CST-MCP/.venv/Scripts/python.exe" -m cst_mcp.server
```

Optional: `CST_TOOLSETS` (comma-separated categories, alias `core`; connection tools are always exposed) limits the tool schemas sent to the model. `CST_ALLOW_RAW_VBA=1` is required before `cst_execute_vba` runs raw VBA in connected mode; its VBA check is a best-effort denylist, not a sandbox.

Set CST_PATH to the actual installation, or omit it to discover CST. The 2026 results module documents reading unpacked, unprotected **2025 and 2026** projects; this does not establish live 2025 automation coverage. A vendor DLL/Python ABI mismatch must be fixed in the environment, not worked around by opening another CST version silently.

## Acceptance order

1. Perform MCP `initialize`, `tools/list`, and `cst_connection_status`. Version should be 1.1.0; the full catalog contains 180+ tools (fewer if `CST_TOOLSETS` is set). Default startup is disconnected. Tools carry `readOnlyHint`/`destructiveHint` annotations, so read-only tools can be auto-approved.
2. Use `cst_search_help` with `{"query":"cst.results"}` and then `cst_read_help` with a returned topic. This reads installed official documentation without opening CST. `offset`/`max_chars` paginate long topics.
3. If a completed saved project is supplied, call `cst_list_saved_results` with its absolute `project_path`. Use an exact returned `tree_path` and `run_id` with `cst_read_saved_result`. No `cst_connect` is required. Use `max_points: 0` for all samples; the default is an explicitly labelled 200-point preview. Preserve real and imaginary values.
4. For live work, call `cst_connect` explicitly. This **may launch CST** if none is open. Inspect the selected project and solver state before changing anything. Do not change an unrelated project. Create a new uniquely named scratch project for model-building acceptance tests when CST is idle.
5. Never treat `offline` (generated VBA), `busy`, `error`, or `timeout` as completed simulation. A timed-out mutation is not automatically replayed. Check status/messages and establish idle state before proceeding. For solves longer than about a minute, start with `cst_run_simulation_async` and call `cst_wait_for_simulation` repeatedly (each call returns within about `max_wait_s` + 2 s; default 45 s) until it reports completion.
6. Native optimizer tools configure goals/parameters only. Starting requires an explicit `Optimizer.Start` action. The connected Python `cst_refine_antenna` workflow remains an explicit run operation with its own iteration limit.

For a completed two-port project, this read-only script checks the real stdio transport and all four complex curves:

```powershell
.\.venv\Scripts\python.exe scripts/verify_saved_results.py C:\CST-Projects\completed.cst
```

The full `.cst` and its result sidecar directory must remain together. A preview is not a full export, and a generated VBA macro is not evidence of successful geometry or solving.

## Prompt to give an agent

> Read https://cst-mcp.akdag.dev/docs/AGENT_SETUP.md and the linked API review. Install/update the local cst-studio-mcp repository in an isolated Python 3.12 environment. Configure this client's local stdio server in manual mode. Test initialize, tools/list, connection status and installed-help discovery. If I supplied a completed CST project, list its actual result paths/run IDs and read its complex S-parameters without opening CST. Report the package version, tests performed and exact failures. Do not start/stop a solver, modify an existing model, dismiss license dialogs, or claim all catalog tools are live-tested. For later modeling work, read the installed Python/VBA help first and follow the documented acceptance scope.

## Scope

Read [the current API review](API_REVIEW_2026.md). Some specialized material, EDA-import and field-analysis paths remain unverified or explicitly unsupported. Missing features are not silently emulated. Multiple agents should not mutate the same CST project concurrently. Different MCP clients share the standard wire protocol, but each client's installation/configuration must still be tested.
