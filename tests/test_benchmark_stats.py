"""Tests for benchmark_stats module."""

from __future__ import annotations

import pytest

from phaseforge_studio.benchmark_stats import (
    analyse_energy_benchmark,
    bootstrap_ci,
    outlier_detection,
    per_composition_error,
)


class TestBootstrapCI:
    def test_known_mean(self) -> None:
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = bootstrap_ci(vals, n_boot=500, seed=0)
        assert result["available"] is True
        assert abs(result["mean"] - 3.0) < 0.01

    def test_ci_contains_mean(self) -> None:
        vals = [0.1, 0.2, 0.15, 0.25, 0.1, 0.3, 0.2, 0.18]
        result = bootstrap_ci(vals, n_boot=500, seed=1)
        assert result["ci_lower"] <= result["mean"] <= result["ci_upper"]

    def test_insufficient_sample(self) -> None:
        result = bootstrap_ci([1.0])
        assert result["available"] is False

    def test_n_effective_lte_n(self) -> None:
        vals = list(range(1, 11))
        result = bootstrap_ci(vals, n_boot=200, seed=42)
        assert result["n_effective"] <= result["n"]

    def test_returns_std(self) -> None:
        vals = [1.0, 2.0, 3.0]
        result = bootstrap_ci(vals)
        assert "std" in result
        assert result["std"] > 0

    def test_constant_sample(self) -> None:
        vals = [5.0, 5.0, 5.0, 5.0]
        result = bootstrap_ci(vals, n_boot=100)
        assert result["available"] is True
        assert result["mean"] == pytest.approx(5.0)
        assert result["std"] == pytest.approx(0.0)


class TestOutlierDetection:
    def test_obvious_outlier(self) -> None:
        # Need Z > 3: with 20 values near 1.0 and one at 100.0
        errors = [1.0] * 20 + [100.0]
        result = outlier_detection(errors)
        assert result["available"] is True
        assert result["n_outliers"] >= 1
        assert 20 in result["outlier_indices"]

    def test_no_outliers(self) -> None:
        errors = [1.0, 1.1, 0.9, 1.05, 0.95]
        result = outlier_detection(errors, z_threshold=3.0)
        assert result["available"] is True
        assert result["n_outliers"] == 0

    def test_z_scores_length(self) -> None:
        errors = [0.1, 0.2, 0.15, 0.3, 50.0]
        result = outlier_detection(errors)
        assert len(result["z_scores"]) == len(errors)

    def test_insufficient_sample(self) -> None:
        result = outlier_detection([1.0, 2.0])
        assert result["available"] is False

    def test_threshold_respected(self) -> None:
        errors = [1.0, 1.0, 1.0, 1.0, 5.0]
        # At threshold=10 there should be no outlier
        result = outlier_detection(errors, z_threshold=10.0)
        assert result["n_outliers"] == 0


class TestPerCompositionError:
    def _make_inputs(self) -> tuple[dict, dict, dict]:
        struct_results = {
            "s0": {"energy_per_atom": -3.70},
            "s1": {"energy_per_atom": -4.10},
            "s2": {"energy_per_atom": -4.20},
            "s3": {"energy_per_atom": -3.65},
        }
        ref_structs = {
            "s0": {"energy_per_atom": -3.72, "composition": {"Cu": 4, "Zr": 0}},
            "s1": {"energy_per_atom": -4.15, "composition": {"Cu": 2, "Zr": 2}},
            "s2": {"energy_per_atom": -4.25, "composition": {"Cu": 1, "Zr": 3}},
            "s3": {"energy_per_atom": -3.70, "composition": {"Cu": 4, "Zr": 0}},
        }
        el_refs = {"Cu": -3.72, "Zr": -6.25}
        return struct_results, ref_structs, el_refs

    def test_returns_bins(self) -> None:
        sr, rr, er = self._make_inputs()
        result = per_composition_error(sr, rr, er)
        assert result["available"] is True
        assert "bins" in result
        assert len(result["bins"]) == 10

    def test_bin_structure(self) -> None:
        sr, rr, er = self._make_inputs()
        result = per_composition_error(sr, rr, er)
        for b in result["bins"]:
            assert "x_min" in b
            assert "x_max" in b
            assert "x_mid" in b
            assert "energy_mae" in b
            assert "n_structures" in b

    def test_empty_structs_unavailable(self) -> None:
        result = per_composition_error({}, {}, {})
        assert result["available"] is False

    def test_n_structures_sums(self) -> None:
        sr, rr, er = self._make_inputs()
        result = per_composition_error(sr, rr, er)
        total = sum(b["n_structures"] for b in result["bins"])
        assert total == result["n_structures_total"]


class TestAnalyseEnergyBenchmark:
    def _make_energy_result(self) -> dict:
        return {
            "available": True,
            "mode": "energy",
            "mlips": {
                "grace": {
                    "energy_mae": 0.05,
                    "results": {
                        "s0": {"energy_per_atom": -3.70},
                        "s1": {"energy_per_atom": -4.10},
                        "s2": {"energy_per_atom": -4.20},
                    },
                }
            },
            "struct_refs": {
                "s0": {"energy_per_atom": -3.72, "composition": {"Cu": 4, "Zr": 0}},
                "s1": {"energy_per_atom": -4.15, "composition": {"Cu": 2, "Zr": 2}},
                "s2": {"energy_per_atom": -4.25, "composition": {"Cu": 1, "Zr": 3}},
            },
            "elemental_references": {"Cu": -3.72, "Zr": -6.25},
        }

    def test_available(self) -> None:
        result = analyse_energy_benchmark(self._make_energy_result())
        assert result["available"] is True

    def test_mlip_present(self) -> None:
        result = analyse_energy_benchmark(self._make_energy_result())
        assert "grace" in result["mlips"]

    def test_ci_keys(self) -> None:
        result = analyse_energy_benchmark(self._make_energy_result())
        grace = result["mlips"]["grace"]
        assert "energy_mae_ci" in grace
        assert "outliers" in grace

    def test_unavailable_input(self) -> None:
        result = analyse_energy_benchmark({"available": False})
        assert result["available"] is False

    def test_empty_input(self) -> None:
        result = analyse_energy_benchmark({})
        assert result["available"] is False
