"""Benchmark mode implementations for MLIP evaluation.

Implements four benchmark modes that share a common structure-dataset and
caching layer:

- Mode 1 — Energy: compare MLIP energies/forces/stresses against DFT reference.
- Mode 2 — Phase Diagram: construct TDBs and compare pycalphad phase diagrams.
  (Dispatched via benchmark_adapter.py; mode-specific helpers live here.)
- Mode 3 — Phase Stability: compare convex hulls, Gibbs energies, miscibility gaps.
- Mode 4 — Complete: run all applicable modes, reusing cached intermediates.

All heavy imports (ASE, pycalphad, numpy) are lazy.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from phaseforge_studio.benchmark_cache import (
    is_cache_valid,
    load_from_cache,
    make_cache_key,
    save_to_cache,
)


# ---------------------------------------------------------------------------
# Mode constants
# ---------------------------------------------------------------------------

mode_names: dict[str, str] = {
    "energy": "Energy Benchmark",
    "phase_diagram": "Phase Diagram Benchmark",
    "stability": "Phase Stability Benchmark",
    "complete": "Complete Benchmark",
}

#: Reference-state normalization convention used for formation energies.
#: Energies are referenced to elemental ground-state structures (zero-K, 0 Pa).
formation_energy_ref_note: str = (
    "Formation energies reference zero-K elemental ground-state structures. "
    "Vibrational and thermal contributions are excluded unless explicitly "
    "computed by the MLIP."
)


# ---------------------------------------------------------------------------
# Mode 1 — Energy Benchmark
# ---------------------------------------------------------------------------


def _load_reference_energies(reference_path: Path) -> dict[str, Any]:
    """Load a DFT reference energy dataset from a JSON file.

    Expected format::

        {
          "structures": {
            "POSCAR_001": {"energy_per_atom": -3.42, "forces": [...], "stress": [...], "composition": {"Cu": 4, "Zr": 4}},
            ...
          },
          "elemental_references": {"Cu": -3.72, "Zr": -8.54}
        }

    Args:
        reference_path (Path): Path to DFT reference JSON file.

    Returns:
        Loaded reference dict, or ``{}`` on failure.
    """
    if not reference_path.exists():
        return {}
    try:
        return json.loads(reference_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _formation_energy(
    total_energy_per_atom: float,
    composition: dict[str, int],
    elemental_refs: dict[str, float],
) -> float | None:
    """Compute formation energy per atom relative to elemental references.

    Args:
        total_energy_per_atom (float): Total MLIP energy per atom in eV/atom.
        composition (dict[str, int]): Atom counts per element.
        elemental_refs (dict[str, float]): Reference energy per atom per element in eV/atom.

    Returns:
        Formation energy in eV/atom, or None when references are missing.
    """
    n_total = sum(composition.values())
    if n_total == 0:
        return None
    weighted_ref = sum(
        (n / n_total) * elemental_refs.get(el, float("nan"))
        for el, n in composition.items()
    )
    if math.isnan(weighted_ref):
        return None
    return total_energy_per_atom - weighted_ref


def run_energy_benchmark(
    structures_dir: Path,
    reference_path: Path,
    mlips: list[str],
    cache_dir: Path,
    *,
    device: str = "cpu",
    use_cache: bool = True,
) -> dict[str, Any]:
    """Compare MLIP single-point energies against a DFT reference dataset.

    For each structure in ``structures_dir`` and each MLIP, computes energy
    per atom, formation energy, and (when available) forces and stresses.
    Caches per-structure per-MLIP results.

    Args:
        structures_dir (Path): Directory containing POSCAR structure files.
        reference_path (Path): DFT reference JSON (see ``_load_reference_energies``).
        mlips (list[str]): MLIP calculator names to evaluate.
        cache_dir (Path): Cache directory for intermediate results.
        device (str): Compute device (``"cpu"`` or ``"cuda"``).
        use_cache (bool): Whether to use cached MLIP calculations.

    Returns:
        Dict with per-MLIP metrics: ``energy_mae``, ``energy_rmse``,
        ``energy_max_ae``, ``formation_energy_mae``, ``force_mae`` (if
        available), ``n_structures``, ``n_failed``, ``results`` (per-structure
        dict), and ``available`` (bool).
    """
    reference = _load_reference_energies(reference_path)
    if not reference:
        return {"available": False, "error": f"Reference data not found at {reference_path}"}

    struct_refs = reference.get("structures", {})
    el_refs = reference.get("elemental_references", {})

    # Discover structure files
    struct_files = sorted(
        p for p in structures_dir.rglob("*")
        if p.is_file() and p.suffix.upper() in ("", ".POSCAR", ".CIF", ".XYZ")
        and p.name.upper().startswith("POSCAR") or p.suffix.lower() in (".cif", ".xyz")
    )
    if not struct_files:
        # Try looking for any files at all
        struct_files = [p for p in structures_dir.rglob("*") if p.is_file() and not p.suffix or p.suffix.lower() in (".vasp", ".poscar", ".cif", ".xyz")]
    if not struct_files:
        return {"available": False, "error": f"No structure files found in {structures_dir}"}

    per_mlip: dict[str, Any] = {}

    for mlip in mlips:
        mlip_results: dict[str, Any] = {}
        errors: list[str] = []

        for struct_path in struct_files:
            struct_key = struct_path.name
            ref_entry = struct_refs.get(struct_key, {})

            # Cache key: mlip + structure content hash
            from phaseforge_studio.benchmark_cache import hash_file
            s_hash = hash_file(struct_path)
            ckey = make_cache_key(mlip, structure_hash=s_hash, calculator_settings={"device": device})

            cached = load_from_cache(ckey, cache_dir) if use_cache else None
            if cached is not None:
                mlip_results[struct_key] = cached
                continue

            calc_result = _calculate_single(struct_path, mlip, device=device)
            if calc_result.get("error"):
                errors.append(f"{struct_key}: {calc_result['error']}")
                mlip_results[struct_key] = {"error": calc_result["error"]}
            else:
                mlip_results[struct_key] = calc_result
                save_to_cache(ckey, calc_result, cache_dir)

        # Aggregate metrics
        energy_errs: list[float] = []
        f_energy_errs: list[float] = []
        force_errs: list[float] = []
        n_failed = len(errors)

        for struct_key, result in mlip_results.items():
            if result.get("error"):
                continue
            ref = struct_refs.get(struct_key, {})
            if not ref:
                continue
            pred_epa = result.get("energy_per_atom")
            ref_epa = ref.get("energy_per_atom")
            if pred_epa is not None and ref_epa is not None:
                energy_errs.append(abs(pred_epa - ref_epa))
            comp = ref.get("composition", {})
            if comp and el_refs:
                pred_eform = _formation_energy(pred_epa, comp, el_refs) if pred_epa is not None else None
                ref_eform = _formation_energy(ref_epa, comp, el_refs) if ref_epa is not None else None
                if pred_eform is not None and ref_eform is not None:
                    f_energy_errs.append(abs(pred_eform - ref_eform))

        def _mae(vals: list[float]) -> float | None:
            return sum(vals) / len(vals) if vals else None

        def _rmse(vals: list[float]) -> float | None:
            return math.sqrt(sum(v * v for v in vals) / len(vals)) if vals else None

        per_mlip[mlip] = {
            "energy_mae": _mae(energy_errs),
            "energy_rmse": _rmse(energy_errs),
            "energy_max_ae": max(energy_errs) if energy_errs else None,
            "formation_energy_mae": _mae(f_energy_errs),
            "force_mae": _mae(force_errs) if force_errs else None,
            "n_structures": len(struct_files),
            "n_evaluated": len(struct_files) - n_failed,
            "n_failed": n_failed,
            "errors": errors[:10],
            "results": mlip_results,
        }

    return {
        "available": True,
        "mode": "energy",
        "mlips": per_mlip,
        "n_structures": len(struct_files),
        "reference_path": str(reference_path),
        "elemental_references": el_refs,
    }


def _calculate_single(struct_path: Path, mlip: str, *, device: str = "cpu") -> dict[str, Any]:
    """Run a single-point MLIP energy calculation on one structure.

    Uses MaterialsFramework's calculator registry when available; falls back
    to a lightweight error stub so callers can distinguish capability absence
    from calculation failures.

    Args:
        struct_path (Path): Path to a POSCAR/CIF/XYZ structure file.
        mlip (str): Calculator name as registered in MaterialsFramework.
        device (str): Compute device.

    Returns:
        Dict with ``energy_per_atom`` (float), ``forces`` (list | None),
        ``stress`` (list | None), ``n_atoms`` (int), or ``error`` (str).
    """
    try:
        import ase.io as aio
        atoms = aio.read(str(struct_path))
    except ImportError:
        return {"error": "ASE not installed; cannot read structures"}
    except Exception as exc:
        return {"error": f"Structure read failed: {exc}"}

    try:
        from materialsframework.calculators.registry import get_calculator
        calc = get_calculator(mlip, device=device)
        atoms.calc = calc
        energy = float(atoms.get_potential_energy())
        n = len(atoms)
        result: dict[str, Any] = {
            "energy_per_atom": energy / n,
            "n_atoms": n,
        }
        try:
            result["forces"] = atoms.get_forces().tolist()
        except Exception:
            result["forces"] = None
        try:
            result["stress"] = atoms.get_stress().tolist()
        except Exception:
            result["stress"] = None
        return result
    except ImportError:
        return {"error": f"MaterialsFramework not installed; cannot use calculator {mlip}"}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Mode 3 — Phase Stability Benchmark
# ---------------------------------------------------------------------------


def _gibbs_energy_grid(
    tdb_path: Path,
    elements: list[str],
    *,
    temperature: float = 1000.0,
    n_points: int = 50,
) -> dict[str, Any]:
    """Compute Gibbs energy vs composition for a binary system at fixed T.

    Uses pycalphad's ``calculate()`` to get G_m on a composition grid.

    Args:
        tdb_path (Path): TDB file path.
        elements (list[str]): Binary element pair.
        temperature (float): Temperature in K.
        n_points (int): Number of composition grid points.

    Returns:
        Dict with ``x`` (list[float]), ``G`` (list[float]), ``elements``,
        ``temperature``, and ``available`` (bool).
    """
    if len(elements) != 2:
        return {"available": False, "error": "Stability grid requires binary system"}
    try:
        import numpy as np
        from pycalphad import Database, calculate
        from pycalphad import variables as v
    except ImportError:
        return {"available": False, "error": "pycalphad not installed"}
    try:
        dbf = Database(str(tdb_path))
    except Exception as exc:
        return {"available": False, "error": f"TDB parse error: {exc}"}

    el_a, el_b = [e.upper() for e in elements]
    comps = [el_a, el_b, "VA"]
    phases = list(dbf.phases.keys())
    x_arr = np.linspace(0.01, 0.99, n_points)

    g_min: list[float] = []
    for x_val in x_arr:
        g_phase_vals = []
        pts = {el_b: np.array([x_val]), el_a: np.array([1.0 - x_val])}
        for phase in phases:
            try:
                res = calculate(dbf, comps, phase, T=temperature, P=101325.0, points=pts)
                gm = float(np.nanmin(res.GM.values))
                if not math.isnan(gm):
                    g_phase_vals.append(gm)
            except Exception:
                pass
        g_min.append(min(g_phase_vals) if g_phase_vals else float("nan"))

    return {
        "available": True,
        "x": x_arr.tolist(),
        "G": g_min,
        "elements": [el_a, el_b],
        "temperature": temperature,
        "n_phases": len(phases),
    }


def _convex_hull(
    x: list[float],
    g: list[float],
) -> dict[str, Any]:
    """Compute the lower convex hull of G(x) and energy above hull.

    Args:
        x (list[float]): Composition values (mole fraction of B).
        g (list[float]): Gibbs energy values in J/mol at corresponding x.

    Returns:
        Dict with ``hull_x``, ``hull_G``, ``above_hull`` (G − convex_hull
        per point), ``stable_compositions`` (x values on hull), and
        ``available``.
    """
    try:
        import numpy as np
    except ImportError:
        return {"available": False, "error": "numpy not installed"}

    pts = [(xi, gi) for xi, gi in zip(x, g, strict=True) if not math.isnan(gi)]
    if len(pts) < 3:
        return {"available": False, "error": "Insufficient non-NaN points"}

    xs = np.array([p[0] for p in pts])
    gs = np.array([p[1] for p in pts])

    # Lower convex hull via sorting + monotone scan
    order = np.argsort(xs)
    xs_s, gs_s = xs[order], gs[order]

    hull_x: list[float] = [float(xs_s[0])]
    hull_g: list[float] = [float(gs_s[0])]
    for xi, gi in zip(xs_s[1:], gs_s[1:], strict=True):
        while (
            len(hull_x) >= 2
            and _cross(hull_x[-2], hull_g[-2], hull_x[-1], hull_g[-1], xi, gi) <= 0
        ):
            hull_x.pop()
            hull_g.pop()
        hull_x.append(float(xi))
        hull_g.append(float(gi))

    # Interpolate hull value at each composition point
    hull_interp = np.interp(xs, hull_x, hull_g)
    above = (gs - hull_interp).tolist()

    return {
        "available": True,
        "hull_x": hull_x,
        "hull_G": hull_g,
        "x": xs.tolist(),
        "above_hull": above,
        "stable_compositions": [float(xi) for xi, ai in zip(xs.tolist(), above, strict=True) if abs(ai) < 1.0],
    }


def _cross(x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> float:
    """2D cross product of vectors (p1→p2) and (p1→p3).

    Args:
        x1, y1 (float): Point 1.
        x2, y2 (float): Point 2.
        x3, y3 (float): Point 3.

    Returns:
        Cross product value; negative means right turn.
    """
    return (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)


def _spinodal_boundaries(
    x: list[float],
    g: list[float],
) -> dict[str, Any]:
    """Estimate spinodal boundaries from sign changes in d²G/dx².

    Uses finite differences to approximate the second derivative of G(x),
    then finds sign-change crossings (d²G/dx² = 0).

    Args:
        x (list[float]): Composition grid.
        g (list[float]): Gibbs energy grid.

    Returns:
        Dict with ``spinodal_x`` (list of spinodal compositions),
        ``d2G`` (list of second derivative values), ``available``.
    """
    try:
        import numpy as np
    except ImportError:
        return {"available": False, "error": "numpy not installed"}

    pairs = [(xi, gi) for xi, gi in zip(x, g, strict=True) if not math.isnan(gi)]
    if len(pairs) < 5:
        return {"available": False, "error": "Insufficient points for spinodal"}

    xs = np.array([p[0] for p in pairs])
    gs = np.array([p[1] for p in pairs])
    d2g = np.gradient(np.gradient(gs, xs), xs)

    spinodal_x: list[float] = []
    for i in range(len(d2g) - 1):
        if d2g[i] * d2g[i + 1] < 0:
            # Linear interpolation to find zero crossing
            x_zero = float(xs[i] - d2g[i] * (xs[i + 1] - xs[i]) / (d2g[i + 1] - d2g[i]))
            spinodal_x.append(x_zero)

    return {
        "available": True,
        "spinodal_x": spinodal_x,
        "d2G": d2g.tolist(),
        "x": xs.tolist(),
        "n_spinodal_boundaries": len(spinodal_x),
    }


def run_stability_benchmark(
    tdb_map: dict[str, Path],
    elements: list[str],
    *,
    temperatures: list[float] | None = None,
    n_grid: int = 50,
) -> dict[str, Any]:
    """Compare phase stability predictions across multiple MLIP TDB files.

    For each MLIP TDB, computes Gibbs energy curves, convex hull, and
    spinodal boundaries at specified temperatures.

    Args:
        tdb_map (dict[str, Path]): Mapping of MLIP name → TDB file path.
        elements (list[str]): Binary element pair, e.g. ``["Cu", "Zr"]``.
        temperatures (list[float] | None): Temperatures in K to evaluate;
            defaults to ``[300, 1000, 2000]``.
        n_grid (int): Composition grid density.

    Returns:
        Dict with per-MLIP results including ``gibbs_curves``,
        ``convex_hull``, ``spinodal``, ``n_stable_phases``.
    """
    if temperatures is None:
        temperatures = [300.0, 1000.0, 2000.0]

    per_mlip: dict[str, Any] = {}

    for mlip, tdb_path in tdb_map.items():
        if not tdb_path.exists():
            per_mlip[mlip] = {"available": False, "error": f"TDB not found: {tdb_path}"}
            continue

        gibbs_curves: dict[str, Any] = {}
        for t_val in temperatures:
            curve = _gibbs_energy_grid(tdb_path, elements, temperature=t_val, n_points=n_grid)
            gibbs_curves[str(int(t_val))] = curve

        # Use first successful temperature for hull/spinodal
        hull_result: dict[str, Any] = {}
        spinodal_result: dict[str, Any] = {}
        for t_val in temperatures:
            curve = gibbs_curves.get(str(int(t_val)), {})
            if curve.get("available") and curve.get("x") and curve.get("G"):
                hull_result = _convex_hull(curve["x"], curve["G"])
                spinodal_result = _spinodal_boundaries(curve["x"], curve["G"])
                break

        per_mlip[mlip] = {
            "available": True,
            "gibbs_curves": gibbs_curves,
            "convex_hull": hull_result,
            "spinodal": spinodal_result,
        }

    return {
        "available": True,
        "mode": "stability",
        "elements": elements,
        "temperatures": temperatures,
        "mlips": per_mlip,
    }


# ---------------------------------------------------------------------------
# Mode 4 — Complete Benchmark (dispatcher)
# ---------------------------------------------------------------------------


def run_complete_benchmark(
    *,
    structures_dir: Path | None = None,
    reference_path: Path | None = None,
    tdb_map: dict[str, Path] | None = None,
    elements: list[str],
    mlips: list[str],
    cache_dir: Path,
    temperatures: list[float] | None = None,
) -> dict[str, Any]:
    """Dispatch all applicable benchmark modes and merge results.

    Reuses TDB map from Phase Diagram mode for Stability mode.
    Marks individual modes as unavailable with reasons rather than failing.

    Args:
        structures_dir (Path | None): Structure directory for energy mode.
        reference_path (Path | None): DFT reference for energy mode.
        tdb_map (dict[str, Path] | None): MLIP→TDB for stability mode.
        elements (list[str]): Element list.
        mlips (list[str]): MLIP names.
        cache_dir (Path): Cache directory.
        temperatures (list[float] | None): Temperatures for stability mode.

    Returns:
        Dict with ``energy``, ``stability``, ``mode_availability`` sections.
    """
    start = time.time()
    result: dict[str, Any] = {
        "mode": "complete",
        "elements": elements,
        "mlips": mlips,
        "mode_availability": {},
    }

    # Energy mode
    if structures_dir and reference_path:
        result["energy"] = run_energy_benchmark(
            structures_dir, reference_path, mlips, cache_dir
        )
        result["mode_availability"]["energy"] = result["energy"].get("available", False)
    else:
        result["energy"] = {"available": False, "error": "No structures_dir or reference_path provided"}
        result["mode_availability"]["energy"] = False

    # Stability mode (needs TDB map — built after phase diagram mode)
    if tdb_map:
        result["stability"] = run_stability_benchmark(tdb_map, elements, temperatures=temperatures)
        result["mode_availability"]["stability"] = result["stability"].get("available", False)
    else:
        result["stability"] = {"available": False, "error": "No TDB map provided; run Phase Diagram mode first"}
        result["mode_availability"]["stability"] = False

    result["elapsed_s"] = time.time() - start
    return result


# ---------------------------------------------------------------------------
# Utility: mode result summary for HTTP status
# ---------------------------------------------------------------------------


def summarise_mode_result(result: dict[str, Any]) -> dict[str, Any]:
    """Extract a compact, JSON-serialisable summary from a mode result.

    Args:
        result (dict[str, Any]): Full mode output dict.

    Returns:
        Compact summary suitable for the benchmark status API endpoint.
    """
    mode = result.get("mode", "unknown")
    summary: dict[str, Any] = {
        "mode": mode,
        "available": result.get("available", False),
    }

    if mode == "energy" and result.get("mlips"):
        summary["mlip_summary"] = {
            m: {
                "energy_mae": v.get("energy_mae"),
                "energy_rmse": v.get("energy_rmse"),
                "formation_energy_mae": v.get("formation_energy_mae"),
                "n_evaluated": v.get("n_evaluated"),
                "n_failed": v.get("n_failed"),
            }
            for m, v in result["mlips"].items()
        }

    if mode == "stability" and result.get("mlips"):
        summary["mlip_summary"] = {
            m: {
                "hull_available": v.get("convex_hull", {}).get("available", False),
                "spinodal_available": v.get("spinodal", {}).get("available", False),
                "n_spinodal": v.get("spinodal", {}).get("n_spinodal_boundaries"),
            }
            for m, v in result["mlips"].items()
        }

    return summary
