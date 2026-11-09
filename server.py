#!/usr/bin/env python3
"""PhaseForge Studio server.

Bidirectional web UI for MaterialsFramework / BLADE / PhaseForge pipelines.
Runs on HPC; access via SSH port forwarding.

Usage:
    python server.py
    python server.py --port 8081
    python server.py --port 8081 --config /path/to/config.json
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pickle
import re
import sys
import threading
import time
import traceback
import uuid
from collections import Counter, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np

# Ensure ATAT/PhaseForge binaries are on PATH regardless of how server is launched.
_atat_bin = Path.home() / "Desktop/School/Research/PhaseForge/bin"
if _atat_bin.exists():
    os.environ["PATH"] = str(_atat_bin) + os.pathsep + os.environ.get("PATH", "")

# Inject editable package sources — fallback for envs where .pth processing is broken.
_gui_dir = Path(__file__).parent
_research = Path.home() / "Desktop/School/Research"
for _src in [
    _gui_dir / "MaterialsFramework/src",  # GUI-local MF v1.0.0 (preferred)
    _research / "BLADE/src",
]:
    _s = str(_src)
    if _src.exists() and _s not in sys.path:
        sys.path.insert(0, _s)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Defaults and config
# ---------------------------------------------------------------------------

_server_dir = Path(__file__).parent

ANALYZER_INFO: dict[str, Any] = {
    "eos": {
        "label": "Equation of State",
        "description": "Birch-Murnaghan EOS: bulk modulus, equilibrium volume",
        "returns": ["volumes", "energies", "b0_GPa", "v0", "e0"],
        "chart": "ev",
    },
    "elastic_constants": {
        "label": "Elastic Constants",
        "description": "Full Cij tensor + Young's, bulk, shear moduli, Poisson ratio",
        "returns": ["Cij", "youngs_modulus", "voigt_bulk_modulus", "voigt_shear_modulus", "poisson_ratio"],
        "chart": None,
    },
    "cubic_elastic_constants": {
        "label": "Cubic Elastic Constants",
        "description": "Elastic constants for cubic systems (C11, C12, C44) + derived moduli",
        "returns": ["C11", "C12", "C44", "youngs_modulus", "bulk_modulus", "shear_modulus", "poisson_ratio"],
        "chart": None,
    },
    "formation_energy": {
        "label": "Formation Energy",
        "description": "ΔHf per atom relative to pure element ground states",
        "returns": ["formation_energy"],
        "chart": None,
    },
    "bain": {
        "label": "Bain Path",
        "description": "Energy along BCC↔FCC Bain transformation path",
        "returns": ["c_a_list", "energy_list"],
        "chart": "bain",
    },
    "usfe": {
        "label": "USFE",
        "description": "Unstable stacking fault energy via GSFE curve",
        "returns": ["usfe_mJ_m2", "gsfe_curve"],
        "chart": "gsfe",
    },
    "cte": {
        "label": "Thermal Expansion (CTE)",
        "description": "Volumetric coefficient of thermal expansion vs temperature",
        "returns": ["temperatures", "volumes", "cte", "cte_ppm"],
        "chart": "cte",
    },
    "surface": {
        "label": "Surface Energy",
        "description": "Surface energies for low-index Miller planes",
        "returns": ["slabs"],
        "chart": None,
    },
    "sbe": {
        "label": "Surface Binding Energy",
        "description": "Surface binding energies and vacancy formation per termination",
        "returns": ["best_miller_index", "best_surface_energy", "avg_surface_binding_energy"],
        "chart": None,
    },
    "phonopy": {
        "label": "Phonon DOS/Spectrum",
        "description": "Phonon density of states and band structure via phonopy",
        "returns": ["frequencies", "dos", "band_structure"],
        "chart": "phonon",
    },
    "phono3py": {
        "label": "Thermal Conductivity",
        "description": "Lattice thermal conductivity via phono3py",
        "returns": ["thermal_conductivity"],
        "chart": None,
    },
    "neb": {
        "label": "NEB",
        "description": "Nudged elastic band: minimum energy path between two structures",
        "returns": ["images", "energies", "barrier"],
        "chart": "neb",
    },
    "h_solubility": {
        "label": "H Solubility",
        "description": "Hydrogen solubility and interstitial site energies",
        "returns": ["solubility", "site_energies"],
        "chart": None,
    },
    "annni": {
        "label": "ANNNI Stacking Fault",
        "description": "Axial next-nearest-neighbor Ising stacking fault energies",
        "returns": ["sfe", "isf", "usf"],
        "chart": None,
    },
}

_default_config: dict[str, Any] = {
    "species": ["Al", "Ni"],
    "lattices": ["FCC_A1"],
    "calculator": "grace",
    "fmax": 0.01,
    "t_min": 298.15,
    "t_max": 6000.0,
    "level": 1,
    "md_temperature": 1000,
    "md_pressure": 1,
    "md_timestep": 1.0,
    "md_scaling_matrix": 2,
    "sro": False,
    "bv": 0.005,
    "phonon": False,
    "open_calphad": False,
    "terms": None,
    "track_trajectory": True,
    "path0": "~/Desktop/School/Research",
    "path1": "~/Desktop/School/Research/BLADE",
    "path2": "~/Desktop/School/Research/PhaseForge/PhaseForge/atat/data/sqsdb",
    "device": "cpu",
}

# Hardcoded fallback when materialsframework is not installed
_fallback_calculators: list[str] = [
    "alignn",
    "alphanet",
    "chgnet",
    "deepmd",
    "eqv2",
    "grace",
    "hienet",
    "m3gnet",
    "mace",
    "mattersim",
    "nequip",
    "orb",
    "sevennet",
    "uma",
]


def _load_config(path: Path) -> dict[str, Any]:
    """Load config JSON, creating it from defaults if absent."""
    if not path.exists():
        path.write_text(json.dumps(_default_config, indent=2))
        return dict(_default_config)
    try:
        loaded = json.loads(path.read_text())
        merged = dict(_default_config)
        merged.update(loaded)
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(_default_config)


def _save_config(path: Path, cfg: dict[str, Any]) -> None:
    """Write config to disk atomically."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(path)


def _resolve(cfg: dict[str, Any], key: str) -> Path:
    """Expand ~ and resolve a path string from config."""
    return Path(cfg.get(key, _default_config[key])).expanduser().resolve()


# ---------------------------------------------------------------------------
# Structure conversion utilities
# ---------------------------------------------------------------------------


def _atoms_to_xyz(atoms: Any) -> str:
    """Convert ASE Atoms to extxyz string."""
    import io as _io

    from ase.io import write as _ase_write

    buf = _io.StringIO()
    _ase_write(buf, atoms, format="extxyz")
    return buf.getvalue()


def _poscar_to_xyz(text: str) -> str | None:
    """Convert POSCAR/CONTCAR text to extxyz string via ASE."""
    try:
        import io as _io

        from ase.io import read as _ase_read

        atoms = _ase_read(_io.StringIO(text), format="vasp")
        return _atoms_to_xyz(atoms)
    except Exception:
        return None


# Calculator discovery
# ---------------------------------------------------------------------------


def list_available_calculators() -> list[dict[str, Any]]:
    """Return calculator metadata from the materialsframework registry."""
    import ast

    try:
        import materialsframework.calculators as _calc_pkg
        from materialsframework.calculators.registry import list_calculators

        calc_dir = Path(_calc_pkg.__file__).parent
        names = list_calculators()
    except Exception:
        return [{"name": n, "supports_device": False, "supports_model": False} for n in sorted(_fallback_calculators)]

    result = []
    for name in sorted(names):
        supports_device = False
        supports_model = False
        py = calc_dir / f"{name}.py"
        if py.exists():
            try:
                tree = ast.parse(py.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                                args = [a.arg for a in item.args.args + item.args.kwonlyargs]
                                supports_device = "device" in args
                                supports_model = "model" in args
            except Exception:
                pass
        result.append({"name": name, "supports_device": supports_device, "supports_model": supports_model})
    return result


# ---------------------------------------------------------------------------
# Lattice discovery
# ---------------------------------------------------------------------------

_lattice_pattern = re.compile(r"^[A-Za-z0-9_]+_\d+$")


def list_available_lattices(sqsdb_path: Path) -> list[str]:
    """Scan sqsdb directory and return unique lattice base names."""
    if not sqsdb_path.is_dir():
        return ["BCC_A2", "FCC_A1", "LIQUID"]

    seen: set[str] = set()
    for entry in sqsdb_path.iterdir():
        if not entry.is_dir():
            continue
        name = re.sub(r"_\d+$", "", entry.name)
        if name:
            seen.add(name)

    return sorted(seen) if seen else ["BCC_A2", "FCC_A1", "LIQUID"]


# ---------------------------------------------------------------------------
# Filesystem scanners
# ---------------------------------------------------------------------------


def scan_latest_structure(path1: Path) -> dict[str, Any]:
    """Find most recently modified CONTCAR or bestsqs*.out across all job outputs."""
    search_roots = [path1 / "Jobs", path1 / "Files" / "SQS", path1 / "Files" / "Comps"]
    best_contcar: tuple[float, Path] | None = None
    best_bestsqs: tuple[float, Path] | None = None

    for root in search_roots:
        if not root.is_dir():
            continue
        for p in root.rglob("CONTCAR"):
            try:
                st = p.stat()
                if st.st_size > 0 and (best_contcar is None or st.st_mtime > best_contcar[0]):
                    best_contcar = (st.st_mtime, p)
            except OSError:
                continue
        for p in root.rglob("bestsqs*.out"):
            try:
                st = p.stat()
                if st.st_size > 0 and (best_bestsqs is None or st.st_mtime > best_bestsqs[0]):
                    best_bestsqs = (st.st_mtime, p)
            except OSError:
                continue

    if best_contcar and (best_bestsqs is None or best_contcar[0] >= best_bestsqs[0]):
        p = best_contcar[1]
        text = p.read_text(errors="ignore")
        if text.strip():
            xyz = _poscar_to_xyz(text)
            if xyz:
                return {"structure": xyz, "format": "xyz", "source": "CONTCAR", "label": p.parent.name}
            return {"structure": text, "format": "vasp", "source": "CONTCAR", "label": p.parent.name}

    if best_bestsqs:
        p = best_bestsqs[1]
        rndstr = p.parent / "rndstr.in"
        elem_map = _build_elem_map(rndstr)
        xyz = _parse_atat_structure(p.read_text(errors="ignore"), elem_map)
        if xyz:
            return {"structure": xyz, "format": "xyz", "source": "bestsqs", "label": p.parent.name}

    return {"structure": None, "format": None, "source": "none", "label": ""}


def scan_energies(path1: Path) -> dict[str, Any]:
    """Read per-structure energies from ATAT 'energy' files in Jobs/ and Files/SQS/.

    Sorted by composition (element fractions) so structures with the same
    composition sit adjacent, regardless of SQS level.
    """
    import re as _re

    roots = [path1 / "Jobs", path1 / "Files" / "SQS"]
    energy_files: list[Path] = []
    for root in roots:
        if root.is_dir():
            energy_files.extend(root.rglob("energy"))

    # Parse composition from each dir name: sqs_lev=N_a_El=frac[,a_El=frac,...]
    records: list[tuple[dict[str, float], str, Path]] = []
    all_elements: set[str] = set()
    for ef in energy_files:
        tokens = _re.findall(r"a_([A-Za-z]+)=([\d.]+)", ef.parent.name)
        fracs = {el: round(float(f), 6) for el, f in tokens}
        all_elements.update(fracs.keys())
        records.append((fracs, ef.parent.name, ef))

    # Fixed-length sort key: fractions for every element seen (0.0 if absent)
    sorted_els = sorted(all_elements)

    def _key(rec: tuple) -> tuple:
        fracs, dirname, _ = rec
        return tuple(fracs.get(el, 0.0) for el in sorted_els) + (dirname,)

    energies: list[float] = []
    labels: list[str] = []
    for _fracs, dirname, ef in sorted(records, key=_key):
        try:
            val = float(ef.read_text().strip())
            energies.append(val)
            labels.append(dirname)
        except (OSError, ValueError):
            continue

    return {"labels": labels, "energies": energies}


def scan_outputs(path1: Path) -> list[dict[str, Any]]:
    """List TDB and PNG output files from Jobs/ and Files/."""
    results: list[dict[str, Any]] = []
    roots = [path1 / "Jobs", path1 / "Files"]
    for root in roots:
        if not root.is_dir():
            continue
        for tdb in sorted(root.rglob("*.tdb"), key=lambda p: p.stat().st_mtime, reverse=True):
            with contextlib.suppress(OSError):
                results.append(
                    {
                        "name": tdb.name,
                        "rel_path": str(tdb.relative_to(path1)),
                        "file_type": "tdb",
                        "mtime": tdb.stat().st_mtime,
                        "size": tdb.stat().st_size,
                    }
                )
        for png in sorted(root.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
            with contextlib.suppress(OSError):
                results.append(
                    {
                        "name": png.name,
                        "rel_path": str(png.relative_to(path1)),
                        "file_type": "png",
                        "mtime": png.stat().st_mtime,
                        "size": png.stat().st_size,
                    }
                )

    return results


def browse_path(path1: Path, rel: str) -> dict[str, Any]:
    """List directory contents relative to path1 for the file browser.

    Args:
        path1 (Path): BLADE root directory.
        rel (str): Relative path under path1 to list (empty = list Jobs/).

    Returns:
        Dict with 'path' (the requested rel path) and 'entries' list.
    """
    safe_rel = rel.strip("/").replace("..", "")
    target = path1 / safe_rel if safe_rel else path1
    display_path = safe_rel if safe_rel else "/"
    if not target.exists() or not target.is_dir():
        return {"path": display_path, "entries": []}

    # At root level only show output-relevant dirs; hide source/config noise
    _root_output_dirs = {"Files", "Jobs", "Comps", "SQS", "Phase_Diagrams", "BCC_Benchmark", "Outputs"}

    entries: list[dict[str, Any]] = []
    try:
        items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return {"path": display_path, "entries": []}

    for item in items:
        # Always skip hidden files/dirs
        if item.name.startswith("."):
            continue
        # At root: only show known output dirs, no loose files
        if not safe_rel:
            if item.is_dir() and item.name not in _root_output_dirs:
                continue
            if item.is_file():
                continue
        try:
            st = item.stat()
        except OSError:
            continue
        ext = item.suffix.lower()
        if item.is_dir():
            kind = "dir"
        elif item.name in ("CONTCAR", "POSCAR") or (ext == ".out" and "bestsqs" in item.name):
            kind = "structure"
        elif ext == ".tdb":
            kind = "tdb"
        elif ext == ".png":
            kind = "png"
        elif item.name == "energy":
            kind = "energy"
        elif item.name == "trajectory.pkl":
            kind = "trajectory"
        elif item.name in (
            "energy",
            "force.out",
            "stress.out",
            "str_relax.out",
            "str.out",
            "str_hint.out",
            "rndstr.in",
            "sqscell.out",
            "bestsqs.out",
            "mcsqs.log",
        ) or ext in (".py", ".toml", ".lock", ".yaml", ".yml", ".md", ".cff", ".txt", ".cfg", ".ini", ".rst"):
            kind = "file"
        else:
            kind = "file"

        entries.append(
            {
                "name": item.name,
                "kind": kind,
                "rel_path": str(item.relative_to(path1)),
                "size": st.st_size,
                "mtime": st.st_mtime,
            }
        )

    return {"path": str(target.relative_to(path1)), "entries": entries}


def scan_structures(path1: Path) -> list[dict[str, Any]]:
    """List all CONTCAR files across all job subdirs, newest first."""
    results: list[dict[str, Any]] = []
    roots = [path1 / "Jobs", path1 / "Files"]
    for root in roots:
        if not root.is_dir():
            continue
        for contcar in root.rglob("CONTCAR"):
            try:
                st = contcar.stat()
                if st.st_size == 0:
                    continue
                results.append(
                    {
                        "label": contcar.parent.name,
                        "rel_path": str(contcar.relative_to(path1)),
                        "source": "CONTCAR",
                        "format": "vasp",
                        "mtime": st.st_mtime,
                    }
                )
            except OSError:
                continue
    return sorted(results, key=lambda x: x["mtime"], reverse=True)


def get_structure_by_label(path1: Path, label: str) -> dict[str, Any]:
    """Return structure text+format for a specific label (CONTCAR parent name)."""
    roots = [path1 / "Jobs", path1 / "Files"]
    for root in roots:
        if not root.is_dir():
            continue
        for contcar in root.rglob("CONTCAR"):
            if contcar.parent.name == label:
                try:
                    text = contcar.read_text(errors="ignore")
                    if text.strip():
                        xyz = _poscar_to_xyz(text)
                        if xyz:
                            return {"structure": xyz, "format": "xyz", "source": "CONTCAR", "label": label}
                        return {"structure": text, "format": "vasp", "source": "CONTCAR", "label": label}
                except OSError:
                    pass
    return {"structure": None, "format": None, "source": "none", "label": label}


def get_live_structure(path1: Path) -> dict[str, Any]:
    """Find the most recently updated trajectory.xyz in Jobs/ and return latest frame as XYZ.

    trajectory.xyz is written per step by BaseCalculator.relax() when traj_file is set.
    Returns {"xyz": str, "frame": int, "total_frames": int, "path": str} or {"xyz": None}.
    """
    roots = [path1 / "Jobs", path1 / "Files"]
    best: tuple[float, Path] | None = None

    for root in roots:
        if not root.is_dir():
            continue
        for xyz_path in root.rglob("trajectory.xyz"):
            try:
                st = xyz_path.stat()
                if st.st_size > 0 and (best is None or st.st_mtime > best[0]):
                    best = (st.st_mtime, xyz_path)
            except OSError:
                continue

    if best is None:
        return {"xyz": None, "full_xyz": None, "frame": 0, "total_frames": 0, "path": ""}

    xyz_path = best[1]
    try:
        text = xyz_path.read_text(errors="ignore")
        frames = _split_xyz_frames(text)
        if not frames:
            return {"xyz": None, "full_xyz": None, "frame": 0, "total_frames": 0, "path": ""}
        return {
            "xyz": frames[-1],  # latest single frame
            "full_xyz": text,  # all frames as multi-frame extxyz
            "frame": len(frames) - 1,
            "total_frames": len(frames),
            "path": str(xyz_path.relative_to(path1)),
            "label": xyz_path.parent.name,
        }
    except Exception:
        return {"xyz": None, "full_xyz": None, "frame": 0, "total_frames": 0, "path": ""}


def _split_xyz_frames(text: str) -> list[str]:
    """Split a multi-frame extxyz string into individual frame strings."""
    lines = text.splitlines()
    frames: list[str] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        try:
            n = int(s)
        except ValueError:
            i += 1
            continue
        end = i + 2 + n
        if end > len(lines):
            break
        frames.append("\n".join(lines[i:end]))
        i = end
    return frames


def get_trajectory_xyz(path1: Path, label: str) -> str | None:
    """Return full extxyz text for a label — from trajectory.xyz (live) or built from trajectory.pkl."""
    roots = [path1 / "Jobs", path1 / "Files"]
    # Prefer trajectory.xyz (written per step — always up to date)
    for root in roots:
        if not root.is_dir():
            continue
        for xyz_path in root.rglob("trajectory.xyz"):
            if xyz_path.parent.name == label:
                try:
                    text = xyz_path.read_text(errors="ignore")
                    if text.strip():
                        return text
                except OSError:
                    pass
    # Fall back to pkl
    for root in roots:
        if not root.is_dir():
            continue
        for traj_pkl in root.rglob("trajectory.pkl"):
            if traj_pkl.parent.name == label:
                try:
                    import io as _io

                    with traj_pkl.open("rb") as f:
                        data = pickle.load(f)
                    n = len(data.get("atom_positions", []))
                    if n == 0:
                        return None
                    frames_text: list[str] = []
                    for idx in range(n):
                        positions = np.array(data["atom_positions"][idx])
                        cell = np.array(data["cells"][idx])
                        symbols = data["chemical_symbols"][idx]
                        energy = data.get("potential_energies", [0.0])[idx]
                        forces_raw = data.get("forces", [])
                        forces = forces_raw[idx] if idx < len(forces_raw) else None
                        try:
                            from ase import Atoms as _Atoms

                            _a = _Atoms(symbols=symbols, positions=positions, cell=cell, pbc=True)
                            _a.info["energy"] = float(energy)
                            if forces is not None:
                                _a.arrays["forces"] = np.array(forces)
                            buf = _io.StringIO()
                            from ase.io import write as _ase_write

                            _ase_write(buf, _a, format="extxyz", append=True)
                            frames_text.append(buf.getvalue())
                        except Exception:
                            pass
                    return "".join(frames_text) if frames_text else None
                except Exception:
                    return None
    return None


def get_system_step_energies(path1: Path, label: str) -> list[dict[str, Any]]:
    """Return step-energy curves for all compositions in the same system as `label`.

    Finds the parent directory of the sqs_lev subdir matching `label`, then
    collects trajectory data for every sibling sqs_lev subdir.
    """
    roots = [path1 / "Jobs", path1 / "Files"]
    parent_dir: Path | None = None
    for root in roots:
        if not root.is_dir():
            continue
        for traj_pkl in root.rglob("trajectory.pkl"):
            if traj_pkl.parent.name == label:
                parent_dir = traj_pkl.parent.parent
                break
        if parent_dir:
            break
    if not parent_dir:
        return []

    results: list[dict[str, Any]] = []
    for subdir in sorted(parent_dir.iterdir()):
        pkl = subdir / "trajectory.pkl"
        if not pkl.exists():
            continue
        try:
            with pkl.open("rb") as f:
                data = pickle.load(f)
            pot_e = data.get("potential_energies", [])
            chem_sym = data.get("chemical_symbols", [])
            n_atoms = len(chem_sym[0]) if chem_sym else 1
            energies_per_atom = [e / n_atoms for e in pot_e]
            if energies_per_atom:
                results.append(
                    {
                        "label": subdir.name,
                        "steps": list(range(len(energies_per_atom))),
                        "energies": energies_per_atom,
                    }
                )
        except Exception:
            continue
    return results


def get_trajectory_data(path1: Path, label: str) -> dict[str, Any] | None:
    """Load trajectory pickle for a sqs_lev subdir, return step energies.

    Returns dict with steps, energies (eV/atom), n_frames, or None if not found.
    """
    roots = [path1 / "Jobs", path1 / "Files"]
    for root in roots:
        if not root.is_dir():
            continue
        for traj_pkl in root.rglob("trajectory.pkl"):
            if traj_pkl.parent.name == label:
                try:
                    with traj_pkl.open("rb") as f:
                        data = pickle.load(f)
                    pot_e = data.get("potential_energies", [])
                    chem_sym = data.get("chemical_symbols", [])
                    n_atoms = len(chem_sym[0]) if chem_sym else 1
                    energies_per_atom = [e / n_atoms for e in pot_e]
                    return {
                        "label": label,
                        "steps": list(range(len(energies_per_atom))),
                        "energies": energies_per_atom,
                        "n_frames": len(data.get("atom_positions", [])),
                    }
                except Exception:
                    return None
    return None


def get_trajectory_frame(path1: Path, label: str, frame: int) -> dict[str, Any] | None:
    """Load a single frame from trajectory pickle, return as VASP POSCAR string."""
    roots = [path1 / "Jobs", path1 / "Files"]
    for root in roots:
        if not root.is_dir():
            continue
        for traj_pkl in root.rglob("trajectory.pkl"):
            if traj_pkl.parent.name == label:
                try:
                    with traj_pkl.open("rb") as f:
                        data = pickle.load(f)
                    n_frames = len(data.get("atom_positions", []))
                    if n_frames == 0:
                        return None
                    idx = max(0, min(frame, n_frames - 1))
                    positions = np.array(data["atom_positions"][idx])
                    cell = np.array(data["cells"][idx])
                    symbols = data["chemical_symbols"][idx]
                    energy = data.get("potential_energies", [0.0])[idx]
                    forces_raw = data.get("forces", [])
                    forces_list = forces_raw[idx].tolist() if idx < len(forces_raw) else []
                    # Build XYZ via ASE for reliable rendering
                    xyz: str | None = None
                    try:
                        from ase import Atoms as _Atoms

                        _a = _Atoms(symbols=symbols, positions=positions, cell=cell, pbc=True)
                        _a.info["energy"] = float(energy)
                        if forces_list:
                            _a.arrays["forces"] = np.array(forces_list)
                        xyz = _atoms_to_xyz(_a)
                    except Exception:
                        xyz = None
                    if xyz is None:
                        xyz = _positions_to_poscar(symbols, positions, cell, energy)
                        fmt = "vasp"
                    else:
                        fmt = "xyz"
                    return {
                        "structure": xyz,
                        "format": fmt,
                        "frame": idx,
                        "n_frames": n_frames,
                        "energy": float(energy),
                        "forces": forces_list,
                        "positions": positions.tolist(),
                    }
                except Exception:
                    return None
    return None


def _positions_to_poscar(symbols: list[str], positions: Any, cell: Any, energy: float = 0.0) -> str:
    """Build a VASP POSCAR string from positions, cell, symbols."""
    cnt: Counter[str] = Counter(symbols)
    unique_syms = list(cnt.keys())
    lines = [f"Frame E={energy:.6f} eV", "1.0"]
    for row in cell:
        lines.append(f"  {row[0]:>16.9f}  {row[1]:>16.9f}  {row[2]:>16.9f}")
    lines.append("  ".join(unique_syms))
    lines.append("  ".join(str(cnt[s]) for s in unique_syms))
    lines.append("Cartesian")
    sym_order = {s: i for i, s in enumerate(unique_syms)}
    atom_data = sorted(zip(symbols, positions, strict=False), key=lambda x: sym_order[x[0]])
    for _, pos in atom_data:
        lines.append(f"  {pos[0]:>16.9f}  {pos[1]:>16.9f}  {pos[2]:>16.9f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ATAT / CONTCAR structure parsers
# ---------------------------------------------------------------------------

_alpha_elems = [
    "Al",
    "Ba",
    "Ca",
    "Cr",
    "Cu",
    "Fe",
    "Ga",
    "Hf",
    "In",
    "Ir",
    "K",
    "La",
    "Mn",
    "Na",
    "Os",
    "Pd",
    "Pt",
    "Re",
    "Si",
    "Ti",
    "U",
    "V",
    "W",
    "Xe",
    "Y",
    "Zr",
]


def _build_elem_map(rndstr_path: Path) -> dict[str, str]:
    """Parse rndstr.in → ATAT component label → real element symbol."""
    try:
        text = rndstr_path.read_text(errors="ignore")
    except OSError:
        return {}

    mapping: dict[str, str] = {}
    sl_letters = "abcdefghijklmnop"
    sl_idx = 0

    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            float(parts[0])
        except ValueError:
            continue
        spec = parts[3]
        if "=" in spec:
            sl = sl_letters[sl_idx] if sl_idx < len(sl_letters) else f"s{sl_idx}"
            for ci, token in enumerate(spec.split(",")):
                elem = token.split("=")[0].strip()
                mapping[f"{sl}_{chr(ord('A') + ci)}"] = elem
            sl_idx += 1

    return mapping


def _atat_species(raw: str, elem_map: dict[str, str], used: set[str]) -> str:
    """Resolve ATAT alloy notation to a real element symbol."""
    if elem_map and raw in elem_map:
        return elem_map[raw]
    m = re.match(r"^[a-z]_([A-Z])$", raw)
    if m:
        idx = ord(m.group(1)) - ord("A")
        candidate = _alpha_elems[idx] if idx < len(_alpha_elems) else "Fe"
        if candidate in used:
            for alt in _alpha_elems:
                if alt not in used:
                    return alt
            return "Xe"
        return candidate
    return raw


def _parse_atat_structure(text: str, elem_map: dict[str, str] | None = None) -> str | None:
    """Convert ATAT bestsqs.out text to XYZ format."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip() and not ln.startswith("#")]
    if len(lines) < 7:
        return None
    try:
        lat = [[float(x) for x in lines[i].split()[:3]] for i in range(3)]
        _atat_pat = re.compile(r"^[a-z]_[A-Z]$")
        real_elems: set[str] = set()
        for line in lines[6:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                float(parts[0])
                raw = parts[3]
            except ValueError:
                raw = parts[0]
            if not _atat_pat.match(raw) and (not elem_map or raw not in elem_map):
                real_elems.add(raw)

        atoms: list[tuple[str, list[float]]] = []
        for line in lines[6:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                frac = [float(parts[0]), float(parts[1]), float(parts[2])]
                species = _atat_species(parts[3], elem_map or {}, real_elems)
            except ValueError:
                species = _atat_species(parts[0], elem_map or {}, real_elems)
                frac = [float(parts[1]), float(parts[2]), float(parts[3])]

            cart = [
                frac[0] * lat[0][0] + frac[1] * lat[1][0] + frac[2] * lat[2][0],
                frac[0] * lat[0][1] + frac[1] * lat[1][1] + frac[2] * lat[2][1],
                frac[0] * lat[0][2] + frac[1] * lat[1][2] + frac[2] * lat[2][2],
            ]
            atoms.append((species, cart))

        if not atoms:
            return None

        xyz_lines = [str(len(atoms)), "PhaseForge Studio"]
        for sp, (x, y, z) in atoms:
            xyz_lines.append(f"{sp} {x:.6f} {y:.6f} {z:.6f}")
        return "\n".join(xyz_lines)
    except Exception:
        return None


def _contcar_to_xyz(text: str) -> str | None:
    """Convert a VASP CONTCAR/POSCAR to XYZ format."""
    try:
        lines = text.strip().splitlines()
        if len(lines) < 9:
            return None
        scale = float(lines[1].strip())
        lat = [[float(v) * scale for v in lines[i + 2].split()[:3]] for i in range(3)]
        species_line = lines[5].split()
        counts_line = [int(x) for x in lines[6].split()]
        coord_type = lines[7].strip()[0].lower()
        atoms: list[tuple[str, list[float]]] = []
        idx = 8
        for sp, count in zip(species_line, counts_line, strict=True):
            for _ in range(count):
                xyz_vals = [float(v) for v in lines[idx].split()[:3]]
                if coord_type == "d":
                    cart = [
                        xyz_vals[0] * lat[0][0] + xyz_vals[1] * lat[1][0] + xyz_vals[2] * lat[2][0],
                        xyz_vals[0] * lat[0][1] + xyz_vals[1] * lat[1][1] + xyz_vals[2] * lat[2][1],
                        xyz_vals[0] * lat[0][2] + xyz_vals[1] * lat[1][2] + xyz_vals[2] * lat[2][2],
                    ]
                else:
                    cart = xyz_vals
                atoms.append((sp, cart))
                idx += 1

        if not atoms:
            return None

        xyz_lines = [str(len(atoms)), "CONTCAR"]
        for sp, (x, y, z) in atoms:
            xyz_lines.append(f"{sp} {x:.6f} {y:.6f} {z:.6f}")
        return "\n".join(xyz_lines)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# MaterialsFramework analysis
# ---------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    """JSON serializer for numpy scalar and array types."""
    import numpy as np

    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def _run_analysis(cfg: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Run a MaterialsFramework analyzer on a structure file."""
    import sys

    mf_src = Path(__file__).parent / "MaterialsFramework" / "src"
    blade_src = Path(__file__).parent.parent / "BLADE" / "src"
    for p in (str(mf_src), str(blade_src)):
        if p not in sys.path:
            sys.path.insert(0, p)

    rel_path: str = params.get("rel_path", "")
    analyzer_name: str = params.get("analyzer", "eos")
    calc_name: str = params.get("calculator", cfg.get("calculator", "grace"))
    device: str = params.get("device", cfg.get("device", "cpu"))
    is_relaxed: bool = bool(params.get("is_relaxed", True))

    if not rel_path:
        return {"error": "No structure path provided"}

    path1 = Path(cfg["path1"]).expanduser().resolve()
    struct_path = path1 / rel_path
    if not struct_path.exists():
        return {"error": f"File not found: {rel_path}"}

    try:
        from ase.io import read as ase_read

        atoms = ase_read(str(struct_path))

        from materialsframework.calculators.registry import get_calculator

        _device_calcs = {"grace", "mace", "chgnet", "orb", "sevennet", "m3gnet", "mattersim"}
        calc_kwargs: dict[str, Any] = {}
        if device and calc_name in _device_calcs:
            calc_kwargs["device"] = device
        calculator = get_calculator(calc_name, **calc_kwargs)

        if analyzer_name == "eos":
            from materialsframework.analysis.eos import EOSAnalyzer

            result = EOSAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            return {
                "analyzer": "eos",
                "volumes": [float(v) for v in result["volumes"]],
                "energies": [float(e) for e in result["energies"]],
                "b0_GPa": float(result["b0_GPa"]),
                "v0": float(result["v0"]),
                "e0": float(result["e0"]),
            }

        if analyzer_name == "elastic_constants":
            from materialsframework.analysis.elastic_constants import ElasticConstantsAnalyzer

            result = ElasticConstantsAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            scalar = {k: float(v) for k, v in result.items() if isinstance(v, (int, float))}
            return {"analyzer": "elastic_constants", **scalar}

        if analyzer_name == "formation_energy":
            from materialsframework.analysis.formation_energy import FormationEnergyAnalyzer

            result = FormationEnergyAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            return {"analyzer": "formation_energy", "formation_energy": float(result["formation_energy"])}

        if analyzer_name == "bain":
            from materialsframework.analysis.bain import BainPathAnalyzer

            result = BainPathAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            return {
                "analyzer": "bain",
                "c_a_list": [float(v) for v in result["c_a_list"]],
                "energy_list": [float(v) for v in result["energy_list"]],
            }

        if analyzer_name == "usfe":
            from materialsframework.analysis.usfe import USFEAnalyzer

            result = USFEAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            return {
                "analyzer": "usfe",
                "usfe_mJ_m2": float(result["usfe_mJ_m2"]),
                "gsfe_curve": result.get("gsfe_curve", []),
                "slip_plane": result.get("slip_plane", ""),
            }

        if analyzer_name == "cubic_elastic_constants":
            from materialsframework.analysis.cubic_elastic_constants import CubicElasticConstantsAnalyzer

            result = CubicElasticConstantsAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            return {"analyzer": "cubic_elastic_constants", **{k: float(v) for k, v in result.items() if isinstance(v, (int, float))}}

        if analyzer_name == "cte":
            from materialsframework.analysis.cte import CTEAnalyzer

            result = CTEAnalyzer(calculator=calculator).calculate(atoms)
            return {
                "analyzer": "cte",
                "temperatures": [float(t) for t in result["temperatures"]],
                "volumes": [float(v) for v in result["volumes"]],
                "cte": [float(c) for c in result["cte"]],
                "cte_ppm": [float(c) for c in result["cte_ppm"]],
            }

        if analyzer_name == "surface":
            from materialsframework.analysis.surface import SurfaceAnalyzer

            result = SurfaceAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            slabs = []
            for s in result.get("slabs", []):
                slabs.append(
                    {
                        k: (float(v) if isinstance(v, (int, float, np.floating)) else str(v))
                        for k, v in s.items()
                        if not hasattr(v, "__len__")
                    }
                )
            return {"analyzer": "surface", "slabs": slabs}

        if analyzer_name == "sbe":
            from materialsframework.analysis.sbe import SBEAnalyzer

            result = SBEAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            scalar = {k: float(v) for k, v in result.items() if isinstance(v, (int, float, np.floating))}
            return {"analyzer": "sbe", **scalar}

        if analyzer_name == "phonopy":
            from materialsframework.analysis.phonopy import PhonopyAnalyzer

            result = PhonopyAnalyzer(calculator=calculator).calculate(atoms)
            out: dict[str, Any] = {"analyzer": "phonopy"}
            for k, v in result.items():
                if hasattr(v, "tolist"):
                    out[k] = v.tolist()
                elif isinstance(v, (int, float)):
                    out[k] = float(v)
                else:
                    out[k] = str(v)
            return out

        if analyzer_name == "phono3py":
            from materialsframework.analysis.phono3py import Phono3pyAnalyzer

            result = Phono3pyAnalyzer(calculator=calculator).calculate(atoms)
            return {
                "analyzer": "phono3py",
                "thermal_conductivity": float(result.get("kappa", 0.0))
                if hasattr(result.get("kappa"), "__float__")
                else str(result.get("kappa", "")),
            }

        if analyzer_name == "h_solubility":
            from materialsframework.analysis.h_solubility import HSolubilityAnalyzer

            result = HSolubilityAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            scalar = {k: float(v) for k, v in result.items() if isinstance(v, (int, float, np.floating))}
            return {"analyzer": "h_solubility", **scalar}

        if analyzer_name == "annni":
            from materialsframework.analysis.annni import ANNNIStackingFaultAnalyzer

            result = ANNNIStackingFaultAnalyzer(calculator=calculator).calculate(atoms)
            scalar = {k: float(v) for k, v in result.items() if isinstance(v, (int, float, np.floating))}
            return {"analyzer": "annni", **scalar}

        if analyzer_name == "neb":
            return {"error": "NEB requires two structures; not supported via single-file analysis"}

        return {"error": f"Unknown analyzer: {analyzer_name}"}

    except Exception as exc:
        import traceback as tb

        return {"error": str(exc), "traceback": tb.format_exc()}


# ---------------------------------------------------------------------------
# Job state machine
# ---------------------------------------------------------------------------


class JobState:
    """Thread-safe state machine for a single background pipeline job."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: str = "idle"
        self.job_id: str | None = None
        self.job_name: str | None = None
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.log: deque[str] = deque(maxlen=2000)
        self._thread: threading.Thread | None = None

    def push_log(self, line: str) -> None:
        with self._lock:
            self.log.append(line)

    def set_state(self, state: str) -> None:
        with self._lock:
            self.state = state
            if state in ("done", "error", "idle") and self.start_time and not self.end_time:
                self.end_time = time.time()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            elapsed = (time.time() - self.start_time) if self.start_time else None
            return {
                "state": self.state,
                "job_id": self.job_id,
                "job_name": self.job_name,
                "elapsed_s": round(elapsed, 1) if elapsed is not None else None,
            }

    def is_running(self) -> bool:
        with self._lock:
            return self.state == "running"

    def stop(self) -> None:
        with self._lock:
            self.state = "idle"
            if self.start_time and not self.end_time:
                self.end_time = time.time()


_job = JobState()
_job_history: list[dict[str, Any]] = []  # completed/stopped jobs (most recent last)
_job_counter: int = 0  # global sequential counter for job names


# ---------------------------------------------------------------------------
# Capturing stdout/stderr from pipeline thread
# ---------------------------------------------------------------------------


class _LogCapture(io.TextIOBase):
    """TextIO shim that forwards writes to JobState.push_log."""

    def __init__(self, job: JobState) -> None:
        super().__init__()
        self._job = job
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._job.push_log(line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self._job.push_log(self._buf)
            self._buf = ""


# ---------------------------------------------------------------------------
# Trajectory-tracking Sqs2tdb factory
# ---------------------------------------------------------------------------


def _make_tracking_sqs2tdb() -> type:
    """Return a Sqs2tdb subclass that saves trajectory.pkl per sqs_lev subdir."""
    from materialsframework.tools.sqs2tdb import Sqs2tdb

    class _TrackingSqs2tdb(Sqs2tdb):
        def _calculate(self, subdir: Path, relax: bool = True) -> None:
            self.calculator.traj_file = str(subdir / "trajectory.pkl")
            try:
                super()._calculate(subdir, relax)
            finally:
                self.calculator.traj_file = None

    return _TrackingSqs2tdb


# ---------------------------------------------------------------------------
# Phase diagram generation
# ---------------------------------------------------------------------------


def _phase_diagram_from_tdb(tdb_path: Path, t_min: float = 300.0, t_max: float = 3000.0) -> list[Path]:
    """Generate phase diagram PNGs from a TDB file.

    For a binary system (2 non-VA elements) produces one diagram.
    For N>2 elements produces all C(N,2) pseudo-binary sections at x_other=0,
    i.e. each binary sub-system of the full alloy.

    Returns list of PNG paths written.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pycalphad import Database, binplot
    from pycalphad import variables as v

    dbf = Database(str(tdb_path))
    phases = list(dbf.phases.keys())
    # dbf.elements returns a frozenset including 'VA' and '/-'
    all_els = sorted(e for e in dbf.elements if e not in ("VA", "/-", "/"))
    if len(all_els) < 2:
        return []
    comps = all_els + ["VA"]

    t_step = max(5.0, (t_max - t_min) / 200)
    eps = 1e-3
    written: list[Path] = []

    # Generate all binary sub-systems
    from itertools import combinations

    pairs = list(combinations(all_els, 2))

    for el_a, el_b in pairs:
        # Fixed: all other elements set to 0 (pure binary sub-system)
        fixed = {el: 0.0 for el in all_els if el not in (el_a, el_b)}
        x_max = 1.0 - sum(fixed.values()) - eps
        conds: dict = {
            v.N: 1,
            v.P: 101325,
            v.T: (t_min, t_max, t_step),
            v.X(el_b): (eps, x_max, x_max / 100),
        }
        for el, frac in fixed.items():
            conds[v.X(el)] = frac

        fig, ax = plt.subplots(figsize=(8, 6))
        try:
            binplot(dbf, comps, phases, conds, plot_kwargs={"ax": ax})
        except (ValueError, KeyError) as exc:
            if "need at least one array" in str(exc) or "degrees of freedom" in str(exc).lower():
                ax.text(0.5, 0.5, "No two-phase boundaries found", ha="center", va="center", transform=ax.transAxes, color="gray")
            else:
                plt.close(fig)
                raise

        pair_label = f"{el_a}–{el_b}"
        sys_label = "–".join(all_els)
        title = f"{pair_label}" if len(all_els) == 2 else f"{pair_label} (in {sys_label})"
        ax.set_title(title)
        ax.set_xlabel(f"X({el_b})")
        ax.set_ylabel("Temperature (K)")
        fig.tight_layout()

        stem = f"{''.join(all_els)}_{el_a}{el_b}_phase_diagram"
        out = tdb_path.parent / f"{stem}.png"
        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        plt.close(fig)
        written.append(out)

    return written


def _generate_phase_diagrams(work_dir: Path, species: list[str], lattices: list[str], job: JobState) -> None:
    """Generate phase diagram PNGs from all TDB files in work_dir."""
    try:
        import matplotlib  # noqa: F401
        from pycalphad import Database  # noqa: F401
    except ImportError as e:
        job.push_log(f"[studio] Phase diagram skipped: {e}")
        return

    tdb_files = list(work_dir.rglob("*.tdb"))
    if not tdb_files:
        job.push_log("[studio] No TDB files found for phase diagram.")
        return

    for tdb_path in tdb_files:
        try:
            pngs = _phase_diagram_from_tdb(tdb_path)
            for p in pngs:
                job.push_log(f"[studio] Phase diagram saved: {p.name}")
            if not pngs:
                job.push_log(f"[studio] Skipped {tdb_path.name}: < 2 components")
        except Exception as e:
            job.push_log(f"[studio] Phase diagram failed for {tdb_path.name}: {e}")
            job.push_log(traceback.format_exc()[:800])


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline(cfg: dict[str, Any], job: JobState) -> None:
    """Background thread: run the full Sqs2tdb pipeline in a job work dir."""
    capture = _LogCapture(job)
    origin = Path.cwd()
    try:
        job.push_log(f"[studio] Starting pipeline — job {job.job_id}")
        job.push_log(f"[studio] species={cfg['species']} lattices={cfg['lattices']}")
        job.push_log(f"[studio] calculator={cfg['calculator']} device={cfg.get('device', 'cpu')} fmax={cfg['fmax']}")

        from materialsframework.calculators.registry import get_calculator
        from materialsframework.tools.sqs2tdb import Sqs2tdb

        sqs_cls = _make_tracking_sqs2tdb() if cfg.get("track_trajectory") else Sqs2tdb

        path1 = Path(cfg["path1"]).expanduser().resolve()

        system_name = "".join(cfg["species"])
        work_dir = path1 / "Jobs" / job.job_id / system_name
        work_dir.mkdir(parents=True, exist_ok=True)
        job.push_log(f"[studio] Work dir: {work_dir}")

        _device_calcs = {m["name"] for m in list_available_calculators() if m["supports_device"]}
        calc_kwargs: dict[str, Any] = {}
        if cfg.get("device") and cfg["calculator"] in _device_calcs:
            calc_kwargs["device"] = cfg["device"]
        calculator = get_calculator(cfg["calculator"], **calc_kwargs)

        # Pre-warm the underlying ASE calculator so heavy imports (tensorflow, etc.)
        # happen BEFORE stdout/stderr are redirected to _LogCapture (which lacks fileno()).
        try:
            _ = calculator.calculator
            job.push_log(f"[studio] Calculator loaded: {type(_).__name__}")
        except Exception as _pre_e:
            job.push_log(f"[studio] Calculator pre-load warning: {_pre_e}")

        pipeline = sqs_cls(
            fmax=cfg["fmax"],
            calculator=calculator,
            md_temperature=cfg.get("md_temperature", 1000),
            md_pressure=cfg.get("md_pressure", 1),
            md_timestep=cfg.get("md_timestep", 1.0),
            md_scaling_matrix=cfg.get("md_scaling_matrix", 2),
            verbose=True,
        )

        os.chdir(work_dir)
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            pipeline.fit(
                species=cfg["species"],
                lattices=cfg.get("lattices"),
                level=cfg.get("level", 1),
                t_min=cfg.get("t_min", 298.15),
                t_max=cfg.get("t_max", 6000.0),
                sro=cfg.get("sro", False),
                bv=cfg.get("bv", 5e-3),
                phonon=cfg.get("phonon", False),
                open_calphad=cfg.get("open_calphad", False),
                terms=cfg.get("terms") or None,
            )

        if job.is_running():
            job.push_log("[studio] Pipeline complete — generating phase diagrams...")
            _generate_phase_diagrams(work_dir, cfg["species"], cfg.get("lattices", []), job)
            job.set_state("done")

    except ImportError as e:
        job.push_log(f"[studio] Import error: {e}")
        job.push_log(traceback.format_exc()[:2000])
        job.set_state("error")
    except Exception as e:
        job.push_log(f"[studio] Error: {e}")
        capture.write(traceback.format_exc())
        capture.flush()
        job.set_state("error")
    finally:
        os.chdir(origin)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class StudioHandler(BaseHTTPRequestHandler):
    """HTTP request handler for PhaseForge Studio."""

    config_path: Path
    cfg: dict[str, Any]

    def log_message(self, fmt: str, *args: Any) -> None:
        """Suppress default access log output."""

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, content_type: str = "text/plain") -> None:
        try:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._json({"error": "not found"}, 404)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _files_dir(self) -> Path:
        return _resolve(self.cfg, "path1") / "Files"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        """Route all GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._serve_file(Path(__file__).parent / "index.html", "text/html; charset=utf-8")

        elif path == "/api/config":
            self._json(self.cfg)

        elif path == "/api/calculators":
            self._json(list_available_calculators())

        elif path == "/api/lattices":
            self._json(list_available_lattices(_resolve(self.cfg, "path2")))

        elif path == "/api/status":
            self._json(_job.as_dict())

        elif path == "/api/jobs":
            current = _job.as_dict() if _job.job_id else None
            self._json({"current": current, "history": list(reversed(_job_history))})

        elif path == "/api/stream":
            self._handle_sse()

        elif path == "/api/structure":
            label = qs.get("label", [""])[0]
            path1 = _resolve(self.cfg, "path1")
            if label:
                self._json(get_structure_by_label(path1, label))
            else:
                self._json(scan_latest_structure(path1))

        elif path == "/api/structures":
            self._json(scan_structures(_resolve(self.cfg, "path1")))

        elif path == "/api/energies":
            self._json(scan_energies(_resolve(self.cfg, "path1")))

        elif path == "/api/energies/system":
            label = qs.get("label", [""])[0]
            curves = get_system_step_energies(_resolve(self.cfg, "path1"), label)
            self._json({"curves": curves})

        elif path == "/api/phase_diagram":
            # On-demand: generate diagrams for a TDB file given its path relative to path1
            rel = qs.get("path", [""])[0]
            path1 = _resolve(self.cfg, "path1")
            tdb_path = (path1 / rel).resolve()
            if not str(tdb_path).startswith(str(path1)) or not tdb_path.exists():
                self._json({"error": "not found"}, 404)
            else:
                try:
                    pngs = _phase_diagram_from_tdb(
                        tdb_path,
                        t_min=float(self.cfg.get("t_min", 300)),
                        t_max=float(self.cfg.get("t_max", 3000)),
                    )
                    # Return relative paths from path1
                    rel_pngs = [str(p.relative_to(path1)) for p in pngs]
                    self._json({"ok": True, "pngs": rel_pngs})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)

        elif path == "/api/outputs":
            self._json(scan_outputs(_resolve(self.cfg, "path1")))

        elif path == "/api/browse":
            rel = qs.get("path", [""])[0]
            self._json(browse_path(_resolve(self.cfg, "path1"), rel))

        elif path == "/api/trajectory":
            label = qs.get("label", [""])[0]
            data = get_trajectory_data(_resolve(self.cfg, "path1"), label)
            if data is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(data)

        elif path == "/api/trajectory/frame":
            label = qs.get("label", [""])[0]
            try:
                frame = int(qs.get("frame", ["0"])[0])
            except (ValueError, IndexError):
                frame = 0
            data = get_trajectory_frame(_resolve(self.cfg, "path1"), label, frame)
            if data is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(data)

        elif path == "/api/trajectory/xyz":
            label = qs.get("label", [""])[0]
            xyz_text = get_trajectory_xyz(_resolve(self.cfg, "path1"), label)
            if xyz_text is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json({"label": label, "xyz": xyz_text})

        elif path == "/api/analyzers":
            self._json(ANALYZER_INFO)

        elif path == "/api/convert_xyz":
            rel = qs.get("path", [""])[0]
            if not rel:
                self._json({"error": "no path"}, 400)
                return
            full = _resolve(self.cfg, "path1") / rel
            if not full.is_file():
                self._json({"error": "not found"}, 404)
                return
            try:
                text = full.read_text(errors="ignore")
                xyz = _poscar_to_xyz(text)
                if xyz:
                    self._json({"xyz": xyz, "format": "xyz"})
                else:
                    self._json({"xyz": text, "format": "vasp"})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/live_structure":
            self._json(get_live_structure(_resolve(self.cfg, "path1")))

        elif path.startswith("/files/"):
            rel = unquote(path[len("/files/") :])
            full = _resolve(self.cfg, "path1") / rel
            if not full.is_file():
                self._json({"error": "not found"}, 404)
                return
            ext = full.suffix.lower()
            mime_map = {".tdb": "text/plain", ".png": "image/png", ".gif": "image/gif", ".json": "application/json"}
            self._serve_file(full, mime_map.get(ext, "application/octet-stream"))

        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        """Route all POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/config":
            try:
                body = json.loads(self._read_body())
                self.cfg.update(body)
                _save_config(self.config_path, self.cfg)
                StudioHandler.cfg = self.cfg
                self._json({"ok": True})
            except (json.JSONDecodeError, OSError) as e:
                self._json({"error": str(e)}, 400)

        elif path == "/api/run":
            if _job.is_running():
                self._json({"error": "job already running"}, 409)
                return
            cfg_snapshot = dict(self.cfg)
            # Save finished job to history before starting new one
            global _job_counter  # noqa: PLW0603
            if _job.job_id and _job.state in ("done", "error", "idle"):
                _job_history.append(
                    {
                        "job_id": _job.job_id,
                        "job_name": _job.job_name,
                        "state": _job.state,
                        "start_time": _job.start_time,
                        "end_time": _job.end_time,
                    }
                )
            _job_counter += 1
            species_str = "".join(cfg_snapshot.get("species", []))
            lattice_str = "-".join(cfg_snapshot.get("lattices", []))
            readable_name = f"{species_str} {lattice_str} #{_job_counter}"
            _job.state = "running"
            _job.job_id = str(uuid.uuid4())[:8]
            _job.job_name = readable_name
            _job.start_time = time.time()
            _job.end_time = None
            _job.log.clear()
            t = threading.Thread(target=_run_pipeline, args=(cfg_snapshot, _job), daemon=True)
            _job._thread = t
            t.start()
            self._json({"ok": True, "job_id": _job.job_id, "job_name": _job.job_name})

        elif path == "/api/stop":
            _job.stop()
            self._json({"ok": True})

        elif path == "/api/analyze":
            try:
                params = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                params = {}
            result = _run_analysis(self.cfg, params)
            body = json.dumps(result, default=_json_default).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        else:
            self._json({"error": "not found"}, 404)

    def _handle_sse(self) -> None:
        """Hold connection open and push log lines via Server-Sent Events."""
        heartbeat_interval = 15.0
        poll_sleep = 0.25

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        last_idx = len(_job.log)
        last_state = _job.state
        last_heartbeat = time.time()
        last_contcar_count = 0
        path1 = _resolve(StudioHandler.cfg, "path1")

        def _send(payload: str) -> bool:
            try:
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        _send(json.dumps({"type": "status", "state": _job.state}))

        while True:
            time.sleep(poll_sleep)

            now = time.time()
            log_snapshot = list(_job.log)
            new_lines = log_snapshot[last_idx:]
            last_idx = len(log_snapshot)

            for line in new_lines:
                if not _send(json.dumps({"type": "log", "line": line})):
                    return

            current_state = _job.state
            if current_state != last_state:
                if not _send(json.dumps({"type": "status", "state": current_state})):
                    return
                last_state = current_state

            # Push structure_updated when new CONTCARs appear during run
            if current_state == "running":
                try:
                    structs = scan_structures(path1)
                    if len(structs) != last_contcar_count:
                        last_contcar_count = len(structs)
                        if structs:
                            latest = structs[0]
                            if not _send(json.dumps({"type": "structure_updated", "label": latest["label"]})):
                                return
                except Exception:
                    pass

            if now - last_heartbeat >= heartbeat_interval:
                try:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    last_heartbeat = now
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse args, load config, and serve."""
    parser = argparse.ArgumentParser(description="PhaseForge Studio server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--config", type=Path, default=_server_dir / "config.json")
    args = parser.parse_args()

    cfg = _load_config(args.config)

    print("PhaseForge Studio")
    print(f"  config : {args.config}")
    print(f"  path1  : {cfg.get('path1')}")
    print(f"  path2  : {cfg.get('path2')}")
    print(f"  http://localhost:{args.port}")
    print()

    StudioHandler.config_path = args.config
    StudioHandler.cfg = cfg

    server = ThreadingHTTPServer(("", args.port), StudioHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
