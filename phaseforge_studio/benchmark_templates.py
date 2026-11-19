"""Predefined benchmark configuration templates for PhaseForgeStudio.

Each template is a dict of keyword arguments compatible with
``create_and_launch_benchmark()`` in ``benchmark_adapter``.  Templates provide
scientifically sensible defaults but are fully overridable.

Available templates:

- ``binary_phase_diagram`` — Binary T–X phase diagram, several MLIPs.
- ``diboride_stability`` — Group IV–V diboride AlB2 miscibility analysis.
- ``multicomponent_solid_solution`` — HEA-style multicomponent assessment.
- ``energy_reference`` — Energy/force/stress vs DFT reference dataset.
"""

from __future__ import annotations

from typing import Any


templates: dict[str, dict[str, Any]] = {
    "binary_phase_diagram": {
        "name": "Binary Phase Diagram Benchmark",
        "description": (
            "Compare multiple MLIPs on a binary T–X phase diagram. "
            "Runs the full PhaseForge pipeline for each MLIP, generates "
            "pycalphad phase diagrams, and computes classification metrics "
            "against an optional reference TDB."
        ),
        "defaults": {
            "elements": ["Cu", "Zr"],
            "mlips": ["grace"],
            "phases": ["FCC_A1", "BCC_A2", "LIQUID"],
            "level": 2,
            "t_min": 300.0,
            "t_max": 2500.0,
            "t_step": 100.0,
            "x_step": 0.02,
            "mode": "relaxed",
            "benchmark_mode": "phase_diagram",
        },
        "notes": [
            "Cu–Zr is a well-characterized binary with assessed experimental data.",
            "Replace elements with your target system.",
            "Provide a reference TDB from ORCHID or literature for quantitative metrics.",
        ],
    },
    "diboride_stability": {
        "name": "Diboride Stability Benchmark",
        "description": (
            "Benchmarks MLIP predictions of AlB2-structure solid solutions "
            "in Group IV–V diboride systems (e.g. ZrB₂–TaB₂). "
            "Tests whether each MLIP predicts one homogeneous AlB2 phase "
            "or decomposition into two compositionally distinct solid solutions."
        ),
        "defaults": {
            "elements": ["Zr", "Ta", "B"],
            "mlips": ["grace"],
            "phases": ["ALPHAB2", "LIQUID", "BCC_A2"],
            "level": 2,
            "t_min": 300.0,
            "t_max": 3500.0,
            "t_step": 200.0,
            "x_step": 0.02,
            "mode": "relaxed",
            "benchmark_mode": "stability",
        },
        "notes": [
            "Target: determine miscibility gap in the AlB2 structure.",
            "Requires ALPHAB2 or equivalent AlB2-structure phase in PhaseForge.",
            "Spinodal and common-tangent analysis enabled in stability mode.",
            "Compare MLIP predictions of decomposition T vs experimental solidus.",
        ],
    },
    "multicomponent_solid_solution": {
        "name": "Multicomponent Solid Solution Benchmark",
        "description": (
            "Assess MLIP predictions for a multicomponent alloy system using "
            "SQS-generated structures.  Evaluates formation energies, "
            "thermodynamic stability, and temperature-dependent phase equilibria."
        ),
        "defaults": {
            "elements": ["Ni", "Cr", "Fe", "Co"],
            "mlips": ["grace"],
            "phases": ["FCC_A1", "BCC_A2", "LIQUID"],
            "level": 2,
            "t_min": 300.0,
            "t_max": 2000.0,
            "t_step": 100.0,
            "x_step": 0.05,
            "mode": "relaxed",
            "benchmark_mode": "phase_diagram",
        },
        "notes": [
            "NiCrFeCo is the canonical Cantor alloy — well-characterized by DFT and experiment.",
            "Replace elements with your target multicomponent system.",
            "Higher SQS level (3) recommended for 4+ component systems.",
            "Phase diagram mode generates pseudo-binary sections for each pair.",
        ],
    },
    "energy_reference": {
        "name": "Energy Reference Benchmark",
        "description": (
            "Compare MLIP energy predictions against a DFT reference dataset. "
            "Evaluates total energies, formation enthalpies, and forces "
            "without constructing thermodynamic models."
        ),
        "defaults": {
            "elements": ["Al", "Ni"],
            "mlips": ["grace"],
            "phases": ["FCC_A1"],
            "level": 1,
            "t_min": 0.0,
            "t_max": 300.0,
            "t_step": 300.0,
            "x_step": 0.05,
            "mode": "fixed",
            "benchmark_mode": "energy",
        },
        "notes": [
            "Provide a DFT reference JSON with structure energies and compositions.",
            "Reference JSON format: {\"structures\": {\"POSCAR_001\": {\"energy_per_atom\": -3.5, \"composition\": {\"Al\": 4, \"Ni\": 4}}}, \"elemental_references\": {\"Al\": -3.74, \"Ni\": -5.46}}",
            "Mode A (fixed-structure) is used here to isolate energy prediction accuracy.",
            "Forces and stresses are computed when the MLIP supports them.",
        ],
    },
}


def get_template(name: str) -> dict[str, Any] | None:
    """Return a template by name, or None if not found.

    Args:
        name (str): Template key, e.g. ``"binary_phase_diagram"``.

    Returns:
        Template dict with ``name``, ``description``, ``defaults``, and ``notes``.
    """
    return templates.get(name)


def list_templates() -> list[dict[str, Any]]:
    """Return summary list of all available templates.

    Returns:
        List of dicts with ``key``, ``name``, ``description``.
    """
    return [
        {"key": k, "name": v["name"], "description": v["description"]}
        for k, v in templates.items()
    ]


def apply_template(name: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return template defaults merged with caller overrides.

    Args:
        name (str): Template key.
        overrides (dict | None): Fields that override the template defaults.

    Returns:
        Merged config dict ready for ``create_and_launch_benchmark()``.

    Raises:
        KeyError: When the template name is not found.
    """
    tmpl = templates.get(name)
    if tmpl is None:
        raise KeyError(f"Unknown template: {name!r}. Available: {list(templates)}")
    result = dict(tmpl["defaults"])
    if overrides:
        result.update(overrides)
    return result
