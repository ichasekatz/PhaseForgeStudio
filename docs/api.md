# API Reference

PhaseForge Studio exposes a JSON HTTP API on the same port as the UI.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve `index.html` |
| `/api/config` | GET / POST | Read / persist `config.json` |
| `/api/calculators` | GET | Available calculators with device/model flags |
| `/api/lattices` | GET | sqsdb lattice names |
| `/api/status` | GET | Job state, name, and elapsed time |
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
| `/api/phase_diagram` | GET | Generate phase diagram PNGs from a TDB |
| `/files/<rel>` | GET | Serve file from `path1` |
