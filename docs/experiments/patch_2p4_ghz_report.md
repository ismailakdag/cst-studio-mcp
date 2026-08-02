# 2.4 GHz Microstrip Patch Antenna — Experiment Report

**Generated (UTC):** 2026-08-02T15:17:56.056331+00:00

## Design dimensions

| Parameter | Value |
|-----------|-------|
| Frequency | 2.4000 GHz |
| Substrate εr | 4.4000 |
| Substrate height | 1.6000 mm |
| tan δ | 0.0200 |
| Feed type | inset |
| Patch width W | 38.0100 mm |
| Patch length L | 29.4216 mm |
| Ground X | 76.0199 mm |
| Ground Y | 58.8432 mm |
| Inset | 8.8265 mm |
| Feed width | 3.2000 mm |
| λ0 | 124.9135 mm |
| ε_eff | 4.0857 |

## Connection / project

- **Connect status:** `{"status": "connected", "message": "Connected via connect_to_any_or_new()", "open_projects": 1, "project_path": "E:\\cstprojects\\patch_2p4_live.cst", "cst_path": "E:\\CST Studio Suite 2026", "python_lib_path": "E:\\CST Studio Suite 2026\\AMD64\\python_cst_libraries"}`
- **Project path:** `E:\cstprojects\patch_2p4_live.cst`
- **Work dir:** `E:\cstprojects`
- **CST path:** `E:\CST Studio Suite 2026`
- **Patch workflow status:** `error`

## Simulation status

*Solver not run or no simulation stage recorded.*

## S11 metrics

*No S-parameters available.*

## Farfield

*No farfield metrics available.*

## Failures / partials

- patch status=error: {'status': 'error', 'design': {'frequency_ghz': 2.4, 'epsilon_r': 4.4, 'height_mm': 1.6, 'tan_delta': 0.02, 'feed_type': 'inset', 'width_mm': 38.0099749575278, 'length_mm': 29.421593084370507, 'ground_x_mm': 76.0199499150556, 'ground_y_mm': 58.84318616874101, 'inset_mm': 8.826477925311151, 'feed_width_mm': 3.2, 'lambda0_mm': 124.91352416666666, 'eps_eff': 4.085676444332395}, 'steps': [{'status': 'error', 'message': 'An error occurred while trying to execute add_to_history:\n(10091) ActiveX Automation: no such property or method.\n(.Apply)', 'label': 'workflow_patch'}], 'next': 'Call cst_workflow_simulate_and_report or cst_run_simulation.'}

### Notes
- Units.Apply removed for CST 2026
- Material uses .TanD value (not TanDValue/TanDModel)
- Waveguide port enlarged (~3x feed width, Z margins) for adaptive port mesh
- CST left connected (no force disconnect)

## Artifacts

- JSON report: `E:\cstprojects\exports\patch_2p4_report.json`
- This markdown: `E:\cst_mcp_update\docs\experiments\patch_2p4_ghz_report.md`
- CST project: `E:\cstprojects\patch_2p4_live.cst`
