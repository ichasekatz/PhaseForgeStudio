"""Tests for phaseforge_studio.core.artifact_registry.

Checks that actions_for_file and frameworks_for_file return the right
entries for each file type, without touching the filesystem beyond
temporary stub files.
"""

from __future__ import annotations

import shutil
import tempfile
import textwrap
from pathlib import Path
from unittest import TestCase

import pytest

from phaseforge_studio.core.artifact_registry import (
    Artifact,
    ArtifactAction,
    actions_for_file,
    frameworks_for_file,
)
from phaseforge_studio.core.file_types import (
    FT_CSV,
    FT_IMAGE,
    FT_POSCAR,
    FT_TDB,
    FT_UNKNOWN,
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

_TDB_TEXT = textwrap.dedent("""\
    $ TDB
    ELEMENT Al FCC_A1 26.982 4.5767E+03 2.8322E+01 !
    PHASE LIQUID % 1 1 !
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


class TestActionsForFile(_TmpDir):
    """actions_for_file returns correct entries for known file types."""

    def test_poscar_has_view_structure_action(self) -> None:
        """A POSCAR file includes the 'view_structure' action."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        ids = {a["action_id"] for a in actions_for_file(p)}
        assert "view_structure" in ids

    def test_poscar_has_paipai_action(self) -> None:
        """A POSCAR file includes the 'paipai_set_input' action."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        ids = {a["action_id"] for a in actions_for_file(p)}
        assert "paipai_set_input" in ids

    def test_tdb_has_blade_open_action(self) -> None:
        """A TDB file includes the 'blade_open_tdb' action."""
        p = self.tmp / "al.tdb"
        p.write_text(_TDB_TEXT)
        ids = {a["action_id"] for a in actions_for_file(p)}
        assert "blade_open_tdb" in ids

    def test_tdb_has_pf_open_action(self) -> None:
        """A TDB file includes the 'pf_open_tdb' action."""
        p = self.tmp / "al.tdb"
        p.write_text(_TDB_TEXT)
        ids = {a["action_id"] for a in actions_for_file(p)}
        assert "pf_open_tdb" in ids

    def test_csv_has_plot_action(self) -> None:
        """A CSV file includes the 'plot_csv' action."""
        p = self.tmp / "data.csv"
        p.write_text("a,b\n1,2\n")
        ids = {a["action_id"] for a in actions_for_file(p)}
        assert "plot_csv" in ids

    def test_unknown_type_returns_empty(self) -> None:
        """A file of unknown type returns an empty action list."""
        p = self.tmp / "mystery"
        p.write_bytes(b"\x00\x01\x02")
        result = actions_for_file(p, FT_UNKNOWN)
        assert result == []

    def test_precomputed_ft_skips_detect(self) -> None:
        """Passing ft= directly bypasses filesystem detect."""
        p = self.tmp / "doesnotmatter.xyz"
        result = actions_for_file(p, FT_POSCAR)
        ids = {a["action_id"] for a in result}
        assert "view_structure" in ids

    def test_actions_sorted_by_framework_then_label(self) -> None:
        """actions_for_file returns entries sorted by framework then label."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        actions = actions_for_file(p)
        pairs = [(a["framework"], a["label"]) for a in actions]
        assert pairs == sorted(pairs)

    def test_action_dict_has_required_keys(self) -> None:
        """Every returned action dict has the expected keys."""
        p = self.tmp / "al.tdb"
        p.write_text(_TDB_TEXT)
        for act in actions_for_file(p):
            assert {"action_id", "label", "framework", "description"} <= act.keys()

    def test_image_has_view_image_action(self) -> None:
        """An image file includes the 'view_image' action."""
        p = self.tmp / "plot.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        ids = {a["action_id"] for a in actions_for_file(p, FT_IMAGE)}
        assert "view_image" in ids


class TestFrameworksForFile(_TmpDir):
    """frameworks_for_file returns the unique sorted set of target frameworks."""

    def test_poscar_includes_mf_paipai_pf(self) -> None:
        """A POSCAR file is usable by mf, paipai, and pf frameworks."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        fws = frameworks_for_file(p)
        assert "mf" in fws
        assert "paipai" in fws
        assert "pf" in fws

    def test_tdb_includes_blade_and_pf(self) -> None:
        """A TDB file is usable by blade, orchid, and pf frameworks."""
        p = self.tmp / "al.tdb"
        p.write_text(_TDB_TEXT)
        fws = frameworks_for_file(p)
        assert "blade" in fws
        assert "pf" in fws

    def test_frameworks_are_sorted(self) -> None:
        """frameworks_for_file returns a sorted list."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        fws = frameworks_for_file(p)
        assert fws == sorted(fws)

    def test_unknown_returns_empty_list(self) -> None:
        """An unknown file type maps to no frameworks."""
        p = self.tmp / "data.bin"
        p.write_bytes(b"\xff\xfe")
        assert frameworks_for_file(p, FT_UNKNOWN) == []


class TestArtifactDataclass(_TmpDir):
    """Artifact dataclass behaves correctly."""

    def test_label_defaults_to_filename(self) -> None:
        """Artifact.label defaults to the path basename when not provided."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        art = Artifact(path=p, ft=FT_POSCAR)
        assert art.label == "POSCAR"

    def test_explicit_label_is_kept(self) -> None:
        """An explicit label is not overwritten by __post_init__."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        art = Artifact(path=p, ft=FT_POSCAR, label="my structure")
        assert art.label == "my structure"

    def test_as_dict_has_path_and_ft(self) -> None:
        """Artifact.as_dict() contains 'path' and 'ft' keys."""
        p = self.tmp / "POSCAR"
        p.write_text(_POSCAR_TEXT)
        d = Artifact(path=p, ft=FT_POSCAR).as_dict()
        assert "path" in d and "ft" in d

    def test_artifact_action_is_frozen(self) -> None:
        """ArtifactAction is immutable after creation."""
        act = ArtifactAction(
            action_id="test",
            label="Test",
            framework="mf",
            input_types=frozenset({FT_POSCAR}),
        )
        with pytest.raises((AttributeError, TypeError)):
            act.label = "changed"  # type: ignore[misc]
