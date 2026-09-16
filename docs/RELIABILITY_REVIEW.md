# Reliability review — 12 September 2026

Current release: [1.1.0 API review](API_REVIEW_2026.md) · [Agent setup](AGENT_SETUP.md).

Adding this server to an MCP client now leaves CST disconnected until `cst_connect` is called.
The default is `CST_CONNECT_MODE=manual`; existing automatic workflows can explicitly opt into
`auto`. Python and native stdout diagnostics are redirected to stderr while JSON-RPC retains
its own output handle. CST loader failures no longer prevent MCP initialization.

The registry validates all 180 tool schemas, supports both MCP Python SDK registration APIs,
and reports error, busy and timeout envelopes with `isError=true`. Busy and timeout payloads
retain the observed solver state, including `null` when CST cannot be queried.

The CST session uses the documented blocking `run_solver` and asynchronous `start_solver`
APIs. A busy solver prevents another solve or parameter update in the reviewed execution
paths. Status queries do not write history or show message boxes. Disconnect drops local
handles without closing CST or its projects; attaching no longer changes the user's UI mode.
Parameter/rebuild/solve and optimization workflows propagate unsuccessful execution and
result-reading states. Mesh setters use CST 2026 `MeshSettings.Set` commands.

## Validation

- 56 tests passed on Windows / Python 3.12 with MCP SDK 1.29.0.
- The same 56 tests passed with MCP SDK 2.2.0.
- The subprocess stdio tests perform initialize, list tools, offline status, invalid-input
  and unknown-tool calls, including injected Python prints and native `os.write(1, ...)`.
- Fake CST tests cover blocking/async calls, busy guards, timeout uncertainty, safe detach,
  open-project references, readonly status, parameter/rebuild paths and result error propagation.
- The generated guide lists the same 180 tools as the registry. The documentation builder
  also works with SDK 2.x field names and the Windows console encoding.
- GitHub Actions runs the offline suite on Windows and Ubuntu with both tested SDK versions.
  Adding that workflow is not itself a claim that remote CI has passed.

No test attached to an existing CST process, started a real solver or closed a project.
Consequently this review does not establish live correctness for all 180 tools, CST 2024/2025,
every MCP desktop client, or license/UI conditions. The current experiment was kept separate.
Native integration should be checked later with a disposable project and an idle CST session.

API review used the installed CST 2026 Python interface documentation, simulation tutorial,
`cst.interface.studio` implementation and Mesh VBA help. Parameter VBA uses the private
`model3d._execute_vba_code` entry point also used by the installed CST post-processing library;
it is version-sensitive and fails explicitly when unavailable.
