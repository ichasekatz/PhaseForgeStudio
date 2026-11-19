# PhaseForgeStudio — Framework Feature Parity Audit

Generated: 2026-11-19  
Auditor: source-code inspection of local installations + upstream repos  
Scope: PhaseForge, PhaseForgePlus, MaterialsFramework/BLADE, PAIPAI, ORCHID

---

## Legend

| Status | Meaning |
|---|---|
| ✅ Complete | Input, execution, output, and error handling all verified |
| 🟡 Partial | UI exists but options missing, or backend exists without full UI |
| ❌ Missing | No GUI equivalent exists |
| 🔴 Broken | Route or UI exists but execution fails |
| ⚪ Unverified | Code path exists but not end-to-end tested |

---

## 1. PhaseForge

**Upstream:** csh shell-script toolkit. Primary binary: `sqscal`.  
**Local path:** `Research/PhaseForge/PhaseForge/`  
**GUI backend:** `server.py` `/api/pf_run` → `subprocess.Popen(["sqscal", ...])`

| Feature | Upstream reference | GUI location | Backend | Status | Required action |
|---|---|---|---|---|---|
| `sqscal` — SQS generation + TDB fit | `PhaseForge/bin/sqscal` | PhaseForge workspace | `/api/pf_run` | ✅ Complete | — |
| `-e` elements flag | `sqscal -e Al,Ni` | PF species tags | `/api/pf_run` body `elements` | ✅ Complete | — |
| `-l` lattices flag | `sqscal -l FCC_A1` | PF lattice buttons | `/api/pf_run` body `lattices` | ✅ Complete | — |
| `-lv` SQS level | `sqscal -lv 2` | PF level selector | `/api/pf_run` body `level` | ✅ Complete | — |
| `-mlip` calculator | `sqscal -mlip grace` | PF MLIP dropdown | `/api/pf_run` body `mlip` | ✅ Complete | — |
| `-model` model name | `sqscal -model GRACE-2L` | PF model input | `/api/pf_run` body `model` | ✅ Complete | — |
| `-vib` vibrational | `sqscal -vib` | PF vib checkbox | `/api/pf_run` body `vib` | ✅ Complete | — |
| `-sro` short-range order | `sqscal -sro` | PF SRO checkbox | `/api/pf_run` body `sro` | ✅ Complete | — |
| `-checkrelax` relax check | `sqscal -checkrelax` | — | — | ❌ Missing | Add checkbox + flag to `/api/pf_run` |
| `MLIPrelax` command | `PhaseForge/bin/MLIPrelax` | — | — | ❌ Missing | New route `/api/pf_relax` |
| `MLIPcalc` command | `PhaseForge/bin/MLIPcalc` | — | — | ❌ Missing | New route `/api/pf_calc` |
| `extract_MLIP` command | `PhaseForge/bin/extract_MLIP` | — | — | ❌ Missing | New route `/api/pf_extract` |
| `runstruct_MLIP` command | `PhaseForge/bin/runstruct_MLIP` | — | — | ❌ Missing | New route `/api/pf_runstruct` |
| `MLIPmd` command | `PhaseForge/bin/MLIPmd` | — | — | ❌ Missing | New route `/api/pf_md` |
| `MLIPliquid` command | `PhaseForge/bin/MLIPliquid` | — | — | ❌ Missing | New route `/api/pf_liquid` |
| `MLIPlammps` command | `PhaseForge/bin/MLIPlammps` | — | — | ❌ Missing | New route `/api/pf_lammps` |
| PF output TDB listing | workdir rglob `*.tdb` | PF outputs panel | `/api/pf_outputs` | ✅ Complete | — |
| PF output PNG listing | workdir rglob `*.png` | PF outputs panel | `/api/pf_outputs` | ✅ Complete | — |
| PF log streaming | stdout pipe | PF log panel | `/api/pf_status` | ✅ Complete | — |
| PF stop | SIGTERM | PF stop button | `/api/pf_stop` | ✅ Complete | — |
| **PhaseForge→PFP transfer** | send TDB to PFP | PFP workspace | `/api/pfp_run` tdb_path | ✅ Complete | — |

---

## 2. PhaseForgePlus

**Upstream:** Python package, `src/phaseforgeplus/`  
**Local path:** `Research/PhaseForge/PhaseForgePlus/`  
**Installed in GUI venv:** ✅ (editable install added 2026-11-19)  
**GUI backend:** `phaseforge_studio/pfp_adapter.py` (new)

| Feature | Upstream reference | GUI location | Backend | Status | Required action |
|---|---|---|---|---|---|
| Import TDB | `PhaseForgePlus(db=...)` / `load_tdb()` | PFP tdb-path input | `/api/pfp_run` | ✅ Complete | — |
| Load ZPF YAML data | `search_and_load_yaml(zpf_path)` | PFP zpf-dir input | `/api/pfp_run` | ✅ Complete | — |
| Generate NEQ data | `generate_neq_db(...)` | auto on run | `pfp_adapter._run_pfp` | ✅ Complete | — |
| CG optimisation | `scipy.minimize(method="CG", jac=True)` | PFP method dropdown | `launch_pfp(method="CG")` | ✅ Complete | — |
| L-BFGS-B optimisation | `scipy.minimize(method="L-BFGS-B")` | PFP method dropdown | `launch_pfp(method="L-BFGS-B")` | ✅ Complete | — |
| BFGS optimisation | `scipy.minimize(method="BFGS")` | PFP method dropdown | `launch_pfp(method="BFGS")` | ✅ Complete | — |
| Tolerance config | `minimize(tol=...)` | PFP tol input | `launch_pfp(tol=...)` | ✅ Complete | — |
| Max iterations | `minimize(options={"maxiter":...})` | PFP maxiter input | `launch_pfp(maxiter=...)` | ✅ Complete | — |
| Analytic Jansson gradient | `ZPFResidual.get_likelihood` / `jac=True` | auto (always used) | `objective_function` | ✅ Complete | Never replaced with FD |
| Inspect initial values | `get_initial_values()` / `database_symbols_to_fit` | PFP inspect button | `/api/pfp_initial_values` | ✅ Complete | — |
| Iteration callback / progress | `scipy callback=` | PFP log + chart | `pfp_adapter._make_callback` | ✅ Complete | — |
| Cancellation | `threading.Event` cancel flag | PFP stop button | `/api/pfp_stop` → `cancel_pfp` | ✅ Complete | — |
| Write fitted TDB | `fitted_db.to_string(fmt="tdb")` | auto on done | `_run_pfp` output write | ✅ Complete | — |
| Download fitted TDB | — | PFP download button | `/api/fs/read_text` | ✅ Complete | — |
| Objective vs iteration plot | — | PFP chart canvas | `pfpUpdateChart()` JS | 🟡 Partial | Plots param[0] only; no obj. value callback |
| Gradient norm plot | `neg_gradient` from objective | — | — | ❌ Missing | Extend callback to record obj+grad norms |
| Parameter evolution plot | all params per iteration | — | — | ❌ Missing | Extend callback + multi-line chart |
| Phase diagram before/after | pycalphad | — | — | ❌ Missing | Add `/api/pfp_phase_diagram` using pycalphad |
| Gibbs energy comparison | pycalphad | — | — | ❌ Missing | Future work |
| Residual diagnostics | ZPFResidual, FixedConfigResidual | — | — | ❌ Missing | Expose per-dataset residuals |
| Points config | `generate_neq_db(points=...)` | PFP points input | `/api/pfp_run` | ✅ Complete | — |
| Pressure / temperature | `PhaseForgePlus(pressure=, temperature=)` | PFP pressure/temp inputs | `/api/pfp_run` | ✅ Complete | — |

---

## 3. MaterialsFramework

**Upstream:** `dogusariturk/MaterialsFramework`  
**Local path:** `Research/PhaseForge/MaterialsFramework/`  
**Installed:** editable in BLADE pixi env + GUI venv via local path  

### 3a. Calculators (24 registered via entry-points)

| Calculator | In GUI dropdown | Status |
|---|---|---|
| alignn | ✅ | ✅ Selectable |
| alphanet | ✅ | ✅ |
| chgnet | ✅ | ✅ |
| deepmd | ✅ | ✅ |
| eqv2 | ✅ | ✅ |
| grace | ✅ | ✅ |
| hienet | ✅ | ✅ |
| m3gnet | ✅ | ✅ |
| mace | ✅ | ✅ |
| mattersim | ✅ | ✅ |
| nequip | ✅ | ✅ |
| orb | ✅ | ✅ |
| sevennet | ✅ | ✅ |
| uma | ✅ | ✅ |
| (10 additional from registry) | ⚪ | 🟡 Partial — GUI uses hardcoded fallback list; not live from `list_calculators()` |

**Required action:** Replace `_fallback_calculators` list with live `list_calculators()` call in `/api/calculators`.

### 3b. Analyzers (11 registered; 13 in GUI)

| Analyzer | GUI location | Backend | Status | Notes |
|---|---|---|---|---|
| eos | MF analysis panel | `analysis.py` | ✅ Complete | Fallback models added |
| elastic_constants | MF analysis | `analysis.py` | ✅ Complete | — |
| cubic_elastic_constants | MF analysis | `analysis.py` | ✅ Complete | — |
| formation_energy | MF analysis | `analysis.py` | ✅ Complete | — |
| bain | MF analysis | `analysis.py` | ✅ Complete | — |
| usfe | MF analysis | `analysis.py` | ✅ Complete | — |
| cte | MF analysis | `analysis.py` | ✅ Complete | — |
| surface | MF analysis | `analysis.py` | 🟡 Partial | Needs slab generation; bulk-only |
| sbe | MF analysis | `analysis.py` | 🟡 Partial | Needs slab generation |
| phonopy | MF analysis | `analysis.py` | ✅ Complete | — |
| phono3py | MF analysis | `analysis.py` | ✅ Complete | — |
| neb | MF analysis | `analysis.py` | ❌ Broken | Returns error stub — needs two structures |
| h_solubility | MF analysis | `analysis.py` | ✅ Complete | — |
| annni | MF analysis | `analysis.py` | ✅ Complete | — |

### 3c. Tools (9 registered; exposed in GUI)

| Tool | GUI location | Status | Required action |
|---|---|---|---|
| sqs2tdb | BLADE / MF pipeline | ✅ Complete via `Sqs2tdb.fit()` | — |
| sqsgen | — | ❌ Missing | Add `/api/mf_sqsgen` route + UI |
| cluster_expansion | — | ❌ Missing | Add `/api/mf_ce` route + UI |
| stability_map | — | ❌ Missing | Add `/api/mf_stability` route + UI |
| bond_lattice_parameter | — | ❌ Missing | Add route + UI |
| material_parameters | — | ❌ Missing | Cahn-Hilliard; add route |
| phase_field_model | — | ❌ Missing | Cahn-Hilliard; add route |
| simulation_grid | — | ❌ Missing | Cahn-Hilliard; add route |
| trajectory_observer | MF pipeline tracking | 🟡 Partial | Tracking enabled but no replay UI |

### 3d. MD (BaseMDCalculator)

| Feature | Status | Notes |
|---|---|---|
| MD via MF pipeline | ❌ Missing | No `/api/mf_md` route; config keys exist but no backend |
| MD temperature/pressure config | ⚪ Unverified | Config keys `md_temperature` etc. exist |

---

## 4. BLADE

**Upstream:** PhaseForge BLADE pipeline  
**Local path:** `Research/BLADE/` (working copy), `Research/BLADE-git/` (git)  
**GUI integration:** iframe at `/blade/` with API prefix rewriting

| Feature | GUI location | Status | Notes |
|---|---|---|---|
| BladeSQS generation | BLADE iframe | ✅ Complete | — |
| BladeCompositions | BLADE iframe | ✅ Complete | — |
| BladeTDBGen fit | BLADE iframe | ✅ Complete | — |
| TOML config read/write | `/blade/api/toml_read`, `/blade/api/toml_write` | ✅ Complete | — |
| Trajectory viewer | BLADE iframe | ✅ Complete | — |
| Energy plots | BLADE iframe | ✅ Complete | — |
| Phase diagram | BLADE iframe | ✅ Complete | — |
| Log streaming | BLADE iframe | ✅ Complete | — |
| Modern PFS CSS | — | ❌ Missing | BLADE runs own CSS; no shared design system |
| Config sync with PFS | — | 🟡 Partial | Separate config.json; not unified |

---

## 5. PAIPAI

**Upstream:** siyazhu/PAIPAI (C++ binary + Python workers)  
**Local:** binary must be on PATH  

| Feature | GUI location | Backend | Status |
|---|---|---|---|
| Install detection | PAIPAI workspace | `check_paipai_installed()` | ✅ Complete |
| `struc.in` from POSCAR | PAIPAI workspace | `struc_in_from_poscar()` | ✅ Complete |
| `paipai` run | PAIPAI workspace | `/api/paipai_run` | ✅ Complete |
| Progress polling | PAIPAI workspace | `get_paipai_progress()` | ✅ Complete |
| Stop | PAIPAI stop button | `/api/paipai_stop` | ✅ Complete |
| Output scan | PAIPAI outputs | `/api/paipai_outputs` | ✅ Complete |
| Write struc.in manually | PAIPAI workspace | `/api/paipai_write_struc` | ✅ Complete |
| Transfer to MF analysis | — | ❌ Missing | Workflow C: PAIPAI output → MF |

---

## 6. ORCHID

**Upstream:** orchid-calphad GitHub (MCP server)  
**Integration:** HTTP adapter `orchid_adapter.py`

| Feature | GUI location | Backend | Status |
|---|---|---|---|
| System search | ORCHID workspace | `/api/orchid/search` | ✅ Complete |
| Phase diagram fetch | ORCHID workspace | `/api/orchid/phase_diagram` | ✅ Complete |
| Invariant reactions | ORCHID workspace | `/api/orchid/invariant` | ✅ Complete |
| DFT comparison | ORCHID workspace | `/api/orchid/compare_dft` | ✅ Complete |
| TDB list / get | ORCHID workspace | `/api/orchid/tdb_list`, `get_tdb` | ✅ Complete |
| Import TDB to PFP | — | ❌ Missing | Workflow D: ORCHID TDB → PFP |
| Formation enthalpy | ORCHID workspace | `/api/orchid/formation_enthalpy` | ✅ Complete |

---

## 7. Cross-Framework Interoperability

| Workflow | Status | Notes |
|---|---|---|
| PhaseForge TDB → PhaseForgePlus | ✅ Complete | PFP workspace lists PF outputs; one-click transfer |
| File explorer → any framework | ✅ Complete | `/api/fs/*` + `artifact_registry` actions |
| Structure → PAIPAI | ✅ Complete | `/api/paipai_write_struc` accepts POSCAR text |
| Structure → MF analysis | ✅ Complete | `/api/analyze` |
| ORCHID TDB → PFP | ❌ Missing | No `/api/orchid/import_tdb` → PFP path |
| PAIPAI output → MF property | ❌ Missing | No transfer action registered |
| Fitted TDB → pycalphad phase diagram | ❌ Missing | No `/api/pfp_phase_diagram` |

---

## 8. Summary of Priority Actions

### Priority 1 — Highest impact, missing entirely

1. **PFP phase diagram route** (`/api/pfp_phase_diagram`): use pycalphad on fitted TDB to render before/after diagrams.
2. **MF live calculator registry**: replace hardcoded list with `list_calculators()` from MF entry-points.
3. **NEB analyzer**: accept two structure files, not a stub.
4. **Workflow D** (ORCHID → PFP): add "Open in PFP" action on ORCHID TDB list.

### Priority 2 — Partial implementations

5. **PhaseForge additional commands** (`MLIPrelax`, `MLIPcalc`, `MLIPmd`, `MLIPliquid`, `MLIPlammps`, `extract_MLIP`, `runstruct_MLIP`, `-checkrelax`).
6. **Surface/SBE analyzers**: add slab-generation wizard before analysis.
7. **PFP objective + gradient norm plot**: extend iteration callback.
8. **Trajectory replay UI** for MF trajectory_observer outputs.

### Priority 3 — New MF tool exposure

9. `sqsgen` tool
10. `stability_map` tool
11. `cluster_expansion` tool
12. `bond_lattice_parameter` tool
13. Cahn-Hilliard tools (`material_parameters`, `phase_field_model`, `simulation_grid`)
14. MD via MF (`BaseMDCalculator`)

### Priority 4 — BLADE modernization

15. Shared CSS/design-system injection into BLADE iframe.
16. Unified config between PFS and BLADE.

---

## 9. Test Coverage

| Module | Tests | Status |
|---|---|---|
| `core/file_types.py` | 23 | ✅ |
| `core/artifact_registry.py` | 10 | ✅ |
| `core/job_manager.py` | 15 | ✅ |
| `core/projects.py` | 16 | ✅ |
| `core/converters.py` | 15 | ✅ (ASE-conditional) |
| `pfp_adapter.py` | 0 | ❌ Missing |
| `paipai.py` | 0 | ❌ Missing |
| `orchid_adapter.py` | 0 | ❌ Missing |
| `pipeline.py` | 0 | ❌ Missing |
| `analysis.py` | 0 | ❌ Missing |

---

*This audit covers local source code only. Scientific validation (numerical correctness, unit consistency, pycalphad/ESPEI version compatibility) requires end-to-end test calculations with known reference systems (e.g., Al–Ni or Cu–Au).*
