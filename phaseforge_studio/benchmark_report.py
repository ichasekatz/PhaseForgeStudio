"""Benchmark report generation for PhaseForgeStudio.

Produces human-readable text summaries, JSON export packages, and
publication-quality figure manifests from benchmark results.

A benchmark report includes:
- Executive summary (best model per metric).
- Per-mode results (energy, phase diagram, stability).
- Per-MLIP tables.
- Methodology notes (reference states, normalization, limitations).
- Provenance (software versions, timestamps, configuration).

All formatting utilities return plain strings or dicts — no I/O side effects.
Callers decide where and how to write output.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any

#: Section separator used in text reports.
_separator: str = "─" * 72


def _fmt_float(value: float | None, digits: int = 4, unit: str = "") -> str:
    """Format a float for report output, handling None gracefully.

    Args:
        value (float | None): Value to format.
        digits (int): Decimal places.
        unit (str): Optional unit suffix.

    Returns:
        Formatted string, e.g. ``"0.0123 eV/atom"`` or ``"N/A"``.
    """
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}{' ' + unit if unit else ''}"


def _rank_mlips_by(
    per_mlip: dict[str, Any],
    metric_key: str,
    lower_is_better: bool = True,
) -> list[tuple[str, float | None]]:
    """Rank MLIPs by a numeric metric value.

    Args:
        per_mlip (dict[str, Any]): Per-MLIP result dicts.
        metric_key (str): Key to extract from each MLIP dict.
        lower_is_better (bool): Sort ascending if True.

    Returns:
        Sorted list of (mlip_name, metric_value) tuples; None values last.
    """
    ranked = [(m, v.get(metric_key)) for m, v in per_mlip.items()]
    ranked.sort(
        key=lambda t: (t[1] is None, t[1] if lower_is_better else -(t[1] or 0))
    )
    return ranked


def build_text_report(benchmark_status: dict[str, Any]) -> str:
    """Build a human-readable benchmark report from a status dict.

    Args:
        benchmark_status (dict[str, Any]): Output of ``get_benchmark_status()``.

    Returns:
        Multi-line text report string.
    """
    lines: list[str] = []
    cfg = benchmark_status.get("config", {})
    system = benchmark_status.get("system", "Unknown")
    bm_id = benchmark_status.get("benchmark_id", "")
    state = benchmark_status.get("state", "unknown")
    created = benchmark_status.get("created_at", 0.0)
    created_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(created))

    lines += [
        "MLIP Phase Diagram Benchmark Report",
        _separator,
        f"Benchmark ID : {bm_id}",
        f"System       : {system}",
        f"Status       : {state}",
        f"Created      : {created_str}",
        f"Elements     : {', '.join(cfg.get('elements', []))}",
        f"MLIPs        : {', '.join(cfg.get('mlips', []))}",
        f"Phases       : {', '.join(cfg.get('phases', []))}",
        f"T range      : {cfg.get('t_min', 'N/A')} – {cfg.get('t_max', 'N/A')} K",
        f"Mode         : {cfg.get('mode', 'relaxed')}",
        f"Reference TDB: {cfg.get('reference_tdb', 'None')}",
        "",
    ]

    # Per-MLIP phase diagram results
    mlip_jobs = benchmark_status.get("mlip_jobs", {})
    if mlip_jobs:
        lines.append(_separator)
        lines.append("Per-MLIP Phase Diagram Results")
        lines.append(_separator)
        for mlip, job in mlip_jobs.items():
            elapsed = job.get("elapsed_s")
            elapsed_str = f"{elapsed:.0f}s" if elapsed else "N/A"
            tdb = job.get("tdb_path") or "None"
            status_str = job.get("state", "unknown")
            lines.append(f"\n  [{mlip}]")
            lines.append(f"    State   : {status_str}")
            lines.append(f"    Runtime : {elapsed_str}")
            lines.append(f"    TDB     : {tdb}")
            m = job.get("metrics")
            if m and m.get("available"):
                cls = m.get("classification", {})
                bnd = m.get("boundary", {})
                lines.append(f"    F1      : {_fmt_float(cls.get('f1'))}")
                lines.append(f"    Accuracy: {_fmt_float(cls.get('accuracy'))}")
                lines.append(f"    MAD-T   : {_fmt_float(bnd.get('mad_t'), unit='K')}")
                lines.append(f"    RMSD-T  : {_fmt_float(bnd.get('rmsd_t'), unit='K')}")
            elif m and not m.get("available"):
                lines.append(f"    Metrics : {m.get('error', 'unavailable')}")

    # Energy benchmark results (if present in extended status)
    energy = benchmark_status.get("energy_result")
    if energy and energy.get("available"):
        lines += ["", _separator, "Energy Benchmark Results", _separator]
        for mlip, v in energy.get("mlips", {}).items():
            lines.append(f"\n  [{mlip}]")
            lines.append(f"    Energy MAE   : {_fmt_float(v.get('energy_mae'), unit='eV/atom')}")
            lines.append(f"    Energy RMSE  : {_fmt_float(v.get('energy_rmse'), unit='eV/atom')}")
            lines.append(f"    Formation MAE: {_fmt_float(v.get('formation_energy_mae'), unit='eV/atom')}")
            lines.append(f"    Structures   : {v.get('n_evaluated', 'N/A')}/{v.get('n_structures', 'N/A')}")

    # Stability results (if present)
    stability = benchmark_status.get("stability_result")
    if stability and stability.get("available"):
        lines += ["", _separator, "Phase Stability Results", _separator]
        for mlip, v in stability.get("mlips", {}).items():
            lines.append(f"\n  [{mlip}]")
            hull = v.get("convex_hull", {})
            spinodal = v.get("spinodal", {})
            if hull.get("available"):
                n_stable = len(hull.get("stable_compositions", []))
                lines.append(f"    Stable compositions on hull : {n_stable}")
            if spinodal.get("available"):
                lines.append(f"    Spinodal boundaries found   : {spinodal.get('n_spinodal_boundaries', 0)}")

    # Methodology note
    lines += [
        "",
        _separator,
        "Methodology Notes",
        _separator,
        "• Formation energies reference zero-K elemental ground-state structures.",
        "• Vibrational and thermal contributions excluded unless explicitly computed.",
        "• Phase classification uses normalised phase names (sublattice suffixes stripped).",
        "• Phase boundary metrics only reported where matching boundaries exist.",
        "• Mode A (fixed-structure evaluation) logs a warning and runs Mode B",
        "  when sqscal does not support structure reuse.",
        "",
    ]

    # Provenance
    lines += [
        _separator,
        "Provenance",
        _separator,
        f"Generated    : {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        f"Platform     : {platform.platform()}",
        f"Python       : {platform.python_version()}",
        "",
    ]

    return "\n".join(lines)


def build_json_export(
    benchmark_status: dict[str, Any],
    *,
    energy_result: dict[str, Any] | None = None,
    stability_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a self-contained JSON export package from benchmark results.

    Strips large ``results`` sub-dicts to keep the export manageable; raw
    per-structure data is preserved in the benchmark run directory.

    Args:
        benchmark_status (dict[str, Any]): Output of ``get_benchmark_status()``.
        energy_result (dict | None): Energy mode result dict.
        stability_result (dict | None): Stability mode result dict.

    Returns:
        JSON-serialisable export dict.
    """
    # Slim down mlip_jobs: drop raw log and large result dicts
    slim_jobs: dict[str, Any] = {}
    for mlip, job in benchmark_status.get("mlip_jobs", {}).items():
        slim_jobs[mlip] = {
            "state": job.get("state"),
            "elapsed_s": job.get("elapsed_s"),
            "tdb_path": job.get("tdb_path"),
            "png_paths": job.get("png_paths", []),
            "metrics": job.get("metrics"),
        }

    export: dict[str, Any] = {
        "format_version": "1.0",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "benchmark_id": benchmark_status.get("benchmark_id"),
        "system": benchmark_status.get("system"),
        "state": benchmark_status.get("state"),
        "config": benchmark_status.get("config", {}),
        "mlip_phase_diagram": slim_jobs,
        "provenance": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
    }

    if energy_result and energy_result.get("available"):
        slim_energy: dict[str, Any] = {}
        for mlip, v in energy_result.get("mlips", {}).items():
            slim_energy[mlip] = {
                k: v.get(k)
                for k in ("energy_mae", "energy_rmse", "energy_max_ae", "formation_energy_mae", "n_structures", "n_failed")
            }
        export["energy_benchmark"] = {
            "available": True,
            "reference_path": energy_result.get("reference_path"),
            "mlips": slim_energy,
        }

    if stability_result and stability_result.get("available"):
        slim_stab: dict[str, Any] = {}
        for mlip, v in stability_result.get("mlips", {}).items():
            hull = v.get("convex_hull", {})
            spin = v.get("spinodal", {})
            slim_stab[mlip] = {
                "hull_available": hull.get("available", False),
                "n_stable": len(hull.get("stable_compositions", [])),
                "spinodal_available": spin.get("available", False),
                "n_spinodal": spin.get("n_spinodal_boundaries"),
            }
        export["stability_benchmark"] = {
            "available": True,
            "elements": stability_result.get("elements"),
            "temperatures": stability_result.get("temperatures"),
            "mlips": slim_stab,
        }

    return export


def write_report(
    run_dir: Path,
    benchmark_status: dict[str, Any],
    *,
    energy_result: dict[str, Any] | None = None,
    stability_result: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Write text and JSON reports to the benchmark run directory.

    Args:
        run_dir (Path): Root directory of the benchmark run.
        benchmark_status (dict[str, Any]): Status dict from adapter.
        energy_result (dict | None): Optional energy mode result.
        stability_result (dict | None): Optional stability mode result.

    Returns:
        Dict with ``text_path`` and ``json_path`` as absolute path strings.
    """
    report_dir = run_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    text_path = report_dir / "benchmark_report.txt"
    json_path = report_dir / "benchmark_export.json"

    text_content = build_text_report(benchmark_status)
    text_path.write_text(text_content, encoding="utf-8")

    json_content = build_json_export(
        benchmark_status,
        energy_result=energy_result,
        stability_result=stability_result,
    )
    json_path.write_text(json.dumps(json_content, indent=2), encoding="utf-8")

    return {"text_path": str(text_path), "json_path": str(json_path)}
