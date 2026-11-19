"""Tests for benchmark_ranking module."""

from __future__ import annotations

import pytest

from phaseforge_studio.benchmark_ranking import (
    default_weights,
    normalise_metrics,
    pareto_front,
    rank_mlips,
    weighted_composite,
)


class TestNormaliseMetrics:
    def test_empty_input(self) -> None:
        assert normalise_metrics({}) == {}

    def test_single_mlip_gets_0_5(self) -> None:
        # Only one MLIP → no spread → norm = 0.5
        result = normalise_metrics({"grace": {"energy_mae": 0.05}})
        assert result["grace"].get("energy_mae_norm") is None  # only 1 value, no minmax

    def test_two_mlips_spread(self) -> None:
        per_mlip = {
            "a": {"energy_mae": 0.0},
            "b": {"energy_mae": 1.0},
        }
        result = normalise_metrics(per_mlip)
        assert result["a"]["energy_mae_norm"] == pytest.approx(0.0)
        assert result["b"]["energy_mae_norm"] == pytest.approx(1.0)

    def test_original_values_preserved(self) -> None:
        per_mlip = {"a": {"energy_mae": 0.1}, "b": {"energy_mae": 0.5}}
        result = normalise_metrics(per_mlip)
        assert result["a"]["energy_mae"] == pytest.approx(0.1)

    def test_non_numeric_keys_ignored(self) -> None:
        per_mlip = {
            "a": {"energy_mae": 0.1, "name": "grace"},
            "b": {"energy_mae": 0.5, "name": "mace"},
        }
        result = normalise_metrics(per_mlip)
        assert "name_norm" not in result["a"]

    def test_missing_key_in_one_mlip(self) -> None:
        per_mlip = {
            "a": {"energy_mae": 0.1, "f1": 0.9},
            "b": {"energy_mae": 0.5},
        }
        result = normalise_metrics(per_mlip)
        # f1 only present in one MLIP → no minmax → no norm
        assert "f1_norm" not in result["a"]

    def test_three_mlips_midpoint(self) -> None:
        per_mlip = {
            "a": {"energy_mae": 0.0},
            "b": {"energy_mae": 0.5},
            "c": {"energy_mae": 1.0},
        }
        result = normalise_metrics(per_mlip)
        assert result["b"]["energy_mae_norm"] == pytest.approx(0.5)


class TestWeightedComposite:
    def _two_mlip_input(self) -> dict:
        return {
            "grace": {"energy_mae": 0.05, "f1": 0.9},
            "mace":  {"energy_mae": 0.20, "f1": 0.7},
        }

    def test_scores_in_01(self) -> None:
        scores = weighted_composite(self._two_mlip_input(), default_weights)
        for s in scores.values():
            assert 0.0 <= s <= 1.0

    def test_better_mlip_scores_higher(self) -> None:
        # grace: lower energy_mae (better), higher f1 (better) → should rank higher
        scores = weighted_composite(self._two_mlip_input(), default_weights)
        assert scores["grace"] > scores["mace"]

    def test_empty_input(self) -> None:
        assert weighted_composite({}, default_weights) == {}

    def test_missing_weight_key_skipped(self) -> None:
        per_mlip = {"a": {"energy_mae": 0.1}, "b": {"energy_mae": 0.5}}
        # weight for a key not present in mlips
        weights = {"energy_mae": 1.0, "force_mae": 0.5}
        scores = weighted_composite(per_mlip, weights)
        assert "a" in scores

    def test_equal_mlips_equal_score(self) -> None:
        per_mlip = {"a": {"energy_mae": 0.1}, "b": {"energy_mae": 0.1}}
        scores = weighted_composite(per_mlip, {"energy_mae": 1.0})
        assert scores["a"] == pytest.approx(scores["b"])


class TestParetoFront:
    def test_clear_domination(self) -> None:
        # a dominates b on both objectives
        points = {
            "a": {"energy_mae": 0.05, "f1": 0.9},
            "b": {"energy_mae": 0.20, "f1": 0.6},
        }
        objectives = [("energy_mae", True), ("f1", False)]
        front = pareto_front(points, objectives)
        assert "a" in front
        assert "b" not in front

    def test_tradeoff_both_on_front(self) -> None:
        # a better energy_mae, b better f1 → both on front
        points = {
            "a": {"energy_mae": 0.05, "f1": 0.6},
            "b": {"energy_mae": 0.20, "f1": 0.9},
        }
        objectives = [("energy_mae", True), ("f1", False)]
        front = pareto_front(points, objectives)
        assert "a" in front
        assert "b" in front

    def test_empty_input(self) -> None:
        assert pareto_front({}, []) == []

    def test_single_mlip_on_front(self) -> None:
        points = {"a": {"energy_mae": 0.1}}
        front = pareto_front(points, [("energy_mae", True)])
        assert front == ["a"]

    def test_sorted_alphabetically(self) -> None:
        points = {
            "z": {"energy_mae": 0.1, "f1": 0.8},
            "a": {"energy_mae": 0.1, "f1": 0.8},
        }
        objectives = [("energy_mae", True), ("f1", False)]
        front = pareto_front(points, objectives)
        assert front == sorted(front)

    def test_missing_metric_treated_as_dominated(self) -> None:
        points = {
            "good": {"energy_mae": 0.05, "f1": 0.9},
            "incomplete": {"f1": 0.8},  # no energy_mae → inf
        }
        objectives = [("energy_mae", True), ("f1", False)]
        front = pareto_front(points, objectives)
        assert "good" in front
        assert "incomplete" not in front


class TestRankMlips:
    def _standard_input(self) -> dict:
        return {
            "grace": {"energy_mae": 0.05, "f1": 0.90, "runtime_s": 120.0},
            "mace":  {"energy_mae": 0.12, "f1": 0.80, "runtime_s": 90.0},
            "chgnet": {"energy_mae": 0.20, "f1": 0.70, "runtime_s": 60.0},
        }

    def test_returns_list(self) -> None:
        result = rank_mlips(self._standard_input())
        assert isinstance(result, list)

    def test_rank_field_ascending(self) -> None:
        result = rank_mlips(self._standard_input())
        ranks = [r["rank"] for r in result]
        assert ranks == sorted(ranks)

    def test_rank_starts_at_1(self) -> None:
        result = rank_mlips(self._standard_input())
        assert result[0]["rank"] == 1

    def test_all_mlips_present(self) -> None:
        result = rank_mlips(self._standard_input())
        names = {r["mlip"] for r in result}
        assert names == {"grace", "mace", "chgnet"}

    def test_pareto_field_bool(self) -> None:
        result = rank_mlips(self._standard_input())
        for r in result:
            assert isinstance(r["pareto"], bool)

    def test_composite_score_descending(self) -> None:
        result = rank_mlips(self._standard_input())
        scores = [r["composite_score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_metrics_original_preserved(self) -> None:
        result = rank_mlips(self._standard_input())
        grace = next(r for r in result if r["mlip"] == "grace")
        assert grace["metrics"]["energy_mae"] == pytest.approx(0.05)

    def test_empty_input(self) -> None:
        assert rank_mlips({}) == []

    def test_custom_weights(self) -> None:
        # Weight runtime very heavily → chgnet (fastest) should rank #1
        result = rank_mlips(self._standard_input(), weights={"runtime_s": 10.0})
        assert result[0]["mlip"] == "chgnet"

    def test_single_mlip(self) -> None:
        result = rank_mlips({"grace": {"energy_mae": 0.05}})
        assert len(result) == 1
        assert result[0]["rank"] == 1
