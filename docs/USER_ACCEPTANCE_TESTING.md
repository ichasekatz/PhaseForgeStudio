# PhaseForgeStudio — User Acceptance Testing Checklist

**Version:** wip @ ec625bf  
**Date:** 2026-11-19

Manual UAT checklist. Each item maps to a spec requirement. Check off as you verify.

---

## Setup

```bash
cd Research/GUI
pixi shell
python server.py --config config.json
# Open http://localhost:8000
```

---

## 1. MF Analysis Workspace

### 1.1 EOS / Elastic Constants
- [ ] Select a POSCAR from the file browser
- [ ] Choose "Equation of State" analyzer, run → E-V curve chart appears
- [ ] Choose "Elastic Constants" analyzer, run → Cij table appears
- [ ] Choose "Formation Energy" analyzer, run → scalar result shown

### 1.2 NEB (Two-Structure)
- [ ] Select initial structure, choose NEB analyzer, omit final_rel_path → error message mentions `final_rel_path`
- [ ] Provide both structures → NEB runs (or ASE import error shown if unavailable)

### 1.3 MF MD
- [ ] Select a structure, open "Molecular Dynamics" panel
- [ ] Set ensemble=NVT Nose-Hoover, T=300, steps=10
- [ ] Click "Run MD" → potential energy chart appears, frame count shown
- [ ] If trajectory written: "Replay in Viewer" button appears → click → slider activates

### 1.4 Slab Generation
- [ ] Select a bulk structure, open "Slab Generator" panel
- [ ] Enter Miller index "1 0 0", click "Generate Slabs"
- [ ] Slab POSCAR files listed → click one to set as active structure

---

## 2. PhaseForgePlus Workspace

### 2.1 Optimization
- [ ] Load a TDB and ZPF directory, click "Start Optimisation"
- [ ] Live iteration counter updates as optimization runs
- [ ] After completion: "Fitted TDB" path shown, fval and grad_norm in last iteration

### 2.2 Phase Diagram
- [ ] After optimization completes, click "📊 Generate Phase Diagram"
- [ ] PNG phase diagram renders in result panel

---

## 3. PhaseForge (PF) Workspace

### 3.1 Command dispatch
- [ ] Set mlip/model, select a structure directory
- [ ] Click "Run Relax" → pf_relax starts, log streams
- [ ] Click "Run MD" (requires temperature) → MLIPmd starts
- [ ] Click "Extract" → extract_MLIP runs in workdir

---

## 4. ORCHID Workspace

### 4.1 CALPHAD data
- [ ] Enter a system (e.g. "Al-Ni"), search phases → results shown
- [ ] Click "Send to PFP" → PFP workspace pre-fills TDB path

---

## 5. PAIPAI Workspace

### 5.1 Monte Carlo
- [ ] Configure species and lattice, click "Start"
- [ ] Progress updates stream, log shows MC steps

---

## 6. BLADE Workspace

### 6.1 Design system
- [ ] Switch to BLADE workspace → iframe loads
- [ ] Dark background and PFS font style applied to BLADE dashboard

### 6.2 Config bridge
- [ ] With a config loaded, switch to BLADE → BLADE's TOML path field pre-fills

---

## 7. Benchmark Workspace

### 7.1 Multi-mode
- [ ] Choose "Energy" mode → runs energy comparisons
- [ ] Choose "Complete" mode → runs all metrics
- [ ] Export report → JSON file downloads

---

## 8. New MF Tools (API-level)

These require manual curl or fetch testing:

```bash
# SQS generation
curl -X POST http://localhost:8000/api/mf_sqsgen \
  -H 'Content-Type: application/json' \
  -d '{"composition":{"Al":0.5,"Ni":0.5},"crystal_structure":"fcc","supercell_size":[2,2,2]}'

# Stability map
curl -X POST http://localhost:8000/api/mf_stability_map \
  -d '{"elements":["Al","Ni"],"calculator":"grace","step":0.1}'

# Cahn-Hilliard
curl -X POST http://localhost:8000/api/mf_cahn_hilliard \
  -d '{"nx":32,"ny":32,"n_steps":100}'
```

- [ ] `mf_sqsgen` returns `{ok, structure, objective}`
- [ ] `mf_stability_map` returns `{ok, elements, step}` (or missing-dep error)
- [ ] `mf_cahn_hilliard` returns `{ok, phi_mean, phi_std, phi_min, phi_max}`

---

## Blockers to Resolve Before Production

| ID | Item | Owner |
|---|---|---|
| B2 | Install MaterialsFramework via entry points for calculator registry | Chase |
| B3 | Verify surface/SBE analyzer availability in installed MF fork | Chase |
