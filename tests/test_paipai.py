"""Tests for paipai adapter module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from phaseforge_studio.paipai import (
    PaipaiState,
    check_paipai_installed,
    get_paipai_progress,
    paipai_install_hint,
    scan_paipai_outputs,
    stop_paipai,
    write_struc_in,
    struc_in_from_poscar,
)


class TestCheckPaipaiInstalled:
    def test_returns_bool(self) -> None:
        result = check_paipai_installed()
        assert isinstance(result, bool)

    def test_true_when_on_path(self) -> None:
        with patch("phaseforge_studio.paipai.shutil.which", return_value="/usr/local/bin/paipai"):
            assert check_paipai_installed() is True

    def test_false_when_not_on_path(self) -> None:
        with patch("phaseforge_studio.paipai.shutil.which", return_value=None):
            assert check_paipai_installed() is False


class TestPaipaiInstallHint:
    def test_returns_string(self) -> None:
        assert isinstance(paipai_install_hint(), str)

    def test_non_empty(self) -> None:
        assert len(paipai_install_hint()) > 0

    def test_mentions_paipai(self) -> None:
        assert "PAIPAI" in paipai_install_hint() or "paipai" in paipai_install_hint()

    def test_mentions_cmake_or_build(self) -> None:
        hint = paipai_install_hint()
        assert "cmake" in hint.lower() or "build" in hint.lower() or "git" in hint.lower()


class TestWriteStrucIn:
    def test_creates_file(self, tmp_path: Path) -> None:
        out = write_struc_in(
            workdir=tmp_path,
            lattice_name="FCC",
            scale=1.0,
            lattice_vectors=[[3.5, 0.0, 0.0], [0.0, 3.5, 0.0], [0.0, 0.0, 3.5]],
            host_elements=["Al", "Ni"],
            host_counts=[2, 2],
            interstitial_elements=[],
            interstitial_counts=[],
            coords=[(0.0, 0.0, 0.0, "Al"), (0.5, 0.5, 0.0, "Al"),
                    (0.5, 0.0, 0.5, "Ni"), (0.0, 0.5, 0.5, "Ni")],
        )
        assert out.exists()
        assert out.name == "struc.in"

    def test_first_line_is_lattice_name(self, tmp_path: Path) -> None:
        write_struc_in(
            workdir=tmp_path,
            lattice_name="BCC",
            scale=1.0,
            lattice_vectors=[[2.9, 0.0, 0.0], [0.0, 2.9, 0.0], [0.0, 0.0, 2.9]],
            host_elements=["Fe"],
            host_counts=[2],
            interstitial_elements=[],
            interstitial_counts=[],
            coords=[(0.0, 0.0, 0.0, "Fe"), (0.5, 0.5, 0.5, "Fe")],
        )
        content = (tmp_path / "struc.in").read_text().splitlines()
        assert content[0] == "BCC"

    def test_elements_in_content(self, tmp_path: Path) -> None:
        write_struc_in(
            workdir=tmp_path,
            lattice_name="FCC",
            scale=1.0,
            lattice_vectors=[[3.5, 0.0, 0.0], [0.0, 3.5, 0.0], [0.0, 0.0, 3.5]],
            host_elements=["Cu", "Zr"],
            host_counts=[1, 1],
            interstitial_elements=[],
            interstitial_counts=[],
            coords=[(0.0, 0.0, 0.0, "Cu"), (0.5, 0.5, 0.0, "Zr")],
        )
        content = (tmp_path / "struc.in").read_text()
        assert "Cu" in content
        assert "Zr" in content

    def test_interstitials_written(self, tmp_path: Path) -> None:
        write_struc_in(
            workdir=tmp_path,
            lattice_name="FCC",
            scale=1.0,
            lattice_vectors=[[3.5, 0.0, 0.0], [0.0, 3.5, 0.0], [0.0, 0.0, 3.5]],
            host_elements=["Fe"],
            host_counts=[4],
            interstitial_elements=["H"],
            interstitial_counts=[1],
            coords=[(0.0, 0.0, 0.0, "Fe")] * 4 + [(0.25, 0.25, 0.25, "H")],
        )
        content = (tmp_path / "struc.in").read_text()
        assert "H" in content

    def test_returns_path(self, tmp_path: Path) -> None:
        result = write_struc_in(
            workdir=tmp_path,
            lattice_name="FCC",
            scale=1.0,
            lattice_vectors=[[3.5, 0.0, 0.0], [0.0, 3.5, 0.0], [0.0, 0.0, 3.5]],
            host_elements=["Al"],
            host_counts=[1],
            interstitial_elements=[],
            interstitial_counts=[],
            coords=[(0.0, 0.0, 0.0, "Al")],
        )
        assert isinstance(result, Path)


class TestStrucInFromPoscar:
    _POSCAR = """Al FCC
1.0
4.050000 0.000000 0.000000
0.000000 4.050000 0.000000
0.000000 0.000000 4.050000
Al
4
Direct
0.000000 0.000000 0.000000
0.500000 0.500000 0.000000
0.500000 0.000000 0.500000
0.000000 0.500000 0.500000
"""

    def test_creates_struc_in(self, tmp_path: Path) -> None:
        out = struc_in_from_poscar(tmp_path, self._POSCAR, lattice_name="FCC")
        assert out.exists()

    def test_elements_present(self, tmp_path: Path) -> None:
        struc_in_from_poscar(tmp_path, self._POSCAR, lattice_name="FCC")
        content = (tmp_path / "struc.in").read_text()
        assert "Al" in content

    def test_too_short_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="too short"):
            struc_in_from_poscar(tmp_path, "line1\nline2", lattice_name="FCC")


class TestPaipaiState:
    def test_initial_state_idle(self) -> None:
        state = PaipaiState()
        assert state.state == "idle"

    def test_initial_log_empty(self) -> None:
        state = PaipaiState()
        assert state.log == []

    def test_push_log_appends(self) -> None:
        state = PaipaiState()
        state.push_log("hello")
        assert state.log == ["hello"]

    def test_reset_clears(self) -> None:
        state = PaipaiState()
        state.state = "running"
        state.log = ["a", "b"]
        state.reset()
        assert state.state == "idle"
        assert state.log == []


class TestStopPaipai:
    def test_no_error_when_idle(self) -> None:
        state = PaipaiState()
        # Should not raise
        stop_paipai(state)

    def test_terminates_running_proc(self) -> None:
        from unittest.mock import MagicMock
        state = PaipaiState()
        mock_proc = MagicMock()
        state.proc = mock_proc
        state.state = "running"
        stop_paipai(state)
        mock_proc.terminate.assert_called_once()
        assert state.state == "stopped"


class TestScanPaipaiOutputs:
    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        result = scan_paipai_outputs(tmp_path)
        assert result == []

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        result = scan_paipai_outputs(tmp_path / "nonexistent")
        assert result == []

    def test_refine_outbox_scanned(self, tmp_path: Path) -> None:
        refine = tmp_path / "refine_outbox" / "task_001"
        refine.mkdir(parents=True)
        (refine / "CONTCAR").write_text("dummy CONTCAR")
        result = scan_paipai_outputs(tmp_path)
        assert len(result) >= 1
        assert any("task_001" in r.get("task_id", "") for r in result)

    def test_result_has_name_equivalent(self, tmp_path: Path) -> None:
        refine = tmp_path / "refine_outbox" / "task_002"
        refine.mkdir(parents=True)
        result = scan_paipai_outputs(tmp_path)
        for r in result:
            assert "task_id" in r

    def test_meta_json_parsed(self, tmp_path: Path) -> None:
        refine = tmp_path / "refine_outbox" / "task_003"
        refine.mkdir(parents=True)
        meta = {"energy_final": -3.5, "step": 100}
        (refine / "meta.json").write_text(json.dumps(meta))
        result = scan_paipai_outputs(tmp_path)
        entry = next(r for r in result if r["task_id"] == "task_003")
        assert entry.get("energy") == -3.5

    def test_sorted_by_energy(self, tmp_path: Path) -> None:
        for tid, energy in [("task_b", -1.0), ("task_a", -5.0), ("task_c", -3.0)]:
            d = tmp_path / "refine_outbox" / tid
            d.mkdir(parents=True)
            (d / "meta.json").write_text(json.dumps({"energy_final": energy}))
        result = scan_paipai_outputs(tmp_path)
        energies = [r["energy"] for r in result if r.get("energy") is not None]
        assert energies == sorted(energies)


class TestGetPaipaiProgress:
    def test_missing_dir_returns_dict(self, tmp_path: Path) -> None:
        result = get_paipai_progress(tmp_path / "nonexistent")
        assert isinstance(result, dict)

    def test_missing_workdir_counters_empty(self, tmp_path: Path) -> None:
        result = get_paipai_progress(tmp_path / "nonexistent")
        assert result.get("counters") == {} or "counters" in result

    def test_counters_read(self, tmp_path: Path) -> None:
        cdir = tmp_path / "counters"
        cdir.mkdir()
        (cdir / "accepted").write_text("42")
        (cdir / "rejected").write_text("8")
        result = get_paipai_progress(tmp_path)
        assert result["counters"].get("accepted") == 42
        assert result["counters"].get("rejected") == 8

    def test_n_refined_counted(self, tmp_path: Path) -> None:
        refine = tmp_path / "refine_outbox"
        for i in range(3):
            (refine / f"task_{i}").mkdir(parents=True)
        result = get_paipai_progress(tmp_path)
        assert result["n_refined"] == 3
