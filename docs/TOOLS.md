## Full tool catalog (178 tools)

Interactive bilingual docs: open [`docs/index.html`](docs/index.html) (EN/TR toggle, search, full-width cards). Rebuild: `python scripts/build_docs.py`.

VBA for geometry/ports/transforms is cross-checked against the CST help dump in [`vba_cst/`](vba_cst/).

### Workflows (start here) (8)

One-shot helpers for common tasks. New users should start here.

| Tool | What it does |
|------|--------------|
| `cst_workflow_patch_antenna` | END-TO-END / Uçtan uca: size a rectangular microstrip patch, build substrate/ground/patch/feed, frequency, open BCs, waveguide port, farf… |
| `cst_workflow_run_and_s11` | Run solver and return structured S11/Sij with metrics (min dB, bandwidth). Solver çalıştırır ve S parametrelerini metriklerle döner. |
| `cst_design_patch_only` | Calculate microstrip patch dimensions only (offline, no CST). Sadece boyut hesabı — CST gerekmez. |
| `cst_export_structure_views` | Export structure screenshots (perspective/xy/xz/yz) via Plot.ExportImage. Yapı görünüm görsellerini dışa aktarır. Connected mode required. |
| `cst_workflow_design_report` | ONE-SHOT design package after modeling/simulation: project status, parameters/dimensions, S-parameters (+metrics), best-effort farfield e… |
| `cst_workflow_simulate_and_report` | Run the solver, then immediately build a design report (S-params + views + optional farfield). Simülasyonu çalıştırıp rapor paketini üretir. |
| `cst_discover_farfield_monitors` | Discover farfield monitors from the project Result folder and tree-path heuristics. Uzak alan monitörlerini disk + path sezgisiyle listeler. |
| `cst_get_farfield_metrics` | Read antenna metrics after a solve: S11 + radiation/total efficiency from 1D Results, plus max realized gain via official FarfieldPlot.Ge… |

### Project & connection (8)

Create, open, save projects and check CST connection.

| Tool | What it does |
|------|--------------|
| `cst_create_project` | Create a new CST Studio Suite project file. In connected mode the project is created directly; in offline mode a VBA script is returned f… |
| `cst_open_project` | Open an existing CST Studio Suite project. In connected mode the project is opened in the running instance; in offline mode a reference i… |
| `cst_save_project` | Save the currently open CST project. Optionally provide a new path to 'Save As'. |
| `cst_close_project` | Close the currently open CST project and release its resources. |
| `cst_project_info` | Get information about the currently open CST project, including connection mode, project path, and status. |
| `cst_project_tree` | List items in the CST project navigation tree. Optionally specify a subtree path such as 'Components', 'Materials', 'Ports', 'Monitors', … |
| `cst_export_project` | Export the current CST project or its geometry to another format such as STL, STEP, IGES, SAT, OBJ, or NASTRAN. |
| `cst_connection_status` | Get the current CST Studio connection status, including mode (connected/offline), CST availability, version, and work directory. |

### Geometry (13)

3D shapes: bricks, cylinders, spheres, extrusions, wires…

| Tool | What it does |
|------|--------------|
| `cst_create_brick` | Create a rectangular brick (box) in CST Studio. |
| `cst_create_cylinder` | Create a cylinder in CST Studio. Use inner_radius=0 for a solid cylinder. |
| `cst_create_cone` | Create a cone or truncated cone in CST Studio. |
| `cst_create_sphere` | Create a sphere in CST Studio. |
| `cst_create_torus` | Create a torus in CST Studio. |
| `cst_create_extrude` | Extrude a 2D polygon profile into a 3D solid in CST Studio. |
| `cst_create_loft` | Create a lofted solid between two or more 2D profiles in CST Studio. |
| `cst_create_wire` | Create a bondwire / wire between two points in CST Studio. |
| `cst_create_polygon3d` | Create a 3D polygon curve in CST Studio. |
| `cst_create_analytical_curve` | Create a parametric analytical curve in CST Studio using expressions of parameter t. |
| `cst_create_face_from_curves` | Create a planar face from one or more closed curves in CST Studio. |
| `cst_create_ecylinder` | Create an elliptical cylinder in CST Studio. |
| `cst_create_polygon_extrude` | Create a polygon and extrude it along an axis in CST Studio. Convenience tool combining polygon profile creation and extrusion. |

### Boolean operations (4)

Combine solids: add, subtract, intersect, insert.

| Tool | What it does |
|------|--------------|
| `cst_boolean_add` | Unite/add two solids together. The result replaces solid1 with the combined volume of both shapes. |
| `cst_boolean_subtract` | Subtract solid2 from solid1. The overlapping volume of solid2 is removed from solid1. Solid2 is deleted. |
| `cst_boolean_intersect` | Intersect two solids. Only the overlapping volume is kept, replacing solid1. Solid2 is deleted. |
| `cst_boolean_insert` | Insert solid2 into solid1. Solid2 is embedded within solid1, maintaining both material regions at the overlap. |

### Transforms (4)

Move, rotate, mirror, and scale solids.

| Tool | What it does |
|------|--------------|
| `cst_transform_translate` | Translate (move) a solid by a displacement vector (dx, dy, dz). Optionally create a translated copy. |
| `cst_transform_rotate` | Rotate a solid by a given angle around an axis (x, y, or z). An optional center point can be specified. |
| `cst_transform_mirror` | Mirror a solid across a plane (xy, xz, or yz). An optional center point can be specified. |
| `cst_transform_scale` | Scale a solid by independent factors along each axis. An optional center point can be specified. |

### Materials (15)

Metals, dielectrics, and advanced material models.

| Tool | What it does |
|------|--------------|
| `cst_create_material` | Create a new material with electromagnetic properties in CST Studio. Specify relative permittivity (epsilon), relative permeability (mu),… |
| `cst_create_lossy_metal` | Create a lossy metal material in CST Studio. Lossy metals model finite conductivity skin-effect losses, essential for accurate loss calcu… |
| `cst_create_anisotropic_material` | Create an anisotropic material with per-axis permittivity, permeability, and loss tangent values. Used for crystals, metamaterials, and c… |
| `cst_load_material` | Load a material from the CST material library by its library name. The material is added to the project under the given name. |
| `cst_list_materials` | List available materials from the bundled material database. Optionally filter by category: 'metals', 'dielectrics', or 'substrates'. Ret… |
| `cst_assign_material` | Assign a material to an existing solid in CST Studio. The solid is specified as 'Component:SolidName'. |
| `cst_get_material_info` | Get electromagnetic properties of a material from the bundled database. Returns epsilon_r, mu_r, conductivity, loss tangent, and usage no… |
| `cst_delete_material` | Delete a material from the current CST project. |
| `cst_create_debye_material` | Create a frequency-dependent dielectric material using the Debye relaxation model. Models polar dielectrics where permittivity decreases … |
| `cst_create_lorentz_material` | Create a Lorentz oscillator dispersive material. Models resonant dielectric behaviour near absorption bands: eps(w) = eps_inf + delta_eps… |
| `cst_create_drude_material` | Create a Drude metal model material for plasmonic and metamaterial simulations. Models free-electron metals: eps(w) = 1 - wp^2 / (w^2 + j… |
| `cst_create_ferrite_material` | Create a ferrite material with gyrotropic permeability tensor (Polder model). Essential for circulators, isolators, and phase shifters. T… |
| `cst_create_temperature_dependent_material` | Create a material with temperature-dependent electromagnetic properties. Specify base properties and temperature coefficients for thermal… |
| `cst_create_cole_cole_material` | Create a Cole-Cole dispersive material. Generalisation of the Debye model with a distribution parameter alpha (0-1) that broadens the rel… |
| `cst_list_ferrite_materials` | List available ferrite materials from the bundled database. Returns name, permittivity, saturation magnetisation, linewidth, loss tangent… |

### Ports & excitations (8)

Waveguide, discrete, plane wave, Floquet…

| Tool | What it does |
|------|--------------|
| `cst_add_waveguide_port` | Add a waveguide port for S-parameter excitation. Defines a port face on the boundary of the simulation domain for guided-wave excitation.… |
| `cst_add_discrete_port` | Add a discrete (lumped) port between two points. Used for circuit-level excitation with a defined impedance. |
| `cst_add_lumped_element` | Add a lumped R, L, C, or RLC element between two points. Value is in ohms for R, henries for L, farads for C. |
| `cst_add_plane_wave` | Add a plane wave excitation source. Defines an incident plane wave with given direction and polarization for scattering / RCS analysis. |
| `cst_add_floquet_port` | Add a Floquet port for periodic structures such as frequency selective surfaces, metamaterials, and phased arrays. |
| `cst_list_ports` | List all ports defined in the current CST project. Returns VBA to query port information, or a description in offline mode. |
| `cst_delete_port` | Delete a port by its port number. |
| `cst_add_multipin_port` | Add a waveguide port with multiple mode monitoring for higher-order mode analysis. Used for multimode waveguides, mode converters, and st… |

### Boundaries & setup (6)

Open/electric walls, background, symmetry, frequency range.

| Tool | What it does |
|------|--------------|
| `cst_set_boundary` | Set boundary conditions for the simulation domain. Each face of the bounding box can be assigned an independent boundary type (open, elec… |
| `cst_set_background` | Set the background material properties of the simulation domain. The background fills all space not occupied by defined solids. |
| `cst_set_symmetry` | Set symmetry planes to reduce computation time. Each axis can be assigned electric or magnetic symmetry, or none. Requires the model geom… |
| `cst_set_frequency_range` | Set the simulation frequency range in GHz. This determines the bandwidth over which the solver computes results. |
| `cst_set_periodic_boundary` | Configure periodic boundary conditions with optional phase shift for unit cell simulation. Sets X and Y boundaries to periodic and config… |
| `cst_set_floquet_port_advanced` | Configure advanced Floquet port settings for periodic structures. Controls the number of Floquet modes and scan angle for phased array el… |

### Mesh (8)

Mesh type, density, refinement, adaptive meshing.

| Tool | What it does |
|------|--------------|
| `cst_set_mesh_type` | Set the mesh type for the simulation. Hexahedral is used for time-domain, Tetrahedral for frequency-domain, Surface for integral-equation… |
| `cst_set_mesh_density` | Set global mesh density parameters controlling automatic mesh generation. Higher cells_per_wavelength gives finer mesh and better accurac… |
| `cst_add_mesh_refinement` | Add local mesh refinement to a specific solid. This creates finer mesh around critical geometry features like feed points, gaps, or thin … |
| `cst_set_adaptive_mesh` | Configure adaptive mesh refinement. When enabled, the solver runs multiple passes, refining the mesh in regions of high field gradient un… |
| `cst_get_mesh_info` | Get current mesh statistics and settings. In connected mode this queries the live mesh data; in offline mode it returns the VBA to retrie… |
| `cst_get_mesh_quality` | Extract mesh quality metrics including total cells, aspect ratios, and cells per wavelength. In connected mode this queries actual mesh s… |
| `cst_set_pml_properties` | Configure PML (Perfectly Matched Layer) absorbing boundary properties. Controls the number of absorbing layers and the target reflection … |
| `cst_add_fixpoint_mesh` | Add a fixed mesh point at specific coordinates for precise field sampling. Ensures the mesh contains a node exactly at the specified loca… |

### Solvers (8)

Time domain, frequency domain, eigenmode, IE…

| Tool | What it does |
|------|--------------|
| `cst_configure_time_domain_solver` | Configure the time domain (transient) solver. This is CST's flagship solver for broadband simulations — it excites the structure with a p… |
| `cst_configure_frequency_domain_solver` | Configure the frequency domain solver. Best for narrowband problems, resonant structures, and when field distributions at specific freque… |
| `cst_configure_eigenmode_solver` | Configure the eigenmode solver. Computes resonant frequencies and field distributions of cavity structures. Used for filter design, reson… |
| `cst_configure_integral_equation_solver` | Configure the integral equation (IE) solver. Best for electrically large, open-boundary problems like antenna placement on vehicles, RCS … |
| `cst_get_solver_info` | Get current solver configuration and status. In connected mode this queries the active solver settings; in offline mode it describes expe… |
| `cst_configure_eigenmode_advanced` | Advanced eigenmode solver configuration for higher-order modes. Use this for waveguide mode analysis, cavity resonator design, and filter… |
| `cst_configure_ie_solver_advanced` | Advanced Integral Equation solver configuration for electrically large structures. Provides control over preconditioner, MLFMM accelerati… |
| `cst_configure_multilayer_solver` | Configure the solver for planar multilayer structures. Optimised for antenna-on-PCB, frequency selective surfaces (FSS), and radome analy… |

### Simulation control (6)

Run, pause, resume, stop simulations.

| Tool | What it does |
|------|--------------|
| `cst_run_simulation` | Start a CST simulation with the current solver settings. This is a blocking call that waits for the simulation to complete. Use cst_run_s… |
| `cst_run_simulation_async` | Start a CST simulation asynchronously (non-blocking). The simulation launches and control returns immediately. Use cst_get_simulation_sta… |
| `cst_get_simulation_status` | Check the status and progress of a running CST simulation. Returns information such as whether a simulation is running, progress percenta… |
| `cst_pause_simulation` | Pause a currently running CST simulation. The simulation can be resumed later with cst_resume_simulation. |
| `cst_resume_simulation` | Resume a previously paused CST simulation. Use after cst_pause_simulation to continue from where it stopped. |
| `cst_stop_simulation` | Stop and abort a running CST simulation. Unlike pause, a stopped simulation cannot be resumed — it must be restarted from the beginning. |

### Results (22)

S-parameters, far-field, VSWR, gain, Smith, bandwidth…

| Tool | What it does |
|------|--------------|
| `cst_get_s_parameters` | Extract S-parameter results from a completed CST simulation. Returns S-parameter data (magnitude, phase, real/imaginary) for the specifie… |
| `cst_get_farfield` | Get far-field radiation pattern results from a completed CST simulation at a specific frequency. Returns gain, directivity, radiation eff… |
| `cst_add_field_monitor` | Add a field monitor at a specific frequency to the CST project. Field monitors must be defined before running a simulation to capture fie… |
| `cst_get_impedance` | Get input impedance (Z-parameters) for a port from a completed CST simulation. Returns real and imaginary impedance vs frequency. Useful … |
| `cst_get_vswr` | Get Voltage Standing Wave Ratio (VSWR) for a port from a completed CST simulation. VSWR indicates impedance matching quality: 1.0 is perf… |
| `cst_get_gain` | Get antenna gain at a specific frequency from a completed CST simulation. Returns peak gain in dBi and the direction (theta, phi) of maxi… |
| `cst_get_efficiency` | Get antenna radiation efficiency from a completed CST simulation at a specific frequency. Returns total efficiency (including mismatch), … |
| `cst_list_results` | List all available results in the CST result tree. Optionally specify a subtree path to narrow the listing. Useful for discovering what s… |
| `cst_export_result` | Export a simulation result to a file (CSV, Touchstone, or text). Specify the result tree path and desired output format. Useful for post-… |
| `cst_get_result_summary` | Get a summary of all key simulation results from a completed CST simulation. Returns an overview of S-parameters, gain, efficiency, and i… |
| `cst_get_s_parameter_phase` | Extract S-parameter phase response from a completed CST simulation. Returns the phase of the specified S-parameter vs frequency. Optional… |
| `cst_get_group_delay` | Compute group delay from S-parameter phase for a port pair. Group delay is defined as tau = -d(phase)/d(2*pi*f) and represents the signal… |
| `cst_get_pattern_cut` | Extract an E-plane, H-plane, or custom radiation pattern cut from a completed CST simulation at a specific frequency. Returns gain vs ang… |
| `cst_get_cross_polarization` | Extract cross-polarization level and cross-polarization discrimination (XPD) from a completed CST simulation. Supports Ludwig-3, Ludwig-2… |
| `cst_get_axial_ratio` | Extract axial ratio for circularly polarized antennas from a completed CST simulation. Axial ratio (AR) indicates the quality of circular… |
| `cst_get_surface_current` | Extract surface current density distribution from a completed CST simulation at a specific frequency. Useful for understanding current fl… |
| `cst_get_efficiency_breakdown` | Get a detailed efficiency breakdown with loss budget from a completed CST simulation. Returns radiation efficiency, total efficiency, and… |
| `cst_get_time_domain_signal` | Extract time-domain port signal waveforms from a completed CST time-domain simulation. Returns incident, reflected, or transmitted signal… |
| `cst_get_smith_chart_data` | Extract Smith chart formatted impedance data from a completed CST simulation. Computes normalized impedance from S11 reflection coefficie… |
| `cst_get_bandwidth` | Calculate impedance bandwidth from S-parameter results. Finds the frequency range where S11 (or VSWR) meets the specified threshold. Retu… |
| `cst_get_radiation_pattern_3d` | Export full 3D radiation pattern data from a completed CST simulation at a specific frequency. Returns gain values over the full sphere i… |
| `cst_get_current_distribution` | Extract volume current distribution from a completed CST simulation at a specific frequency. Complements surface current extraction by pr… |

### Import / export (5)

CAD and Touchstone import/export, far-field export.

| Tool | What it does |
|------|--------------|
| `cst_import_cad` | Import a CAD file into CST Studio. Supports STEP (.stp/.step), IGES (.igs/.iges), STL (.stl), SAT/ACIS (.sat), DXF (.dxf), and OBJ (.obj)… |
| `cst_export_cad` | Export the current CST model (or a specific component) to a CAD format. Supports STL, SAT/ACIS, STEP, IGES, OBJ, and NASTRAN. |
| `cst_import_touchstone` | Import a Touchstone S-parameter file (.s1p, .s2p, .snp) into CST Studio for use as a reference or circuit element. |
| `cst_export_touchstone` | Export S-parameter simulation results to a Touchstone file. Requires a completed simulation with S-parameter data. |
| `cst_export_farfield` | Export far-field radiation pattern data to a file. Requires a completed simulation with far-field monitor results. |

### Parameters & optimizers (11)

Design parameters, sweeps, optimizers, sensitivity, yield.

| Tool | What it does |
|------|--------------|
| `cst_set_parameter` | Set or create a design parameter in CST Studio. Parameters can hold numeric values or string expressions referencing other parameters. |
| `cst_get_parameter` | Get the current value of a design parameter. Returns both the stored expression and the evaluated numeric value. |
| `cst_list_parameters` | List all design parameters in the current CST project with their names, expressions, and evaluated numeric values. |
| `cst_delete_parameter` | Delete a design parameter from the CST project. The parameter must not be referenced by other parameters or geometry. |
| `cst_parameter_sweep` | Set up a parameter sweep in CST Studio. The sweep runs the simulation multiple times, varying the specified parameter across a range of v… |
| `cst_optimizer` | Set up an optimization in CST Studio. Define a goal (minimize, maximize, or target a specific value for a result), specify which paramete… |
| `cst_multi_objective_optimizer` | Set up a multi-objective optimization with weighted goals and optional constraints. Supports Pareto-front exploration using Genetic Algor… |
| `cst_sensitivity_analysis` | Set up a one-at-a-time sensitivity analysis to rank parameters by their impact on a result. Varies each parameter individually while keep… |
| `cst_yield_analysis` | Set up a Monte Carlo yield analysis to estimate manufacturing yield. Randomly varies parameters according to their tolerances and evaluat… |
| `cst_constrained_optimizer` | Single-objective optimization with explicit inequality constraints. Example: minimize S11 subject to gain > 8 dBi and bandwidth > 100 MHz. |
| `cst_parameter_interpolation` | Interpolate results between parameter sweep data points to estimate performance at a specific parameter value without running a new simul… |

### Antenna evaluation (3)

Goal-driven evaluation and refinement helpers.

| Tool | What it does |
|------|--------------|
| `cst_evaluate_antenna` | Evaluate current antenna simulation results against performance goals. Exports S-parameter data and checks VSWR (or return loss) against … |
| `cst_analyze_impedance` | Analyze antenna impedance match quality across frequency bands using S-parameter data. Exports S11 from a completed simulation, computes … |
| `cst_refine_antenna` | Run an automated Nelder-Mead optimization loop to tune CST design parameters toward VSWR goals across specified frequency bands. Each ite… |

### Diagnostics (5)

Logs, delete results, auto-dismiss blocking CST dialogs.

| Tool | What it does |
|------|--------------|
| `cst_delete_results` | Delete simulation results from the current CST project. This prevents the 'Results May Get Incompatible With Model' dialog that blocks au… |
| `cst_read_project_log` | Read solver log files and project status information from the current CST project. Returns solver running state and the contents of the m… |
| `cst_dismiss_dialogs` | Find and dismiss any visible CST dialog windows (error popups, 'Results Incompatible' dialogs, solver warnings). Returns the title and te… |
| `cst_start_dialog_watcher` | Start a background thread that automatically detects and dismisses CST dialog windows as they appear. Essential for long-running operatio… |
| `cst_stop_dialog_watcher` | Stop the background dialog watcher and return its log of all dialogs that were auto-dismissed. Use after completing an operation that req… |

### Antenna templates (13)

Parametric antennas: patch, dipole, horn, Yagi, helix…

| Tool | What it does |
|------|--------------|
| `cst_antenna_patch` | Create a rectangular microstrip patch antenna with calculated dimensions for a target frequency. Supports inset, microstrip, and probe fe… |
| `cst_antenna_dipole` | Create a half-wave dipole antenna at a target frequency. Generates two wire arms with a discrete port at the feed gap. |
| `cst_antenna_monopole` | Create a quarter-wave monopole antenna over a ground plane. Generates a vertical wire element, ground plane, and feed port. |
| `cst_antenna_horn` | Create a pyramidal horn antenna for a target frequency and gain. Generates the waveguide section, flared horn, and waveguide port. |
| `cst_antenna_yagi` | Create a Yagi-Uda antenna with a reflector, driven element, and configurable number of directors. Generates wire elements and a discrete … |
| `cst_antenna_helix` | Create an axial-mode helical antenna for circular polarization. Generates helix coil, ground plane, and feed. |
| `cst_antenna_vivaldi` | Create a Vivaldi (tapered slot) antenna on a dielectric substrate. Generates substrate, exponential taper metallisation, and feed. |
| `cst_antenna_slot` | Create a slot antenna in a ground plane. Generates the ground plane with a resonant slot and microstrip feed. |
| `cst_antenna_ifa` | Create an Inverted-F antenna (IFA) suitable for mobile devices. Generates ground plane, radiating arm, shorting pin, and feed. |
| `cst_antenna_pifa` | Create a Planar Inverted-F Antenna (PIFA) for compact wireless devices. Generates ground plane, top patch, shorting wall, and feed. |
| `cst_antenna_spiral` | Create a wideband Archimedean spiral antenna. Generates two spiral arms with a discrete port feed at the center. |
| `cst_antenna_bowtie` | Create a planar bowtie antenna. Generates two triangular arms with a discrete port at the feed gap. |
| `cst_list_antenna_templates` | List all available parametric antenna templates with descriptions and typical use cases. No arguments required. |

### Antenna arrays (8)

Linear/planar/circular arrays, beam steering, taper.

| Tool | What it does |
|------|--------------|
| `cst_array_linear` | Create a linear antenna array by replicating an element along a chosen axis. Uses Transform.Translate to produce copies named Element_1 t… |
| `cst_array_planar` | Create a 2D planar antenna array with rectangular or triangular lattice. Replicates an element in X and Y using Transform.Translate. |
| `cst_array_circular` | Create a circular antenna array by placing elements at equal angular intervals around a circle of given radius. |
| `cst_array_compute_factor` | Compute the array factor analytically for a linear or planar array. Returns AF(theta) in dB, half-power beamwidth, first null beamwidth, … |
| `cst_array_beam_steering` | Calculate progressive phase weights to steer the main beam to a specified angle. Returns phase weights and VBA to set port phases in CST. |
| `cst_array_taper_design` | Design amplitude taper weights for sidelobe control. Supports uniform, cosine, Hamming, Hanning, Blackman, Taylor, and Chebyshev window f… |
| `cst_array_grating_lobe_analysis` | Analyse whether grating lobes exist for a given element spacing and maximum scan angle. Returns safe spacing and grating lobe angles. |
| `cst_array_mutual_coupling` | Set up a multi-port S-parameter simulation in CST for mutual coupling extraction between array elements. |

### PCB / SI (12)

Stackups, traces, vias, ground planes, Gerber import.

| Tool | What it does |
|------|--------------|
| `cst_pcb_create_stackup` | Create a PCB layer stackup in CST Studio. Generates brick geometry for each layer (signal, ground, power, dielectric) positioned vertical… |
| `cst_pcb_create_trace` | Create a PCB trace (microstrip, stripline, coplanar waveguide, or grounded CPW) in CST Studio. Optionally calculates trace width from a t… |
| `cst_pcb_create_via` | Create a PCB via (through, blind, or buried) in CST Studio. Generates the cylindrical via barrel with specified drill and pad dimensions.… |
| `cst_pcb_create_ground_plane` | Create a ground or power plane with optional cutouts (split planes, isolation slots) in CST Studio. Generates a solid copper brick and su… |
| `cst_pcb_import_gerber` | Import a Gerber/ODB++/DXF file for PCB analysis in CST Studio. Generates VBA for the CST Gerber import wizard. In offline mode, explains … |
| `cst_pcb_list_stackup_templates` | List predefined PCB stackup templates with complete layer definitions. Includes standard 2/4/6-layer FR-4 and RF-grade Rogers stackups. U… |
| `cst_pcb_differential_pair` | Create a differential pair of PCB traces in CST Studio. Generates two parallel bricks separated by a gap and calculates the differential … |
| `cst_pcb_via_model` | Create a detailed PCB via model in CST Studio with parasitic inductance and capacitance estimates. Uses the Goldfarb model for via induct… |
| `cst_pcb_via_fence` | Create a row (or multiple rows) of vias along a path for isolation or Substrate Integrated Waveguide (SIW) construction. Generates an arr… |
| `cst_pcb_cpw_transition` | Create a coplanar waveguide (CPW) to microstrip transition in CST Studio. Generates a tapered geometry that linearly tapers the center co… |
| `cst_pcb_calculate_coupling` | Calculate electromagnetic coupling between parallel PCB traces. Computes even/odd mode impedances, coupling coefficient, and near-end/far… |
| `cst_pcb_siw_waveguide` | Create a Substrate Integrated Waveguide (SIW) in CST Studio. Generates top and bottom copper planes with two rows of via fences forming t… |

### Matching networks (8)

L / Pi / T networks, stubs, quarter-wave, Smith transforms.

| Tool | What it does |
|------|--------------|
| `cst_matching_l_network` | Design an L-section impedance matching network. Computes inductor and capacitor values for matching a source impedance to a load impedanc… |
| `cst_matching_pi_network` | Design a Pi-section impedance matching network (C-L-C or L-C-L). Uses two back-to-back L-sections via a virtual resistance for controllab… |
| `cst_matching_t_network` | Design a T-section impedance matching network (L-C-L). Dual of Pi-network, uses two back-to-back L-sections. Pure Python computation. |
| `cst_matching_stub` | Design a single-stub impedance matching network. Computes the stub length and distance from the load using Smith chart transmission-line … |
| `cst_matching_quarter_wave` | Design a quarter-wave transformer matching network. Supports single and multi-section designs with maximally flat (binomial) or Chebyshev… |
| `cst_matching_create_lumped` | Generate CST VBA code to create a lumped-element matching network. Each component (inductor, capacitor, resistor) is placed as a CST Lump… |
| `cst_impedance_smith_transform` | Apply a reactive element transformation to an impedance on the Smith chart. Supports series L/C, shunt L/C, and transmission line operati… |
| `cst_matching_microstrip_impedance` | Calculate microstrip transmission line characteristic impedance from physical dimensions using the Hammerstad-Jensen model with optional … |

### VBA escape hatch (3)

Raw VBA execution and built-in VBA object reference.

| Tool | What it does |
|------|--------------|
| `cst_execute_vba` | Execute raw VBA code in CST Studio Suite. The code is validated for safety (shell access, file I/O, and external process execution are bl… |
| `cst_vba_help` | Get VBA reference documentation for a CST Studio object. Returns the object description and a list of its common methods and properties. |
| `cst_list_vba_objects` | List available CST Studio VBA objects, optionally filtered by category. Returns object names with brief descriptions. |

