"""Statistical analysis for MLIP benchmark results.

Provides bootstrap confidence intervals, per-composition and per-temperature
error analysis, outlier detection, and effective sample size estimation.

All heavy computation (numpy) is imported lazily so optional dependencies
do not break the rest of PhaseForgeStudio.
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Bootstrap confidence interval
# ---------------------------------------------------------------------------


def bootstrap_ci(
    values: list[float],
    *,
    n_boot: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> dict[str, Any]:
    """Bootstrap confidence interval for the mean of a sample.

    Uses simple non-parametric bootstrap resampling.  Also estimates the
    effective sample size from the lag-1 autocorrelation to flag correlated
    structures.

    Args:
        values (list[float]): Numeric sample.
        n_boot (int): Number of bootstrap replicates.
        ci (float): Coverage, e.g. 0.95 for 95 % CI.
        seed (int): Random seed for reproducibility.

    Returns:
        Dict with ``mean``, ``ci_lower``, ``ci_upper``, ``n``,
        ``n_effective``, ``std`` (sample standard deviation).
        Returns ``{"available": False}`` for samples shorter than 2.
    """
    n = len(values)
    if n < 2:
        return {"available": False, "error": "Insufficient sample (n < 2)"}

    try:
        import numpy as np
    except ImportError:
        return {"available": False, "error": "numpy not installed"}

    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=float)
    mean_val = float(arr.mean())
    std_val = float(arr.std(ddof=1)) if n > 1 else 0.0

    # Effective sample size from lag-1 autocorrelation
    if n >= 5:
        try:
            corr = float(np.corrcoef(arr[:-1], arr[1:])[0, 1])
            if math.isfinite(corr) and abs(corr) < 1.0:
                n_eff = max(1, int(n / (1 + 2 * abs(corr))))
            else:
                n_eff = n
        except Exception:
            n_eff = n
    else:
        n_eff = n

    # Bootstrap
    boot_means = np.array([
        rng.choice(arr, size=n, replace=True).mean()
        for _ in range(n_boot)
    ])
    alpha = (1.0 - ci) / 2.0
    ci_lower = float(np.quantile(boot_means, alpha))
    ci_upper = float(np.quantile(boot_means, 1.0 - alpha))

    return {
        "available": True,
        "mean": mean_val,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "n": n,
        "n_effective": n_eff,
        "std": std_val,
    }


# ---------------------------------------------------------------------------
# Per-composition error analysis
# ---------------------------------------------------------------------------


def per_composition_error(
    struct_results: dict[str, dict[str, Any]],
    ref_structs: dict[str, dict[str, Any]],
    el_refs: dict[str, float],
    *,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Group per-structure energy errors by composition of the second element.

    Args:
        struct_results (dict[str, dict]): Per-structure MLIP results keyed by
            structure name; each must contain ``energy_per_atom``.
        ref_structs (dict[str, dict]): Reference data keyed by structure name;
            each must contain ``energy_per_atom`` and ``composition``.
        el_refs (dict[str, float]): Elemental reference energies per atom.
        n_bins (int): Number of composition bins.

    Returns:
        Dict with ``available`` (bool) and ``bins`` (list of dicts with
        ``x_min``, ``x_max``, ``x_mid``, ``energy_mae``, ``n_structures``,
        ``ci``).
    """
    points: list[tuple[float, float]] = []  # (x_B, |energy_error|)

    el_list = sorted({
        el
        for ref in ref_structs.values()
        for el in ref.get("composition", {})
    })
    el_b = el_list[1] if len(el_list) >= 2 else ""

    for key, result in struct_results.items():
        if result.get("error"):
            continue
        ref = ref_structs.get(key, {})
        if not ref:
            continue
        pred_epa = result.get("energy_per_atom")
        ref_epa = ref.get("energy_per_atom")
        if pred_epa is None or ref_epa is None:
            continue
        comp = ref.get("composition", {})
        n_total = sum(comp.values())
        if n_total == 0:
            continue
        x_b = comp.get(el_b, 0) / n_total if el_b else 0.0
        points.append((x_b, abs(pred_epa - ref_epa)))

    if not points:
        return {"available": False, "error": "No valid structures for composition analysis"}

    bins: list[dict[str, Any]] = []
    step = 1.0 / n_bins
    for i in range(n_bins):
        x_lo = i * step
        x_hi = (i + 1) * step
        x_mid = (x_lo + x_hi) / 2.0
        errs = [err for x, err in points if x_lo <= x < x_hi or (i == n_bins - 1 and x == 1.0)]
        ci = bootstrap_ci(errs) if errs else {"available": False}
        bins.append({
            "x_min": round(x_lo, 4),
            "x_max": round(x_hi, 4),
            "x_mid": round(x_mid, 4),
            "energy_mae": sum(errs) / len(errs) if errs else None,
            "n_structures": len(errs),
            "ci": ci,
        })

    return {
        "available": True,
        "bins": bins,
        "second_element": el_b,
        "n_structures_total": len(points),
    }


# ---------------------------------------------------------------------------
# Per-temperature phase-diagram accuracy
# ---------------------------------------------------------------------------


def per_temperature_analysis(
    mlip_jobs: dict[str, dict[str, Any]],
    ref_grid: dict[str, Any],
) -> dict[str, Any]:
    """Analyse phase-diagram accuracy per temperature slice.

    For each MLIP in mlip_jobs, extracts per-temperature phase accuracy by
    comparing predicted phase grid rows to the reference grid.

    Args:
        mlip_jobs (dict[str, dict]): mlip → job status dict (from
            ``get_benchmark_status``).  Each job may have ``metrics``
            containing a ``classification`` sub-dict.
        ref_grid (dict): Reference phase grid from
            ``benchmark_metrics.compute_phase_grid`` with ``"temperatures"``
            and ``"phase_grid"`` keys.

    Returns:
        Dict with ``available`` (bool) and ``mlips`` mapping each MLIP to a
        list of ``{"temperature": float, "accuracy": float}`` dicts.
    """
    ref_temps = ref_grid.get("temperatures", [])
    ref_pg = ref_grid.get("phase_grid", [])
    if not ref_temps or not ref_pg:
        return {"available": False, "error": "No reference grid provided"}

    mlip_analysis: dict[str, list[dict[str, Any]]] = {}

    for mlip, job in mlip_jobs.items():
        metrics = job.get("metrics") or {}
        pred_pg = metrics.get("pred_phase_grid", [])
        if not pred_pg or len(pred_pg) != len(ref_pg):
            mlip_analysis[mlip] = []
            continue

        per_temp: list[dict[str, Any]] = []
        for i, t_val in enumerate(ref_temps):
            if i >= len(pred_pg) or i >= len(ref_pg):
                break
            pred_row = pred_pg[i]
            ref_row = ref_pg[i]
            n = min(len(pred_row), len(ref_row))
            if n == 0:
                continue
            correct = sum(p == r for p, r in zip(pred_row[:n], ref_row[:n]))
            per_temp.append({
                "temperature": float(t_val),
                "accuracy": float(correct / n),
            })
        mlip_analysis[mlip] = per_temp

    return {
        "available": bool(mlip_analysis),
        "mlips": mlip_analysis,
    }


# ---------------------------------------------------------------------------
# Outlier detection
# ---------------------------------------------------------------------------


def outlier_detection(
    errors: list[float],
    *,
    z_threshold: float = 3.0,
) -> dict[str, Any]:
    """Detect outliers in an error distribution via Z-score.

    Args:
        errors (list[float]): Per-structure error values.
        z_threshold (float): Z-score threshold above which a point is an
            outlier.

    Returns:
        Dict with ``outlier_indices`` (list[int]), ``outlier_values``
        (list[float]), ``z_scores`` (list[float]), ``threshold`` (float),
        ``n_outliers`` (int).  Returns ``{"available": False}`` for n < 3.
    """
    n = len(errors)
    if n < 3:
        return {"available": False, "error": "Insufficient sample (n < 3)"}

    mean = sum(errors) / n
    variance = sum((e - mean) ** 2 for e in errors) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    if std == 0.0:
        return {
            "available": True,
            "outlier_indices": [],
            "outlier_values": [],
            "z_scores": [0.0] * n,
            "threshold": z_threshold,
            "n_outliers": 0,
        }

    z_scores = [(e - mean) / std for e in errors]
    outlier_indices = [i for i, z in enumerate(z_scores) if abs(z) > z_threshold]
    outlier_values = [errors[i] for i in outlier_indices]

    return {
        "available": True,
        "outlier_indices": outlier_indices,
        "outlier_values": outlier_values,
        "z_scores": z_scores,
        "threshold": z_threshold,
        "n_outliers": len(outlier_indices),
    }


# ---------------------------------------------------------------------------
# Top-level energy benchmark statistical analysis
# ---------------------------------------------------------------------------


def analyse_energy_benchmark(energy_result: dict[str, Any]) -> dict[str, Any]:
    """Compute statistical summaries for an energy benchmark result.

    For each MLIP, extracts per-structure errors (energy and formation
    energy), computes bootstrap confidence intervals, and runs outlier
    detection.

    Args:
        energy_result (dict[str, Any]): Output of
            ``benchmark_modes.run_energy_benchmark``.

    Returns:
        Dict with ``available`` (bool) and ``mlips`` mapping each MLIP to
        ``{"energy_mae_ci": {...}, "formation_mae_ci": {...},
        "outliers": {...}}``.
    """
    if not energy_result or not energy_result.get("available"):
        return {"available": False, "error": "No energy benchmark result available"}

    per_mlip_in = energy_result.get("mlips", {})
    el_refs = energy_result.get("elemental_references", {})
    per_mlip_out: dict[str, Any] = {}

    for mlip, mlip_data in per_mlip_in.items():
        struct_results = mlip_data.get("results", {})
        ref_structs = energy_result.get("struct_refs", {})

        energy_errs: list[float] = []
        f_energy_errs: list[float] = []

        for key, r in struct_results.items():
            if r.get("error"):
                continue
            pred_epa = r.get("energy_per_atom")
            # Reference may live at top-level or be embedded
            ref_entry = ref_structs.get(key, {})
            ref_epa = ref_entry.get("energy_per_atom")
            if pred_epa is not None and ref_epa is not None:
                energy_errs.append(abs(pred_epa - ref_epa))
            comp = ref_entry.get("composition", {})
            if comp and el_refs and pred_epa is not None and ref_epa is not None:
                n_total = sum(comp.values())
                if n_total > 0:
                    weighted_ref = sum(
                        (n / n_total) * el_refs.get(el, float("nan"))
                        for el, n in comp.items()
                    )
                    if math.isfinite(weighted_ref):
                        pred_eform = pred_epa - weighted_ref
                        ref_eform = ref_epa - weighted_ref
                        f_energy_errs.append(abs(pred_eform - ref_eform))

        per_mlip_out[mlip] = {
            "energy_mae_ci": bootstrap_ci(energy_errs) if energy_errs else {"available": False},
            "formation_mae_ci": bootstrap_ci(f_energy_errs) if f_energy_errs else {"available": False},
            "outliers": outlier_detection(energy_errs) if len(energy_errs) >= 3 else {"available": False},
            "n_structures": len(energy_errs),
        }

    return {
        "available": True,
        "mlips": per_mlip_out,
    }
