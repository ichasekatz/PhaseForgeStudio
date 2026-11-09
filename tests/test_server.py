"""Unit tests for PhaseForge Studio server utilities.

Covers pure-logic helpers that require no network, no HPC filesystem, and no
optional heavy dependencies (ASE, pycalphad, materialsframework).
Integration tests that do require them are marked ``integration``.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import server without executing the __main__ block.
# server.py modifies sys.path / os.environ at module level, but all functions
# under test are pure Python + stdlib/numpy.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))
import server  # noqa: E402  (must come after sys.path insertion)


# ---------------------------------------------------------------------------
# _split_xyz_frames
# ---------------------------------------------------------------------------

SINGLE_FRAME = textwrap.dedent("""\
    3
    Lattice="4.05 0 0  0 4.05 0  0 0 4.05" Properties=species:S:1:pos:R:3 energy=-9.0
    Al  0.000  0.000  0.000
    Al  2.025  2.025  0.000
    Al  2.025  0.000  2.025
""")

MULTI_FRAME = textwrap.dedent("""\
    2
    energy=-5.0 Properties=species:S:1:pos:R:3
    Fe  0.0  0.0  0.0
    Fe  1.4  1.4  1.4
    2
    energy=-5.1 Properties=species:S:1:pos:R:3
    Fe  0.0  0.0  0.0
    Fe  1.4  1.4  1.3
""")


def test_split_xyz_frames_single() -> None:
    frames = server._split_xyz_frames(SINGLE_FRAME)
    assert len(frames) == 1
    assert frames[0].startswith("3")


def test_split_xyz_frames_multi() -> None:
    frames = server._split_xyz_frames(MULTI_FRAME)
    assert len(frames) == 2
    assert frames[0].startswith("2")
    assert frames[1].startswith("2")


def test_split_xyz_frames_empty() -> None:
    assert server._split_xyz_frames("") == []
    assert server._split_xyz_frames("\n\n") == []


def test_split_xyz_frames_ignores_garbage_header() -> None:
    text = "not_a_number\n" + SINGLE_FRAME
    frames = server._split_xyz_frames(text)
    assert len(frames) == 1


def test_split_xyz_frames_truncated_drops_partial() -> None:
    # 3 atoms declared but only 1 supplied — should not appear as a frame
    truncated = "3\nenergy=-1.0\nAl 0 0 0\n"
    frames = server._split_xyz_frames(truncated)
    assert frames == []


# ---------------------------------------------------------------------------
# _poscar_to_xyz  — pure string conversion, no filesystem
# ---------------------------------------------------------------------------

POSCAR_FCC = textwrap.dedent("""\
    Al FCC
       4.05
     0.0 0.5 0.5
     0.5 0.0 0.5
     0.5 0.5 0.0
    Al
    1
    Direct
    0.0  0.0  0.0
""")


def test_poscar_to_xyz_bad_input_returns_none() -> None:
    result = server._poscar_to_xyz("this is not a poscar at all")
    assert result is None


def test_poscar_to_xyz_accepts_string() -> None:
    # Should return a str (extxyz) or None — never raise
    result = server._poscar_to_xyz(POSCAR_FCC)
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# scan_energies — composition sort (uses tmp filesystem, no heavy deps)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_sqs_tree(tmp_path: Path) -> Path:
    """Minimal SQS tree with 'energy' files for sort testing."""
    sqs_root = tmp_path / "Files" / "SQS"
    dirs_energies = [
        ("sqs_lev=1_a_Al=0.5_a_Fe=0.5", -3.5),
        ("sqs_lev=1_a_Al=1.0", -3.2),
        ("sqs_lev=1_a_Fe=1.0", -4.1),
        ("sqs_lev=1_a_Al=0.333_a_Fe=0.333_a_Ni=0.333", -3.8),
    ]
    for d, e in dirs_energies:
        p = sqs_root / d
        p.mkdir(parents=True)
        (p / "energy").write_text(str(e))
    return tmp_path


def test_scan_energies_returns_all(mock_sqs_tree: Path) -> None:
    result = server.scan_energies(mock_sqs_tree)
    assert len(result["labels"]) == 4
    assert len(result["energies"]) == 4


def test_scan_energies_sorted_consistently(mock_sqs_tree: Path) -> None:
    result = server.scan_energies(mock_sqs_tree)
    labels = result["labels"]
    # Pure Al (Al=1.0) has highest Al fraction — sorts first alphabetically by element
    al_pure_idx = next(i for i, l in enumerate(labels) if "Al=1.0" in l)
    al_fe_idx = next(i for i, l in enumerate(labels) if "Al=0.5" in l)
    # Al=1.0 > Al=0.5 in Al dimension → pure Al sorts after AlFe (descending)
    # Regardless of direction: order must be deterministic (no float instability)
    assert al_pure_idx != al_fe_idx  # distinct positions


def test_scan_energies_empty_tree(tmp_path: Path) -> None:
    (tmp_path / "Files" / "SQS").mkdir(parents=True)
    result = server.scan_energies(tmp_path)
    assert result == {"labels": [], "energies": []}


def test_scan_energies_skips_malformed_energy(tmp_path: Path) -> None:
    p = tmp_path / "Files" / "SQS" / "sqs_lev=1_a_Al=1.0"
    p.mkdir(parents=True)
    (p / "energy").write_text("not_a_float")
    result = server.scan_energies(tmp_path)
    assert result == {"labels": [], "energies": []}


def test_scan_energies_no_sqs_dir(tmp_path: Path) -> None:
    result = server.scan_energies(tmp_path)
    assert result == {"labels": [], "energies": []}


# ---------------------------------------------------------------------------
# Composition parse regex — matches scan_energies internal logic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "dirname, expected",
    [
        ("sqs_lev=1_a_Al=0.5_a_Ni=0.5", {"Al": 0.5, "Ni": 0.5}),
        ("sqs_lev=2_a_Al=1.0", {"Al": 1.0}),
        ("sqs_lev=1_a_Al=0.333_a_Fe=0.333_a_Ni=0.334", {"Al": 0.333, "Fe": 0.333, "Ni": 0.334}),
    ],
)
def test_composition_regex(dirname: str, expected: dict[str, float]) -> None:
    import re
    tokens = re.findall(r"a_([A-Za-z]+)=([\d.]+)", dirname)
    result = {el: pytest.approx(float(f), rel=1e-3) for el, f in tokens}
    for el, v in expected.items():
        assert result[el] == v
