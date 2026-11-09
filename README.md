# PhaseForge Studio

Browser-based dashboard for [MaterialsFramework](https://github.com/dogusariturk/MaterialsFramework) / BLADE / PhaseForge pipelines. Runs on HPC; access via SSH port forwarding. No npm, no build step — single Python file server + single HTML file frontend.

![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Configure & Run** — species, lattices, calculator (GRACE / MACE / CHGNet), fmax, T range, SQS level, supercell x/y/z
- **Live Structure Viewer** — 3Dmol.js with ball+stick / sphere / stick / surface styles, bond cutoff control, force vector overlay
- **Live Trajectory Playback** — in-memory extxyz frame array; scrub, play, or click ⬤ Live to auto-follow the running relaxation
- **Energy Chart** — three modes: all-compositions final energies (sorted by composition), per-structure step convergence, all-in-system step curves overlaid
- **File Browser** — hierarchical view of Jobs/ and Files/ with POSCAR/CONTCAR/TDB/PNG preview
- **Analysis Panel** — 14 MaterialsFramework analyzers (EOS, elastic constants, formation energy, Bain path, USFE, phonon, surface, NEB, …)
- **Job History** — readable job names (`AlNiFe BCC_A2 #1`), clickable history panel, `updated HH:MM:SS` badge
- **Phase Diagram Preview** — renders PNG outputs from TDB fitting inline

## Quick start

```bash
# activate your environment (pixi, conda, or venv with materialsframework installed)
cp config.json.example config.json   # edit paths
python server.py --port 8080
```

From your laptop:

```bash
ssh -L 8080:localhost:8080 <hpc-host>
# open http://localhost:8080
```

## Layout

```
┌─────────────────┬──────────────────────────────┬──────────────────┐
│   Configure     │        Visualize              │     Outputs      │
│                 │  ┌──────────────────────────┐ │                  │
│  Species        │  │  Structure  Energy  Log  │ │  TDB files       │
│  Lattices       │  │                          │ │  Phase diagrams  │
│  Calculator     │  │   3D viewer / chart /    │ │  File browser    │
│  Fit options    │  │   log stream             │ │                  │
│  Paths          │  └──────────────────────────┘ │  Analysis        │
│                 │  [▶ slider ⬤ Live]            │                  │
└─────────────────┴──────────────────────────────┴──────────────────┘
```

## Configuration (`config.json`)

| Key | Default | Description |
|-----|---------|-------------|
| `species` | `["Al","Ni"]` | Element symbols |
| `lattices` | `["FCC_A1"]` | ATAT lattice names (from sqsdb) |
| `calculator` | `"grace"` | Calculator name |
| `device` | `"cpu"` | `"cpu"` or `"cuda"` |
| `fmax` | `0.01` | Force convergence (eV/Å) |
| `t_min` / `t_max` | `298.15` / `6000` | CALPHAD temperature range (K) |
| `level` | `1` | SQS enumeration level |
| `md_scaling_matrix` | `2` | Supercell scale — scalar or `[x,y,z]` |
| `track_trajectory` | `true` | Write per-step extxyz during relaxation |
| `path1` | — | BLADE staging directory |
| `path2` | — | sqsdb base directory |

## API routes

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | `index.html` |
| `/api/config` | GET / POST | Read / persist config |
| `/api/calculators` | GET | Available calculators with device/model flags |
| `/api/lattices` | GET | sqsdb lattice names |
| `/api/status` | GET | Job state + name + elapsed |
| `/api/jobs` | GET | Current job + history list |
| `/api/stream` | GET | SSE log + state events |
| `/api/run` | POST | Start pipeline |
| `/api/stop` | POST | Signal stop |
| `/api/structure` | GET | Latest structure as extxyz |
| `/api/live_structure` | GET | Most recent trajectory frame (live) |
| `/api/energies` | GET | Final energies sorted by composition |
| `/api/energies/system` | GET | All step-energy curves for a system |
| `/api/trajectory/xyz` | GET | Full multi-frame extxyz for a label |
| `/api/outputs` | GET | TDB / PNG listing |
| `/api/analyze` | POST | Run a MaterialsFramework analyzer |
| `/api/browse` | GET | File browser entries |
| `/api/convert_xyz` | GET | POSCAR → extxyz conversion |
| `/files/<rel>` | GET | Serve file from path1 |

## Requirements

- Python ≥ 3.11 (stdlib only — no extra Python deps for the server itself)
- [`MaterialsFramework`](https://github.com/dogusariturk/MaterialsFramework) — MLIP calculator + analyzer library
- [`PhaseForge`](https://github.com/dogusariturk/PhaseForge) — CALPHAD TDB fitting layer
- [`BLADE`](https://github.com/ichasekatz/BLADE) — SQS generation + MLIP relaxation pipeline that PhaseForge Studio fronts
- `mcsqs` / `sqs2tdb` on `$PATH` (from [ATAT](https://www.brown.edu/Departments/Engineering/Labs/avdw/atat/))

## License

MIT
