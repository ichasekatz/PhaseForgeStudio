# PhaseForgeStudio — Master Engineering Specification

**Status:** Full requested scope; not an implementation report.  
**Repository:** https://github.com/ichasekatz/PhaseForgeStudio  
**Authority:** This document preserves the six supplied specifications in full; the execution rules below clarify how to implement them without losing requirements.

## Mission and scope

Build and verify a unified PhaseForgeStudio across PhaseForge, PhaseForgePlus, BLADE, MaterialsFramework, PAIPAI, ORCHID, shared file explorer/artifact registry, jobs, projects, visualization, and four MLIP benchmark modes. Preserve existing capabilities and scientific correctness. Do not equate a present GUI tab, API route, or adapter stub with a completed working feature.

## Source specifications (complete, unchanged text below)

1. PAIPAI + ORCHID integration
2. Unified architecture, universal explorer, BLADE GUI modernization
3. Upstream audit and feature parity for PhaseForge/Plus/MaterialsFramework/BLADE
4. MLIP phase diagram benchmarking
5. Four MLIP benchmark modes and reusable caching
6. Final end-to-end scientific and GUI validation

All six are mandatory. Later sections expand earlier sections; overlapping instructions are cumulative, not alternative tasks.

## Clarifications / precedence

- **Workspace navigation:** The early suggestion of exactly four primary workspaces is not a cap. PhaseForgePlus and MLIP Benchmarking must also remain discoverable, either as dedicated workspaces or clearly accessible nested workspaces. BLADE and MaterialsFramework may be separately presented or grouped, but preserve all verified functionality.
- **Upstream capabilities:** Compare upstream versions/commits actually deployed. Implement supported features, clearly mark incompatible, absent, license-restricted or inaccessible capabilities rather than fabricating them. Tests and demonstrable functionality govern completion.
- **Scientific benchmarks:** Maintain strict separation of unrefitted predictions, fitted evaluations, and independent held-out reference comparisons. Never infer phase boundaries from sparse experiments. Flag missing finite-temperature energy terms.
- **No unapproved expensive jobs:** Small local computations and normal tests are allowed within environment limits; do not submit expensive HPC/cloud jobs or purchase services without permission.
- **Existing work:** Preserve users' calculations and data and confirm functionality before major refactors. Use incremental commits/checkpoints; do not falsely report 100% complete.
- **Screenshots and fixtures:** If the previous Cu–Zr screenshot is unavailable on disk, request its location once or implement the described multi-panel layout; do not pretend to have inspected the image.
- **Reliability:** Missing dependency, inaccessible upstream, unavailable credentials or restricted remote operations must be recorded as BLOCKED with actionable next steps, not silently omitted.

## Required implementation process

1. Inspect existing code, preserve existing behavior, record upstream versions, and create `docs/FRAMEWORK_FEATURE_AUDIT.md` + machine-readable matrix with an ID for every audited feature.
2. Produce `docs/IMPLEMENTATION_ROADMAP.md` with dependencies, implementation stages, tests, and acceptance conditions. Make concrete code changes in the same session after the initial audit rather than stopping at planning.
3. Create `docs/IMPLEMENTATION_PROGRESS.md` and a machine-readable task ledger containing: feature ID, originating spec/section, upstream source, implementation location, status, verification evidence, blockers, next action, and commit ID. Do not drop any original requirement.
4. Build common artifact registry, file-explorer actions, converters, provenance, job/project/visualization components before using them for all frameworks.
5. Verify existing framework parity and modernize BLADE; complete PAIPAI/ORCHID and benchmarking modules on common infrastructure; implement working UI/backends.
6. Run numerical, backend, browser, cross-framework, and regression tests. Save `docs/FINAL_VALIDATION_REPORT.md` and `docs/USER_ACCEPTANCE_TESTING.md` with exact reproducible commands and observed results.
7. At each session boundary commit/checkpoint code and progress, identify exact remaining work, and include a copy/paste resume instruction. The next session should inspect progress and continue rather than begin the audit again.

**Completion rule:** No overall completion claim until every feature ID is PASS or transparently BLOCKED with reason; critically broken features cannot be considered a successful release. Mark tests PASS, FAIL, BLOCKED, NOT TESTED or MOCK ONLY, with evidence. Do not assume an autonomous process continues after a session or usage limit.

## Crosscutting acceptance scenarios

- Generate a PhaseForge SQS -> select it in shared explorer -> run supported PAIPAI calculation -> inspect trajectory -> send configuration to MaterialsFramework -> view downstream result with preserved provenance.
- Create PhaseForge TDB -> open in PhaseForgePlus -> optimize using appropriate data -> view before/after diagrams -> overlay independent ORCHID reference observations where available.
- Use BLADE's full preexisting feature set through a visually consistent GUI, verified with a feature-parity checklist and regression tests.
- Run two available MLIPs on the same binary system -> calculate comparable energies -> build TDBs -> plot aligned phase diagrams -> evaluate valid reference metrics and produce a report; test all four modes and caching.
- Interrupt/fail jobs; verify correct cancellation, restart, safe file conversion, cross-framework discoverability, provenance and export.

## Complete original source specifications

---

# ORIGINAL SPECIFICATION: 01_PAIPAI_ORCHID

_Source file: `Pasted text(20261119-215943).txt`. The text below is preserved as supplied._

# Claude Code Task: Integrate PAIPAI and ORCHID into PhaseForgeStudio

I want you to implement full PAIPAI and ORCHID integration into my existing PhaseForgeStudio GUI.

**Main repository:** https://github.com/ichasekatz/PhaseForgeStudio

**PAIPAI:** https://github.com/siyazhu/PAIPAI

**ORCHID:** https://orchid-project.org/

**ORCHID GitHub:** https://github.com/orchid-calphad

**ORCHID data:** https://data.orchid-project.org/

## 1. Inspect the existing codebase

Before making changes, inspect the entire PhaseForgeStudio architecture, especially:

- `server.py`
- `index.html`
- `phaseforge_studio/`
- Configuration handling
- Existing workspace navigation
- MaterialsFramework and BLADE integrations
- Job execution, logging, cancellation, and history
- File browsing and visualization
- Current tests and documentation

Understand how the current GUI works and reuse its architecture wherever possible.

The goal is to add new functionality without breaking existing PhaseForge, BLADE, SQS, MLIP, or analysis workflows.

Do not create an unrelated application or introduce a new frontend framework unnecessarily.

## 2. Add PAIPAI as a computational workspace

PAIPAI (Package for Alloy Interstitial Predictions using Artificial Intelligence) combines Monte Carlo sampling with machine-learning interatomic potentials to search for low-energy atomic configurations, including defective and interstitial-containing alloys.

Inspect the actual PAIPAI repository to determine its installation requirements, APIs, command-line interfaces, inputs, outputs, and supported workflows.

Do not assume undocumented APIs exist.

### GUI features

Add a PAIPAI workspace with:

**Structure and composition configuration**
- Import POSCAR, CIF, and other formats supported by PAIPAI.
- Select alloy elements and compositions.
- Configure lattice structures and supercells.
- Configure vacancies, interstitial species, and defect concentrations where supported.
- Reuse existing structures from PhaseForgeStudio.

**Monte Carlo configuration**
- Expose documented MC sampling parameters.
- Configure temperature and number of MC steps.
- Configure random seeds and parallelization.
- Select available MLIP calculators.
- Support documented restart/checkpoint functionality.
- Display input validation and resource requirements.

**Execution**
- Launch PAIPAI calculations from the GUI.
- Display live logs, progress, energies, and job status.
- Allow safe cancellation.
- Integrate with existing HPC execution patterns.
- Support simultaneous jobs only where execution isolation is reliable.

**Visualization**
- Visualize initial and final atomic configurations using the existing 3D viewer.
- Show energy versus MC step.
- Show accepted/rejected moves if available.
- Show defect/interstitial distributions.
- Compare initial and final configurations.
- Display short-range-order metrics where supported.
- Support trajectory playback when trajectory data are available.

**Outputs**
- Export resulting structures and numerical data.
- Save input parameters and software versions.
- Store reproducible run metadata.
- Make PAIPAI outputs available through the existing file browser.

Use an adapter around the PAIPAI API or CLI so its implementation remains modular.

Do not substitute SQS generation for a PAIPAI Monte Carlo calculation; they perform different tasks.

## 3. Add ORCHID as a CALPHAD data workspace

ORCHID is an open, provenance-tracked collection of thermodynamic and phase-equilibrium data.

Inspect the actual ORCHID documentation, APIs, data schemas, releases, and licensing before implementation.

### GUI features

Create a dedicated ORCHID workspace with:

**Data discovery**
- Search by element or chemical system.
- Browse available binary systems.
- Explore phase-equilibrium observations.
- View reported thermodynamic measurements.
- Browse available TDB assessments and their provenance.
- Identify which data are experimental, calculated, assessed, or machine-extracted.

**Phase-diagram visualization**
- Display available binary phase diagrams.
- Plot composition versus temperature.
- Compare different assessments when available.
- Display phase regions and boundaries.
- Overlay experimental observations.
- Allow filtering by source, phase, temperature, and evidence type.

**Thermodynamic data**
- Explore formation enthalpies.
- View Gibbs-energy-related data when available.
- Compare Materials Project, OQMD, and assessed CALPHAD hull data where supported.
- Inspect phase registry information.
- Display source uncertainties, quality flags, and citations.

**CALPHAD integration**
- Allow users to select compatible ORCHID datasets.
- Import permitted TDB files into PhaseForgeStudio.
- Use imported databases with existing pycalphad analysis workflows.
- Compare PhaseForge-generated TDB results with external assessments.
- Support exporting selected thermodynamic data for subsequent fitting or validation.

**Comparison and validation**
- Compare calculated phase boundaries with ORCHID data.
- Overlay experimental observations on predicted phase diagrams.
- Calculate quantitative residuals when the values and conditions are comparable.
- Provide comparison plots and downloadable data tables.
- Clearly distinguish predicted and measured values.

### Data access

Investigate:

- ORCHID's published static datasets and documented endpoints.
- The `orchid-mcp` package and its available tools.
- Downloadable versioned ORCHID releases.
- Local caching for HPC environments without unrestricted network access.

Choose the most maintainable supported integration path.

Do not invent endpoints or use fragile webpage scraping when documented machine-readable data are available.

Respect licenses, original-source attribution, and dataset provenance.

## 4. Integrate both into the existing workspace navigation

The GUI should have four primary workspace options:

1. PhaseForge
2. BLADE
3. PAIPAI
4. ORCHID

Use the existing tab/navigation design and styling.

Every workspace should preserve its configuration and user state when switching.

Do not create unnecessary duplicate servers or incompatible UI patterns.

If PAIPAI or ORCHID is unavailable, the GUI should still launch normally and display a clear installation/configuration message for that workspace.

## 5. Enable interoperability between workspaces

I want PhaseForgeStudio to function as a unified materials research platform.

Implement supported data transfers such as:

**PhaseForge → PAIPAI**
- Send generated structures or relaxed SQS configurations to PAIPAI.
- Preserve lattice, composition, atom ordering, and metadata.
- Verify that transferred structures meet PAIPAI's requirements.

**PAIPAI → PhaseForge**
- Import resulting configurations.
- Visualize and compare energies.
- Reuse structures in existing calculations where compatible.

**PhaseForge/BLADE → ORCHID**
- Compare generated CALPHAD predictions against external thermodynamic data.
- Compare calculated phase diagrams and phase stability.
- Match systems, phases, compositions, temperatures, and units correctly.

**ORCHID → PhaseForge/BLADE**
- Import compatible thermodynamic reference data.
- Reuse permitted TDB assessments.
- Make provenance information available to subsequent analysis.

Never silently replace simulated values with ORCHID values.

## 6. Technical requirements

- Preserve compatibility with the existing Python-server and HTML/JavaScript frontend architecture.
- Reuse existing job and event-streaming infrastructure.
- Introduce modular backend adapters rather than putting all integration logic directly into `server.py`.
- Implement secure file-path validation.
- Avoid arbitrary shell-command execution from user inputs.
- Validate downloaded data and imported files.
- Handle network failures, missing packages, and unsupported systems gracefully.
- Keep optional dependencies optional.
- Maintain support for SSH port forwarding and HPC deployment.
- Do not introduce large mandatory dependencies without justification.
- Use supported APIs and documented commands, not fabricated interfaces.

## 7. Testing

Implement automated tests covering:

- PAIPAI dependency detection.
- PAIPAI input validation and job execution.
- Job cancellation and failure handling.
- Structure import/export.
- ORCHID data retrieval and parsing.
- Phase/composition matching.
- Unit conversion.
- Workspace switching and configuration persistence.
- Backward compatibility with existing PhaseForge/BLADE features.

Use mocks or small test fixtures when actual PAIPAI calculations are too expensive.

Clearly distinguish integration tests requiring installed external software from tests that run without it.

## 8. Documentation

Update the README and configuration examples to explain:

- How to install PAIPAI.
- How to configure the PAIPAI executable/package.
- How to configure ORCHID data access.
- How to use all four workspaces.
- How to exchange structures and data between workflows.
- Which optional functionality requires external dependencies.
- How to run tests and troubleshoot failures.

Include links to the original PAIPAI and ORCHID projects and appropriate citations.

## 9. Implementation expectations

I want working functionality, not just mockups or empty tabs.

Follow this order:

1. Audit the existing PhaseForgeStudio codebase.
2. Inspect the actual PAIPAI and ORCHID implementations.
3. Design compatible backend adapters.
4. Implement navigation and configuration handling.
5. Implement PAIPAI execution and visualization.
6. Implement ORCHID data discovery and analysis.
7. Implement cross-workspace data transfer.
8. Add automated tests.
9. Update documentation.
10. Run tests and fix regressions.

Do not stop after writing a plan. Proceed with implementation.

If an external tool lacks a required capability, implement the supported portion and document the limitation instead of fabricating behavior.

At completion, provide:
- A summary of changes.
- Files modified or created.
- New API endpoints.
- Dependencies and installation steps.
- Test results.
- Any limitations or unfinished features.

**The final result should be a cohesive PhaseForgeStudio application with PhaseForge, BLADE, PAIPAI, and ORCHID integrated into one consistent GUI.**

---

# ORIGINAL SPECIFICATION: 02_UNIFIED_ARCHITECTURE_BLADE

_Source file: `Pasted text (2)(20261119-215949).txt`. The text below is preserved as supplied._

# Additional Requirements: Unified PhaseForgeStudio Architecture, Cross-Framework Interoperability, and BLADE GUI Modernization

In addition to the PAIPAI and ORCHID integrations described previously, I want PhaseForgeStudio to function as one fully interconnected application rather than four independent tools placed inside the same GUI.

**Repository:** https://github.com/ichasekatz/PhaseForgeStudio

The four primary frameworks are:

1. PhaseForge
2. BLADE
3. PAIPAI
4. ORCHID

The entire application should have a consistent design, shared file management, interchangeable inputs and outputs where scientifically compatible, centralized job management, and seamless navigation.

## 1. Universal File Explorer — Central to Everything

The existing file exploration feature should become a shared workspace accessible from every framework.

I want to browse files produced by any framework and use those files directly as inputs to another framework without manually downloading, uploading, or copying them.

For example:

- Generate an SQS using PhaseForge → select the structure in the file explorer → open it in PAIPAI.
- Relax a structure with an MLIP → use the relaxed structure as the starting configuration for another calculation.
- Generate a TDB using BLADE → select the database → open it in PhaseForge for phase-diagram calculations.
- Retrieve compatible thermodynamic data using ORCHID → use that data in a BLADE fitting or validation workflow.
- Generate stability data in PhaseForge → compare it with experimental data using ORCHID.
- Select a structure from a previous run → use it in a new workflow without regenerating it.

### File Explorer Features

Preserve all current file exploration functionality and extend it with:

**A. Shared access**

Every framework must be able to access the same file explorer.

All generated outputs should appear automatically when saved.

Support existing local and HPC directory structures, including files stored in external project locations, without forcing users to relocate their data.

**B. File recognition**

Automatically recognize supported materials science formats, including:

- POSCAR / CONTCAR
- CIF
- XYZ / extended XYZ
- LAMMPS structure and trajectory files
- ASE-readable structures
- TDB
- CSV / TSV
- JSON
- YAML
- NumPy arrays
- Pickle files where explicitly trusted
- Calculation logs and output files
- Other file types already supported by the application

Inspect actual file contents where needed rather than relying solely on extensions.

Do not automatically deserialize untrusted pickle files.

**C. Context-aware actions**

When I right-click or select a file, display actions based on its type and compatibility.

For example, selecting a POSCAR might offer:

- Open structure viewer
- Use as PhaseForge input
- Use as PAIPAI input
- Relax with MLIP
- Create supercell
- Export to another supported format

Selecting a TDB might offer:

- Open in BLADE
- Calculate phase diagram
- Evaluate Gibbs energies
- Compare with ORCHID data
- Inspect phases and constituents

Selecting a stability-results CSV might offer:

- Plot results
- Generate contour plots
- Perform Pareto analysis
- Compare with experimental measurements
- Export or use as input to a compatible analysis workflow

Show only valid actions, and explain why an action is unavailable when necessary.

**D. Drag-and-drop**

Support dragging files from the explorer into compatible input fields and calculation panels.

Where possible, also provide an explicit "Send to..." action so drag-and-drop is not required.

**E. Metadata and provenance**

Track:

- Source framework
- Original path
- Producing calculation
- Composition and chemical system
- Crystal structure, where applicable
- Temperature and pressure, where applicable
- Software version
- Input parameters
- Creation date
- Parent files and downstream calculations

Preserve the relationship between files and calculations.

## 2. Build a Shared Data and Workflow System

I want interoperability to be implemented through a reusable architecture rather than one-off integrations between every pair of frameworks.

Introduce a common artifact registry and adapter system.

Each framework should declare:

- Supported input types
- Supported output types
- File compatibility requirements
- Available actions
- Supported conversions
- Required parameters
- Validation functions

The shared system should determine whether a file can be transferred from one workflow to another.

### Data conversion

Use scientifically appropriate conversions where possible.

Examples:

- CIF → POSCAR
- POSCAR → extended XYZ
- ASE structure → LAMMPS input
- Calculation results → standardized CSV
- Compatible thermodynamic measurements → a BLADE-supported data format

Preserve units, lattice vectors, coordinate conventions, chemical species, atomic ordering where required, and provenance.

Never silently convert thermodynamic data in a way that changes their meaning.

A structure file is not automatically a valid thermodynamic database input, and a stability-metrics CSV is not automatically compatible with a fitting routine.

If a conversion is impossible or scientifically invalid, explain why.

### Unified workflows

Allow workflows to be chained:

PhaseForge → PAIPAI → PhaseForge analysis

PhaseForge → BLADE → PhaseForge stability calculations

ORCHID → BLADE fitting → PhaseForge phase-diagram analysis

PhaseForge stability results → ORCHID experimental comparison

These are examples, not an exhaustive list.

Add an extensible workflow/action registry so future frameworks can be integrated without rewriting the whole application.

## 3. Modernize the BLADE GUI Without Losing Features

The existing BLADE interface was built using older code, so it looks different from the newer PhaseForgeStudio components.

I want BLADE to have the **same appearance, styling, layout patterns, navigation behavior, and user experience as the other frameworks**.

However, this must be a presentation-layer modernization, not a reduction of BLADE's capabilities.

### Requirements

First, thoroughly inspect the entire existing BLADE GUI.

Create an inventory of every currently supported feature, including:

- Inputs
- Calculation settings
- Advanced configuration options
- Workflow stages
- Buttons and actions
- Forms
- Job submission
- Progress reporting
- Logs
- File browsing
- Visualization
- Data management
- Export functions
- Error handling
- Any specialized functionality

Do not assume the above list is complete.

Compare the old BLADE implementation with the current PhaseForgeStudio GUI and identify which components can be reused.

Then migrate BLADE's interface to the shared design system.

### Visual consistency

BLADE should use the same:

- Navigation structure
- Typography
- Colors and theme handling
- Buttons
- Input controls
- Cards and panels
- Spacing
- Icons
- Tables
- Plot styling
- Modal dialogs
- Notifications
- Loading indicators
- File explorer
- Job progress indicators
- Responsive layout

I should be able to switch between PhaseForge, BLADE, PAIPAI, and ORCHID without feeling like I am using four unrelated applications.

### Feature preservation

**Absolutely do not remove or simplify existing BLADE features to make the redesign easier.**

All current functionality must remain accessible and operational.

If a BLADE component requires specialized controls, retain the functionality while adapting its presentation to the shared visual language.

Do not replace functional features with placeholders or mock controls.

Create a feature-parity checklist comparing the old and new BLADE interfaces.

Test each feature before considering the migration complete.

The new BLADE GUI should have 100% functional parity with the current BLADE GUI, subject to any independently verified existing defects that you document.

## 4. Centralized Job Management

All computational frameworks should use a shared job-management interface.

I want to monitor calculations without switching between different framework-specific job panels.

Each job should display:

- Framework
- Calculation type
- Job name
- Working directory
- Submission time
- Current status
- Progress, where measurable
- Elapsed runtime
- Relevant CPU/GPU resources
- Live logs
- Input files
- Output files
- Errors and warnings

Support local and HPC execution through existing supported methods.

Preserve framework-specific execution parameters.

Use a common state model for queued, running, completed, failed, and canceled jobs.

Ensure canceling a job terminates the correct underlying process or scheduler job and does not inadvertently terminate unrelated calculations.

Support reopening completed calculations and accessing their outputs directly through the shared file explorer.

## 5. Unified Visualization System

Every framework should reuse the same visualization infrastructure wherever possible.

Implement common viewers for:

- Crystal structures
- Atomic trajectories
- Energy curves
- Phase diagrams
- Gibbs-energy curves
- Composition–temperature contour plots
- Phase fractions
- Stability maps
- Pareto fronts
- Experimental versus predicted data

If a plot already exists in the application, reuse and improve it rather than implementing a visually inconsistent duplicate.

Allow a plot generated by one framework to be opened from the file explorer while another framework is active.

Where scientifically meaningful, allow compatible plots to be compared or overlaid.

Provide consistent export options and properly labeled units.

## 6. Shared Project Organization

Introduce or extend a project system so each research project can contain outputs from multiple frameworks.

Example:

```text
projects/
└── HEDB_Stability/
    ├── project.json
    ├── structures/
    ├── phaseforge/
    ├── blade/
    ├── paipai/
    ├── orchid/
    ├── shared_data/
    ├── comparisons/
    └── figures/
```

This is an organizational example, not a requirement to move all existing files.

Existing project directories must continue working.

Support registering existing directories as project resources without copying their entire contents.

Every file should retain its original provenance.

## 7. Maintain Scientific and Computational Compatibility

I use PhaseForgeStudio for materials research, including multicomponent diborides, SQS calculations, MLIP workflows, CALPHAD fitting, phase stability, spinodal analysis, and oxidation-related calculations.

The integration must preserve scientific correctness.

Particularly important:

- Distinguish structure retention from homogeneous single-phase stability.
- Do not confuse Gibbs energy above the hull with formation energy.
- Preserve temperature and composition conventions.
- Respect dependent-element conventions in chemical-Hessian calculations.
- Support multicomponent and multisublattice systems.
- Avoid treating experimental observations and computational predictions as equivalent.
- Track units and reference states explicitly.
- Never silently overwrite source datasets.

The framework should remain extensible to other materials systems, not just diborides.

## 8. Architecture and Maintainability

Refactor shared functionality into reusable modules.

Prefer a structure conceptually similar to:

```text
phaseforge_studio/
├── core/
│   ├── artifact_registry.py
│   ├── file_types.py
│   ├── converters.py
│   ├── workflows.py
│   ├── job_manager.py
│   └── projects.py
├── integrations/
│   ├── phaseforge/
│   ├── blade/
│   ├── paipai/
│   └── orchid/
├── visualization/
└── ...
```

Adapt this to the actual repository structure instead of blindly imposing it.

Keep scientific engines separate from interface code.

Avoid creating four versions of the same file explorer, job manager, or plotting functions.

Use adapters and reusable components to make future integrations straightforward.

## 9. Testing and Regression Prevention

Before redesigning BLADE, capture the current behavior with tests or reproducible workflows.

Implement tests for:

- Every existing BLADE feature
- Framework navigation
- Cross-framework file selection
- File format recognition
- Data conversion
- Drag-and-drop
- Context-aware file actions
- Workflow chaining
- Job execution and cancellation
- Local/HPC file handling
- Metadata and provenance
- Plot and viewer compatibility
- Backward compatibility with previous projects

Test a full workflow where a structure is generated in one framework, selected from the explorer, passed to another framework, processed, and returned for visualization.

Test a thermodynamic workflow involving a TDB and phase-diagram calculation.

Verify that existing workflows still work without PAIPAI or ORCHID installed.

## 10. Final Expectations

Do not simply add two new tabs or visually redesign BLADE.

I want a unified, interoperable materials-science research environment.

**Implementation priorities:**

1. Inspect and document existing features and dependencies.
2. Establish a common visual design system.
3. Implement the universal file explorer and artifact registry.
4. Implement standardized cross-framework input/output actions.
5. Modernize BLADE while retaining all functionality.
6. Integrate PAIPAI and ORCHID into the common architecture.
7. Unify job management and visualization.
8. Test complete end-to-end workflows.
9. Update documentation.

Proceed with actual implementation rather than stopping after proposing an architecture.

Preserve existing functionality and data throughout the process.

At completion, provide a feature-parity report for BLADE, an interoperability matrix for all four frameworks, a list of modified files, test results, and any verified limitations.

**Success means I can navigate one consistent GUI, locate a file produced by any framework, select it as input to another compatible framework, execute the next calculation, and visualize all results without leaving PhaseForgeStudio.**

---

# ORIGINAL SPECIFICATION: 03_FEATURE_PARITY

_Source file: `Pasted text (3).txt`. The text below is preserved as supplied._

# Claude Code — Full Framework Audit, Feature Completion, and Seamless PhaseForgeStudio Integration

This is an additional requirement to my previous instructions for PAIPAI, ORCHID, the universal file explorer, shared workflows, and BLADE GUI modernization.

**I want PhaseForgeStudio to provide the complete functionality of its underlying frameworks, not merely partial GUI implementations.**

Some frameworks have already been integrated, especially PhaseForge and PhaseForgePlus, but I am unsure whether every feature, option, calculation method, and output is actually available or implemented correctly.

Your task is to perform a comprehensive source-code-level audit, identify all missing or incorrectly implemented functionality, implement the missing features, and establish seamless interoperability between all supported frameworks.

## 1. Source Repositories

Use these original repositories as references:

- PhaseForgeStudio: https://github.com/ichasekatz/PhaseForgeStudio
- PhaseForge: https://github.com/dogusariturk/PhaseForge
- PhaseForgePlus: https://github.com/dogusariturk/PhaseForgePlus
- MaterialsFramework: https://github.com/dogusariturk/MaterialsFramework
- PAIPAI: https://github.com/siyazhu/PAIPAI
- ORCHID: https://orchid-project.org/
- ORCHID GitHub: https://github.com/orchid-calphad

Also locate the actual BLADE implementation currently used by PhaseForgeStudio. Do not assume BLADE and MaterialsFramework are identical.

Inspect the version, branch, and commit of each framework actually installed or referenced by PhaseForgeStudio.

Compare those versions against the latest compatible upstream implementations.

Do not blindly update dependencies if doing so would break existing workflows.

## 2. Audit PhaseForge — Complete Feature Parity

PhaseForge already exists in my GUI, but I want you to determine whether the integration exposes and correctly executes all supported original functionality.

Inspect the full upstream source code, executables, command-line parameters, configuration files, and examples.

Pay particular attention to:

### Structure generation and SQS

- ATAT integration and mcsqs workflows.
- Available structure types and lattice selections.
- Multicomponent composition definitions.
- Sublattice configuration, where supported.
- SQS generation levels and settings.
- Pair, triplet, and quadruplet correlations.
- Neighbor-shell configurations.
- Short-range-order options.
- Structure generation, selection, and export.

### MLIP calculations

- All upstream-supported MLIP calculators and models.
- Single-point energy calculations.
- Structure relaxation.
- Force and stress calculations.
- Molecular dynamics.
- Liquid-state calculations.
- LAMMPS integration.
- Phonon and vibrational free-energy calculations.
- Formation-enthalpy extraction.
- Relevant job-execution and configuration options.

### PhaseForge commands

Audit all actual CLI commands and options, including:

- `sqscal`
- `MLIPrelax`
- `MLIPcalc`
- `extract_MLIP`
- `runstruct_MLIP`
- `MLIPmd`
- `MLIPliquid`
- `MLIPlammps`

Continue examining the repository for additional commands and utilities.

For every upstream command, determine whether there is a functional GUI equivalent.

### CALPHAD generation

- Automatic TDB generation.
- Gibbs-energy fitting.
- Temperature-dependent contributions.
- Multiple lattice/phase selection.
- Export and reuse of generated databases.
- Connections to pycalphad and other compatible tools.
- Benchmarking and validation of MLIP energies.

Verify that all GUI controls generate the correct underlying arguments and that calculations produce scientifically consistent results.

## 3. Audit PhaseForgePlus — Complete Feature Parity

PhaseForgePlus is particularly important because it extends PhaseForge from TDB generation into thermodynamic model optimization.

I want full integration of its supported capabilities.

### Model fitting

Audit and implement any missing functionality for:

- Importing existing TDB files.
- Starting from PhaseForge-generated databases.
- Selecting parameters to optimize.
- Configuring thermodynamic conditions.
- Loading Zero Phase Fraction (ZPF) and other supported experimental datasets.
- Using experimental phase-equilibrium data.
- Configuring residual/error functions.
- Running gradient-based parameter fitting.
- Inspecting convergence and optimized parameters.
- Exporting optimized TDB files.

### Optimization

The upstream framework supports conjugate-gradient optimization and alternative SciPy optimizer methods, including L-BFGS-B.

Expose all applicable documented optimization parameters, including tolerances, iteration limits, starting points, and relevant optimizer options.

Audit the actual implementation for additional supported methods and options.

### Jansson derivatives

Verify that the integration correctly uses the original framework's equilibrium derivative calculations.

Ensure that optimized thermodynamic parameters and gradients are computed consistently with the installed pycalphad and ESPEI versions.

Add gradient verification using finite differences for small test cases where practical.

Do not silently replace analytic-gradient implementations with numerical approximations.

### Fitting visualization

Provide a consistent interface for:

- Objective function versus iteration.
- Gradient norms.
- Parameter evolution.
- Experimental versus calculated equilibria.
- Phase diagrams before and after fitting.
- Gibbs-energy comparisons.
- Residual/error diagnostics.
- Exporting fitted databases and numerical results.

Only show plots supported by actual available calculation data.

### PhaseForge → PhaseForgePlus

This must become a seamless workflow.

I should be able to generate a TDB in PhaseForge, select it in the file explorer, and send it directly into PhaseForgePlus.

The destination workspace should automatically populate compatible inputs, preserve provenance, and allow further model optimization.

## 4. Audit MaterialsFramework and BLADE

I want the complete set of supported MaterialsFramework capabilities available through PhaseForgeStudio, including those currently accessible through BLADE.

Inspect all calculator, analyzer, transformation, and tool registries from the installed MaterialsFramework version.

### MLIP functionality

Ensure all supported calculators can be discovered and configured through the GUI.

Do not hardcode a small list if the framework already provides a supported registry.

Expose supported relaxation, single-point, and MD configurations.

### Material-property analysis

Audit all upstream analyzers, including where supported:

- Formation energy.
- Elastic properties.
- Hydrogen solubility.
- Phonons and thermal properties.
- Anharmonic phonon calculations.
- Surface energies.
- Surface binding energies.
- Stacking-fault energies.
- NEB reaction barriers.
- Additional analyzers present in the installed version.

### Additional tools

Audit and expose supported tools such as:

- SQS generation.
- Cluster expansion.
- Phase-field modeling.
- Stability maps.
- Coherent stability maps.
- SQS-to-TDB conversion.
- Trajectory recording and visualization.
- Other tools discovered from the source.

Do not assume these are all available in my current installation. Verify each capability.

### BLADE modernization

Preserve every existing BLADE-specific function.

Redesign the BLADE interface to match the modern PhaseForgeStudio GUI, retaining all existing controls, advanced settings, workflows, and outputs.

Where MaterialsFramework functionality overlaps with PhaseForge or BLADE, reuse backend services rather than duplicating calculation implementations.

## 5. Make All Frameworks Interoperable

PhaseForge, PhaseForgePlus, BLADE, MaterialsFramework, PAIPAI, and ORCHID must operate as one interconnected environment.

The shared file explorer should enable users to select compatible outputs from one framework as inputs to another.

Implement a common artifact registry with metadata, provenance, validation, and supported conversion actions.

### Example workflow A — Thermodynamic modeling

PhaseForge SQS generation → MaterialsFramework MLIP relaxation → PhaseForge energy extraction → PhaseForge TDB generation → PhaseForgePlus parameter optimization → ORCHID experimental comparison.

### Example workflow B — Materials properties

PhaseForge structure → MaterialsFramework elastic-property calculation → shared visualization and analysis.

### Example workflow C — Atomic configurations

PhaseForge SQS → PAIPAI Monte Carlo → relaxed configurations → MaterialsFramework property calculations → PhaseForge analysis.

### Example workflow D — Experimental validation

ORCHID reference data → PhaseForgePlus experimental fitting → optimized TDB → pycalphad phase diagrams → comparison against ORCHID observations.

All transfers must preserve scientifically relevant units, reference states, phase names, structure information, and calculation provenance.

A file should be selectable from the explorer and automatically populate the correct destination inputs wherever compatibility is verified.

Unsupported transfers must produce clear explanations.

## 6. Feature-Parity Audit Matrix

Before implementation, generate a comprehensive machine-readable feature matrix.

For each original upstream feature, report:

| Field | Required information |
|---|---|
| Framework | Original framework |
| Feature | Command, API, analyzer, or tool |
| Upstream reference | Source file/function |
| GUI location | Where it is exposed |
| Backend implementation | Actual connected function |
| Status | Complete, partial, missing, broken, or unverified |
| Evidence | Test or code-path verification |
| Required action | Fix or integration work |
| Test status | Passed, failed, or not tested |

Do not classify a feature as complete simply because a button or menu exists.

A feature is complete only when its inputs, execution, outputs, and errors are handled correctly.

Save this report as `docs/FRAMEWORK_FEATURE_AUDIT.md`, plus a structured CSV or JSON.

## 7. Unified GUI and User Experience

All frameworks must share the same design system.

Use consistent navigation, styling, panels, file selection, logging, progress reporting, plots, and configuration handling.

Where two frameworks offer related capabilities, give users a clear choice of calculation engine.

For example, SQS generation may be provided by PhaseForge's ATAT workflow or MaterialsFramework's SQS generator. Preserve both where appropriate, but present them through a consistent interface with clear distinctions.

Do not remove advanced options just to simplify the GUI.

Provide basic and advanced controls when necessary.

## 8. Shared Job Execution and HPC Support

Reuse or extend the existing job infrastructure so every framework supports appropriate local and HPC execution.

Maintain:

- Working-directory management.
- Environment/dependency detection.
- Job configuration.
- Progress and status reporting.
- Live logs.
- Cancellation.
- Output discovery.
- Result visualization.
- Reproducible input files.

Do not claim that calculations support HPC execution until they have verified submission and execution paths.

Preserve all existing cluster-specific configurations.

## 9. Scientific Validation

Do more than verify that code runs.

Use small reference calculations from upstream examples and tests to compare results.

Where appropriate, validate:

- Structure compositions and lattice parameters.
- Energy and formation-enthalpy units.
- Relaxation energies and forces.
- TDB generation and parsing.
- CALPHAD equilibria.
- Parameter optimization.
- Analytical versus finite-difference gradients.
- Phase fractions and chemical potentials.
- Phase-stability predictions.
- Elastic and thermodynamic property outputs.

Apply appropriate numerical tolerances and document them.

Distinguish failures caused by integration code from upstream limitations or model differences.

## 10. Implementation Requirements

Proceed with the actual implementation after auditing.

Prioritize fixing broken existing functionality before adding new features that depend on it.

Keep upstream scientific algorithms intact wherever possible, using compatible adapters.

Avoid unnecessary forks and duplicated implementations.

Use feature detection and dependency checks so missing optional packages do not prevent PhaseForgeStudio from launching.

Document exact supported versions and compatibility constraints.

Do not delete or overwrite existing research data, configurations, or working calculations.

Do not claim full parity until it is demonstrated by source-code comparison and tests.

## 11. Final Deliverables

At completion, provide:

1. Complete feature-parity matrices for PhaseForge, PhaseForgePlus, BLADE, and MaterialsFramework.
2. Identification of all missing, partial, or broken features.
3. Implemented fixes and missing functionality.
4. Modernized BLADE GUI with existing feature parity.
5. Universal cross-framework file selection and transfer.
6. ORCHID and PAIPAI integration through the shared architecture.
7. End-to-end workflow tests.
8. Updated documentation.
9. Detailed list of modified files.
10. Remaining limitations, with evidence and explanations.

**Do not stop at auditing, planning, or implementing superficial UI controls. Implement and verify as much as the actual frameworks support.**

My ultimate goal is a single scientific research application that exposes the full capabilities of each underlying framework and allows me to move seamlessly between structure generation, machine-learning potentials, thermodynamic modeling, optimization, experimental validation, and material-property prediction.

---

# ORIGINAL SPECIFICATION: 04_PHASE_DIAGRAM_BENCHMARKING

_Source file: `Pasted text (4).txt`. The text below is preserved as supplied._

# Additional PhaseForgeStudio Feature: Comprehensive MLIP Phase Diagram Benchmarking

Add a fully integrated MLIP Phase Diagram Benchmarking workspace to PhaseForgeStudio.

This is an extension of my earlier requirements for full framework feature parity, ORCHID, PAIPAI, PhaseForge/PhaseForgePlus, BLADE/MaterialsFramework, and the universal file explorer.

## 1. Main Objective

I want to select one chemical system, run multiple machine-learning interatomic potentials on the same structures and compositions, construct an independent thermodynamic model using each MLIP, and compare the resulting phase diagrams against experimental or assessed reference data.

For example, for Cu–Zr, I want to reproduce the type of comparison shown in my attached screenshot:

- One phase diagram per MLIP.
- Identical composition and temperature ranges.
- Same reference experimental/assessed phase diagram.
- Same input dataset and fitting methodology.
- Quantitative benchmark scores for each MLIP.
- A multi-panel comparison showing all calculated phase diagrams together.

Inspect the screenshot for the desired comparison layout and functionality.

The objective is not merely to compare MLIP energy errors. I want to measure how errors in MLIP-predicted energies affect the **final thermodynamic phase diagrams and phase stability predictions**.

## 2. Select a System and MLIPs

Create a GUI workflow where I can specify:

- Chemical elements and system.
- Binary, ternary, or higher-order system, where supported.
- Crystal structures and phases to evaluate.
- Composition range and sampling resolution.
- Temperature range and resolution.
- Number and type of structures per composition.
- Available MLIP models.
- Reference thermodynamic dataset or TDB.
- CALPHAD fitting configuration.

Automatically discover available MLIPs through MaterialsFramework and other supported calculator registries.

Show the actual models available in the configured environment rather than relying solely on a hardcoded list.

Allow testing multiple models in the same benchmark.

Support user-defined MLIPs through a documented adapter interface.

## 3. Generate a Consistent Evaluation Dataset

For fair comparison, all MLIPs should evaluate the same chemical system using comparable structure datasets.

Reuse the existing PhaseForge capabilities for:

- SQS generation.
- Composition sampling.
- Structure generation.
- Phase selection.
- Supercell construction.
- Input preparation.
- Data organization.

Provide two benchmark modes.

**Mode A — Fixed-structure evaluation**

All MLIPs evaluate identical structures without relaxation.

This isolates differences in predicted energies and allows direct comparisons.

**Mode B — Independently relaxed evaluation**

Each MLIP relaxes the same initial structures independently.

This measures how each potential affects both predicted energies and resulting configurations.

Make the distinction clear in results and reports.

Optionally support additional modes using reference DFT-relaxed structures, where such structures are available.

Use identical initial configurations, composition grids, sampling settings, and thermodynamic fitting methodology across the MLIPs wherever scientifically possible.

Store all settings and random seeds.

## 4. Construct Phase Diagrams Independently for Each MLIP

For every selected potential, execute the complete workflow:

Structure generation → MLIP energy evaluation → formation-energy extraction → thermodynamic model construction → TDB generation → pycalphad equilibrium calculations → phase diagram.

Use the existing PhaseForge and PhaseForgePlus capabilities rather than duplicating their scientific algorithms.

For each MLIP:

1. Calculate energies for every required structure.
2. Compute formation enthalpies using internally consistent reference states.
3. Construct the supported Gibbs-energy model.
4. Include temperature-dependent contributions when available.
5. Generate a separate TDB.
6. Calculate equilibrium phase diagrams.
7. Save results in a standardized format.
8. Record all warnings and failed calculations.

Use the same fitting objective, model form, phase definitions, and thermodynamic assumptions for every MLIP, unless differences are explicitly required and documented.

Do not present a zero-K energy model as a fully validated finite-temperature phase diagram.

Where vibrational, electronic, liquid, or other free-energy contributions are missing, document their treatment and the associated limitations.

## 5. Multi-Panel Phase Diagram Comparison

Create a comparison interface similar to the attached screenshot.

For example, if I select 12 MLIPs, display a 3 × 4 grid of phase diagrams.

Each subplot must contain:

- MLIP name.
- Predicted phase boundaries.
- Reference assessed phase boundaries in gray.
- Experimental observations when available.
- Temperature axis in K or °C.
- Composition axis as mole fraction.
- Quantitative model score.
- Consistent axis ranges.
- Consistent colors and legends.

Allow switching between:

- Grid view.
- Individual model view.
- Overlay view.
- Difference view.

Allow selecting models to hide/show.

Support interactive zooming, hovering, and exporting individual figures or the complete multi-panel plot.

Reuse the existing PhaseForgeStudio plotting infrastructure.

## 6. Quantitative Benchmark Metrics

Implement multiple complementary metrics rather than relying on a single score.

### Phase-diagram classification metrics

Compare predicted equilibrium phases against reference phase classifications on a common composition–temperature grid.

Calculate:

- Accuracy.
- Precision.
- Recall.
- F1 score.
- Balanced accuracy.
- Jaccard similarity.
- Phase-region agreement.

Use explicitly documented matching rules for phase names and phase assemblages.

Distinguish single-phase regions from multiphase regions.

### Phase-boundary metrics

Where compatible reference boundaries exist, calculate:

- Mean absolute temperature deviation.
- Root mean square temperature deviation.
- Composition error at phase boundaries.
- Boundary distance.
- Transition-temperature error.
- Invariant-reaction temperature and composition errors.

Avoid assigning meaningless boundary metrics when phase topology differs or boundaries cannot be matched.

### Thermodynamic metrics

Where reference thermodynamic measurements are available, calculate:

- Formation-enthalpy MAE/RMSE.
- Mixing-enthalpy errors.
- Relative stability errors.
- Energy above hull errors.
- Predicted versus reference phase stability.
- Ranking correlation.

### Model performance

Track:

- Total runtime.
- MLIP inference time.
- Relaxation time.
- CPU/GPU usage where measurable.
- Memory usage.
- Calculation failure rate.
- Number of successful structures.
- TDB fitting convergence.
- Numerical equilibrium failures.

Use these metrics to characterize both physical accuracy and computational efficiency.

## 7. Ranking and Statistical Analysis

Create an interactive benchmark table showing:

- MLIP.
- Phase-diagram recall.
- F1 score.
- Phase-boundary error.
- Formation-energy error.
- Runtime.
- Computational cost.
- Number of valid calculations.
- Overall status.

Allow sorting and filtering by any metric.

Provide optional user-defined weighted composite scores, but keep individual metrics visible.

Do not silently combine metrics with different units or treat missing results as zero error.

Support Pareto ranking between accuracy and computational cost.

Add uncertainty estimates or bootstrap confidence intervals when enough independent data are available.

## 8. Connect with ORCHID

ORCHID should be one of the supported sources for experimental and assessed reference data.

From the shared file explorer, I should be able to:

1. Select a chemical system.
2. Search ORCHID for corresponding phase-equilibrium or thermodynamic records.
3. Inspect the original sources and provenance.
4. Select compatible reference data.
5. Run benchmarking.
6. Save the reference selection alongside the benchmark.

Also allow importing local TDB files and user-provided experimental CSV files.

Do not assume every system has a complete ORCHID phase diagram.

If the required reference data are unavailable, explain this and support running the benchmark without a quantitative reference score.

## 9. Integration with MaterialsFramework and BLADE

Use MaterialsFramework to discover, configure, and execute supported MLIP calculators.

Use existing BLADE features where applicable for calculations and thermodynamic analysis.

A model configured in the MaterialsFramework/BLADE workspace should be reusable in the benchmarking workspace.

The user should not have to configure the same calculator separately in each workspace.

Preserve framework-specific calculator options and supported device settings.

## 10. Integration with PhaseForge and PhaseForgePlus

Use PhaseForge for the structure-to-TDB pipeline.

Allow PhaseForgePlus to optimize or refit the resulting thermodynamic models using compatible thermodynamic reference data.

Provide two comparison categories:

**Unrefitted MLIP predictions:** Phase diagrams obtained before fitting to the experimental reference used for evaluation.

**Refitted CALPHAD predictions:** Phase diagrams obtained after optimization using experimental or assessed data.

Clearly distinguish these categories.

Avoid data leakage: if a reference dataset is used to fit a model, do not present agreement with that same dataset as independent predictive validation.

Support train/validation/test partitioning by observation or experimental source where appropriate.

## 11. Shared File Explorer and Workflow Interoperability

All benchmark data should appear automatically in the universal file explorer.

I should be able to:

- Select existing structures instead of generating them again.
- Reuse an earlier MLIP calculation dataset.
- Import a previously generated PhaseForge TDB.
- Send a benchmark TDB to PhaseForgePlus.
- Send configurations into PAIPAI.
- Open benchmark results in the analysis workspace.
- Compare benchmarked models against other systems.
- Reproduce a previous benchmark using saved configuration files.

Avoid unnecessary duplication of large structure and trajectory files.

Maintain provenance and checksums for reproducibility.

## 12. Reusable Benchmark Projects

Create a standardized project structure such as:

```text
benchmarks/
└── Cu-Zr/
    ├── benchmark_config.yaml
    ├── reference/
    ├── structures/
    ├── mlips/
    │   ├── model_01/
    │   ├── model_02/
    │   └── model_03/
    ├── tdb/
    ├── phase_diagrams/
    ├── metrics/
    ├── figures/
    └── report/
```

Allow resuming incomplete benchmarks and rerunning only failed or outdated stages.

Cache calculations by model, version, input structure, and calculation settings to prevent redundant work.

## 13. Additional Analysis Capabilities

Include optional advanced analyses:

- Quantify sensitivity of phase boundaries to changes in formation energies.
- Identify which compositions contribute most strongly to disagreement.
- Determine which phases are responsible for incorrect equilibria.
- Compare MLIP-induced changes in Gibbs-energy curvature.
- Compare predicted miscibility gaps and spinodal boundaries.
- Evaluate single-phase stability versus decomposition.
- Plot energy and phase-stability errors versus composition.
- Analyze model performance as a function of temperature.
- Identify systems for which MLIP rankings change depending on the metric.

For diborides, allow benchmarking of Group IV–Group V systems such as ZrB2–TaB2, including predictions of decomposition into two compositionally distinct AlB2 solid solutions.

## 14. Validation and Testing

Before implementing the feature, inspect the existing PhaseForge, PhaseForgePlus, BLADE, and MaterialsFramework integrations.

Reuse working components.

Create tests for:

- Calculator discovery and model selection.
- Fair dataset generation.
- Energy referencing.
- Per-model TDB generation.
- Phase-diagram calculation.
- Phase-name matching.
- Quantitative metrics.
- Reference-data loading.
- Multi-panel plotting.
- Job execution and cancellation.
- Resume functionality.
- Cross-framework file reuse.

Test a small binary benchmark end to end using at least two available calculators or deterministic test fixtures.

## 15. Final Requirements

Implement this as a functional, reusable workspace in PhaseForgeStudio.

It should use the same modern design system, file explorer, job manager, and plotting tools as every other framework.

Do not add mock buttons or empty features.

At completion, report the implemented functionality, comparison methodology, tests performed, supported MLIPs, dependency requirements, and remaining limitations.

**Success means I can select one binary system, choose multiple MLIPs, run the entire PhaseForge thermodynamic workflow for each, and produce a single scientifically consistent comparison figure showing all predicted phase diagrams against a common experimental reference, with quantitative accuracy and computational-efficiency rankings.**

---

# ORIGINAL SPECIFICATION: 05_FOUR_BENCHMARK_MODES

_Source file: `Pasted text (5).txt`. The text below is preserved as supplied._

# Additional PhaseForgeStudio Requirements — Universal MLIP Benchmarking System

Extend the MLIP Phase Diagram Benchmarking module I previously requested.

I want a comprehensive, scientifically rigorous benchmarking environment that compares machine-learning interatomic potentials across energy accuracy, thermodynamic stability, phase-diagram accuracy, and computational efficiency.

**Repository:** https://github.com/ichasekatz/PhaseForgeStudio

These requirements are additive. Do not remove, simplify, or replace any features requested in my earlier PhaseForge, PhaseForgePlus, BLADE/MaterialsFramework, PAIPAI, ORCHID, file-explorer, or benchmarking integration instructions.

## 1. Implement Four Benchmark Modes

Add a benchmark mode selector with four options:

### Mode 1 — Energy Benchmark

Compare multiple MLIPs against the same reference DFT dataset.

Include:

- Total energy and energy per atom.
- Formation energy.
- Mixing enthalpy.
- Energy above convex hull.
- Forces and stresses, when reference data exist.
- Relaxed lattice parameters.
- Structural differences and relaxation convergence.
- Energy MAE, RMSE, and maximum absolute error.
- Force and stress errors.
- Error versus composition.
- Error versus crystal structure.
- Error versus energy above hull.

Distinguish fixed-geometry evaluations from independently relaxed evaluations.

Use consistent elemental reference states and normalization conventions.

### Mode 2 — Phase Diagram Benchmark

For one selected chemical system, evaluate multiple MLIPs using the same structures and thermodynamic modeling pipeline.

For each MLIP:

1. Calculate structure energies.
2. Generate consistent formation-energy data.
3. Construct thermodynamic models using PhaseForge.
4. Generate independent TDB files.
5. Calculate phase diagrams using pycalphad.
6. Compare phase boundaries with experimental or assessed reference data.
7. Calculate quantitative agreement metrics.
8. Generate multi-panel comparison figures like the Cu–Zr example I previously provided.

Support reference datasets from ORCHID, existing TDB files, and imported experimental datasets.

Include:

- Phase-region accuracy.
- Precision, recall, and F1.
- Boundary temperature MAE/RMSE.
- Invariant reaction errors.
- Phase topology agreement.
- Phase assemblage confusion matrices.
- Predicted versus experimental phase boundaries.

Use the same composition-temperature grid and phase-matching rules across all models.

Clearly distinguish unrefitted predictions from models fitted to experimental references.

### Mode 3 — Phase Stability Benchmark

Compare how different MLIPs predict phase stability for the same chemical system.

Include:

- Formation-energy convex hulls.
- Gibbs energy above the hull.
- Predicted stable phases.
- Metastable phases.
- Homogeneous versus multiphase stability.
- Solid-solution fraction.
- Unique homogeneous single-phase fraction.
- Temperature-dependent stability.
- Miscibility gaps and binodal boundaries.
- Chemical-Hessian curvature.
- Spinodal boundaries.
- Gibbs-energy-versus-composition curves.
- Common-tangent constructions.
- Phase decomposition products.

Use compatible equilibrium calculations and thermodynamic reference states.

Do not confuse a retained parent crystal structure with homogeneous single-phase stability.

Distinguish global thermodynamic stability from local Hessian stability.

For example, the method should be able to compare how different MLIPs predict whether ZrB2–TaB2 forms one homogeneous AlB2 phase or separates into two compositionally distinct AlB2 solid solutions.

### Mode 4 — Complete Benchmark

Run all applicable benchmark modes together.

Automatically reuse intermediate calculations rather than generating the same data multiple times.

Include:

- Energy benchmarking.
- Phase-diagram benchmarking.
- Stability benchmarking.
- Runtime and resource benchmarking.
- Combined visualization.
- Model ranking.
- Statistical analysis.
- Comprehensive benchmark report.

If required reference data or calculation capabilities are unavailable, mark the relevant analysis as unavailable and explain why.

Do not fabricate metrics or fill missing data with assumed values.

## 2. Shared Calculation Engine and Caching

Implement a dependency-aware benchmarking workflow.

For example:

Structure dataset
→ MLIP evaluations
→ energy and property extraction
→ formation-energy calculations
→ thermodynamic model generation
→ phase equilibrium
→ benchmark metrics
→ plots and reports.

Each stage should save reusable outputs.

If I run an energy benchmark first and later select a complete benchmark, reuse the existing compatible energy calculations.

Cache validity must consider:

- Exact MLIP model and version.
- Model weights/checkpoints.
- Structure contents.
- Calculator settings.
- Relaxation parameters.
- Software versions.
- Relevant thermodynamic model settings.
- Reference-state definitions.

Do not reuse stale or incompatible results.

Allow users to inspect, invalidate, and selectively recompute cached stages.

## 3. Automatic MLIP Discovery and Configuration

Inspect MaterialsFramework, BLADE, PhaseForge, and available installed calculators.

Discover all supported MLIPs dynamically where possible.

Expose calculator-specific settings.

Support:

- Selecting multiple models simultaneously.
- Device selection.
- Precision options.
- Model versions and checkpoints.
- Batch processing.
- Local and HPC execution.
- User-installed compatible calculators.
- Optional custom calculator adapters.

Clearly display unavailable models and missing dependencies.

Do not assume every MLIP supports stress, molecular dynamics, or every chemical element.

Validate element coverage and calculation capabilities before running.

## 4. Benchmark Dashboard

Create an interactive dashboard containing:

**Model comparison table**
- MLIP name and version.
- Energy errors.
- Force errors.
- Phase-diagram scores.
- Stability prediction accuracy.
- Runtime.
- Memory/resource usage.
- Number of successful calculations.
- Failure rate.

**Visualization**
- Multi-panel phase diagrams.
- Convex-hull comparisons.
- Gibbs-energy curves.
- Composition-temperature contour plots.
- Predicted versus reference energies.
- Phase-boundary error plots.
- Confusion matrices.
- Pareto fronts.
- Model ranking plots.

**Filtering**
- MLIP.
- Chemical system.
- Benchmark mode.
- Crystal structure.
- Composition.
- Temperature.
- Reference dataset.
- Evaluation status.

Use the same GUI design system as the rest of PhaseForgeStudio.

## 5. Interactive Model Ranking

Allow ranking models by:

- Lowest energy MAE.
- Lowest force RMSE.
- Highest phase-diagram F1.
- Highest phase-region recall.
- Lowest phase-boundary error.
- Highest stability classification accuracy.
- Fastest runtime.
- Best accuracy-cost tradeoff.

Add optional user-defined weighted composite rankings.

Normalize scores appropriately and retain all individual metrics.

Support Pareto analysis to identify MLIPs that offer the best tradeoff between accuracy and computational cost.

Do not create an arbitrary default ranking that implies all scientific objectives are equally important.

## 6. Statistical Reliability and Model Diagnostics

Add:

- Bootstrap uncertainty intervals where justified.
- Per-composition error analysis.
- Per-temperature error analysis.
- Per-phase performance.
- Outlier detection.
- Model failure analysis.
- Missing-data diagnostics.
- Convergence diagnostics.
- Confidence intervals for benchmark metrics where sample sizes permit.
- Assessment of sensitivity to structure sampling and thermodynamic fitting choices.

Avoid treating correlated structures or densely sampled phase-diagram pixels as statistically independent observations.

Report the effective sample size and uncertainty assumptions.

## 7. Shared File Explorer and Cross-Framework Integration

Every input and output must be accessible through the universal file explorer.

Examples:

- Select an SQS dataset generated by PhaseForge and benchmark multiple MLIPs.
- Select a MaterialsFramework-relaxed structure and compare calculator energies.
- Select a PhaseForge-generated TDB for phase-diagram benchmarking.
- Select ORCHID observations for experimental comparison.
- Send optimized thermodynamic databases to PhaseForgePlus.
- Open benchmark results in the PhaseForgeStudio analysis workspace.
- Reuse compatible PAIPAI configurations for further evaluation.

Include context-aware actions such as:

- Benchmark with selected MLIPs.
- Compare energies.
- Build phase diagrams.
- Evaluate stability.
- Compare with reference.
- Generate benchmark report.

Ensure transferred data retain provenance, units, and scientific meaning.

## 8. Benchmark Templates

Include configurable benchmark templates such as:

**Binary phase-diagram benchmark**
- One binary system.
- Several MLIPs.
- Common structure dataset.
- Shared reference TDB.
- Multi-panel phase diagrams.

**Diboride stability benchmark**
- Group IV–Group V diborides.
- AlB2 solid-solution structures.
- Composition-dependent mixing energetics.
- Multiple MLIPs.
- Miscibility-gap comparison.
- Common-tangent and Hessian analyses.

**Multicomponent solid-solution benchmark**
- User-selected multicomponent alloy.
- SQS-generated structures.
- Formation energies.
- Thermodynamic stability.
- Temperature-dependent equilibria.

**General energy benchmark**
- User-provided DFT reference structures.
- Energies, forces, and stresses.
- Per-model error comparison.

Templates should provide useful defaults but remain fully configurable.

## 9. Reproducibility and Export

Every benchmark should save:

- Input configuration.
- Exact MLIP models and versions.
- Structure dataset manifest.
- Reference dataset provenance.
- Calculator parameters.
- Calculation results.
- Generated TDB files.
- Benchmark metrics.
- Figures.
- Execution logs.
- Software/environment information.
- Validation status.

Allow exporting a self-contained report with sufficient provenance to reproduce the calculations.

Support CSV, JSON, and publication-quality figure export.

Produce a human-readable benchmark report summarizing model strengths, weaknesses, and limitations.

## 10. Testing and Implementation

Inspect the current repository and previous benchmarking implementation before adding code.

Reuse existing scientific workflows and GUI components.

Implement automated tests for all four modes, shared caching, model discovery, validation, rankings, file transfers, and plotting.

Run a small end-to-end comparison with at least two available MLIPs or deterministic test fixtures.

Verify that each benchmark mode produces correct outputs.

Ensure optional dependencies do not break the rest of PhaseForgeStudio.

Do not stop after creating the interface. Implement backend execution, valid data handling, visualizations, and reports.

At completion, provide:

1. Implemented benchmark modes.
2. Supported models and capabilities.
3. Files added or modified.
4. End-to-end workflow verification.
5. Test results.
6. Known limitations.
7. Remaining unsupported functionality and reasons.

**Final objective:** I want PhaseForgeStudio to become a unified MLIP evaluation platform capable of answering not only which potential best reproduces DFT energies, but which potential most accurately predicts experimentally observed phase diagrams, thermodynamic stability, miscibility gaps, and material behavior, while also considering computational efficiency.

---

# ORIGINAL SPECIFICATION: 06_FINAL_VALIDATION

_Source file: `Pasted text (6).txt`. The text below is preserved as supplied._

# Final Requirement — Comprehensive End-to-End Testing of PhaseForgeStudio

Once all previously requested development work is complete, perform a comprehensive, systematic validation of the entire PhaseForgeStudio application.

**Repository:** https://github.com/ichasekatz/PhaseForgeStudio

This is a mandatory final stage of the project, not an optional improvement.

I want the completed framework tested as a whole, including all existing features, newly added frameworks, scientific calculations, cross-framework interoperability, visualization, GUI functionality, and HPC execution.

Do not consider the development complete until this testing phase has been performed and its results documented.

## 1. Test Every Integrated Framework

Perform complete feature-by-feature testing of:

- PhaseForge
- PhaseForgePlus
- BLADE
- MaterialsFramework
- PAIPAI
- ORCHID
- MLIP Phase Diagram Benchmarking
- Shared file explorer
- Shared job manager
- Shared visualization and analysis tools

Use the previously generated feature-parity audit as the testing checklist.

For each feature, verify that:

1. It is accessible from the GUI.
2. All expected inputs and settings are available.
3. Input validation works.
4. Backend execution invokes the correct scientific implementation.
5. The calculation produces valid outputs.
6. Outputs are automatically discovered.
7. Results can be visualized and exported.
8. Errors and cancellation are handled correctly.

Record any failures and fix integration defects.

Do not classify a feature as tested merely because its GUI opens successfully.

## 2. Test Complete Scientific Workflows

Run representative end-to-end workflows using small reference systems.

### Workflow A — PhaseForge

Generate structures → perform SQS calculations → run MLIP energy/relaxation calculations → extract thermodynamic data → generate TDB → calculate phase diagram.

Verify the numerical outputs and intermediate data.

### Workflow B — PhaseForgePlus

Import an existing TDB → import fitting data → configure optimization → run gradient-based fitting → export optimized TDB → compare phase diagrams before and after fitting.

Verify gradient calculations and optimization results using established reference examples.

### Workflow C — BLADE/MaterialsFramework

Import atomic structure → select MLIP → calculate energies, forces, and relaxation → execute supported property analyzers → visualize results.

Test advanced tools and specialized calculations separately where required.

### Workflow D — PAIPAI

Import a compatible structure → configure Monte Carlo calculation → run a small sampling job → inspect trajectory and energies → export resulting configuration → import it into another framework.

### Workflow E — ORCHID

Search for thermodynamic reference data → inspect provenance → import compatible records → compare results with calculated phase diagrams → export comparison.

### Workflow F — MLIP Benchmarking

Select one binary chemical system → choose at least two available MLIPs → generate a common dataset → construct individual TDBs → calculate individual phase diagrams → evaluate benchmark metrics → produce multi-panel comparison.

Test all four benchmark modes:

- Energy Benchmark
- Phase Diagram Benchmark
- Phase Stability Benchmark
- Complete Benchmark

Use real small-scale calculations where feasible, not just mocks.

## 3. Test Cross-Framework Interoperability

Test the entire universal file exploration and artifact transfer system.

Include:

- PhaseForge → PhaseForgePlus
- PhaseForge → MaterialsFramework
- PhaseForge → PAIPAI
- MaterialsFramework → PhaseForge
- BLADE → PhaseForge
- PhaseForgePlus → PhaseForge
- ORCHID → PhaseForgePlus
- PhaseForge → ORCHID comparison
- MLIP Benchmarking → PhaseForgePlus
- PAIPAI → MaterialsFramework

For each transfer, verify:

- Correct file recognition.
- Compatible input selection.
- Correct data conversion.
- Preservation of physical units.
- Preservation of crystal structure.
- Preservation of composition and atomic coordinates.
- Correct phase mapping.
- Metadata and provenance.
- Correct execution after transfer.

Test unsupported conversions to ensure they fail safely and explain why.

## 4. Test the Entire GUI

Perform actual GUI interaction testing, preferably using browser automation such as Playwright when compatible with the existing architecture.

Test:

- Every navigation tab.
- Framework switching.
- Persistent settings.
- Input forms.
- Advanced settings.
- Buttons and dropdowns.
- Shared file explorer.
- Drag-and-drop.
- Context-aware file actions.
- Plotting.
- 3D structure viewing.
- Job monitoring.
- Progress and logs.
- File export.
- Error messages.
- Responsive layouts.
- Light and dark themes, where available.

Specifically compare the redesigned BLADE GUI against the original feature-parity checklist.

Ensure no features disappeared during the redesign.

Capture screenshots of major workspaces for visual regression testing.

Test that the interface works at normal desktop screen sizes and that important controls remain visible and usable.

## 5. Scientific Accuracy and Numerical Validation

Do not rely only on whether calculations finish.

Compare numerical outputs against trusted reference examples or upstream tests.

Validate:

- Energy units and normalization.
- Elemental reference energies.
- Formation and mixing enthalpies.
- Relaxed structures.
- Force/stress conventions.
- Gibbs-energy calculations.
- Chemical potentials.
- Phase equilibria.
- Phase fractions.
- TDB generation.
- Optimization convergence.
- Jansson derivatives.
- Chemical-Hessian calculations.
- Convex-hull stability.
- Miscibility-gap boundaries.
- Spinodal boundaries.
- Phase-diagram benchmark scores.

Use numerical tolerances appropriate to each property and document them.

In particular, distinguish homogeneous single-phase stability from phase separation into two solid solutions with the same parent crystal structure.

Do not treat agreement with a dataset used for fitting as independent experimental validation.

## 6. Test Job Execution and HPC Integration

Test local execution first.

Then validate the available HPC integration using a small calculation, provided cluster access and scheduler permissions are available.

Verify:

- Remote working-directory handling.
- Job submission.
- Scheduler job IDs.
- Job status tracking.
- Log streaming.
- Output collection.
- Cancellation.
- Resource settings.
- Failed-job recovery.
- Resume/restart behavior.
- Multiple concurrent jobs.

Never submit expensive HPC jobs without appropriate configured resource limits and authorization.

If cluster access is unavailable, perform mocked scheduler tests and mark real HPC execution as unverified.

Do not claim that mocked tests prove cluster execution works.

## 7. Test Reliability and Failure Handling

Intentionally test:

- Missing dependencies.
- Invalid structures.
- Unsupported elements.
- Invalid TDB files.
- Missing or corrupted results.
- Failed MLIP calculations.
- Interrupted jobs.
- Network failures during ORCHID access.
- Missing experimental reference data.
- Invalid file transfers.
- Repeated benchmark executions.
- Restarting the GUI during a calculation.

Verify that failures are reported clearly and do not corrupt project data or crash unrelated workspaces.

Ensure existing input and output files are not overwritten unexpectedly.

## 8. Performance and Resource Testing

Measure representative:

- GUI startup time.
- File explorer loading time.
- Plot rendering time.
- Structure visualization performance.
- MLIP execution overhead.
- Benchmark memory usage.
- Cache reuse performance.
- Job-management responsiveness.

Check for unnecessary file duplication, memory leaks, and redundant calculations.

For large datasets, verify that the interface remains usable through pagination, lazy loading, or other appropriate mechanisms.

## 9. Automated Regression Test Suite

Create a reusable test suite that covers all integrated frameworks.

Include:

- Unit tests.
- Backend integration tests.
- Scientific numerical regression tests.
- GUI tests.
- Cross-framework end-to-end tests.
- File conversion tests.
- Benchmark calculation tests.
- Optional real-HPC smoke tests.

Configure a reproducible command or script for running the complete local test suite.

Where practical, add CI automation so future code changes can be tested automatically.

Keep expensive numerical tests and external-service tests separately selectable.

Document required dependencies, reference datasets, and environment variables.

## 10. Final Validation Report

Create:

`docs/FINAL_VALIDATION_REPORT.md`

Include:

- Date and tested commit.
- Operating system and software versions.
- Tested framework versions.
- Test environment.
- Total tests.
- Passed tests.
- Failed tests.
- Skipped tests.
- Features that could not be tested.
- Scientific reference comparisons.
- Numerical tolerances.
- GUI screenshots.
- HPC validation status.
- Interoperability test results.
- Performance measurements.
- Remaining limitations.
- Reproduction instructions.

Also create a machine-readable report in JSON or CSV.

Use explicit classifications:

**PASS:** Verified with real execution and appropriate assertions.

**FAIL:** Tested and did not meet expected behavior.

**BLOCKED:** Could not execute because of missing access, dependencies, or required external resources.

**NOT TESTED:** No test was performed.

**MOCK ONLY:** Verified against simulated dependencies, not actual scientific execution.

Never mark blocked, skipped, or mocked tests as passed real-world validation.

## 11. Fix and Retest

After executing the complete test suite:

1. Identify failures.
2. Diagnose their causes.
3. Fix defects in PhaseForgeStudio.
4. Rerun affected tests.
5. Rerun relevant regression tests.
6. Update the validation report.

Repeat until all feasible critical tests pass.

Do not modify upstream scientific algorithms merely to make tests pass unless a genuine defect is established and documented.

Preserve the original calculations, datasets, and user configuration files.

## 12. Final Acceptance Criteria

The final application should satisfy the following:

- All supported framework features are exposed and functional.
- PhaseForge and PhaseForgePlus have verified upstream feature parity.
- BLADE retains its existing functionality with the new unified GUI.
- MaterialsFramework tools are correctly integrated.
- PAIPAI and ORCHID work through the shared architecture.
- Cross-framework file transfers are validated.
- MLIP benchmarking works end to end.
- The file explorer, job manager, and visualization tools are shared.
- Scientific calculations match trusted reference results within documented tolerances.
- All feasible critical integration and regression tests pass.
- Blocked or unverified features are explicitly identified.

Do not report 100% validation if some important workflows could not be tested.

## 13. Provide a Final User Acceptance Testing Guide

In addition to automated testing, create:

`docs/USER_ACCEPTANCE_TESTING.md`

This should be a step-by-step manual checklist that I can follow to personally test the completed GUI.

Include:

- How to launch PhaseForgeStudio.
- Which tab to open.
- Which example file to select.
- What parameters to enter.
- Which button to click.
- What output to expect.
- How to verify the calculation is correct.
- How to test transferring a file into another framework.
- How to test the MLIP benchmarking dashboard.
- How to verify BLADE feature parity.
- How to report problems.

Use small example datasets and calculations that can run on a normal workstation wherever possible.

**Final instruction: After completing all development and automated testing, launch the application where the execution environment permits, verify that the GUI loads successfully, and provide the exact instructions I need to open it and test everything myself.**

I want a fully tested scientific research platform, not just completed code.

Do not claim the application is production-ready until its critical workflows are actually verified.

If anything remains broken, untested, or blocked, tell me explicitly and provide the steps needed to resolve it.
