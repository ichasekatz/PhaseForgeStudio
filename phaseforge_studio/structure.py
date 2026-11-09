"""Structure conversion utilities: ATAT, VASP POSCAR/CONTCAR, XYZ/extxyz."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

_alpha_elems: list[str] = [
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
"""Ordered list of elements used for ATAT alloy-notation fallback resolution."""


def _atoms_to_xyz(atoms: Any) -> str:
    """Convert an ASE Atoms object to an extxyz string.

    Args:
        atoms: ASE Atoms object with optional info/arrays set.

    Returns:
        extxyz-formatted string.
    """
    import io as _io

    from ase.io import write as _ase_write

    buf = _io.StringIO()
    _ase_write(buf, atoms, format="extxyz")
    return buf.getvalue()


def _poscar_to_xyz(text: str) -> str | None:
    """Convert POSCAR/CONTCAR text to extxyz string via ASE.

    Args:
        text (str): Raw POSCAR/CONTCAR file contents.

    Returns:
        extxyz string, or None if parsing fails.
    """
    try:
        import io as _io

        from ase.io import read as _ase_read

        atoms = _ase_read(_io.StringIO(text), format="vasp")
        return _atoms_to_xyz(atoms)
    except Exception:
        return None


def _positions_to_poscar(
    symbols: list[str],
    positions: Any,
    cell: Any,
    energy: float = 0.0,
) -> str:
    """Build a VASP POSCAR string from positions, cell, and symbols.

    Args:
        symbols (list[str]): Per-atom element symbols.
        positions: Array-like of Cartesian coordinates, shape (N, 3), in Å.
        cell: Array-like of lattice vectors, shape (3, 3), in Å.
        energy (float): Total energy in eV, written into the title line.

    Returns:
        POSCAR-formatted string.
    """
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


def _build_elem_map(rndstr_path: Path) -> dict[str, str]:
    """Parse rndstr.in and return a map from ATAT component label to element symbol.

    Args:
        rndstr_path (Path): Path to the rndstr.in file.

    Returns:
        Dict mapping ATAT labels (e.g. ``"a_A"``) to element symbols (e.g. ``"Al"``).
        Empty dict if file is missing or unparseable.
    """
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
    """Resolve an ATAT alloy-notation token to a real element symbol.

    Args:
        raw (str): ATAT token, e.g. ``"a_A"`` or ``"Al"``.
        elem_map (dict[str, str]): Map from ATAT label to element symbol.
        used (set[str]): Elements already assigned (to avoid duplicates).

    Returns:
        Element symbol string.
    """
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
    """Convert ATAT bestsqs.out text to XYZ format.

    Args:
        text (str): Raw bestsqs.out file contents.
        elem_map (dict[str, str] | None): Optional ATAT label → element map
            from :func:`_build_elem_map`.

    Returns:
        XYZ-formatted string, or None if parsing fails.
    """
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
    """Convert a VASP CONTCAR/POSCAR to XYZ format without ASE.

    Args:
        text (str): Raw CONTCAR/POSCAR file contents.

    Returns:
        XYZ-formatted string, or None if parsing fails.
    """
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
