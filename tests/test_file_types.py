"""Tests for phaseforge_studio.core.file_types.

Covers detect(), probe(), and the predicate helpers (is_structure, etc.)
using only in-memory temporary files — no HPC filesystem, no heavy deps.
"""

from __future__ import annotations

import shutil
import tempfile
import textwrap
from pathlib import Path
from unittest import TestCase

import pytest

from phaseforge_studio.core.file_types import (
    FT_CIF,
    FT_CSV,
    FT_ENERGY,
    FT_EXTXYZ,
    FT_IMAGE,
    FT_JSON,
    FT_LOG,
    FT_NUMPY,
    FT_PICKLE,
    FT_POSCAR,
    FT_PYTHON,
    FT_TDB,
    FT_TOML,
    FT_UNKNOWN,
    FT_XYZ,
    FT_YAML,
    describe,
    detect,
    is_structure,
    is_thermodynamic_db,
    is_trajectory,
    probe,
)

_POSCAR_TEXT = textwrap.dedent("""\
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

_XYZ_TEXT = textwrap.dedent("""\
    3
    AlFCC
    Al  0.000  0.000  0.000
    Al  2.025  2.025  0.000
    Al  2.025  0.000  2.025
""")

_EXTXYZ_TEXT = textwrap.dedent("""\
    3
    Lattice="4.05 0 0  0 4.05 0  0 0 4.05" Properties=species:S:1:pos:R:3 energy=-9.0
    Al  0.000  0.000  0.000
    Al  2.025  2.025  0.000
    Al  2.025  0.000  2.025
""")

_CIF_TEXT = textwrap.dedent("""\
    data_AlFCC
    _cell_length_a 4.050
    _symmetry_space_group_name_H-M 'F m -3 m'
    loop_
    _atom_site_label
    _atom_site_type_symbol
    Al1 Al
""")

_TDB_TEXT = textwrap.dedent("""\
    $ TDB file for Al-Fe system
    ELEMENT Al FCC_A1 26.982 4.5767E+03 2.8322E+01 !
    ELEMENT Fe BCC_A2 55.845 4.4890E+03 2.7280E+01 !
    PHASE LIQUID % 1 1 !
""")


class _TmpDir(TestCase):
    """Base class providing self.tmp as a temporary directory Path."""

    def setUp(self) -> None:
        """Create a temporary directory for the test."""
        self._td = tempfile.mkdtemp()
        self.tmp = Path(self._td)

    def tearDown(self) -> None:
        """Remove the temporary directory after the test."""
        shutil.rmtree(self._td, ignore_errors=True)


# ---------------------------------------------------------------------------
# detect(): extension shortcuts
# ---------------------------------------------------------------------------


class TestDetectByExtension(_TmpDir):
    """detect() uses extension hints before content sniffing where unambiguous."""

    def test_py_extension_returns_python(self) -> None:
        """A .py file is FT_PYTHON regardless of content."""
        p = self.tmp / "run.py"
        p.write_text("print('hello')")
        assert detect(p) == FT_PYTHON

    def test_npy_extension_returns_numpy(self) -> None:
        """A .npy file is FT_NUMPY without content inspection."""
        p = self.tmp / "data.npy"
        p.write_bytes(b"\x93NUMPY\x01\x00")
        assert detect(p) == FT_NUMPY

    def test_pkl_extension_returns_pickle(self) -> None:
        """A .pkl file maps to FT_PICKLE."""
        p = self.tmp / "traj.pkl"
        p.write_bytes(b"\x80\x05")
        assert detect(p) == FT_PICKLE

    def test_png_extension_returns_image(self) -> None:
        """A .png file is FT_IMAGE."""
        p = self.tmp / "plot.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        assert detect(p) == FT_IMAGE

    def test_toml_extension_returns_toml(self) -> None:
        """A .toml file is FT_TOML."""
        p = self.tmp / "config.toml"
        p.write_text("[section]\nkey = 'val'")
        assert detect(p) == FT_TOML

    def test_yaml_extension_returns_yaml(self) -> None:
        """A .yml file is FT_YAML."""
        p = self.tmp / "config.yml"
        p.write_text("key: val\n")
        assert detect(p) == FT_YAML

    def test_log_extension_returns_log(self) -> None:
        """A .log file is FT_LOG."""
        p = self.tmp / "run.log"
        p.write_text("INFO: started\n")
        assert detect(p) == FT_LOG

    def test_tdb_extension_returns_tdb(self) -> None:
        """A .tdb file is FT_TDB."""
        p = self.tmp / "al_fe.tdb"
        p.write_text(_TDB_TEXT)
        assert detect(p) == FT_TDB

    def test_csv_extension_returns_csv(self) -> None:
        """A .csv file is FT_CSV."""
        p = self.tmp / "data.csv"
        p.write_text("a,b,c\n1,2,3\n")
        assert detect(p) == FT_CSV

    def test_json_extension_returns_json(self) -> None:
        """A .json file is FT_JSON."""
        p = self.tmp / "meta.json"
        p.write_text('{"key": 1}')
        assert detect(p) == FT_JSON


# ---------------------------------------------------------------------------
# detect(): content sniffing for structure files
# ---------------------------------------------------------------------------


class TestDetectByContent(_TmpDir):
    """detect() falls back to content sniffing for ambiguous/no extension."""

    def test_poscar_content_sniffed(self) -> None:
        """POSCAR content is recognised regardless of filename."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        assert detect(p) == FT_POSCAR

    def test_contcar_content_sniffed(self) -> None:
        """CONTCAR is recognised as FT_POSCAR by content."""
        p = self.tmp / "CONTCAR"
        p.write_text(_POSCAR_TEXT)
        assert detect(p) == FT_POSCAR

    def test_xyz_content_sniffed(self) -> None:
        """Plain XYZ is detected without extension."""
        p = self.tmp / "struct"
        p.write_text(_XYZ_TEXT)
        assert detect(p) == FT_XYZ

    def test_extxyz_properties_line_detected(self) -> None:
        """Extended XYZ (Lattice= … Properties=) is detected as FT_EXTXYZ."""
        p = self.tmp / "struct.xyz"
        p.write_text(_EXTXYZ_TEXT)
        assert detect(p) == FT_EXTXYZ

    def test_cif_content_sniffed(self) -> None:
        """CIF header 'data_' is sniffed without relying on extension."""
        p = self.tmp / "crystal"
        p.write_text(_CIF_TEXT)
        assert detect(p) == FT_CIF

    def test_nonexistent_path_returns_unknown(self) -> None:
        """A path that does not exist returns FT_UNKNOWN."""
        p = self.tmp / "ghost.xyz"
        assert detect(p) == FT_UNKNOWN

    def test_empty_file_no_extension_returns_unknown(self) -> None:
        """An empty file with no recognisable extension is FT_UNKNOWN."""
        p = self.tmp / "empty"
        p.write_text("")
        assert detect(p) == FT_UNKNOWN


# ---------------------------------------------------------------------------
# Predicate helpers
# ---------------------------------------------------------------------------


class TestPredicates(TestCase):
    """is_structure, is_trajectory, is_thermodynamic_db return correct booleans."""

    def test_poscar_is_structure(self) -> None:
        """FT_POSCAR is recognised as a structure type."""
        assert is_structure(FT_POSCAR)

    def test_cif_is_structure(self) -> None:
        """FT_CIF is recognised as a structure type."""
        assert is_structure(FT_CIF)

    def test_tdb_is_not_structure(self) -> None:
        """FT_TDB is not a structure type."""
        assert not is_structure(FT_TDB)

    def test_tdb_is_thermodynamic_db(self) -> None:
        """FT_TDB is recognised as a thermodynamic database."""
        assert is_thermodynamic_db(FT_TDB)

    def test_poscar_is_not_thermodynamic_db(self) -> None:
        """FT_POSCAR is not a thermodynamic database."""
        assert not is_thermodynamic_db(FT_POSCAR)

    def test_energy_is_not_trajectory(self) -> None:
        """FT_ENERGY is not classified as a trajectory."""
        assert not is_trajectory(FT_ENERGY)

    def test_unknown_is_not_structure(self) -> None:
        """FT_UNKNOWN is not classified as a structure."""
        assert not is_structure(FT_UNKNOWN)


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------


class TestDescribe(TestCase):
    """describe() returns expected metadata dicts."""

    def test_poscar_has_label_and_icon(self) -> None:
        """POSCAR description has non-empty label and icon."""
        d = describe(FT_POSCAR)
        assert d["label"]
        assert d["icon"]

    def test_tdb_has_label(self) -> None:
        """TDB description has a label."""
        assert describe(FT_TDB)["label"]

    def test_unknown_returns_dict(self) -> None:
        """describe() on FT_UNKNOWN returns a dict, not an error."""
        d = describe(FT_UNKNOWN)
        assert isinstance(d, dict)


# ---------------------------------------------------------------------------
# probe()
# ---------------------------------------------------------------------------


class TestProbe(_TmpDir):
    """probe() returns a metadata dict for a file."""

    def test_probe_poscar_includes_ft(self) -> None:
        """probe() on a POSCAR includes 'ft' key equal to FT_POSCAR."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        result = probe(p)
        assert result["ft"] == FT_POSCAR

    def test_probe_includes_label(self) -> None:
        """probe() includes a 'label' key from the file type metadata."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        result = probe(p)
        assert result.get("label")

    def test_probe_nonexistent_returns_unknown(self) -> None:
        """probe() on a missing path returns a dict with FT_UNKNOWN."""
        p = self.tmp / "nope"
        result = probe(p)
        assert result["ft"] == FT_UNKNOWN
