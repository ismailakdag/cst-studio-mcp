# Python / VBA API review — 16 September 2026

Version **1.1.0** repairs the core connected-result contract and adds access to installed official help. This review is deliberately narrower than a claim that every CST tool or license/UI state is fault-free.

## Verified evidence

- **85 tests passed** on Windows/Python 3.12 with each of MCP SDK **1.29.0** and **2.2.0**. Tests include real stdio initialization/calls, schema discovery, fake connected-mode contracts, numerical conversions, and busy/unknown-state behavior.
- A real completed CST 2026 two-port project was read through the actual stdio server without `cst_connect`: S11/S12/S21/S22 each contained **4,001 complex samples**. Every real/imaginary sample matched the pre-existing research archive exactly: maximum absolute complex difference **0.0** for all four curves. This was read-only; no new solver or live model mutation was used for this check.
- All statically referenced `client` attributes in registered tool source resolve on CSTClient. This is a contract check, not evidence of every branch executing on CST.
- Installed official `cst.results`/`cst.interface` help, plus Brick, DiscretePort, LumpedElement, Wire, ExtrudeCurve, SweepCurve, FloquetPort, ParameterSweep, Optimizer and TOUCHSTONE VBA topics were inspected. Documentation paths/hashes and a limited literal-builder scan are in [installed-api-audit.json](installed-api-audit.json). Name matches do not establish signatures, units or live execution.

- A separate **live CST 2026 modeler fixture** completed through stdio after the research queue finished: parameter write/read/list, dielectric material, brick/cylinder/sphere, straight wire, polygon extrusion, discrete port, lumped resistor, sweep and native optimizer configuration, empty message query, save, close and disconnect. No solver was started. [Modeler evidence](modeler-validation.json) records the actual responses.
- The initial Wire-to-solid conversion stalled. That path was replaced by a cylindrical solid plus rigid transforms; the complete fixture then passed. Native VBA commands now have a 30-second response timeout, report uncertain execution, and are not replayed. This is not a solver runtime limit.

## Changes

| Area | Behavior in 1.1.0 |
| --- | --- |
| Missing compatibility methods | `get_result`, `read_project_messages`, `export_result` implemented; the export bridge writes explicit GHz/dB data expected by optimization. |
| Complex result reading | Official `cst.results.ProjectFile/get_3d/get_result_item/get_xdata/get_ydata`; raw real/imaginary arrays retained; explicit run IDs and preview flags. |
| Derived quantities | Actual magnitude/dB/phase/unwrap, finite-difference group delay with unit conversion, VSWR, Smith impedance and all contiguous matched bands with interpolated edges. Singular values are explicit JSON nulls/errors. |
| CSV imports | Headers define units and layout; negative real parts are not mistaken for dB. Magnitude-only input does not invent phase. Ambiguous/non-finite exports are rejected. |
| API bridge | ASCIIExport runs as VBA through the Python execution bridge; COM-style attributes are no longer assumed to exist on Model3D. |
| Queries | Official Project.get_messages is preferred. Legacy Debug.Print/MsgBox query output can be returned through MCP instead of a blocking popup. |
| Execution safety | Active or unknown solver state blocks history mutation, query execution and project close. A failed/timed-out VBA attempt is not replayed through another entry point. |
| Geometry and ports | Antenna DiscretePort endpoints use SetP1/SetP2 with the picked flag. Lumped elements use SetName/SetType/SetR/L/C and endpoints; nH/pF matching values convert to SI. Floquet selection uses zmin/zmax and SetNumberOfModesConsidered. Straight wire uses Cylinder plus rigid transforms; polygon extrusion uses the documented curve contract. |
| Sweeps/optimization | AddSequence/AddParameter_Samples replace nonexistent linear-sweep calls. Seeded Monte Carlo uses one sample per sequence, not a Cartesian grid. Native optimizer uses documented goal/parameter lifecycle and evaluation-capped methods; configuring does not start it. Weighted goals are not advertised as a Pareto-front study. |
| Touchstone export | Uses the official TOUCHSTONE object, RI format and Write. CST derives port count from the actual project. |
| Agent documentation | Installed-help search/read and a copyable setup/acceptance prompt are available. Bundled legacy help is labelled when an installed topic is unavailable. |

## Remaining limits

**The catalog is not a list of 184 live-certified features.** The numerical, transport and enumerated modeler paths above were tested. Farfield-export VBA and advanced modeler branches still need dedicated live fixtures. There was no live CST 2025 test or new 3D solver acceptance run.

Advanced dispersion/ferrite/temperature-dependent material builders and EDA/PCB import require further version-specific checks. The local documentation scan still reports unresolved names; do not interpret absence from that scan as proof a method is invalid, or a match as proof it works. Cartesian farfield resampling, specialized polarization/cut extraction, and generic 3D-field-to-1D conversion are not certified. Unavailable quantities return an error rather than fabricated scalar data. Efficiency does not determine conductor/dielectric loss separation without the corresponding monitors.

The old Touchstone-import schema only provides a port number, which cannot describe a schematic network or lumped-element pin mapping. It now rejects the request rather than generating a nonexistent TouchstoneImport object. Use the appropriate explicitly defined CST network workflow.

No blanket license-dialog recovery, every-client compatibility, physical antenna/sensor accuracy, convergence, or clinical performance claim follows from these software tests. See [agent setup](AGENT_SETUP.md) for a reproducible acceptance sequence.
