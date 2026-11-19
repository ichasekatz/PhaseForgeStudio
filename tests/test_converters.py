"""Tests for phaseforge_studio.core.converters.

Runs with and without ASE installed.  ASE-dependent tests are marked
``integration`` and skipped automatically when ASE is unavailable.
Pure-logic tests (reject_thermodynamic_coercion, error classes) always run.
"""

from __future__ import annotations

import shutil
import tempfile
import textwrap
from pathlib import Path
from unittest import TestCase

import pytest

from phaseforge_studio.core.converters import ConversionError, reject_thermodynamic_coercion
from phaseforge_studio.core.file_types import FT_POSCAR, FT_TDB

try:
    import ase  # noqa: F401

    _ase_available = True
except ImportError:
    _ase_available = False

_skip_no_ase = pytest.mark.skipif(not _ase_available, reason="ASE not installed")

_POSCAR_FCC_AL = textwrap.dedent("""\
    Al FCC
    1.0
    4.05  0.0   0.0
    0.0   4.05  0.0
    0.0   0.0   4.05
    Al
    4
    Direct
    0.0  0.0  0.0
    0.5  0.5  0.0
    0.5  0.0  0.5
    0.0  0.5  0.5
""")


class _TmpDir(TestCase):
    """Base class providing self.tmp as a temporary directory Path."""

    def setUp(self) -> None:
        """Create a temporary directory."""
        self._td = tempfile.mkdtemp()
        self.tmp = Path(self._td)

    def tearDown(self) -> None:
        """Remove the temporary directory."""
        shutil.rmtree(self._td, ignore_errors=True)


class TestRejectThermodynamicCoercion(TestCase):
    """reject_thermodynamic_coercion raises on scientifically invalid transfers."""

    def test_tdb_to_structure_input_raises(self) -> None:
        """Converting a TDB for use as structure input raises ConversionError."""
        with pytest.raises(ConversionError):
            reject_thermodynamic_coercion("tdb", "structure_input")

    def test_csv_to_tdb_fitting_raises(self) -> None:
        """Using tabular CSV data as TDB fitting input raises ConversionError."""
        with pytest.raises(ConversionError):
            reject_thermodynamic_coercion("csv", "tdb_fitting")

    def test_poscar_to_structure_is_fine(self) -> None:
        """A POSCAR used as structure input does not raise."""
        reject_thermodynamic_coercion(FT_POSCAR, "structure")

    def test_tdb_to_thermodynamic_is_fine(self) -> None:
        """A TDB used as thermodynamic data does not raise."""
        reject_thermodynamic_coercion(FT_TDB, "thermodynamic_db")

    def test_energy_to_tdb_fitting_raises(self) -> None:
        """Using raw energy values as TDB fitting input raises ConversionError."""
        with pytest.raises(ConversionError):
            reject_thermodynamic_coercion("energy", "tdb_fitting")


class TestConversionError(TestCase):
    """ConversionError is a subclass of ValueError."""

    def test_is_value_error(self) -> None:
        """ConversionError can be caught as ValueError."""
        with pytest.raises(ValueError):
            raise ConversionError("bad conversion")

    def test_message_is_preserved(self) -> None:
        """ConversionError preserves the message string."""
        try:
            raise ConversionError("test message")
        except ConversionError as e:
            assert "test message" in str(e)


@_skip_no_ase
class TestPoscarToXyz(TestCase):
    """poscar_to_xyz() produces valid XYZ output from a POSCAR string."""

    def test_xyz_starts_with_atom_count(self) -> None:
        """XYZ output's first line is the integer atom count."""
        from phaseforge_studio.core.converters import poscar_to_xyz

        xyz = poscar_to_xyz(_POSCAR_FCC_AL)
        first_line = xyz.strip().splitlines()[0].strip()
        assert first_line.isdigit()
        assert int(first_line) == 4

    def test_xyz_has_correct_line_count(self) -> None:
        """XYZ output has exactly atom_count + 2 lines (count + comment + atoms)."""
        from phaseforge_studio.core.converters import poscar_to_xyz

        xyz = poscar_to_xyz(_POSCAR_FCC_AL)
        lines = [line for line in xyz.strip().splitlines() if line.strip()]
        # 1 count line + 1 comment line + 4 atom lines
        assert len(lines) == 6

    def test_xyz_contains_al_symbol(self) -> None:
        """XYZ output contains the element symbol Al."""
        from phaseforge_studio.core.converters import poscar_to_xyz

        xyz = poscar_to_xyz(_POSCAR_FCC_AL)
        assert "Al" in xyz


@_skip_no_ase
class TestAtomsToDict(TestCase):
    """atoms_to_dict() returns a dict with n_atoms and species."""

    def test_n_atoms_correct(self) -> None:
        """n_atoms matches the atom count in the POSCAR."""
        from phaseforge_studio.core.converters import atoms_to_dict

        d = atoms_to_dict(_POSCAR_FCC_AL)
        assert d["n_atoms"] == 4

    def test_species_contains_al(self) -> None:
        """species list contains 'Al'."""
        from phaseforge_studio.core.converters import atoms_to_dict

        d = atoms_to_dict(_POSCAR_FCC_AL)
        assert "Al" in d["species"]

    def test_lattice_has_three_rows(self) -> None:
        """lattice is a 3×3 matrix (list of 3 lists)."""
        from phaseforge_studio.core.converters import atoms_to_dict

        d = atoms_to_dict(_POSCAR_FCC_AL)
        assert len(d["lattice"]) == 3
        assert all(len(row) == 3 for row in d["lattice"])

    def test_formula_in_result(self) -> None:
        """formula key is present and non-empty."""
        from phaseforge_studio.core.converters import atoms_to_dict

        d = atoms_to_dict(_POSCAR_FCC_AL)
        assert d.get("formula")


@_skip_no_ase
class TestConvertFile(_TmpDir):
    """convert_file() dispatches to the right converter."""

    def test_poscar_to_xyz_produces_string(self) -> None:
        """convert_file(poscar, 'xyz') returns a non-empty XYZ string."""
        from phaseforge_studio.core.converters import convert_file

        src = self.tmp / "POSCAR"
        src.write_text(_POSCAR_FCC_AL)
        result = convert_file(src, "xyz")
        assert isinstance(result, str)
        assert "Al" in result

    def test_unsupported_format_raises(self) -> None:
        """convert_file() raises ConversionError for an unsupported target format."""
        from phaseforge_studio.core.converters import convert_file

        src = self.tmp / "POSCAR"
        src.write_text(_POSCAR_FCC_AL)
        with pytest.raises(ConversionError):
            convert_file(src, "unsupported_format_xyz_123")

    def test_non_structure_file_raises(self) -> None:
        """convert_file() raises ConversionError when the source is not a structure."""
        from phaseforge_studio.core.converters import convert_file

        src = self.tmp / "data.csv"
        src.write_text("a,b\n1,2\n")
        with pytest.raises(ConversionError):
            convert_file(src, "xyz")
