"""Tests for phaseforge_studio.pipeline — background runner and Sqs2tdb factory."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from phaseforge_studio.pipeline import _make_tracking_sqs2tdb, _run_pipeline


# ---------------------------------------------------------------------------
# _make_tracking_sqs2tdb
# ---------------------------------------------------------------------------


class TestMakeTrackingSqs2tdb:
    """Tests for the Sqs2tdb trajectory-tracking subclass factory."""

    def test_requires_materialsframework(self) -> None:
        try:
            import materialsframework.tools.sqs2tdb  # noqa: F401
            mf_available = True
        except ImportError:
            mf_available = False

        if mf_available:
            cls = _make_tracking_sqs2tdb()
            assert cls is not None
            assert issubclass(cls, object)
        else:
            with pytest.raises(ImportError):
                _make_tracking_sqs2tdb()

    def test_subclass_has_calculate_override(self) -> None:
        # Provide a minimal Sqs2tdb stub so we can test the subclass structure.
        class _FakeSqs2tdb:
            called_super: bool = False

            def _calculate(self, subdir: Path, relax: bool = True) -> None:
                _FakeSqs2tdb.called_super = True

            class calculator:
                traj_file = None

        with patch.dict(
            sys.modules,
            {"materialsframework": MagicMock(), "materialsframework.tools": MagicMock(), "materialsframework.tools.sqs2tdb": MagicMock(Sqs2tdb=_FakeSqs2tdb)},
        ):
            cls = _make_tracking_sqs2tdb()
            assert hasattr(cls, "_calculate")

    def test_tracking_subclass_sets_traj_file(self, tmp_path: Path) -> None:
        traj_calls: list[str | None] = []

        class _FakeSqs2tdb:
            class calculator:
                traj_file: str | None = None

            def _calculate(self, subdir: Path, relax: bool = True) -> None:
                traj_calls.append(type(self).calculator.traj_file)

        with patch.dict(
            sys.modules,
            {"materialsframework": MagicMock(), "materialsframework.tools": MagicMock(), "materialsframework.tools.sqs2tdb": MagicMock(Sqs2tdb=_FakeSqs2tdb)},
        ):
            cls = _make_tracking_sqs2tdb()
            inst = cls()
            inst._calculate(tmp_path)
            assert len(traj_calls) == 1
            # traj_file was set to <subdir>/trajectory.pkl before super call
            assert traj_calls[0] is not None
            assert "trajectory.pkl" in str(traj_calls[0])


# ---------------------------------------------------------------------------
# _run_pipeline — error handling paths
# ---------------------------------------------------------------------------


def _make_job(state_store: list[str]) -> Any:
    """Return a minimal JobState mock."""
    job = MagicMock()
    job.job_id = "test1234"
    job.job_name = "test_job"
    job.is_running.return_value = False

    def _set_state(s: str) -> None:
        state_store.append(s)

    job.set_state.side_effect = _set_state
    return job


def _mock_mf_registry(side_effect: Exception) -> dict:
    """Return sys.modules overrides that make get_calculator raise side_effect."""
    registry_mod = MagicMock()
    registry_mod.get_calculator.side_effect = side_effect
    calcs_mod = MagicMock()
    calcs_mod.registry = registry_mod
    mf_mod = MagicMock()
    mf_mod.calculators = calcs_mod
    mf_tools = MagicMock()
    mf_sqs2tdb = MagicMock()

    class _FakeSqs2tdb:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def fit(self, **kwargs: Any) -> None:
            pass

    mf_sqs2tdb.Sqs2tdb = _FakeSqs2tdb
    return {
        "materialsframework": mf_mod,
        "materialsframework.calculators": calcs_mod,
        "materialsframework.calculators.registry": registry_mod,
        "materialsframework.tools": mf_tools,
        "materialsframework.tools.sqs2tdb": mf_sqs2tdb,
    }


class TestRunPipelineErrors:
    """Test _run_pipeline error-path branches."""

    def _base_cfg(self, path1: str) -> dict[str, Any]:
        return {
            "path1": path1,
            "species": ["Al", "Ni"],
            "lattices": ["FCC_A1"],
            "calculator": "grace",
            "device": "cpu",
            "fmax": 0.05,
            "track_trajectory": False,
        }

    def test_import_error_sets_error_state(self, tmp_path: Path) -> None:
        states: list[str] = []
        job = _make_job(states)
        cfg = self._base_cfg(str(tmp_path))

        with patch("phaseforge_studio.pipeline.list_available_calculators", return_value=[]), \
             patch.dict(sys.modules, _mock_mf_registry(ImportError("no mf"))):
            _run_pipeline(cfg, job)

        assert "error" in states

    def test_runtime_error_sets_error_state(self, tmp_path: Path) -> None:
        states: list[str] = []
        job = _make_job(states)
        cfg = self._base_cfg(str(tmp_path))

        with patch("phaseforge_studio.pipeline.list_available_calculators", return_value=[]), \
             patch.dict(sys.modules, _mock_mf_registry(RuntimeError("calc failed"))):
            _run_pipeline(cfg, job)

        assert "error" in states

    def test_cwd_restored_after_error(self, tmp_path: Path) -> None:
        import os
        original = os.getcwd()
        states: list[str] = []
        job = _make_job(states)
        cfg = self._base_cfg(str(tmp_path))

        with patch("phaseforge_studio.pipeline.list_available_calculators", return_value=[]), \
             patch.dict(sys.modules, _mock_mf_registry(ImportError("no mf"))):
            _run_pipeline(cfg, job)

        assert os.getcwd() == original

    def test_job_name_sanitised_for_path(self, tmp_path: Path) -> None:
        # job_name with special chars should not cause path errors
        states: list[str] = []
        job = _make_job(states)
        job.job_name = "Al/Ni test run!"
        cfg = self._base_cfg(str(tmp_path))

        with patch("phaseforge_studio.pipeline.list_available_calculators", return_value=[]), \
             patch.dict(sys.modules, _mock_mf_registry(ImportError("no mf"))):
            _run_pipeline(cfg, job)

        assert "error" in states

    def test_pipeline_logs_species(self, tmp_path: Path) -> None:
        states: list[str] = []
        job = _make_job(states)
        cfg = self._base_cfg(str(tmp_path))
        log_lines: list[str] = []
        job.push_log.side_effect = log_lines.append

        with patch("phaseforge_studio.pipeline.list_available_calculators", return_value=[]), \
             patch.dict(sys.modules, _mock_mf_registry(ImportError("no mf"))):
            _run_pipeline(cfg, job)

        # At least one log line should mention the species
        assert any("Al" in line and "Ni" in line for line in log_lines)
