"""MaterialsFramework analyzer dispatch and JSON serialisation helpers."""

from __future__ import annotations

import traceback as tb
from pathlib import Path
from typing import Any

analyzer_info: dict[str, Any] = {
    "eos": {
        "label": "Equation of State",
        "description": "Birch-Murnaghan EOS: bulk modulus, equilibrium volume",
        "returns": ["volumes", "energies", "b0_GPa", "v0", "e0"],
        "chart": "ev",
    },
    "elastic_constants": {
        "label": "Elastic Constants",
        "description": "Full Cij tensor + Young's, bulk, shear moduli, Poisson ratio",
        "returns": ["Cij", "youngs_modulus", "voigt_bulk_modulus", "voigt_shear_modulus", "poisson_ratio"],
        "chart": None,
    },
    "cubic_elastic_constants": {
        "label": "Cubic Elastic Constants",
        "description": "Elastic constants for cubic systems (C11, C12, C44) + derived moduli",
        "returns": ["C11", "C12", "C44", "youngs_modulus", "bulk_modulus", "shear_modulus", "poisson_ratio"],
        "chart": None,
    },
    "formation_energy": {
        "label": "Formation Energy",
        "description": "ΔHf per atom relative to pure element ground states",
        "returns": ["formation_energy"],
        "chart": None,
    },
    "bain": {
        "label": "Bain Path",
        "description": "Energy along BCC↔FCC Bain transformation path",
        "returns": ["c_a_list", "energy_list"],
        "chart": "bain",
    },
    "usfe": {
        "label": "USFE",
        "description": "Unstable stacking fault energy via GSFE curve",
        "returns": ["usfe_mJ_m2", "gsfe_curve"],
        "chart": "gsfe",
    },
    "cte": {
        "label": "Thermal Expansion (CTE)",
        "description": "Volumetric coefficient of thermal expansion vs temperature",
        "returns": ["temperatures", "volumes", "cte", "cte_ppm"],
        "chart": "cte",
    },
    "surface": {
        "label": "Surface Energy",
        "description": "Surface energies for low-index Miller planes",
        "returns": ["slabs"],
        "chart": None,
    },
    "sbe": {
        "label": "Surface Binding Energy",
        "description": "Surface binding energies and vacancy formation per termination",
        "returns": ["best_miller_index", "best_surface_energy", "avg_surface_binding_energy"],
        "chart": None,
    },
    "phonopy": {
        "label": "Phonon DOS/Spectrum",
        "description": "Phonon density of states and band structure via phonopy",
        "returns": ["frequencies", "dos", "band_structure"],
        "chart": "phonon",
    },
    "phono3py": {
        "label": "Thermal Conductivity",
        "description": "Lattice thermal conductivity via phono3py",
        "returns": ["thermal_conductivity"],
        "chart": None,
    },
    "neb": {
        "label": "NEB",
        "description": "Nudged elastic band: minimum energy path between two structures",
        "returns": ["images", "energies", "barrier"],
        "chart": "neb",
    },
    "h_solubility": {
        "label": "H Solubility",
        "description": "Hydrogen solubility and interstitial site energies",
        "returns": ["solubility", "site_energies"],
        "chart": None,
    },
    "annni": {
        "label": "ANNNI Stacking Fault",
        "description": "Axial next-nearest-neighbor Ising stacking fault energies",
        "returns": ["sfe", "isf", "usf"],
        "chart": None,
    },
}


def _json_default(obj: Any) -> Any:
    """JSON serialiser for numpy scalar and array types.

    Args:
        obj: Object that the standard JSON encoder cannot handle.

    Returns:
        A JSON-serialisable Python primitive.

    Raises:
        TypeError: When ``obj`` is not a recognised numpy type.
    """
    import numpy as np

    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def _run_analysis(cfg: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Run a MaterialsFramework analyzer on a structure file.

    Args:
        cfg (dict[str, Any]): Live server config (used for path1 and device).
        params (dict[str, Any]): Request parameters: ``rel_path``, ``analyzer``,
            ``calculator``, ``device``, ``is_relaxed``.

    Returns:
        Dict with ``analyzer`` key plus analyzer-specific result fields,
        or ``{"error": str}`` on failure.
    """
    import sys

    import numpy as np  # noqa: PLC0415

    mf_src = Path(__file__).parent.parent / "MaterialsFramework" / "src"
    blade_src = Path(__file__).parent.parent.parent / "BLADE" / "src"
    for p in (str(mf_src), str(blade_src)):
        if p not in sys.path:
            sys.path.insert(0, p)

    rel_path: str = params.get("rel_path", "")
    analyzer_name: str = params.get("analyzer", "eos")
    calc_name: str = params.get("calculator", cfg.get("calculator", "grace"))
    device: str = params.get("device", cfg.get("device", "cpu"))
    is_relaxed: bool = bool(params.get("is_relaxed", True))

    if not rel_path:
        return {"error": "No structure path provided"}

    path1 = Path(cfg["path1"]).expanduser().resolve()
    struct_path = path1 / rel_path
    if not struct_path.exists():
        return {"error": f"File not found: {rel_path}"}

    try:
        from ase.io import read as ase_read

        atoms = ase_read(str(struct_path))

        from materialsframework.calculators.registry import get_calculator

        _device_calcs = {"grace", "mace", "chgnet", "orb", "sevennet", "m3gnet", "mattersim"}
        calc_kwargs: dict[str, Any] = {}
        if device and calc_name in _device_calcs:
            calc_kwargs["device"] = device
        calculator = get_calculator(calc_name, **calc_kwargs)

        if analyzer_name == "eos":
            from materialsframework.analysis.eos import EOSAnalyzer

            analyzer = EOSAnalyzer(calculator=calculator)
            # Compute V-E data once; try progressively simpler EOS models if fit fails
            from pymatgen.analysis.eos import EOS, EOSError

            structure = analyzer._ensure_relaxed(atoms, is_relaxed)
            structures = analyzer.eos_transformation.apply_transformation(structure)
            prev_relax_cell = analyzer.calculator.relax_cell
            analyzer.calculator.relax_cell = False
            try:
                raw = [analyzer.calculator.relax(structure=s) for s in structures]
                volume_list = [r["final_structure"].volume for r in raw]
                energy_list = [r["energy"] for r in raw]
            finally:
                analyzer.calculator.relax_cell = prev_relax_cell

            fit_result: dict[str, float] = {}
            for eos_name in ("birch_murnaghan", "murnaghan", "vinet"):
                try:
                    f = EOS(eos_name=eos_name).fit(volumes=volume_list, energies=energy_list)
                    fit_result = {"b0_GPa": float(f.b0_GPa), "v0": float(f.v0), "e0": float(f.e0), "eos_name": eos_name}
                    break
                except (EOSError, Exception):
                    continue

            return {
                "analyzer": "eos",
                "volumes": [float(v) for v in volume_list],
                "energies": [float(e) for e in energy_list],
                **fit_result,
            }

        if analyzer_name == "elastic_constants":
            from materialsframework.analysis.elastic_constants import ElasticConstantsAnalyzer

            result = ElasticConstantsAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            scalar = {k: float(v) for k, v in result.items() if isinstance(v, (int, float))}
            return {"analyzer": "elastic_constants", **scalar}

        if analyzer_name == "formation_energy":
            from materialsframework.analysis.formation_energy import FormationEnergyAnalyzer

            result = FormationEnergyAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            return {"analyzer": "formation_energy", "formation_energy": float(result["formation_energy"])}

        if analyzer_name == "bain":
            from materialsframework.analysis.bain import BainPathAnalyzer

            result = BainPathAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            return {
                "analyzer": "bain",
                "c_a_list": [float(v) for v in result["c_a_list"]],
                "energy_list": [float(v) for v in result["energy_list"]],
            }

        if analyzer_name == "usfe":
            from materialsframework.analysis.usfe import USFEAnalyzer

            result = USFEAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            return {
                "analyzer": "usfe",
                "usfe_mJ_m2": float(result["usfe_mJ_m2"]),
                "gsfe_curve": result.get("gsfe_curve", []),
                "slip_plane": result.get("slip_plane", ""),
            }

        if analyzer_name == "cubic_elastic_constants":
            from materialsframework.analysis.cubic_elastic_constants import CubicElasticConstantsAnalyzer

            result = CubicElasticConstantsAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            return {
                "analyzer": "cubic_elastic_constants",
                **{k: float(v) for k, v in result.items() if isinstance(v, (int, float))},
            }

        if analyzer_name == "cte":
            from materialsframework.analysis.cte import CTEAnalyzer

            result = CTEAnalyzer(calculator=calculator).calculate(atoms)
            return {
                "analyzer": "cte",
                "temperatures": [float(t) for t in result["temperatures"]],
                "volumes": [float(v) for v in result["volumes"]],
                "cte": [float(c) for c in result["cte"]],
                "cte_ppm": [float(c) for c in result["cte_ppm"]],
            }

        if analyzer_name == "surface":
            from materialsframework.analysis.surface import SurfaceAnalyzer

            result = SurfaceAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            slabs = []
            for s in result.get("slabs", []):
                slabs.append(
                    {
                        k: (float(v) if isinstance(v, (int, float, np.floating)) else str(v))
                        for k, v in s.items()
                        if not hasattr(v, "__len__")
                    }
                )
            return {"analyzer": "surface", "slabs": slabs}

        if analyzer_name == "sbe":
            from materialsframework.analysis.sbe import SBEAnalyzer

            result = SBEAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            scalar = {k: float(v) for k, v in result.items() if isinstance(v, (int, float, np.floating))}
            return {"analyzer": "sbe", **scalar}

        if analyzer_name == "phonopy":
            from materialsframework.analysis.phonopy import PhonopyAnalyzer

            result = PhonopyAnalyzer(calculator=calculator).calculate(atoms)
            out: dict[str, Any] = {"analyzer": "phonopy"}
            for k, v in result.items():
                if hasattr(v, "tolist"):
                    out[k] = v.tolist()
                elif isinstance(v, (int, float)):
                    out[k] = float(v)
                else:
                    out[k] = str(v)
            return out

        if analyzer_name == "phono3py":
            from materialsframework.analysis.phono3py import Phono3pyAnalyzer

            result = Phono3pyAnalyzer(calculator=calculator).calculate(atoms)
            return {
                "analyzer": "phono3py",
                "thermal_conductivity": (
                    float(result.get("kappa", 0.0)) if hasattr(result.get("kappa"), "__float__") else str(result.get("kappa", ""))
                ),
            }

        if analyzer_name == "h_solubility":
            from materialsframework.analysis.h_solubility import HSolubilityAnalyzer

            result = HSolubilityAnalyzer(calculator=calculator).calculate(atoms, is_relaxed=is_relaxed)
            scalar = {k: float(v) for k, v in result.items() if isinstance(v, (int, float, np.floating))}
            return {"analyzer": "h_solubility", **scalar}

        if analyzer_name == "annni":
            from materialsframework.analysis.annni import ANNNIStackingFaultAnalyzer

            result = ANNNIStackingFaultAnalyzer(calculator=calculator).calculate(atoms)
            scalar = {k: float(v) for k, v in result.items() if isinstance(v, (int, float, np.floating))}
            return {"analyzer": "annni", **scalar}

        if analyzer_name == "neb":
            return {"error": "NEB requires two structures; not supported via single-file analysis"}

        return {"error": f"Unknown analyzer: {analyzer_name}"}

    except Exception as exc:
        return {"error": str(exc), "traceback": tb.format_exc()}
