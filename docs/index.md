# PhaseForge Studio

Browser-based dashboard for [MaterialsFramework](https://github.com/dogusariturk/MaterialsFramework) / [BLADE](https://github.com/ichasekatz/BLADE) / [PhaseForge](https://github.com/dogusariturk/PhaseForge) pipelines.

Runs on HPC; access via SSH port forwarding. No npm, no build step — single Python file server + single HTML file frontend.

## Features

- **Configure & Run** — species, lattices, calculator (GRACE / MACE / CHGNet), fmax, T range, SQS level, supercell x/y/z
- **Live Structure Viewer** — 3Dmol.js with ball+stick / sphere / stick / surface styles, bond cutoff, force vector overlay
- **Live Trajectory Playback** — in-memory extxyz frame array; scrub, play, or ⬤ Live to auto-follow the running relaxation
- **Energy Chart** — three modes: all-compositions final energies, per-structure step convergence, all-in-system step curves
- **Phase Diagram** — on-demand generation for binary and N-component TDB files via pycalphad
- **File Browser** — hierarchical view with POSCAR/CONTCAR/TDB/PNG inline preview
- **Analysis Panel** — 14 MaterialsFramework analyzers

See [Installation](installation.md) to get started.
