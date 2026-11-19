"""Quantitative metrics for MLIP phase diagram benchmarking.

Computes classification, boundary, and thermodynamic metrics by comparing
a predicted TDB against a reference TDB on a common composition-temperature grid.
All grid computation uses pycalphad as an optional dependency — imported lazily.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Phase name normalisation
# ---------------------------------------------------------------------------


def _normalise_phase(name: str) -> str:
    """Normalise a pycalphad phase name for comparison.

    Strips sublattice-composition suffixes (#1, #2 …) and uppercases.

    Args:
        name (str): Raw phase label from pycalphad output.

    Returns:
        Normalised, uppercase phase name without numeric suffix.
    """
    return re.sub(r"#\d+$", "", name.strip().upper())


# ---------------------------------------------------------------------------
# Phase-grid computation
# ---------------------------------------------------------------------------


def compute_phase_grid(
    tdb_path: Path,
    elements: list[str],
    *,
    t_min: float = 300.0,
    t_max: float = 3000.0,
    t_step: float = 200.0,
    x_step: float = 0.05,
) -> dict[str, Any]:
    """Compute equilibrium phase labels on a T×X grid via pycalphad.

    Uses ``pycalphad.equilibrium()`` on a binary composition-temperature grid.
    Currently supports binary systems only; returns ``{}`` for N≠2.

    Args:
        tdb_path (Path): Path to TDB file.
        elements (list[str]): Element symbols, e.g. ``["Cu", "Zr"]``.
        t_min (float): Minimum temperature in K.
        t_max (float): Maximum temperature in K.
        t_step (float): Temperature grid spacing in K.
        x_step (float): Composition grid spacing in mole fraction.

    Returns:
        Dict with keys ``temperatures`` (list[float]), ``compositions``
        (list[float]), ``phase_grid`` (list[list[str]]), ``elements``
        (list[str]), ``phases_seen`` (list[str]).  Returns ``{}`` on failure.
    """
    if len(elements) != 2:
        return {}
    try:
        import numpy as np
        from pycalphad import Database, equilibrium
        from pycalphad import variables as v
    except ImportError:
        return {}

    try:
        dbf = Database(str(tdb_path))
    except Exception:
        return {}

    el_a, el_b = [e.upper() for e in elements]
    comps = [el_a, el_b, "VA"]
    phases = list(dbf.phases.keys())

    temps = list(np.arange(t_min, t_max + t_step * 0.5, t_step, dtype=float))
    comps_x = list(np.arange(x_step, 1.0 - x_step * 0.5, x_step, dtype=float))
    if not temps or not comps_x:
        return {}

    conds: dict[Any, Any] = {
        v.N: 1,
        v.P: 101325,
        v.T: temps,
        v.X(el_b): comps_x,
    }

    try:
        result = equilibrium(dbf, comps, phases, conds, to_xarray=True)
    except Exception:
        return {}

    phase_grid: list[list[str]] = []
    phases_seen: set[str] = set()

    for t_val in temps:
        row: list[str] = []
        for x_val in comps_x:
            try:
                pt = result.sel(T=t_val, X_ZR=x_val, method="nearest") if el_b == "ZR" else result.isel(
                    T=list(np.asarray(result.coords["T"].values)).index(
                        min(result.coords["T"].values, key=lambda t: abs(t - t_val))
                    ),
                    X_ZR=0,
                )
                # Extract dominant phase: highest Phase_frac
                pf = result.Phase.sel(T=t_val, method="nearest") if hasattr(result, "Phase") else None
                label = "UNKNOWN"
                if pf is not None:
                    # Find x nearest
                    x_coord = [k for k in result.coords if k.startswith("X_")][0] if any(
                        k.startswith("X_") for k in result.coords
                    ) else None
                    if x_coord:
                        pt_phase = result.Phase.sel(
                            T=t_val,
                            method="nearest",
                        ).sel(
                            {x_coord: x_val},
                            method="nearest",
                        )
                        phase_arr = np.asarray(pt_phase.values).ravel()
                        pf_arr = np.asarray(result.NP.sel(
                            T=t_val, method="nearest"
                        ).sel(
                            {x_coord: x_val}, method="nearest"
                        ).values).ravel()
                        if len(phase_arr) > 0:
                            best_idx = int(np.argmax(pf_arr))
                            raw = str(phase_arr[best_idx])
                            label = _normalise_phase(raw) if raw else "UNKNOWN"
            except Exception:
                label = "UNKNOWN"
            phases_seen.add(label)
            row.append(label)
        phase_grid.append(row)

    return {
        "temperatures": [float(t) for t in temps],
        "compositions": [float(x) for x in comps_x],
        "phase_grid": phase_grid,
        "elements": [el_a, el_b],
        "phases_seen": sorted(phases_seen),
    }


# ---------------------------------------------------------------------------
# Classification metrics
# ---------------------------------------------------------------------------


def classification_metrics(
    pred_grid: dict[str, Any],
    ref_grid: dict[str, Any],
) -> dict[str, float]:
    """Compare phase classification on a common T×X grid.

    Aligns both grids to the same (T, X) points via nearest-match.
    Normalises phase names before comparison.

    Args:
        pred_grid (dict[str, Any]): Output of ``compute_phase_grid`` for prediction.
        ref_grid (dict[str, Any]): Output of ``compute_phase_grid`` for reference.

    Returns:
        Dict with ``accuracy``, ``f1``, ``precision``, ``recall``,
        ``jaccard``, ``n_points``.  Returns ``{}`` if grids incompatible.
    """
    if not pred_grid or not ref_grid:
        return {}
    pred_phases = pred_grid.get("phase_grid", [])
    ref_phases = ref_grid.get("phase_grid", [])
    if not pred_phases or not ref_phases:
        return {}

    # Flatten both to 1-D lists aligned on min(rows) × min(cols)
    n_rows = min(len(pred_phases), len(ref_phases))
    n_cols = min(
        min((len(r) for r in pred_phases), default=0),
        min((len(r) for r in ref_phases), default=0),
    )
    if n_rows == 0 or n_cols == 0:
        return {}

    pred_flat: list[str] = []
    ref_flat: list[str] = []
    for i in range(n_rows):
        for j in range(n_cols):
            pred_flat.append(_normalise_phase(pred_phases[i][j]))
            ref_flat.append(_normalise_phase(ref_phases[i][j]))

    n_total = len(pred_flat)
    correct = sum(p == r for p, r in zip(pred_flat, ref_flat, strict=True))
    accuracy = correct / n_total

    # Macro-averaged precision/recall/F1 over all phase classes
    all_classes = sorted(set(pred_flat) | set(ref_flat))
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    jaccards: list[float] = []

    for cls in all_classes:
        tp = sum(p == cls and r == cls for p, r in zip(pred_flat, ref_flat, strict=True))
        fp = sum(p == cls and r != cls for p, r in zip(pred_flat, ref_flat, strict=True))
        fn = sum(p != cls and r == cls for p, r in zip(pred_flat, ref_flat, strict=True))
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        jacc = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0
        precisions.append(prec)
        recalls.append(rec)
        f1s.append(f1)
        jaccards.append(jacc)

    n_cls = len(all_classes)
    return {
        "accuracy": float(accuracy),
        "precision": float(sum(precisions) / n_cls) if n_cls else 0.0,
        "recall": float(sum(recalls) / n_cls) if n_cls else 0.0,
        "f1": float(sum(f1s) / n_cls) if n_cls else 0.0,
        "jaccard": float(sum(jaccards) / n_cls) if n_cls else 0.0,
        "n_points": n_total,
        "n_classes": n_cls,
    }


# ---------------------------------------------------------------------------
# Phase-boundary metrics
# ---------------------------------------------------------------------------


def _find_transitions(column: list[str]) -> list[int]:
    """Return row indices where phase label changes.

    Args:
        column (list[str]): Phase labels for a fixed composition, ordered by T.

    Returns:
        Row indices (0-based) immediately before the transition.
    """
    return [i for i in range(1, len(column)) if column[i] != column[i - 1]]


def boundary_metrics(
    pred_grid: dict[str, Any],
    ref_grid: dict[str, Any],
) -> dict[str, float]:
    """Compute phase boundary deviation between predicted and reference grids.

    For each composition column, finds T where phase changes in both grids
    and computes temperature deviation where matching boundaries exist.

    Args:
        pred_grid (dict[str, Any]): Output of ``compute_phase_grid`` for prediction.
        ref_grid (dict[str, Any]): Output of ``compute_phase_grid`` for reference.

    Returns:
        Dict with ``mad_t`` (mean absolute T deviation in K), ``rmsd_t``
        (RMSD in K), ``n_boundaries_matched``.  Returns ``{}`` on failure.
    """
    if not pred_grid or not ref_grid:
        return {}
    pred_pg = pred_grid.get("phase_grid", [])
    ref_pg = ref_grid.get("phase_grid", [])
    pred_temps = pred_grid.get("temperatures", [])
    ref_temps = ref_grid.get("temperatures", [])
    if not pred_pg or not ref_pg or not pred_temps or not ref_temps:
        return {}

    n_rows = min(len(pred_pg), len(ref_pg))
    n_cols = min(
        min((len(r) for r in pred_pg), default=0),
        min((len(r) for r in ref_pg), default=0),
    )
    if n_rows == 0 or n_cols == 0:
        return {}

    deviations: list[float] = []
    for j in range(n_cols):
        pred_col = [_normalise_phase(pred_pg[i][j]) for i in range(n_rows)]
        ref_col = [_normalise_phase(ref_pg[i][j]) for i in range(n_rows)]
        pred_trans = _find_transitions(pred_col)
        ref_trans = _find_transitions(ref_col)
        # Match each predicted transition to nearest reference transition
        for pi in pred_trans:
            if not ref_trans:
                continue
            nearest_ri = min(ref_trans, key=lambda ri: abs(ri - pi))
            pred_t = pred_temps[min(pi, len(pred_temps) - 1)]
            ref_t = ref_temps[min(nearest_ri, len(ref_temps) - 1)]
            deviations.append(abs(pred_t - ref_t))

    if not deviations:
        return {"mad_t": None, "rmsd_t": None, "n_boundaries_matched": 0}

    import math

    mad = sum(deviations) / len(deviations)
    rmsd = math.sqrt(sum(d * d for d in deviations) / len(deviations))
    return {
        "mad_t": float(mad),
        "rmsd_t": float(rmsd),
        "n_boundaries_matched": len(deviations),
    }


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------


def compute_metrics(
    pred_tdb_path: Path,
    ref_tdb_path: Path,
    elements: list[str],
    *,
    t_min: float = 300.0,
    t_max: float = 3000.0,
    t_step: float = 200.0,
    x_step: float = 0.05,
) -> dict[str, Any]:
    """Compute all benchmark metrics for one predicted TDB versus reference.

    Args:
        pred_tdb_path (Path): Path to predicted TDB (from MLIP run).
        ref_tdb_path (Path): Path to reference TDB.
        elements (list[str]): Element symbols.
        t_min (float): Minimum temperature in K.
        t_max (float): Maximum temperature in K.
        t_step (float): Temperature grid spacing in K.
        x_step (float): Composition grid spacing in mole fraction.

    Returns:
        Dict with ``available`` (bool), ``classification`` (dict),
        ``boundary`` (dict), ``error`` (str if failed).
    """
    if not pred_tdb_path.exists():
        return {"available": False, "error": f"Predicted TDB not found: {pred_tdb_path}"}
    if not ref_tdb_path.exists():
        return {"available": False, "error": f"Reference TDB not found: {ref_tdb_path}"}

    try:
        grid_kwargs = {"t_min": t_min, "t_max": t_max, "t_step": t_step, "x_step": x_step}
        pred_grid = compute_phase_grid(pred_tdb_path, elements, **grid_kwargs)
        ref_grid = compute_phase_grid(ref_tdb_path, elements, **grid_kwargs)

        if not pred_grid or not ref_grid:
            return {"available": False, "error": "Phase grid computation failed (pycalphad unavailable or TDB parse error)"}

        cls_m = classification_metrics(pred_grid, ref_grid)
        bnd_m = boundary_metrics(pred_grid, ref_grid)

        return {
            "available": True,
            "classification": cls_m,
            "boundary": bnd_m,
            "error": "",
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}
