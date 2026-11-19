"""MLIP ranking and Pareto analysis for PhaseForgeStudio benchmarks.

Provides weighted composite scoring, Pareto-front identification, and
normalised metric tables for the benchmark dashboard.

All functions operate on plain dicts and require no optional dependencies.
"""

from __future__ import annotations

import math
from typing import Any

#: Default metric weights for composite ranking.
#: Keys match the per-MLIP metric names; values are importance weights (not
#: automatically normalised — relative magnitudes matter).
default_weights: dict[str, float] = {
    "energy_mae": 1.0,
    "force_mae": 0.5,
    "f1": 1.5,
    "mad_t": 1.0,
    "runtime_s": 0.3,
}

#: Metrics where lower value is better (used by normalisation and Pareto).
_lower_is_better: set[str] = {"energy_mae", "force_mae", "mad_t", "rmsd_t", "runtime_s", "energy_rmse"}

#: Metrics where higher value is better.
_higher_is_better: set[str] = {"f1", "accuracy", "recall", "precision", "jaccard"}


def normalise_metrics(per_mlip: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalise numeric benchmark metrics to [0, 1] across MLIPs.

    For each numeric metric key, the minimum MLIP value is mapped to 0 and the
    maximum to 1.  Original values are preserved; normalised copies are added
    with a ``_norm`` suffix.

    Args:
        per_mlip (dict[str, dict]): Mapping of MLIP name → metric dict.

    Returns:
        New dict with the same keys; each metric dict has ``<key>_norm``
        entries added where normalisation is possible.
    """
    if not per_mlip:
        return {}

    # Collect all numeric keys and their finite values
    all_keys: set[str] = set()
    for metrics in per_mlip.values():
        all_keys.update(k for k, v in metrics.items() if isinstance(v, (int, float)) and math.isfinite(v))

    # Min / max per key
    minmax: dict[str, tuple[float, float]] = {}
    for key in all_keys:
        vals = [
            float(m[key])
            for m in per_mlip.values()
            if isinstance(m.get(key), (int, float)) and math.isfinite(m[key])
        ]
        if len(vals) >= 2:
            minmax[key] = (min(vals), max(vals))

    result: dict[str, dict[str, Any]] = {}
    for mlip, metrics in per_mlip.items():
        entry = dict(metrics)
        for key, (lo, hi) in minmax.items():
            if key not in entry or entry[key] is None:
                continue
            val = float(entry[key])
            if not math.isfinite(val):
                continue
            denom = hi - lo
            norm = (val - lo) / denom if denom > 0 else 0.5
            entry[f"{key}_norm"] = round(norm, 6)
        result[mlip] = entry

    return result


def weighted_composite(
    per_mlip: dict[str, dict[str, Any]],
    weights: dict[str, float],
) -> dict[str, float]:
    """Compute a weighted composite score (higher = better) per MLIP.

    For lower-is-better metrics, the normalised score is inverted (1 − norm).
    For higher-is-better metrics, the normalised score is used directly.
    Missing or non-finite metrics are excluded; their weights are redistributed
    proportionally.

    Args:
        per_mlip (dict[str, dict]): Metric dicts, ideally already normalised
            by ``normalise_metrics``.
        weights (dict[str, float]): Metric → weight mapping.

    Returns:
        Mapping of MLIP name → composite score in [0, 1]; empty dict if no
        weighted metrics are available.
    """
    normed = normalise_metrics(per_mlip)
    scores: dict[str, float] = {}

    for mlip, metrics in normed.items():
        total_weight = 0.0
        weighted_sum = 0.0
        for key, w in weights.items():
            if w <= 0:
                continue
            norm_key = f"{key}_norm"
            if norm_key not in metrics:
                continue
            norm_val = metrics[norm_key]
            if not math.isfinite(norm_val):
                continue
            # Flip lower-is-better so that higher score = better
            if key in _lower_is_better:
                score_component = 1.0 - norm_val
            else:
                score_component = norm_val
            weighted_sum += w * score_component
            total_weight += w
        scores[mlip] = round(weighted_sum / total_weight, 6) if total_weight > 0 else 0.0

    return scores


def pareto_front(
    mlip_points: dict[str, dict[str, Any]],
    objectives: list[tuple[str, bool]],
) -> list[str]:
    """Identify the Pareto-optimal MLIPs for a set of objectives.

    An MLIP is on the Pareto front if no other MLIP is at least as good on
    every objective and strictly better on at least one.

    Args:
        mlip_points (dict[str, dict]): MLIP → metric dict.
        objectives (list[tuple[str, bool]]): Each tuple is
            ``(metric_key, lower_is_better)``.  MLIPs missing a metric are
            treated as dominated for that objective.

    Returns:
        List of MLIP names on the Pareto front, sorted alphabetically.
    """
    mlips = list(mlip_points.keys())
    if not mlips:
        return []

    def _get(mlip: str, key: str, lib: bool) -> float:
        """Return value normalised so lower = better."""
        v = mlip_points[mlip].get(key)
        if v is None or not math.isfinite(float(v)):
            return float("inf")
        return float(v) if lib else -float(v)

    front: list[str] = []
    for candidate in mlips:
        dominated = False
        for other in mlips:
            if other == candidate:
                continue
            # Does `other` dominate `candidate`?
            at_least_as_good = all(
                _get(other, k, lib) <= _get(candidate, k, lib)
                for k, lib in objectives
            )
            strictly_better = any(
                _get(other, k, lib) < _get(candidate, k, lib)
                for k, lib in objectives
            )
            if at_least_as_good and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append(candidate)

    return sorted(front)


def rank_mlips(
    per_mlip: dict[str, dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Rank MLIPs by weighted composite score with Pareto annotation.

    Args:
        per_mlip (dict[str, dict]): Per-MLIP metric dicts.  Keys should include
            any subset of ``energy_mae``, ``force_mae``, ``f1``, ``mad_t``,
            ``runtime_s``.
        weights (dict[str, float] | None): Optional weight overrides.  If
            None, uses ``default_weights`` but restricted to metrics actually
            present in at least one MLIP.

    Returns:
        List of dicts sorted by composite score descending, each with
        ``mlip``, ``rank`` (1-based int), ``composite_score``, ``pareto``
        (bool), and ``metrics`` (original metric dict).
    """
    if not per_mlip:
        return []

    # Restrict weights to metrics that exist in at least one MLIP
    effective_weights = dict(weights) if weights is not None else {}
    if not effective_weights:
        present_keys: set[str] = set()
        for m in per_mlip.values():
            present_keys.update(k for k, v in m.items() if isinstance(v, (int, float)) and v is not None)
        effective_weights = {k: v for k, v in default_weights.items() if k in present_keys}
        if not effective_weights:
            # Fall back: give equal weight to whatever numeric fields exist
            effective_weights = {k: 1.0 for k in present_keys if isinstance(list(per_mlip.values())[0].get(k), (int, float))}

    scores = weighted_composite(per_mlip, effective_weights)

    # Pareto objectives: energy_mae, force_mae lower-better; f1 higher-better
    objectives: list[tuple[str, bool]] = []
    for key in effective_weights:
        lib = key in _lower_is_better
        objectives.append((key, lib))

    pareto_set = set(pareto_front(per_mlip, objectives)) if objectives else set()

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    result: list[dict[str, Any]] = []
    for rank_i, (mlip, score) in enumerate(ranked, start=1):
        result.append({
            "mlip": mlip,
            "rank": rank_i,
            "composite_score": score,
            "pareto": mlip in pareto_set,
            "metrics": per_mlip.get(mlip, {}),
        })

    return result
