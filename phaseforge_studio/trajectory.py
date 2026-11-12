"""Trajectory loading and frame access utilities."""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Any

from phaseforge_studio.structure import _atoms_to_xyz, _positions_to_poscar


def _parse_xyz_step_energies(xyz_path: Path) -> list[float] | None:
    """Return per-frame eV/atom energies from a multi-frame extxyz file, or None."""
    try:
        text = xyz_path.read_text(errors="ignore")
    except OSError:
        return None
    frames = _split_xyz_frames(text)
    if not frames:
        return None
    energies: list[float] = []
    for frame in frames:
        lines = frame.splitlines()
        if len(lines) < 2:
            continue
        m = re.search(r"energy\s*=\s*([-\d.eE+]+)", lines[1], re.IGNORECASE)
        if not m:
            continue
        try:
            n_atoms = int(lines[0].strip())
            e = float(m.group(1))
            energies.append(e / n_atoms if n_atoms > 0 else e)
        except (ValueError, ZeroDivisionError):
            continue
    return energies if energies else None


def _split_xyz_frames(text: str) -> list[str]:
    """Split a multi-frame extxyz string into individual frame strings.

    Args:
        text (str): Multi-frame extxyz text.

    Returns:
        List of single-frame extxyz strings.
    """
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
    """Return full extxyz text for a label — from trajectory.xyz or trajectory.pkl.

    Prefers the live-written trajectory.xyz (updated per step). Falls back to
    reconstructing from the pickle when xyz is absent.

    Args:
        path1 (Path): BLADE root directory.
        label (str): Subdirectory name identifying the structure.

    Returns:
        Multi-frame extxyz string, or None if not found.
    """
    import numpy as np

    roots = [path1 / "Jobs"]
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
    """Return per-step energy curves for all compositions in the same system as `label`.

    Locates the parent directory of the sqs_lev subdir matching ``label``, then
    collects trajectory data for every sibling sqs_lev subdir.

    Args:
        path1 (Path): BLADE root directory.
        label (str): Subdirectory name of one structure in the target system.

    Returns:
        List of dicts with keys ``label``, ``steps``, ``energies`` (eV/atom).
    """
    roots = [path1 / "Jobs"]
    parent_dir: Path | None = None
    for root in roots:
        if not root.is_dir():
            continue
        for traj in list(root.rglob("trajectory.pkl")) + list(root.rglob("trajectory.xyz")):
            if traj.parent.name == label:
                parent_dir = traj.parent.parent
                break
        if parent_dir:
            break
    if not parent_dir:
        return []

    # Scan all phase dirs within the same system (parent_dir.parent)
    system_dir = parent_dir.parent
    phase_dirs = sorted(
        p for p in system_dir.iterdir()
        if p.is_dir()
    )

    results: list[dict[str, Any]] = []
    for phase_dir in phase_dirs:
        for subdir in sorted(phase_dir.iterdir()):
            if not subdir.is_dir():
                continue
            energies_per_atom: list[float] = []
            pkl = subdir / "trajectory.pkl"
            if pkl.exists():
                try:
                    with pkl.open("rb") as f:
                        data = pickle.load(f)
                    pot_e = data.get("potential_energies", [])
                    chem_sym = data.get("chemical_symbols", [])
                    n_atoms = len(chem_sym[0]) if chem_sym else 1
                    energies_per_atom = [e / n_atoms for e in pot_e]
                except Exception:
                    pass
            if not energies_per_atom:
                xyz = subdir / "trajectory.xyz"
                if xyz.exists():
                    energies_per_atom = _parse_xyz_step_energies(xyz) or []
            if energies_per_atom:
                results.append(
                    {
                        "label": f"{phase_dir.name} · {subdir.name}",
                        "phase": phase_dir.name,
                        "raw_label": subdir.name,
                        "steps": list(range(len(energies_per_atom))),
                        "energies": energies_per_atom,
                    }
                )
    return results


def get_trajectory_data(path1: Path, label: str) -> dict[str, Any] | None:
    """Load trajectory pickle for a sqs_lev subdir and return step energies.

    Args:
        path1 (Path): BLADE root directory.
        label (str): Subdirectory name identifying the structure.

    Returns:
        Dict with ``steps``, ``energies`` (eV/atom), and ``n_frames``,
        or None if not found.
    """
    roots = [path1 / "Jobs"]
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
    """Load a single frame from a trajectory pickle and return structure data.

    Args:
        path1 (Path): BLADE root directory.
        label (str): Subdirectory name identifying the structure.
        frame (int): Zero-based frame index (clamped to valid range).

    Returns:
        Dict with ``structure`` (XYZ/POSCAR string), ``format``, ``frame``,
        ``n_frames``, ``energy`` (eV), ``forces``, and ``positions``,
        or None if not found.
    """
    import numpy as np

    roots = [path1 / "Jobs"]
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
