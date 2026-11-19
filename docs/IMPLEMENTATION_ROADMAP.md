# PhaseForgeStudio — Implementation Roadmap

Generated: 2026-11-19  
Baseline commit: faa2205  
Tests at baseline: 247 passed, 10 skipped  

Dependencies flow downward: each stage may use everything in earlier stages.

---

## Stage 0 — Core Infrastructure (DONE)

All items committed on or before faa2205.

| ID | Feature | Upstream ref | Status | Acceptance |
|----|---------|-------------|--------|-----------|
| S0-01 | `core/file_types.py` — format detection | spec 02 §1B | DONE | 23 tests pass |
| S0-02 | `core/artifact_registry.py` — artifact CRUD + actions | spec 02 §2 | DONE | 10 tests pass |
| S0-03 | `core/converters.py` — CIF/POSCAR/XYZ/CSV transforms | spec 02 §2 | DONE | 15 tests pass (ASE-conditional) |
| S0-04 | `core/job_manager.py` — unified job state machine | spec 02 §4 | DONE | 15 tests pass |
| S0-05 | `core/projects.py` — multi-framework project dirs | spec 02 §6 | DONE | 16 tests pass |
| S0-06 | `core/workflows.py` — chained workflow registry | spec 02 §2 | DONE | (covered by registry tests) |
| S0-07 | PAIPAI adapter + workspace UI | spec 01 §2 | DONE | install detection, run, stop, outputs |
| S0-08 | ORCHID adapter + workspace UI | spec 01 §3 | DONE | search, phase_diagram, TDB list/get |
| S0-09 | PhaseForgePlus adapter + workspace UI | spec 03 §3 | DONE | CG/LBFGS/BFGS, cancel, TDB output |
| S0-10 | MLIP benchmark workspace (4 modes) | spec 04/05 | DONE | 247 tests pass |
| S0-11 | Universal file explorer + `/api/fs/*` | spec 02 §1 | DONE | artifact_registry actions |
| S0-12 | PhaseForge → PFP transfer | spec 03 §3 | DONE | one-click TDB send |
| S0-13 | `-checkrelax` flag in `/api/pf_run` | spec 03 §2 | DONE | commit 6e6054b |

---

## Stage 1 — Priority 1 Gaps (IN PROGRESS)

Highest impact; unblock downstream tests and workflows.

| ID | Feature | Upstream ref | Status | Acceptance |
|----|---------|-------------|--------|-----------|
| S1-01 | `/api/pfp_phase_diagram` — pycalphad on fitted TDB | PFP §2.4, spec 03 §3 | TODO | POST {tdb_path, elements, T_min, T_max} → PNG or JSON phase boundary |
| S1-02 | NEB analyzer — accept two POSCAR paths | MF `neb` analyzer, spec 03 §4 | TODO | `/api/analyze` with `analyzer=neb, structure2=...` returns barrier array |
| S1-03 | PhaseForge `MLIPrelax` command | `PhaseForge/bin/MLIPrelax` | TODO | `/api/pf_relax` route; job state; log streaming |
| S1-04 | PhaseForge `MLIPcalc` command | `PhaseForge/bin/MLIPcalc` | TODO | `/api/pf_calc` route |
| S1-05 | PhaseForge `extract_MLIP` | `PhaseForge/bin/extract_MLIP` | TODO | `/api/pf_extract` route |
| S1-06 | PhaseForge `runstruct_MLIP` | `PhaseForge/bin/runstruct_MLIP` | TODO | `/api/pf_runstruct` route |
| S1-07 | PhaseForge `MLIPmd` | `PhaseForge/bin/MLIPmd` | TODO | `/api/pf_md` route |
| S1-08 | PhaseForge `MLIPliquid` | `PhaseForge/bin/MLIPliquid` | TODO | `/api/pf_liquid` route |
| S1-09 | PhaseForge `MLIPlammps` | `PhaseForge/bin/MLIPlammps` | TODO | `/api/pf_lammps` route |
| S1-10 | ORCHID TDB → PFP workflow | spec 01 §5, spec 03 §3 | TODO | ORCHID TDB list shows "Open in PFP" button; PFP workspace pre-fills tdb_path |
| S1-11 | PAIPAI output → MF property transfer | spec 01 §5 | TODO | artifact action "Analyze with MF" on PAIPAI output POSCAR |

---

## Stage 2 — Priority 2 Partial Implementations (TODO)

| ID | Feature | Upstream ref | Status | Acceptance |
|----|---------|-------------|--------|-----------|
| S2-01 | PFP objective + gradient norm plot | PFP callback, spec 03 §3 | TODO | Chart shows obj value and ‖grad‖ per iteration |
| S2-02 | PFP parameter evolution plot | PFP callback all params | TODO | Multi-line chart; each param one line |
| S2-03 | PFP residual diagnostics | ZPFResidual, FixedConfigResidual | TODO | Per-dataset residual table in PFP panel |
| S2-04 | Surface analyzer slab wizard | MF `surface` | TODO | `/api/mf_slab` generates slab; passes to `surface` analyzer |
| S2-05 | SBE analyzer slab wizard | MF `sbe` | TODO | Same slab wizard as surface |
| S2-06 | MF MD route | `BaseMDCalculator` | TODO | `/api/mf_md` accepts T, P, steps; streams log |
| S2-07 | Trajectory replay UI | `trajectory_observer` output | TODO | Scrubber + frame canvas in MF panel |
| S2-08 | MF live calculator registry | `list_calculators()` entry-points | TODO | `/api/calculators` returns live list; no hardcoded fallback needed |

---

## Stage 3 — New MF Tool Exposure (TODO)

| ID | Feature | Upstream ref | Status | Acceptance |
|----|---------|-------------|--------|-----------|
| S3-01 | `sqsgen` tool | MF tools registry | TODO | `/api/mf_sqsgen`; returns SQS structure |
| S3-02 | `stability_map` tool | MF tools registry | TODO | `/api/mf_stability`; returns phase-stability grid |
| S3-03 | `cluster_expansion` tool | MF tools registry | TODO | `/api/mf_ce`; returns CE model |
| S3-04 | `bond_lattice_parameter` tool | MF tools registry | TODO | `/api/mf_bond_lp` |
| S3-05 | `material_parameters` (Cahn-Hilliard) | MF tools registry | TODO | `/api/mf_ch_params` |
| S3-06 | `phase_field_model` | MF tools registry | TODO | `/api/mf_pfm` |
| S3-07 | `simulation_grid` | MF tools registry | TODO | `/api/mf_simgrid` |

---

## Stage 4 — BLADE Modernization (TODO)

| ID | Feature | Status | Acceptance |
|----|---------|--------|-----------|
| S4-01 | Shared CSS injection into BLADE iframe | TODO | BLADE iframe loads PFS design tokens; fonts/colors match |
| S4-02 | Unified config (PFS ↔ BLADE) | TODO | BLADE reads from PFS `config.json`; no separate `blade/config.json` |
| S4-03 | BLADE feature-parity checklist | TODO | `docs/BLADE_FEATURE_PARITY.md` documents every old feature; each row verified |

---

## Stage 5 — Test Coverage (TODO)

| ID | Module | Current tests | Target | Status |
|----|--------|--------------|--------|--------|
| S5-01 | `pfp_adapter.py` | 0 | ≥ 12 | TODO |
| S5-02 | `paipai.py` | 0 | ≥ 12 | TODO |
| S5-03 | `orchid_adapter.py` | 0 | ≥ 10 | TODO |
| S5-04 | `pipeline.py` | 0 | ≥ 8 | TODO |
| S5-05 | `analysis.py` | 0 | ≥ 10 | TODO |
| S5-06 | Stage 1 routes (server.py) | 0 | ≥ 15 | TODO |

---

## Stage 6 — Final Validation (TODO, requires Stage 0–5 complete)

| ID | Deliverable | Status |
|----|------------|--------|
| S6-01 | `docs/FINAL_VALIDATION_REPORT.md` — full test run with PASS/FAIL/BLOCKED | TODO |
| S6-02 | `docs/USER_ACCEPTANCE_TESTING.md` — step-by-step manual checklist | TODO |
| S6-03 | End-to-end workflow A: PF SQS → MF relax → PF TDB → pycalphad | TODO |
| S6-04 | End-to-end workflow B: PF TDB → PFP optimize → before/after phase diagrams | TODO |
| S6-05 | End-to-end workflow C: PF SQS → PAIPAI MC → MF property | TODO |
| S6-06 | End-to-end workflow D: ORCHID TDB → PFP fitting → pycalphad | TODO |
| S6-07 | End-to-end workflow F: MLIP benchmark, 2 MLIPs, all 4 modes | TODO |
