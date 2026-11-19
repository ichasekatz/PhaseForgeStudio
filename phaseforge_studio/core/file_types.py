"""File type detection and metadata extraction for materials-science files.

Inspects file contents and paths to identify supported formats without
relying on extension alone.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# File-type constants
# ---------------------------------------------------------------------------

FT_POSCAR = "poscar"
FT_CIF = "cif"
FT_XYZ = "xyz"
FT_EXTXYZ = "extxyz"
FT_LAMMPS_DATA = "lammps_data"
FT_LAMMPS_DUMP = "lammps_dump"
FT_TDB = "tdb"
FT_CSV = "csv"
FT_TSV = "tsv"
FT_JSON = "json"
FT_YAML = "yaml"
FT_NUMPY = "numpy"
FT_PICKLE = "pickle"
FT_ENERGY = "energy"
FT_TRAJECTORY_PKL = "trajectory_pkl"
FT_TRAJECTORY_XYZ = "trajectory_xyz"
FT_BESTCORR = "bestcorr"
FT_BESTSQS = "bestsqs"
FT_RNDSTR = "rndstr"
FT_IMAGE = "image"
FT_LOG = "log"
FT_TOML = "toml"
FT_PYTHON = "python"
FT_DIR = "dir"
FT_UNKNOWN = "unknown"

# Maps file type → human label, icon hint, description
_ft_meta: dict[str, dict[str, str]] = {
    FT_POSCAR: {"label": "POSCAR/CONTCAR", "icon": "structure", "desc": "VASP structure file"},
    FT_CIF: {"label": "CIF", "icon": "structure", "desc": "Crystallographic Information File"},
    FT_XYZ: {"label": "XYZ", "icon": "structure", "desc": "XYZ structure/trajectory"},
    FT_EXTXYZ: {"label": "Extended XYZ", "icon": "structure", "desc": "Extended XYZ with metadata"},
    FT_LAMMPS_DATA: {"label": "LAMMPS Data", "icon": "structure", "desc": "LAMMPS structure input"},
    FT_LAMMPS_DUMP: {"label": "LAMMPS Dump", "icon": "trajectory", "desc": "LAMMPS trajectory dump"},
    FT_TDB: {"label": "TDB", "icon": "database", "desc": "CALPHAD thermodynamic database"},
    FT_CSV: {"label": "CSV", "icon": "table", "desc": "Comma-separated values"},
    FT_TSV: {"label": "TSV", "icon": "table", "desc": "Tab-separated values"},
    FT_JSON: {"label": "JSON", "icon": "file", "desc": "JSON data"},
    FT_YAML: {"label": "YAML", "icon": "file", "desc": "YAML data"},
    FT_NUMPY: {"label": "NumPy", "icon": "array", "desc": "NumPy array file"},
    FT_PICKLE: {"label": "Pickle", "icon": "file", "desc": "Python pickle (untrusted)"},
    FT_ENERGY: {"label": "Energy", "icon": "energy", "desc": "Total energy (eV)"},
    FT_TRAJECTORY_PKL: {"label": "Trajectory (pkl)", "icon": "trajectory", "desc": "ASE trajectory pickle"},
    FT_TRAJECTORY_XYZ: {"label": "Trajectory (xyz)", "icon": "trajectory", "desc": "XYZ trajectory file"},
    FT_BESTCORR: {"label": "ATAT bestcorr", "icon": "atat", "desc": "ATAT correlation objective"},
    FT_BESTSQS: {"label": "ATAT bestsqs", "icon": "atat", "desc": "ATAT best SQS structure"},
    FT_RNDSTR: {"label": "ATAT rndstr.in", "icon": "atat", "desc": "ATAT random structure input"},
    FT_IMAGE: {"label": "Image", "icon": "image", "desc": "Phase diagram or plot image"},
    FT_LOG: {"label": "Log", "icon": "log", "desc": "Calculation log"},
    FT_TOML: {"label": "TOML", "icon": "config", "desc": "TOML configuration"},
    FT_PYTHON: {"label": "Python", "icon": "code", "desc": "Python source file"},
    FT_DIR: {"label": "Directory", "icon": "dir", "desc": "Directory"},
    FT_UNKNOWN: {"label": "File", "icon": "file", "desc": "Unknown file"},
}

# Content-based detectors (checked in order; return file type or None)
_poscar_re = re.compile(r"^\s*\S.*\n\s*[\d.]+\s*\n", re.MULTILINE)
_cif_re = re.compile(r"^data_|_cell_length_a|_atom_site_label", re.MULTILINE)
_tdb_re = re.compile(r"^\s*(ELEMENT|SPECIES|PHASE|CONSTITUENT|PARAMETER|FUNCTION)\b", re.MULTILINE)
_extxyz_re = re.compile(r'^(\d+)\s*\n.*Properties=', re.MULTILINE)
_xyz_re = re.compile(r'^(\d+)\s*\n\s*\S*\s*\n(\s*[A-Za-z]+\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+)', re.MULTILINE)
_lammps_data_re = re.compile(r'\b(atoms|bonds|atom types|LAMMPS data)\b', re.MULTILINE)
_lammps_dump_re = re.compile(r'^ITEM: TIMESTEP', re.MULTILINE)


def _sniff_text(path: Path, max_bytes: int = 4096) -> str:
    """Read up to *max_bytes* of a text file without raising.

    Args:
        path (Path): File to read.
        max_bytes (int): Maximum bytes to read.

    Returns:
        Decoded text, or empty string on error.
    """
    try:
        with path.open("rb") as f:
            raw = f.read(max_bytes)
        return raw.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _is_binary(path: Path) -> bool:
    """Return True if the file appears to be binary.

    Args:
        path (Path): File to check.

    Returns:
        bool: True if null bytes found in first 4 KiB.
    """
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
        return b"\x00" in chunk
    except OSError:
        return False


def detect(path: Path) -> str:
    """Detect the file type for a given path.

    Uses a combination of filename patterns and content sniffing.
    Does NOT deserialise pickle or numpy files.

    Args:
        path (Path): File or directory to classify.

    Returns:
        One of the ``FT_*`` constants defined in this module.
    """
    if path.is_dir():
        return FT_DIR

    name = path.name
    ext = path.suffix.lower()

    # --- Extension / name shortcuts (cheap) ---
    if name in ("POSCAR", "CONTCAR"):
        return FT_POSCAR
    if name in ("energy",):
        return FT_ENERGY
    if name == "rndstr.in":
        return FT_RNDSTR
    if name == "trajectory.pkl":
        return FT_TRAJECTORY_PKL
    if name.startswith("bestsqs") and ext == ".out":
        return FT_BESTSQS
    if name.startswith("bestcorr") and ext == ".out":
        return FT_BESTCORR
    if name in ("trajectory.xyz", "relaxation_live.xyz", "relaxation_final.xyz"):
        return FT_TRAJECTORY_XYZ
    if ext == ".tdb":
        return FT_TDB
    if ext == ".cif":
        return FT_CIF
    if ext in (".xyz",):
        pass  # fall through to content sniff
    if ext == ".csv":
        return FT_CSV
    if ext == ".tsv":
        return FT_TSV
    if ext == ".json":
        return FT_JSON
    if ext in (".yaml", ".yml"):
        return FT_YAML
    if ext == ".npy":
        return FT_NUMPY
    if ext in (".pkl", ".pickle"):
        return FT_PICKLE
    if ext in (".png", ".gif", ".jpg", ".jpeg", ".svg"):
        return FT_IMAGE
    if ext in (".log",):
        return FT_LOG
    if ext == ".toml":
        return FT_TOML
    if ext == ".py":
        return FT_PYTHON

    # --- Content sniffing (more expensive) ---
    if _is_binary(path):
        if ext in (".pkl", ".pickle") or name == "trajectory.pkl":
            return FT_PICKLE
        if ext == ".npy":
            return FT_NUMPY
        return FT_UNKNOWN

    text = _sniff_text(path)
    if not text:
        return FT_UNKNOWN

    if _lammps_dump_re.search(text):
        return FT_LAMMPS_DUMP
    if _lammps_data_re.search(text):
        return FT_LAMMPS_DATA
    if _extxyz_re.search(text):
        return FT_EXTXYZ
    if ext == ".xyz" or _xyz_re.search(text):
        return FT_XYZ
    if _tdb_re.search(text):
        return FT_TDB
    if _cif_re.search(text):
        return FT_CIF
    if _poscar_re.search(text):
        return FT_POSCAR

    return FT_UNKNOWN


def describe(ft: str) -> dict[str, str]:
    """Return display metadata for a file type constant.

    Args:
        ft (str): One of the ``FT_*`` constants.

    Returns:
        Dict with ``label``, ``icon``, ``desc`` keys.
    """
    return dict(_ft_meta.get(ft, _ft_meta[FT_UNKNOWN]))


def is_structure(ft: str) -> bool:
    """Return True if the type represents an atomic structure.

    Args:
        ft (str): File type constant.

    Returns:
        bool
    """
    return ft in {FT_POSCAR, FT_CIF, FT_XYZ, FT_EXTXYZ, FT_LAMMPS_DATA, FT_BESTSQS}


def is_trajectory(ft: str) -> bool:
    """Return True if the type represents a multi-frame trajectory.

    Args:
        ft (str): File type constant.

    Returns:
        bool
    """
    return ft in {FT_TRAJECTORY_PKL, FT_TRAJECTORY_XYZ, FT_LAMMPS_DUMP, FT_EXTXYZ}


def is_thermodynamic_db(ft: str) -> bool:
    """Return True if the type is a thermodynamic database.

    Args:
        ft (str): File type constant.

    Returns:
        bool
    """
    return ft == FT_TDB


def probe(path: Path) -> dict[str, Any]:
    """Detect file type and extract lightweight metadata without full parsing.

    Args:
        path (Path): File to probe.

    Returns:
        Dict with ``ft``, ``label``, ``icon``, ``desc``, and optionally
        ``n_atoms`` (for structure files) or ``n_frames`` (for trajectories).
    """
    ft = detect(path)
    result: dict[str, Any] = {"ft": ft, **describe(ft)}

    if ft == FT_ENERGY:
        try:
            result["value_eV"] = float(path.read_text().strip().split()[0])
        except (OSError, ValueError, IndexError):
            pass

    elif ft in {FT_POSCAR, FT_XYZ, FT_EXTXYZ}:
        try:
            first = path.read_text(errors="ignore").splitlines()[0]
            if ft == FT_POSCAR:
                result["title"] = first.strip()
            else:
                result["n_atoms"] = int(first.strip())
        except (OSError, ValueError, IndexError):
            pass

    elif ft == FT_TRAJECTORY_XYZ:
        try:
            text = path.read_text(errors="ignore")
            result["n_frames"] = text.count("\n") // max(
                1, int(text.splitlines()[0].strip()) + 2
            ) if text else 0
        except (OSError, ValueError):
            pass

    return result
