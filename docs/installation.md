# Installation

## Requirements

- Python ≥ 3.11
- [`MaterialsFramework`](https://github.com/dogusariturk/MaterialsFramework) installed in your environment
- [`PhaseForge`](https://github.com/dogusariturk/PhaseForge) installed in your environment
- `mcsqs` / `sqs2tdb` on `$PATH` (from [ATAT](https://www.brown.edu/Departments/Engineering/Labs/avdw/atat/))

## Quick start

```bash
git clone https://github.com/ichasekatz/PhaseForgeStudio.git
cd PhaseForgeStudio
cp config.json.example config.json   # edit paths
python server.py --port 8080
```

From your laptop:

```bash
ssh -L 8080:localhost:8080 <hpc-host>
# open http://localhost:8080
```

## Configuration

Copy `config.json.example` to `config.json` and edit:

```json
{
  "path1": "/path/to/BLADE",
  "path2": "/path/to/PhaseForge/atat/data/sqsdb",
  "species": ["Al", "Ni"],
  "lattices": ["FCC_A1"],
  "calculator": "grace",
  "device": "cpu"
}
```

See the [README](https://github.com/ichasekatz/PhaseForgeStudio#configuration-configjson) for all configuration keys.
