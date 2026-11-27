"""Phase diagram computation from TDB content using pycalphad."""

from __future__ import annotations

import io
from typing import Any

_PHASE_COLORS = [
    "#5dade2", "#e8a030", "#58d68d", "#ec7063",
    "#a569bd", "#f39c12", "#17a589", "#aab7b8",
]


def _pycalphad_available() -> bool:
    try:
        import pycalphad  # noqa: F401
        return True
    except ImportError:
        return False


def compute_binary_diagram(
    tdb_content: str,
    elements: list[str],
    T_min: float = 300.0,
    T_max: float = 2000.0,
    n_T: int = 60,
    n_X: int = 50,
) -> dict[str, Any]:
    """Compute binary phase diagram from TDB string using pycalphad.

    Returns dict with ``lines`` list (scatter points per phase) for the
    frontend ``_renderOrchidDiagram`` function.
    """
    if not _pycalphad_available():
        return {
            "error": "pycalphad not installed",
            "hint": "pip install pycalphad",
        }
    if len(elements) < 2:
        return {"error": "Need at least 2 elements for a binary diagram"}

    try:
        import numpy as np
        from pycalphad import Database, equilibrium
        from pycalphad import variables as v
    except ImportError as exc:
        return {"error": str(exc), "hint": "pip install pycalphad numpy"}

    try:
        db = Database(io.StringIO(tdb_content))
    except Exception as exc:
        return {"error": f"TDB parse error: {exc}"}

    el1, el2 = elements[0].upper(), elements[1].upper()
    comps = [el1, el2, "VA"]
    # Only keep phases that reference both elements.
    phases = [
        p for p, pdata in db.phases.items()
        if any(e in pdata.constituents[0] for s in pdata.constituents for e in (el1, el2))
    ] or list(db.phases.keys())

    x_vals = list(np.linspace(0.01, 0.99, n_X))
    T_vals = list(np.linspace(T_min, T_max, n_T))

    try:
        result = equilibrium(
            db, comps, phases,
            {
                v.X(el2): x_vals,
                v.T: T_vals,
                v.P: 101325,
                v.N: 1,
            },
        )
    except Exception as exc:
        return {"error": f"Equilibrium calculation failed: {exc}"}

    # Collect (x, T) points per stable phase for scatter rendering.
    phase_points: dict[str, list[list[float]]] = {}
    try:
        phase_arr = result["Phase"].values  # shape: (N, T, X, n_phases)
        # Squeeze leading dimensions if present.
        while phase_arr.ndim > 3:
            phase_arr = phase_arr[0]
        # phase_arr shape: (T, X, n_phases)
        for ti, T in enumerate(T_vals):
            for xi, x in enumerate(x_vals):
                stable = {
                    p for p in phase_arr[ti, xi]
                    if isinstance(p, str) and p and p != ""
                }
                for ph in stable:
                    phase_points.setdefault(ph, []).append([round(x, 4), round(T, 1)])
    except Exception as exc:
        return {"error": f"Result extraction failed: {exc}"}

    if not phase_points:
        return {"error": "No phase data extracted — check TDB elements match"}

    lines = [
        {
            "label": ph,
            "points": pts,
            "color": _PHASE_COLORS[i % len(_PHASE_COLORS)],
            "scatter": True,
        }
        for i, (ph, pts) in enumerate(sorted(phase_points.items()))
    ]
    return {
        "lines": lines,
        "elements": elements,
        "T_range": [T_min, T_max],
        "x_label": f"x({el2})",
    }


def compute_diagram_from_file(
    tdb_path: str,
    elements: list[str],
    **kwargs: Any,
) -> dict[str, Any]:
    """Read TDB from disk path and compute diagram."""
    try:
        content = open(tdb_path).read()
    except OSError as exc:
        return {"error": f"Cannot read {tdb_path}: {exc}"}
    return compute_binary_diagram(content, elements, **kwargs)
