# BLADE Feature Parity Checklist

Generated from BLADE dashboard source inspection (`phaseforge_studio/blade.py`) against
the PhaseForgeStudio Unified Architecture spec (spec doc 02 §3).

## Status legend

- ✅ Implemented and exposed via PFS
- 🟡 Partial — route exists but UI not fully wired
- ❌ Not yet implemented
- N/A — BLADE-only concern, no PFS equivalent needed

---

## Core BLADE Pipeline Features

| Feature | BLADE source | PFS exposure | Status | Notes |
|---|---|---|---|---|
| SQS scan / list | `scan_sqs()` | `/blade/api/status` | ✅ | Full SQS tree scan |
| Composition scan | `scan_comps()` | `/blade/api/status` | ✅ | Comps folder scan |
| Plot scan | `scan_plots()` | `/blade/api/plots` | ✅ | PNG/plot listing |
| Composition stage listing | `scan_compositions()` | `/blade/api/compositions` | ✅ | Per-comp stage info |
| Energy scan per comp | `scan_energy()` | `/blade/api/energy` | ✅ | eV values per SQS dir |
| Pipeline stage status | `infer_stage_status()` | `/blade/api/status` | ✅ | SQS/MLIP/TDB stage |
| Log tail read | `read_log_tail()` | `/blade/api/log` | ✅ | Last N lines |
| Live trajectory detect | `find_live_trajectory()` | SSE events | ✅ | trajectory.xyz streaming |
| TOML read | `read_toml_parsed()` | `/blade/api/config` | ✅ | Parsed TOML |
| TOML patch | `patch_toml()` | `/blade/api/config` POST | ✅ | Key-value patch |
| ATAT structure parse | `parse_atat_structure()` | `/blade/api/structure` | ✅ | str.out → extxyz |
| Bestcorr parse | `parse_bestcorr()` | Embedded in SQS scan | ✅ | Correlation quality |

## UI / Design Integration

| Feature | Spec reference | PFS status | Notes |
|---|---|---|---|
| Shared CSS design system | 02 §3.1 | ✅ | Injected via `serve_blade_index()` |
| PFS colour tokens in iframe | 02 §3.1 | ✅ | `--bg`, `--accent`, `--text` vars injected |
| postMessage config bridge | 02 §3.2 | ✅ | Parent sends `{type:"pfs-config"}` on iframe load |
| Unified font (JetBrains Mono) | 02 §3.1 | ✅ | Injected in CSS |
| BLADE API prefix rewrite | 02 §3 | ✅ | `/api/` → `/blade/api/` in `serve_blade_index()` |

## Config Bridge

| Feature | PFS status | Notes |
|---|---|---|
| `blade_toml` pre-fill | ✅ | Injected as script on `serve_blade_index()` |
| PFS config → BLADE sync | ✅ | Via postMessage `pfs-config` event |
| BLADE → PFS config write | ❌ | BLADE would need to postMessage back to parent |

## Gaps / TODO

| ID | Gap | Priority |
|---|---|---|
| S4-02b | BLADE → PFS reverse config sync (child → parent postMessage) | Low |
| S4-04 | BLADE workspace TOML editor in PFS sidebar (not iframe) | Medium |
| S4-05 | Live SQS progress bar in PFS status bar when BLADE workspace active | Low |
