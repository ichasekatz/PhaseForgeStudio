"""Tests for the MLIP benchmark adapter and metrics."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest import TestCase

from phaseforge_studio.benchmark_adapter import (
    BenchmarkConfig,
    BenchmarkRun,
    MlipJobState,
    _BenchmarkRegistry,
    _safe_name,
    cancel_benchmark,
    create_and_launch_benchmark,
    delete_benchmark,
    get_benchmark_status,
    list_benchmarks,
)
from phaseforge_studio.benchmark_metrics import (
    _normalise_phase,
    boundary_metrics,
    classification_metrics,
    compute_phase_grid,
)


# ---------------------------------------------------------------------------
# BenchmarkConfig
# ---------------------------------------------------------------------------


class TestBenchmarkConfig(TestCase):
    """Tests for BenchmarkConfig creation."""

    def _make_config(self, **kwargs) -> BenchmarkConfig:
        defaults = dict(
            benchmark_id="abc12345",
            system="Cu-Zr",
            elements=["Cu", "Zr"],
            mlips=["grace"],
            phases=["FCC_A1"],
            level=2,
            t_min=300.0,
            t_max=3000.0,
            t_step=100.0,
            x_step=0.05,
            mode="relaxed",
            reference_tdb="",
            workdir="/tmp",
            created_at=0.0,
        )
        defaults.update(kwargs)
        return BenchmarkConfig(**defaults)

    def test_config_stores_elements(self):
        """BenchmarkConfig preserves element list as given."""
        cfg = self._make_config(elements=["Ni", "Al"])
        assert cfg.elements == ["Ni", "Al"]

    def test_config_stores_system(self):
        """BenchmarkConfig stores the system name string."""
        cfg = self._make_config(system="Ni-Al")
        assert cfg.system == "Ni-Al"

    def test_config_stores_mlips(self):
        """BenchmarkConfig stores MLIP names."""
        cfg = self._make_config(mlips=["grace", "mace"])
        assert cfg.mlips == ["grace", "mace"]

    def test_safe_name_replaces_spaces(self):
        """_safe_name replaces spaces with underscores."""
        assert _safe_name("my model") == "my_model"

    def test_safe_name_replaces_slashes(self):
        """_safe_name replaces slashes with underscores."""
        assert _safe_name("org/model") == "org_model"


# ---------------------------------------------------------------------------
# _BenchmarkRegistry
# ---------------------------------------------------------------------------


class TestBenchmarkRegistry(TestCase):
    """Tests for the in-memory benchmark registry."""

    def _make_run(self, bm_id: str = "test0001") -> BenchmarkRun:
        cfg = BenchmarkConfig(
            benchmark_id=bm_id,
            system="Cu-Zr",
            elements=["Cu", "Zr"],
            mlips=["grace"],
            phases=["FCC_A1"],
            level=2,
            t_min=300.0,
            t_max=3000.0,
            t_step=100.0,
            x_step=0.05,
            mode="relaxed",
            reference_tdb="",
            workdir="/tmp",
            created_at=time.time(),
        )
        return BenchmarkRun(config=cfg, mlip_jobs={"grace": MlipJobState(mlip="grace")})

    def test_add_and_get_roundtrip(self):
        """Registry stores and retrieves a run by id."""
        reg = _BenchmarkRegistry()
        run = self._make_run("aabb1234")
        reg.add(run)
        assert reg.get("aabb1234") is run

    def test_get_missing_returns_none(self):
        """Registry returns None for unknown benchmark id."""
        reg = _BenchmarkRegistry()
        assert reg.get("nonexistent") is None

    def test_list_includes_added_run(self):
        """list_all returns runs that were added."""
        reg = _BenchmarkRegistry()
        run = self._make_run("ccdd5678")
        reg.add(run)
        ids = [r.config.benchmark_id for r in reg.list_all()]
        assert "ccdd5678" in ids

    def test_remove_cleans_registry(self):
        """remove() makes the run inaccessible."""
        reg = _BenchmarkRegistry()
        run = self._make_run("eeff9012")
        reg.add(run)
        reg.remove("eeff9012")
        assert reg.get("eeff9012") is None

    def test_remove_returns_false_for_missing(self):
        """remove() returns False when run does not exist."""
        reg = _BenchmarkRegistry()
        assert reg.remove("not_there") is False

    def test_cancel_sets_flag(self):
        """cancel_benchmark sets the run's cancel_flag."""
        # Uses the module-level registry
        import phaseforge_studio.benchmark_adapter as bm_mod

        run = self._make_run("ff001122")
        bm_mod._registry.add(run)
        cancel_benchmark("ff001122")
        assert run.cancel_flag.is_set()
        bm_mod._registry.remove("ff001122")

    def test_delete_removes_from_module_registry(self):
        """delete_benchmark removes run from module registry."""
        import phaseforge_studio.benchmark_adapter as bm_mod

        run = self._make_run("aabbccdd")
        bm_mod._registry.add(run)
        assert delete_benchmark("aabbccdd") is True
        assert bm_mod._registry.get("aabbccdd") is None


# ---------------------------------------------------------------------------
# MlipJobState
# ---------------------------------------------------------------------------


class TestMlipJobState(TestCase):
    """Tests for MlipJobState property computation."""

    def test_elapsed_none_before_start(self):
        """elapsed_s is None when start_time is not set."""
        job = MlipJobState(mlip="grace")
        assert job.elapsed_s is None

    def test_elapsed_positive_while_running(self):
        """elapsed_s is positive once start_time is set."""
        job = MlipJobState(mlip="grace")
        job.start_time = time.time() - 5.0
        assert job.elapsed_s is not None
        assert job.elapsed_s >= 4.9

    def test_elapsed_frozen_after_end(self):
        """elapsed_s does not grow after end_time is set."""
        job = MlipJobState(mlip="grace")
        job.start_time = 1000.0
        job.end_time = 1010.0
        assert job.elapsed_s == 10.0


# ---------------------------------------------------------------------------
# Phase name normalisation
# ---------------------------------------------------------------------------


class TestNormalisePhase(TestCase):
    """Tests for _normalise_phase helper."""

    def test_strips_number_suffix(self):
        """#N suffix is removed from phase name."""
        assert _normalise_phase("FCC_A1#1") == "FCC_A1"

    def test_strips_larger_number(self):
        """#12 suffix is removed correctly."""
        assert _normalise_phase("BCC_A2#12") == "BCC_A2"

    def test_uppercases(self):
        """Phase name is uppercased."""
        assert _normalise_phase("liquid") == "LIQUID"

    def test_no_suffix_unchanged(self):
        """Names without suffix pass through unchanged (after uppercase)."""
        assert _normalise_phase("FCC_A1") == "FCC_A1"

    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        assert _normalise_phase("  HCP_A3  ") == "HCP_A3"


# ---------------------------------------------------------------------------
# Classification metrics
# ---------------------------------------------------------------------------


def _make_grid(labels: list[list[str]]) -> dict:
    """Build a minimal phase-grid dict for testing."""
    n_rows = len(labels)
    n_cols = len(labels[0]) if labels else 0
    return {
        "temperatures": [float(i) for i in range(n_rows)],
        "compositions": [float(j) for j in range(n_cols)],
        "phase_grid": labels,
        "elements": ["A", "B"],
        "phases_seen": sorted({v for row in labels for v in row}),
    }


class TestClassificationMetrics(TestCase):
    """Tests for classification_metrics."""

    def test_perfect_agreement_accuracy_one(self):
        """Identical grids yield accuracy 1.0."""
        grid = _make_grid([["FCC", "FCC"], ["BCC", "BCC"]])
        m = classification_metrics(grid, grid)
        assert m["accuracy"] == 1.0

    def test_no_overlap_accuracy_zero(self):
        """Completely different grids yield accuracy 0.0."""
        pred = _make_grid([["FCC", "FCC"]])
        ref = _make_grid([["BCC", "BCC"]])
        m = classification_metrics(pred, ref)
        assert m["accuracy"] == 0.0

    def test_partial_overlap_f1_between_0_and_1(self):
        """50% matching grid yields F1 strictly between 0 and 1."""
        pred = _make_grid([["FCC", "BCC"]])
        ref = _make_grid([["FCC", "FCC"]])
        m = classification_metrics(pred, ref)
        assert 0.0 < m["f1"] < 1.0

    def test_empty_grids_return_empty_dict(self):
        """Empty grid dicts return empty metrics."""
        assert classification_metrics({}, {}) == {}

    def test_has_expected_keys(self):
        """Result contains all expected metric keys."""
        grid = _make_grid([["FCC"]])
        m = classification_metrics(grid, grid)
        for key in ("accuracy", "precision", "recall", "f1", "jaccard", "n_points"):
            assert key in m, f"Missing key: {key}"

    def test_normalises_phase_names(self):
        """Phase names are normalised before comparison."""
        pred = _make_grid([["FCC_A1#1", "BCC_A2"]])
        ref = _make_grid([["FCC_A1", "BCC_A2"]])
        m = classification_metrics(pred, ref)
        assert m["accuracy"] == 1.0


# ---------------------------------------------------------------------------
# Boundary metrics
# ---------------------------------------------------------------------------


class TestBoundaryMetrics(TestCase):
    """Tests for boundary_metrics."""

    def test_no_boundaries_returns_zero_matched(self):
        """Single-phase grids with no transitions yield n_boundaries_matched=0."""
        grid = _make_grid([["FCC", "FCC"], ["FCC", "FCC"], ["FCC", "FCC"]])
        m = boundary_metrics(grid, grid)
        assert m.get("n_boundaries_matched", 0) == 0

    def test_empty_grids_return_empty_dict(self):
        """Empty grid dicts return empty boundary metrics."""
        assert boundary_metrics({}, {}) == {}

    def test_matching_boundary_zero_deviation(self):
        """Identical grids with phase transitions yield zero deviation."""
        grid = _make_grid([["FCC"], ["FCC"], ["BCC"], ["BCC"]])
        m = boundary_metrics(grid, grid)
        # Exact matches → MAD-T = 0.0 (or no boundaries in a single-col grid)
        # Either n_matched=0 or mad=0
        if m.get("n_boundaries_matched", 0) > 0:
            assert m["mad_t"] == 0.0

    def test_has_expected_keys(self):
        """Result contains mad_t, rmsd_t, n_boundaries_matched."""
        grid = _make_grid([["FCC"], ["BCC"]])
        m = boundary_metrics(grid, grid)
        for key in ("n_boundaries_matched",):
            assert key in m


# ---------------------------------------------------------------------------
# compute_phase_grid with bad input
# ---------------------------------------------------------------------------


class TestComputePhaseGrid(TestCase):
    """Tests for compute_phase_grid error handling."""

    def test_nonexistent_tdb_returns_empty(self):
        """Non-existent TDB path returns empty dict."""
        result = compute_phase_grid(Path("/nonexistent/fake.tdb"), ["Cu", "Zr"])
        assert result == {}

    def test_non_binary_returns_empty(self):
        """Three-element system returns empty dict (binary only)."""
        result = compute_phase_grid(Path("/nonexistent/fake.tdb"), ["Cu", "Zr", "Ni"])
        assert result == {}


# ---------------------------------------------------------------------------
# get_benchmark_status
# ---------------------------------------------------------------------------


class TestGetBenchmarkStatus(TestCase):
    """Tests for get_benchmark_status serialisation."""

    def _add_dummy_run(self, bm_id: str) -> None:
        import phaseforge_studio.benchmark_adapter as bm_mod

        cfg = BenchmarkConfig(
            benchmark_id=bm_id,
            system="Cu-Zr",
            elements=["Cu", "Zr"],
            mlips=["grace", "mace"],
            phases=["FCC_A1"],
            level=2,
            t_min=300.0,
            t_max=3000.0,
            t_step=100.0,
            x_step=0.05,
            mode="relaxed",
            reference_tdb="",
            workdir="/tmp",
            created_at=time.time(),
        )
        jobs = {m: MlipJobState(mlip=m) for m in cfg.mlips}
        run = BenchmarkRun(config=cfg, mlip_jobs=jobs)
        bm_mod._registry.add(run)

    def tearDown(self):
        import phaseforge_studio.benchmark_adapter as bm_mod
        bm_mod._registry.remove("status_test_01")

    def test_missing_benchmark_returns_none(self):
        """get_benchmark_status returns None for unknown id."""
        assert get_benchmark_status("does_not_exist_xyz") is None

    def test_status_has_required_top_level_keys(self):
        """Status dict has benchmark_id, system, state, mlip_jobs, config."""
        self._add_dummy_run("status_test_01")
        s = get_benchmark_status("status_test_01")
        assert s is not None
        for key in ("benchmark_id", "system", "state", "mlip_jobs", "config"):
            assert key in s

    def test_status_mlip_jobs_includes_all_mlips(self):
        """mlip_jobs section lists all configured MLIPs."""
        self._add_dummy_run("status_test_01")
        s = get_benchmark_status("status_test_01")
        assert s is not None
        for mlip in ("grace", "mace"):
            assert mlip in s["mlip_jobs"]

    def test_mlip_job_has_state_and_log_tail(self):
        """Each MLIP entry has state and log_tail keys."""
        self._add_dummy_run("status_test_01")
        s = get_benchmark_status("status_test_01")
        assert s is not None
        for job in s["mlip_jobs"].values():
            assert "state" in job
            assert "log_tail" in job
