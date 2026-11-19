# PhaseForgeStudio — Implementation Progress Ledger

Date: 2026-11-19  
Baseline commit: faa2205  
Test count: 247 passed, 10 skipped (ASE-conditional)  

**Resume instruction:** Read this file. Find the first row where Status ≠ DONE. Implement it. Update Status + Evidence + Commit. Commit code. Move to next non-DONE row. Do not re-implement DONE rows.

---

| ID | Feature | Spec | Upstream ref | GUI location | Backend | Status | Evidence | Blockers | Next action | Commit |
|----|---------|------|-------------|-------------|---------|--------|---------|---------|------------|--------|
| S0-01 | file_types.py format detection | 02 §1B | spec | file explorer | `core/file_types.py` | DONE | 23 tests pass | — | — | f660eff |
| S0-02 | artifact_registry CRUD + actions | 02 §2 | spec | explorer context menu | `core/artifact_registry.py` | DONE | 10 tests pass | — | — | f660eff |
| S0-03 | converters CIF/POSCAR/XYZ/CSV | 02 §2 | spec | cross-framework transfer | `core/converters.py` | DONE | 15 tests pass | — | — | f660eff |
| S0-04 | job_manager unified state machine | 02 §4 | spec | all workspaces | `core/job_manager.py` | DONE | 15 tests pass | — | — | f660eff |
| S0-05 | projects.py multi-framework dirs | 02 §6 | spec | project panel | `core/projects.py` | DONE | 16 tests pass | — | — | f660eff |
| S0-06 | workflows.py chained registry | 02 §2 | spec | cross-framework | `core/workflows.py` | DONE | registry unit tests | — | — | f660eff |
| S0-07 | PAIPAI adapter + workspace | 01 §2 | siyazhu/PAIPAI | PAIPAI tab | `paipai.py` | DONE | install detect, run, stop, outputs | — | — | 45bed7b |
| S0-08 | ORCHID adapter + workspace | 01 §3 | orchid-calphad | ORCHID tab | `orchid_adapter.py` | DONE | search, phase_diagram, TDB | — | — | 45bed7b |
| S0-09 | PhaseForgePlus adapter + workspace | 03 §3 | dogusariturk/PFP | PFP tab | `pfp_adapter.py` | DONE | CG/LBFGS, cancel, TDB output | — | — | 47c04d8 |
| S0-10 | MLIP benchmark 4 modes | 04/05 | spec | Benchmark tab | `benchmark_*.py` | DONE | 247 tests pass | — | — | faa2205 |
| S0-11 | Universal file explorer `/api/fs/*` | 02 §1 | spec | Files panel | `filesystem.py` + `artifact_registry` | DONE | explorer loads, actions work | — | — | f660eff |
| S0-12 | PhaseForge → PFP transfer | 03 §3 | spec | PFP workspace | `/api/pfp_run` tdb_path | DONE | one-click TDB send | — | — | 47c04d8 |
| S0-13 | `-checkrelax` flag | 03 §2 | `sqscal -checkrelax` | PF workspace | `/api/pf_run` | DONE | commit 6e6054b | — | — | 6e6054b |
| S1-01 | `/api/pfp_phase_diagram` | 03 §3, 06 wf-B | PFP + pycalphad | PFP workspace | `server.py` + `pfp_adapter.py` | TODO | — | pycalphad must be installed | Add route; use `_phase_diagram_from_tdb(tdb_path, elements, T_min, T_max)` | — |
| S1-02 | NEB analyzer two-structure | 03 §4 | MF `neb` | MF analysis panel | `analysis.py` `/api/analyze` | TODO | — | needs second POSCAR input in UI | Add `structure2` param to analyze route; remove stub error | — |
| S1-03 | PhaseForge `MLIPrelax` | 03 §2 | `PhaseForge/bin/MLIPrelax` | PF workspace | `/api/pf_relax` | TODO | — | binary must be on PATH | Add route + UI panel like `/api/pf_run` | — |
| S1-04 | PhaseForge `MLIPcalc` | 03 §2 | `PhaseForge/bin/MLIPcalc` | PF workspace | `/api/pf_calc` | TODO | — | binary on PATH | Add route | — |
| S1-05 | PhaseForge `extract_MLIP` | 03 §2 | `PhaseForge/bin/extract_MLIP` | PF workspace | `/api/pf_extract` | TODO | — | binary on PATH | Add route | — |
| S1-06 | PhaseForge `runstruct_MLIP` | 03 §2 | `PhaseForge/bin/runstruct_MLIP` | PF workspace | `/api/pf_runstruct` | TODO | — | binary on PATH | Add route | — |
| S1-07 | PhaseForge `MLIPmd` | 03 §2 | `PhaseForge/bin/MLIPmd` | PF workspace | `/api/pf_md` | TODO | — | binary on PATH | Add route | — |
| S1-08 | PhaseForge `MLIPliquid` | 03 §2 | `PhaseForge/bin/MLIPliquid` | PF workspace | `/api/pf_liquid` | TODO | — | binary on PATH | Add route | — |
| S1-09 | PhaseForge `MLIPlammps` | 03 §2 | `PhaseForge/bin/MLIPlammps` | PF workspace | `/api/pf_lammps` | TODO | — | binary on PATH | Add route | — |
| S1-10 | ORCHID TDB → PFP workflow | 01 §5, 03 §3 | spec | ORCHID workspace | `/api/orchid/import_tdb` already saves; needs UI button in ORCHID TDB list | TODO | — | route exists; UI button missing | Add "Open in PFP" button in ORCHID TDB list JS; populate PFP tdb_path | — |
| S1-11 | PAIPAI output → MF transfer | 01 §5 | spec | PAIPAI workspace | artifact action | TODO | — | — | Register artifact action for PAIPAI POSCAR outputs → `/api/analyze` | — |
| S2-01 | PFP objective + gradient norm plot | 03 §3 | PFP callback | PFP workspace | `pfp_adapter._make_callback` | TODO | — | — | Extend callback to record obj_value + grad_norm; extend chart JS | — |
| S2-02 | PFP parameter evolution plot | 03 §3 | PFP callback all params | PFP workspace | `pfp_adapter._make_callback` | TODO | — | — | Record all params per iter; multi-line chart | — |
| S2-03 | PFP residual diagnostics | 03 §3 | ZPFResidual | PFP workspace | `pfp_adapter` | TODO | — | — | Expose per-dataset residuals from final objective eval | — |
| S2-04 | Surface analyzer slab wizard | 03 §4 | MF `surface` | MF panel | `/api/mf_slab` + `/api/analyze` | TODO | — | ASE needed for slab gen | Add slab generation endpoint; wire to surface analyzer | — |
| S2-05 | SBE analyzer slab wizard | 03 §4 | MF `sbe` | MF panel | `/api/mf_slab` + `/api/analyze` | TODO | — | ASE needed | Same as S2-04 | — |
| S2-06 | MF MD route | 03 §4 | `BaseMDCalculator` | MF panel | `/api/mf_md` | TODO | — | config keys exist; no backend | Add route that calls MF MD calculator | — |
| S2-07 | Trajectory replay UI | 03 §4 | trajectory_observer | MF panel | `/api/trajectory` | TODO | — | — | Add scrubber + frame canvas in MF panel | — |
| S2-08 | MF live calculator registry | 03 §4 | `list_calculators()` | MF panel dropdown | `filesystem.list_available_calculators` | TODO | — | — | Already calls `list_calculators()` with fallback; verify fallback not hiding live ones | — |
| S3-01 | `sqsgen` tool | 03 §4 | MF tools registry | MF panel | `/api/mf_sqsgen` | TODO | — | tool may need MF install | Inspect MF `sqsgen` API; add route + UI | — |
| S3-02 | `stability_map` tool | 03 §4 | MF tools registry | MF panel | `/api/mf_stability` | TODO | — | — | Add route | — |
| S3-03 | `cluster_expansion` tool | 03 §4 | MF tools registry | MF panel | `/api/mf_ce` | TODO | — | — | Add route | — |
| S3-04 | `bond_lattice_parameter` tool | 03 §4 | MF tools registry | MF panel | `/api/mf_bond_lp` | TODO | — | — | Add route | — |
| S3-05 | `material_parameters` Cahn-Hilliard | 03 §4 | MF tools | MF panel | `/api/mf_ch_params` | TODO | — | — | Add route | — |
| S3-06 | `phase_field_model` | 03 §4 | MF tools | MF panel | `/api/mf_pfm` | TODO | — | — | Add route | — |
| S3-07 | `simulation_grid` | 03 §4 | MF tools | MF panel | `/api/mf_simgrid` | TODO | — | — | Add route | — |
| S4-01 | BLADE shared CSS injection | 02 §3 | spec | BLADE iframe | `server.py` iframe injection | TODO | — | BLADE has own CSS | Inject PFS CSS vars via iframe `<style>` override or postMessage | — |
| S4-02 | Unified PFS ↔ BLADE config | 02 §3 | spec | config.json | server.py config bridge | TODO | — | BLADE reads own config | BLADE API to read/write PFS config keys | — |
| S4-03 | BLADE feature-parity checklist | 02 §3 | spec | docs/ | `docs/BLADE_FEATURE_PARITY.md` | TODO | — | — | Create checklist from BLADE source inspection | — |
| S5-01 | Tests for `pfp_adapter.py` | 06 §9 | spec | tests/ | `tests/test_pfp_adapter.py` | TODO | — | — | Write ≥12 tests covering install detect, launch, cancel, status, phase_diagram | — |
| S5-02 | Tests for `paipai.py` | 06 §9 | spec | tests/ | `tests/test_paipai.py` | TODO | — | — | Write ≥12 tests covering write_struc, run, stop, progress, outputs | — |
| S5-03 | Tests for `orchid_adapter.py` | 06 §9 | spec | tests/ | `tests/test_orchid_adapter.py` | TODO | — | network (use mocks) | Write ≥10 tests with mocked HTTP | — |
| S5-04 | Tests for `pipeline.py` | 06 §9 | spec | tests/ | `tests/test_pipeline.py` | TODO | — | — | Write ≥8 tests covering pipeline stages | — |
| S5-05 | Tests for `analysis.py` | 06 §9 | spec | tests/ | `tests/test_analysis.py` | TODO | — | — | Write ≥10 tests covering analyzer dispatch | — |
| S5-06 | Tests for Stage 1 routes | 06 §9 | spec | tests/ | `tests/test_server.py` additions | TODO | — | — | Add route tests for each new `/api/pf_*` endpoint | — |
| S6-01 | FINAL_VALIDATION_REPORT.md | 06 §10 | spec | docs/ | — | TODO | — | requires S0–S5 | Run full suite; record PASS/FAIL/BLOCKED per feature | — |
| S6-02 | USER_ACCEPTANCE_TESTING.md | 06 §13 | spec | docs/ | — | TODO | — | requires S6-01 | Write step-by-step manual test guide | — |
| S6-03 | E2E workflow A: PF→MF→PF TDB→pycalphad | 06 §2 | spec | — | — | TODO | — | MLIPs must be installed | Small reference system (Al-Ni) end-to-end | — |
| S6-04 | E2E workflow B: PF TDB→PFP→diagrams | 06 §2 | spec | — | — | TODO | — | requires S1-01 | Before/after phase diagram comparison | — |
| S6-05 | E2E workflow C: PF SQS→PAIPAI→MF | 06 §2 | spec | — | — | TODO | — | PAIPAI binary on PATH | Small MC run then MF property calc | — |
| S6-06 | E2E workflow D: ORCHID→PFP→pycalphad | 06 §2 | spec | — | — | TODO | — | requires S1-10 | ORCHID TDB import, PFP fit, diagram | — |
| S6-07 | E2E workflow F: MLIP benchmark 2 MLIPs 4 modes | 06 §2 | spec | — | — | TODO | — | MLIPs must be installed | Deterministic fixture acceptable for CI | — |
