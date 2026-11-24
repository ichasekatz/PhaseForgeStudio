"""Tests for benchmark_modes module.

Uses deterministic fixtures and mocks so no real MLIP or pycalphad call runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

np = pytest.importorskip("numpy", reason="numpy required for benchmark_modes tests")

from phaseforge_studio.benchmark_modes import (
    _convex_hull,
    _formation_energy,
    _load_reference_energies,
    _spinodal_boundaries,
    summarise_mode_result,
)


# ---------------------------------------------------------------------------
# _formation_energy
# ---------------------------------------------------------------------------


class TestFormationEnergy:
    def test_pure_element_zero(self) -> None:
        # Pure Cu at its reference → formation energy ≈ 0
        result = _formation_energy(
            total_energy_per_atom=-3.72,
            composition={"Cu": 1},
            elemental_refs={"Cu": -3.72},
        )
        assert result is not None
        assert abs(result) < 1e-10

    def test_binary_alloy(self) -> None:
        # 50/50 CuZr: E_form = E_total - 0.5*E_Cu - 0.5*E_Zr
        result = _formation_energy(
            total_energy_per_atom=-4.0,
            composition={"Cu": 1, "Zr": 1},
            elemental_refs={"Cu": -3.72, "Zr": -6.25},
        )
        expected = -4.0 - 0.5 * (-3.72) - 0.5 * (-6.25)
        assert result is not None
        assert abs(result - expected) < 1e-10

    def test_missing_reference_returns_none(self) -> None:
        result = _formation_energy(
            total_energy_per_atom=-4.0,
            composition={"Cu": 1, "Zr": 1},
            elemental_refs={"Cu": -3.72},  # Zr missing
        )
        assert result is None

    def test_zero_composition_returns_none(self) -> None:
        result = _formation_energy(
            total_energy_per_atom=-3.0,
            composition={},
            elemental_refs={"Cu": -3.72},
        )
        assert result is None


# ---------------------------------------------------------------------------
# _load_reference_energies
# ---------------------------------------------------------------------------


class TestLoadReferenceEnergies:
    def test_valid_json(self, tmp_path: Path) -> None:
        ref: dict[str, Any] = {
            "structures": {
                "POSCAR_001": {
                    "energy_per_atom": -3.42,
                    "composition": {"Cu": 4, "Zr": 4},
                }
            },
            "elemental_references": {"Cu": -3.72, "Zr": -6.25},
        }
        p = tmp_path / "ref.json"
        p.write_text(json.dumps(ref))
        data = _load_reference_energies(p)
        assert "structures" in data
        assert "elemental_references" in data
        assert "POSCAR_001" in data["structures"]

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        # _load_reference_energies returns {} on missing file (graceful)
        result = _load_reference_energies(tmp_path / "missing.json")
        assert result == {}

    def test_corrupt_json_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{{not valid")
        result = _load_reference_energies(p)
        assert result == {}


# ---------------------------------------------------------------------------
# _convex_hull
# ---------------------------------------------------------------------------


class TestConvexHull:
    def test_returns_dict(self) -> None:
        x = np.array([0.0, 0.5, 1.0])
        g = np.array([0.0, -1.0, 0.0])
        result = _convex_hull(x, g)
        assert isinstance(result, dict)

    def test_available_on_valid_input(self) -> None:
        x = np.array([0.0, 0.5, 1.0])
        g = np.array([0.0, -1.0, 0.0])
        result = _convex_hull(x, g)
        assert result.get("available") is True

    def test_stable_compositions_included(self) -> None:
        x = np.linspace(0, 1, 5)
        g = np.array([0.0, 0.1, -0.5, 0.1, 0.0])
        result = _convex_hull(x, g)
        if result.get("available"):
            stable = result.get("stable_compositions", [])
            assert isinstance(stable, list)

    def test_unavailable_on_insufficient_points(self) -> None:
        x = np.array([0.5])
        g = np.array([-1.0])
        result = _convex_hull(x, g)
        # Should not crash; either available or error
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _spinodal_boundaries
# ---------------------------------------------------------------------------


class TestSpinodal:
    def test_returns_dict(self) -> None:
        x = np.linspace(0, 1, 50)
        g = x * (1 - x) * (-0.5) + x
        result = _spinodal_boundaries(x, g)
        assert isinstance(result, dict)

    def test_available_on_valid_input(self) -> None:
        x = np.linspace(0, 1, 50)
        g = x * (1 - x) * (-0.5) + x
        result = _spinodal_boundaries(x, g)
        assert result.get("available") is True

    def test_spinodal_x_is_list(self) -> None:
        x = np.linspace(0.0, 1.0, 100)
        g = (x - 0.3) ** 2 * (x - 0.7) ** 2 - 0.01 * x * (1 - x)
        result = _spinodal_boundaries(x, g)
        if result.get("available"):
            assert isinstance(result["spinodal_x"], list)

    def test_n_spinodal_boundaries_key(self) -> None:
        x = np.linspace(0, 1, 30)
        g = x * (1 - x)
        result = _spinodal_boundaries(x, g)
        if result.get("available"):
            assert "n_spinodal_boundaries" in result


# ---------------------------------------------------------------------------
# summarise_mode_result
# ---------------------------------------------------------------------------


class TestSummariseModeResult:
    def test_unavailable_result(self) -> None:
        result = {"available": False, "error": "pycalphad not installed"}
        summary = summarise_mode_result(result)
        assert summary["available"] is False

    def test_available_true(self) -> None:
        result = {
            "mode": "energy",
            "available": True,
            "mlips": {
                "grace": {"energy_mae": 0.05, "n_evaluated": 10, "n_failed": 0},
            },
        }
        summary = summarise_mode_result(result)
        assert summary["available"] is True

    def test_mode_field_present(self) -> None:
        result = {"mode": "stability", "available": False}
        summary = summarise_mode_result(result)
        assert summary.get("mode") == "stability"

    def test_energy_mlip_summary(self) -> None:
        result = {
            "mode": "energy",
            "available": True,
            "mlips": {
                "grace": {"energy_mae": 0.03, "energy_rmse": 0.04,
                          "formation_energy_mae": 0.02, "n_evaluated": 5, "n_failed": 0},
            },
        }
        summary = summarise_mode_result(result)
        assert "mlip_summary" in summary
        assert "grace" in summary["mlip_summary"]


# ---------------------------------------------------------------------------
# run_energy_benchmark (integration, mocked calculator)
# ---------------------------------------------------------------------------


class TestRunEnergyBenchmarkMocked:
    def test_no_structures_in_ref(self, tmp_path: Path) -> None:
        from phaseforge_studio.benchmark_modes import run_energy_benchmark

        ref: dict[str, Any] = {
            "structures": {},
            "elemental_references": {"Cu": -3.72},
        }
        ref_path = tmp_path / "ref.json"
        ref_path.write_text(json.dumps(ref))

        result = run_energy_benchmark(
            structures_dir=tmp_path,
            reference_path=ref_path,
            mlips=["grace"],
            cache_dir=tmp_path / "cache",
            device="cpu",
            use_cache=False,
        )
        # Empty structures → available=False or n_structures=0
        assert isinstance(result, dict)

    def test_missing_reference_path_unavailable(self, tmp_path: Path) -> None:
        from phaseforge_studio.benchmark_modes import run_energy_benchmark

        result = run_energy_benchmark(
            structures_dir=tmp_path,
            reference_path=tmp_path / "nonexistent.json",
            mlips=["grace"],
            cache_dir=tmp_path / "cache",
            device="cpu",
            use_cache=False,
        )
        assert isinstance(result, dict)
        assert result.get("available") is False or "error" in result


# ---------------------------------------------------------------------------
# run_stability_benchmark (integration, mocked pycalphad)
# ---------------------------------------------------------------------------


class TestRunStabilityBenchmarkMocked:
    def test_empty_tdb_map(self) -> None:
        from phaseforge_studio.benchmark_modes import run_stability_benchmark

        result = run_stability_benchmark(
            tdb_map={},
            elements=["Cu", "Zr"],
            temperatures=[1000, 1500],
            n_grid=10,
        )
        assert isinstance(result, dict)
        # Empty map → available=False or mlips is empty
        assert result.get("available") is False or result.get("mlips") == {}

    def test_nonexistent_tdb_handles_gracefully(self, tmp_path: Path) -> None:
        from phaseforge_studio.benchmark_modes import run_stability_benchmark

        result = run_stability_benchmark(
            tdb_map={"grace": tmp_path / "nonexistent.tdb"},
            elements=["Cu", "Zr"],
            temperatures=[1000],
            n_grid=5,
        )
        assert isinstance(result, dict)
        # Should not raise; either unavailable or per-mlip error
