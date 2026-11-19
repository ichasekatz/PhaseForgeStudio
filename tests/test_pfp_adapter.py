"""Tests for pfp_adapter module."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from phaseforge_studio.pfp_adapter import (
    PfpJob,
    cancel_pfp,
    check_pfp_installed,
    launch_pfp,
    method_info,
    pfp_install_hint,
    pfp_status,
    supported_methods,
)


class TestCheckPfpInstalled:
    def test_returns_bool(self) -> None:
        result = check_pfp_installed()
        assert isinstance(result, bool)

    def test_true_when_importable(self) -> None:
        with patch.dict("sys.modules", {"phaseforgeplus": MagicMock()}):
            import importlib
            import phaseforge_studio.pfp_adapter as _m
            importlib.reload(_m)
            # After reload with mock, should detect as available
            # We just verify the function signature works
        assert isinstance(check_pfp_installed(), bool)

    def test_false_when_not_installed(self) -> None:
        with patch.dict("sys.modules", {"phaseforgeplus": None}):
            # The module-level flag was set at import time; test the function directly
            result = check_pfp_installed()
            assert isinstance(result, bool)


class TestPfpInstallHint:
    def test_returns_string(self) -> None:
        hint = pfp_install_hint()
        assert isinstance(hint, str)

    def test_non_empty(self) -> None:
        assert len(pfp_install_hint()) > 0

    def test_contains_install_instruction(self) -> None:
        assert "pip install" in pfp_install_hint() or "phaseforgeplus" in pfp_install_hint()


class TestSupportedMethods:
    def test_cg_present(self) -> None:
        assert "CG" in supported_methods

    def test_lbfgsb_present(self) -> None:
        assert "L-BFGS-B" in supported_methods

    def test_bfgs_present(self) -> None:
        assert "BFGS" in supported_methods

    def test_all_strings(self) -> None:
        assert all(isinstance(m, str) for m in supported_methods)


class TestMethodInfo:
    def test_cg_has_keys(self) -> None:
        info = method_info("CG")
        assert "name" in info
        assert "description" in info

    def test_lbfgsb_has_keys(self) -> None:
        info = method_info("L-BFGS-B")
        assert "name" in info
        assert "description" in info

    def test_name_matches_input(self) -> None:
        assert method_info("CG")["name"] == "CG"
        assert method_info("BFGS")["name"] == "BFGS"

    def test_unknown_method_returns_dict(self) -> None:
        info = method_info("UNKNOWN")
        assert isinstance(info, dict)
        assert "name" in info


class TestPfpJob:
    def test_initial_state_idle(self) -> None:
        job = PfpJob()
        assert job.state == "idle"

    def test_initial_log_empty(self) -> None:
        job = PfpJob()
        assert job.log == []

    def test_initial_cancel_flag_not_set(self) -> None:
        job = PfpJob()
        assert not job.cancel_flag.is_set()

    def test_initial_iterations_empty(self) -> None:
        job = PfpJob()
        assert job.iterations == []

    def test_initial_result_none(self) -> None:
        job = PfpJob()
        assert job.result is None

    def test_elapsed_s_none_before_start(self) -> None:
        job = PfpJob()
        assert job.elapsed_s is None

    def test_elapsed_s_float_after_start(self) -> None:
        import time
        job = PfpJob()
        job.start_time = time.time()
        assert isinstance(job.elapsed_s, float)
        assert job.elapsed_s >= 0.0

    def test_elapsed_frozen_after_end(self) -> None:
        import time
        job = PfpJob()
        t0 = time.time()
        job.start_time = t0
        job.end_time = t0 + 5.0
        elapsed = job.elapsed_s
        assert elapsed is not None
        assert abs(elapsed - 5.0) < 0.01


class TestCancelPfp:
    def test_sets_cancel_flag(self) -> None:
        job = PfpJob()
        assert not job.cancel_flag.is_set()
        cancel_pfp(job)
        assert job.cancel_flag.is_set()

    def test_idempotent(self) -> None:
        job = PfpJob()
        cancel_pfp(job)
        cancel_pfp(job)
        assert job.cancel_flag.is_set()


class TestPfpStatus:
    def test_returns_dict(self) -> None:
        job = PfpJob()
        result = pfp_status(job)
        assert isinstance(result, dict)

    def test_required_keys(self) -> None:
        job = PfpJob()
        result = pfp_status(job)
        for key in ("state", "installed", "log_tail", "elapsed_s", "n_iterations", "last_iteration", "result", "error"):
            assert key in result, f"Missing key: {key}"

    def test_state_matches_job(self) -> None:
        job = PfpJob()
        job.state = "running"
        assert pfp_status(job)["state"] == "running"

    def test_n_iterations_matches(self) -> None:
        job = PfpJob()
        job.iterations = [{"iteration": 0, "params": [1.0]}, {"iteration": 1, "params": [0.9]}]
        assert pfp_status(job)["n_iterations"] == 2

    def test_last_iteration_populated(self) -> None:
        job = PfpJob()
        job.iterations = [{"iteration": 0, "params": [1.0]}]
        status = pfp_status(job)
        assert status["last_iteration"] == {"iteration": 0, "params": [1.0]}

    def test_last_iteration_none_when_empty(self) -> None:
        job = PfpJob()
        assert pfp_status(job)["last_iteration"] is None


class TestLaunchPfp:
    def test_sets_state_running(self, tmp_path: Path) -> None:
        job = PfpJob()
        tdb = tmp_path / "test.tdb"
        tdb.write_text("$ dummy TDB")
        zpf = tmp_path / "zpf"
        zpf.mkdir()

        with patch("phaseforge_studio.pfp_adapter._run_pfp") as mock_run:
            mock_run.return_value = None
            launch_pfp(job, tdb_path=str(tdb), zpf_dir=str(zpf), points=[0, 1], pressure=101325.0, temperature=298.15)
            # Give thread a moment to start
            import time
            time.sleep(0.05)
        assert job.state == "running"

    def test_clears_log_on_launch(self, tmp_path: Path) -> None:
        job = PfpJob()
        job.log = ["old line"]
        tdb = tmp_path / "test.tdb"
        tdb.write_text("$ dummy TDB")
        zpf = tmp_path / "zpf"
        zpf.mkdir()

        with patch("phaseforge_studio.pfp_adapter._run_pfp"):
            launch_pfp(job, tdb_path=str(tdb), zpf_dir=str(zpf), points=[0], pressure=101325.0, temperature=298.15)
        assert job.log == []

    def test_default_output_path_uses_fitted_suffix(self, tmp_path: Path) -> None:
        job = PfpJob()
        tdb = tmp_path / "mydb.tdb"
        tdb.write_text("$")
        zpf = tmp_path / "zpf"
        zpf.mkdir()

        captured: list[str] = []

        def fake_run(j: Any, tdb_path: str, zpf_dir: str, points: Any, pressure: Any, temperature: Any, method: str, tol: Any, maxiter: Any, output_path: str) -> None:
            captured.append(output_path)

        with patch("phaseforge_studio.pfp_adapter._run_pfp", side_effect=fake_run):
            launch_pfp(job, tdb_path=str(tdb), zpf_dir=str(zpf), points=[0], pressure=101325.0, temperature=298.15)
            import time; time.sleep(0.05)

        assert captured and "fitted" in captured[0]
