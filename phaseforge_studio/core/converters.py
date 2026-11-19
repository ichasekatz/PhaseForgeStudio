"""Structure and data format converters.

All conversions preserve units, lattice vectors, coordinate conventions,
atomic species ordering, and provenance.  Conversions that are scientifically
invalid are refused with a ``ConversionError``.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any


class ConversionError(ValueError):
    """Raised when a requested conversion is impossible or scientifically invalid."""


# ---------------------------------------------------------------------------
# POSCAR ↔ XYZ helpers (ASE-based)
# ---------------------------------------------------------------------------


def _require_ase():
    """Import ase.io, raising ConversionError if not installed."""
    try:
        import ase.io  # noqa: F401
        return ase.io
    except ImportError as e:
        raise ConversionError("ASE is required for structure conversions (pip install ase)") from e


def poscar_to_xyz(poscar_text: str, comment: str = "") -> str:
    """Convert a POSCAR/CONTCAR string to XYZ format.

    Args:
        poscar_text (str): Raw POSCAR or CONTCAR file contents.
        comment (str): Optional comment line for the XYZ header.

    Returns:
        XYZ string.

    Raises:
        ConversionError: If ASE is unavailable or parsing fails.
    """
    ase_io = _require_ase()
    try:
        atoms = ase_io.read(io.StringIO(poscar_text), format="vasp")
        buf = io.StringIO()
        ase_io.write(buf, atoms, format="xyz", comment=comment or atoms.get_chemical_formula())
        return buf.getvalue()
    except Exception as exc:
        raise ConversionError(f"POSCAR → XYZ failed: {exc}") from exc


def poscar_to_extxyz(poscar_text: str) -> str:
    """Convert a POSCAR/CONTCAR string to extended XYZ format with lattice.

    Args:
        poscar_text (str): Raw POSCAR or CONTCAR file contents.

    Returns:
        Extended XYZ string with lattice vectors in Properties line.

    Raises:
        ConversionError: If ASE is unavailable or parsing fails.
    """
    ase_io = _require_ase()
    try:
        atoms = ase_io.read(io.StringIO(poscar_text), format="vasp")
        buf = io.StringIO()
        ase_io.write(buf, atoms, format="extxyz")
        return buf.getvalue()
    except Exception as exc:
        raise ConversionError(f"POSCAR → extXYZ failed: {exc}") from exc


def xyz_to_poscar(xyz_text: str) -> str:
    """Convert an XYZ string to POSCAR format.

    Args:
        xyz_text (str): XYZ file contents (plain or extended).

    Returns:
        POSCAR string.

    Raises:
        ConversionError: If ASE is unavailable or the XYZ lacks cell information.
    """
    ase_io = _require_ase()
    try:
        atoms = ase_io.read(io.StringIO(xyz_text), format="extxyz")
    except Exception:
        try:
            atoms = ase_io.read(io.StringIO(xyz_text), format="xyz")
        except Exception as exc:
            raise ConversionError(f"XYZ read failed: {exc}") from exc
    if not atoms.pbc.any():
        raise ConversionError(
            "XYZ has no periodic boundary conditions — cannot produce a valid POSCAR. "
            "Use extended XYZ with Lattice= header or CIF as the source format."
        )
    buf = io.StringIO()
    ase_io.write(buf, atoms, format="vasp")
    return buf.getvalue()


def cif_to_poscar(cif_text: str) -> str:
    """Convert a CIF string to POSCAR format.

    Args:
        cif_text (str): CIF file contents.

    Returns:
        POSCAR string.

    Raises:
        ConversionError: If ASE is unavailable or parsing fails.
    """
    ase_io = _require_ase()
    try:
        atoms = ase_io.read(io.StringIO(cif_text), format="cif")
        buf = io.StringIO()
        ase_io.write(buf, atoms, format="vasp")
        return buf.getvalue()
    except Exception as exc:
        raise ConversionError(f"CIF → POSCAR failed: {exc}") from exc


def cif_to_xyz(cif_text: str) -> str:
    """Convert a CIF string to XYZ format.

    Args:
        cif_text (str): CIF file contents.

    Returns:
        XYZ string.

    Raises:
        ConversionError: If ASE is unavailable or parsing fails.
    """
    ase_io = _require_ase()
    try:
        atoms = ase_io.read(io.StringIO(cif_text), format="cif")
        buf = io.StringIO()
        ase_io.write(buf, atoms, format="xyz")
        return buf.getvalue()
    except Exception as exc:
        raise ConversionError(f"CIF → XYZ failed: {exc}") from exc


def lammps_data_to_poscar(lammps_text: str) -> str:
    """Convert a LAMMPS data file string to POSCAR format.

    Args:
        lammps_text (str): LAMMPS data file contents.

    Returns:
        POSCAR string.

    Raises:
        ConversionError: If ASE is unavailable or parsing fails.
    """
    ase_io = _require_ase()
    try:
        atoms = ase_io.read(io.StringIO(lammps_text), format="lammps-data")
        buf = io.StringIO()
        ase_io.write(buf, atoms, format="vasp")
        return buf.getvalue()
    except Exception as exc:
        raise ConversionError(f"LAMMPS data → POSCAR failed: {exc}") from exc


# ---------------------------------------------------------------------------
# File-path based dispatch
# ---------------------------------------------------------------------------

_structure_readers: dict[str, str] = {
    "poscar": "vasp",
    "cif": "cif",
    "xyz": "xyz",
    "extxyz": "extxyz",
    "lammps_data": "lammps-data",
    "bestsqs": "vasp",  # bestsqs.out is ATAT format — handled separately
}


def convert_file(source: Path, target_format: str) -> str:
    """Convert a structure file to the requested format using ASE.

    Args:
        source (Path): Path to the source structure file.
        target_format (str): One of ``"xyz"``, ``"extxyz"``, ``"poscar"``, ``"cif"``.

    Returns:
        Converted file contents as a string.

    Raises:
        ConversionError: If the conversion is unsupported or fails.
    """
    from phaseforge_studio.core.file_types import detect, is_structure

    ft = detect(source)
    if not is_structure(ft):
        raise ConversionError(f"{source.name} (type={ft!r}) is not a structure file.")

    text = source.read_text(errors="ignore")

    if target_format in ("xyz", "extxyz"):
        return poscar_to_extxyz(text) if target_format == "extxyz" else poscar_to_xyz(text)
    if target_format == "poscar":
        if ft == "cif":
            return cif_to_poscar(text)
        if ft in ("xyz", "extxyz"):
            return xyz_to_poscar(text)
        if ft == "lammps_data":
            return lammps_data_to_poscar(text)
        return text  # already POSCAR-like

    raise ConversionError(f"Target format {target_format!r} not supported (use 'xyz', 'extxyz', 'poscar').")


# ---------------------------------------------------------------------------
# Thermodynamic data — no silent conversion
# ---------------------------------------------------------------------------


def reject_thermodynamic_coercion(source_ft: str, target_use: str) -> None:
    """Raise ConversionError if a thermodynamic coercion would change data meaning.

    Scientific rule: a TDB is not a structure file; stability CSV is not a
    fitting input; computed energies are not experimental measurements.

    Args:
        source_ft (str): File type of the source artifact.
        target_use (str): Intended use description.

    Raises:
        ConversionError: Always, when the coercion is invalid.
    """
    _invalid_pairs: list[tuple[str, str]] = [
        ("csv", "tdb_fitting"),
        ("json", "tdb_fitting"),
        ("tdb", "structure_input"),
        ("energy", "tdb_fitting"),
    ]
    for bad_ft, bad_use in _invalid_pairs:
        if source_ft == bad_ft and target_use == bad_use:
            raise ConversionError(
                f"Cannot use a {source_ft!r} file as {target_use!r} input — "
                "this conversion would silently change the scientific meaning of the data."
            )


# ---------------------------------------------------------------------------
# Supercell convenience wrapper
# ---------------------------------------------------------------------------


def make_supercell(poscar_text: str, matrix: list[list[int]]) -> str:
    """Create a supercell from a POSCAR string.

    Args:
        poscar_text (str): POSCAR/CONTCAR file contents.
        matrix (list[list[int]]): 3×3 supercell matrix.

    Returns:
        POSCAR string for the supercell.

    Raises:
        ConversionError: If ASE is unavailable or the matrix is invalid.
    """
    import numpy as np

    ase_io = _require_ase()
    try:
        from ase.build import make_supercell as ase_supercell

        atoms = ase_io.read(io.StringIO(poscar_text), format="vasp")
        sc = ase_supercell(atoms, np.array(matrix))
        buf = io.StringIO()
        ase_io.write(buf, sc, format="vasp")
        return buf.getvalue()
    except Exception as exc:
        raise ConversionError(f"Supercell creation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# ASE atoms → dict (for JSON serialization)
# ---------------------------------------------------------------------------


def atoms_to_dict(poscar_text: str) -> dict[str, Any]:
    """Parse a POSCAR and return a plain dict for JSON serialization.

    Args:
        poscar_text (str): POSCAR/CONTCAR contents.

    Returns:
        Dict with ``species``, ``positions``, ``lattice``, ``n_atoms``.

    Raises:
        ConversionError: If ASE is unavailable or parsing fails.
    """
    ase_io = _require_ase()
    try:
        atoms = ase_io.read(io.StringIO(poscar_text), format="vasp")
        return {
            "species": atoms.get_chemical_symbols(),
            "positions": atoms.get_positions().tolist(),
            "lattice": atoms.get_cell().tolist(),
            "n_atoms": len(atoms),
            "formula": atoms.get_chemical_formula(),
            "pbc": atoms.get_pbc().tolist(),
        }
    except Exception as exc:
        raise ConversionError(f"POSCAR parse failed: {exc}") from exc
