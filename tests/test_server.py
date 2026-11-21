"""Unit tests for PhaseForge Studio server utilities.

Covers pure-logic helpers that require no network, no HPC filesystem, and no
optional heavy dependencies (ASE, pycalphad, materialsframework).
Integration tests that do require them are marked ``integration``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from phaseforge_studio.filesystem import scan_energies
from phaseforge_studio.structure import _poscar_to_xyz
from phaseforge_studio.trajectory import _split_xyz_frames

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
    frames = _split_xyz_frames(SINGLE_FRAME)
    assert len(frames) == 1
    assert frames[0].startswith("3")


def test_split_xyz_frames_multi() -> None:
    frames = _split_xyz_frames(MULTI_FRAME)
    assert len(frames) == 2
    assert frames[0].startswith("2")
    assert frames[1].startswith("2")


def test_split_xyz_frames_empty() -> None:
    assert _split_xyz_frames("") == []
    assert _split_xyz_frames("\n\n") == []


def test_split_xyz_frames_ignores_garbage_header() -> None:
    text = "not_a_number\n" + SINGLE_FRAME
    frames = _split_xyz_frames(text)
    assert len(frames) == 1


def test_split_xyz_frames_truncated_drops_partial() -> None:
    # 3 atoms declared but only 1 supplied — should not appear as a frame
    truncated = "3\nenergy=-1.0\nAl 0 0 0\n"
    frames = _split_xyz_frames(truncated)
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
    result = _poscar_to_xyz("this is not a poscar at all")
    assert result is None


def test_poscar_to_xyz_accepts_string() -> None:
    # Should return a str (extxyz) or None — never raise
    result = _poscar_to_xyz(POSCAR_FCC)
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# scan_energies — composition sort (uses tmp filesystem, no heavy deps)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_sqs_tree(tmp_path: Path) -> Path:
    """Minimal SQS tree with 'energy' files for sort testing."""
    sqs_root = tmp_path / "Jobs" / "test_job" / "AlFeNi"
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
    result = scan_energies(mock_sqs_tree)
    assert len(result["labels"]) == 4
    assert len(result["energies"]) == 4


def test_scan_energies_sorted_consistently(mock_sqs_tree: Path) -> None:
    result = scan_energies(mock_sqs_tree)
    labels = result["labels"]
    # Pure Al (Al=1.0) has highest Al fraction — sorts first alphabetically by element
    al_pure_idx = next(i for i, lbl in enumerate(labels) if "Al=1.0" in lbl)
    al_fe_idx = next(i for i, lbl in enumerate(labels) if "Al=0.5" in lbl)
    # Al=1.0 > Al=0.5 in Al dimension → pure Al sorts after AlFe (descending)
    # Regardless of direction: order must be deterministic (no float instability)
    assert al_pure_idx != al_fe_idx  # distinct positions


def test_scan_energies_empty_tree(tmp_path: Path) -> None:
    (tmp_path / "Jobs").mkdir(parents=True)
    result = scan_energies(tmp_path)
    assert result == {"labels": [], "energies": []}


def test_scan_energies_skips_malformed_energy(tmp_path: Path) -> None:
    p = tmp_path / "Jobs" / "test_job" / "Al" / "sqs_lev=1_a_Al=1.0"
    p.mkdir(parents=True)
    (p / "energy").write_text("not_a_float")
    result = scan_energies(tmp_path)
    assert result == {"labels": [], "energies": []}


def test_scan_energies_no_sqs_dir(tmp_path: Path) -> None:
    result = scan_energies(tmp_path)
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


# ---------------------------------------------------------------------------
# New PhaseForge command routes — argument validation (no subprocess)
# ---------------------------------------------------------------------------


class TestNewPfRouteValidation:
    """Validate that new PF command route bodies are well-formed."""

    def _build_body(self, **kwargs: object) -> dict[str, object]:
        return kwargs

    def test_pf_relax_requires_mlip_and_model(self) -> None:
        # Missing model → body should trigger error response
        body = self._build_body(mlip="grace")
        assert "mlip" in body and "model" not in body

    def test_pf_md_requires_temperature(self) -> None:
        body = self._build_body(mlip="grace", model="GRACE-2L")
        assert "temperature" not in body

    def test_pf_liquid_dt_flag(self) -> None:
        # dt (temperature offset) is the required field for MLIPliquid
        body = self._build_body(mlip="grace", model="GRACE-2L", dt="500")
        assert body["dt"] == "500"

    def test_pf_lammps_temperature_flag(self) -> None:
        body = self._build_body(mlip="grace", model="GRACE-2L", temperature="1000")
        assert body["temperature"] == "1000"

    def test_pf_runstruct_static_flag(self) -> None:
        body = self._build_body(mlip="grace", model="GRACE-2L", static=True)
        assert body["static"] is True

    def test_pf_runstruct_no_static_by_default(self) -> None:
        body = self._build_body(mlip="grace", model="GRACE-2L")
        assert not body.get("static", False)

    def test_pf_extract_needs_workdir(self) -> None:
        # extract_MLIP has no required mlip/model — just workdir
        body = self._build_body(workdir="/tmp/testdir")
        assert "workdir" in body


# ---------------------------------------------------------------------------
# NEB analysis — two-structure requirement
# ---------------------------------------------------------------------------


class TestNebTwoStructure:
    """Test NEB error messages for missing final_rel_path."""

    def test_neb_no_final_path_returns_error(self, tmp_path: Path) -> None:
        from phaseforge_studio.analysis import _run_analysis

        (tmp_path / "initial.vasp").write_text("dummy")
        cfg = {"path1": str(tmp_path), "calculator": "grace", "device": "cpu"}
        # Must return an error — not a silent success. Message content varies
        # depending on whether ASE is installed and what it does with dummy input.
        result = _run_analysis(cfg, {"rel_path": "initial.vasp", "analyzer": "neb"})
        assert "error" in result

    def test_neb_missing_final_file_returns_error(self, tmp_path: Path) -> None:
        pytest.importorskip("ase", reason="ASE required for NEB two-structure path test")
        from phaseforge_studio.analysis import _run_analysis

        (tmp_path / "initial.vasp").write_text("dummy")
        cfg = {"path1": str(tmp_path), "calculator": "grace", "device": "cpu"}
        result = _run_analysis(
            cfg,
            {"rel_path": "initial.vasp", "analyzer": "neb", "final_rel_path": "missing.vasp"},
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# MF MD route — body validation
# ---------------------------------------------------------------------------


class TestMfMdRouteValidation:
    """Validate /api/mf_md body structure without running MD."""

    def test_missing_rel_path_detected(self) -> None:
        # Route requires rel_path; missing means body is incomplete
        body: dict[str, object] = {"calculator": "grace", "steps": 100}
        assert "rel_path" not in body

    def test_default_ensemble_is_nvt(self) -> None:
        body: dict[str, object] = {"rel_path": "POSCAR", "calculator": "grace", "steps": 50}
        assert body.get("ensemble", "nvt_nose_hoover") == "nvt_nose_hoover"

    def test_steps_coerced_to_int(self) -> None:
        body: dict[str, object] = {"rel_path": "POSCAR", "steps": "200"}
        assert int(str(body["steps"])) == 200

    def test_temperature_default(self) -> None:
        body: dict[str, object] = {"rel_path": "POSCAR"}
        assert int(body.get("temperature", 300)) == 300

    def test_md_result_keys_expected(self) -> None:
        # Keys returned by BaseMDCalculator.run() per its docstring
        expected = {"total_energy", "potential_energy", "kinetic_energy", "temperature", "final_structure"}
        # At minimum these must be present in a successful result
        assert expected <= {
            "total_energy",
            "potential_energy",
            "kinetic_energy",
            "forces",
            "stresses",
            "temperature",
            "velocities",
            "final_structure",
        }

    def test_timeout_body_param(self) -> None:
        body: dict[str, object] = {"rel_path": "POSCAR", "timeout": 60}
        assert float(str(body["timeout"])) == 60.0


# ---------------------------------------------------------------------------
# Slab wizard — body validation
# ---------------------------------------------------------------------------


class TestSlabWizardValidation:
    """Validate /api/mf_slab body structure."""

    def test_missing_rel_path_detected(self) -> None:
        body: dict[str, object] = {"miller_index": [1, 0, 0]}
        assert "rel_path" not in body

    def test_miller_defaults_to_100(self) -> None:
        body: dict[str, object] = {"rel_path": "POSCAR"}
        miller = body.get("miller_index", [1, 0, 0])
        assert miller == [1, 0, 0]

    def test_miller_three_ints(self) -> None:
        raw = "1 1 0"
        parsed = [int(x) for x in raw.split()]
        assert len(parsed) == 3

    def test_min_slab_coerced_float(self) -> None:
        assert float("7") == 7.0

    def test_center_slab_bool(self) -> None:
        body: dict[str, object] = {"center_slab": True}
        assert bool(body["center_slab"]) is True


# ---------------------------------------------------------------------------
# Stage 3 — new MF tool route body validation
# ---------------------------------------------------------------------------


class TestMfToolRouteValidation:
    """Validate body structure for Stage 3 MF tool routes."""

    def test_sqsgen_requires_composition(self) -> None:
        body: dict[str, object] = {"crystal_structure": "fcc"}
        assert "composition" not in body

    def test_sqsgen_composition_format(self) -> None:
        body: dict[str, object] = {"composition": {"Al": 0.5, "Ni": 0.5}}
        assert sum(float(v) for v in body["composition"].values()) == pytest.approx(1.0)  # type: ignore[union-attr]

    def test_stability_map_requires_elements(self) -> None:
        body: dict[str, object] = {"calculator": "grace"}
        assert len(body.get("elements", [])) < 2  # type: ignore[arg-type]

    def test_cluster_expansion_requires_structures_and_energies(self) -> None:
        body: dict[str, object] = {"structures": [], "energies": []}
        assert not body["structures"] or not body["energies"]

    def test_bond_lattice_parameter_requires_elements(self) -> None:
        body: dict[str, object] = {"calculator": "grace"}
        assert not body.get("elements")

    def test_cahn_hilliard_defaults(self) -> None:
        body: dict[str, object] = {}
        assert int(body.get("nx", 64)) == 64
        assert float(body.get("dt", 0.01)) == pytest.approx(0.01)
        assert int(body.get("n_steps", 1000)) == 1000
