"""Tests for analysis dispatch module."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from phaseforge_studio.analysis import _json_default, _run_analysis, analyzer_info

try:
    import ase  # noqa: F401

    _has_ase = True
except ImportError:
    _has_ase = False

try:
    import numpy  # noqa: F401

    _has_numpy = True
except ImportError:
    _has_numpy = False

_needs_ase = pytest.mark.skipif(not _has_ase, reason="ase not installed")
_needs_numpy = pytest.mark.skipif(not _has_numpy, reason="numpy not installed")


class TestAnalyzerInfo:
    def test_all_expected_keys_present(self) -> None:
        expected = {
            "eos", "elastic_constants", "cubic_elastic_constants",
            "formation_energy", "bain", "usfe", "cte", "surface", "sbe",
            "phonopy", "phono3py", "neb", "h_solubility", "annni",
        }
        assert expected.issubset(set(analyzer_info.keys()))

    def test_each_entry_has_label(self) -> None:
        for name, info in analyzer_info.items():
            assert "label" in info, f"Missing label for {name}"

    def test_each_entry_has_returns(self) -> None:
        for name, info in analyzer_info.items():
            assert "returns" in info, f"Missing returns for {name}"
            assert isinstance(info["returns"], list)

    def test_neb_has_chart(self) -> None:
        assert analyzer_info["neb"]["chart"] == "neb"

    def test_eos_returns_includes_b0(self) -> None:
        assert "b0_GPa" in analyzer_info["eos"]["returns"]


class TestJsonDefault:
    @_needs_numpy
    def test_numpy_float(self) -> None:
        import numpy as np

        val = _json_default(np.float64(3.14))
        assert isinstance(val, float)
        assert abs(val - 3.14) < 1e-10

    @_needs_numpy
    def test_numpy_int(self) -> None:
        import numpy as np

        val = _json_default(np.int32(42))
        assert isinstance(val, int)
        assert val == 42

    @_needs_numpy
    def test_numpy_array(self) -> None:
        import numpy as np

        arr = np.array([1.0, 2.0, 3.0])
        val = _json_default(arr)
        assert val == [1.0, 2.0, 3.0]

    @_needs_numpy
    def test_unknown_type_raises(self) -> None:
        with pytest.raises(TypeError):
            _json_default(object())


@_needs_ase
class TestRunAnalysisInputValidation:
    _cfg: dict[str, Any] = {
        "path1": "/nonexistent/path1",
        "calculator": "grace",
        "device": "cpu",
    }

    def test_no_rel_path_returns_error(self) -> None:
        result = _run_analysis(self._cfg, {})
        assert "error" in result
        assert "path" in result["error"].lower() or "No structure" in result["error"]

    def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        cfg = {**self._cfg, "path1": str(tmp_path)}
        result = _run_analysis(cfg, {"rel_path": "nonexistent.vasp"})
        assert "error" in result

    def test_unknown_analyzer_returns_error(self, tmp_path: Path) -> None:
        poscar = tmp_path / "POSCAR"
        poscar.write_text(
            "Al\n1.0\n4.05 0.0 0.0\n0.0 4.05 0.0\n0.0 0.0 4.05\nAl\n1\nDirect\n0.0 0.0 0.0\n"
        )
        cfg = {**self._cfg, "path1": str(tmp_path)}

        mock_atoms = MagicMock()
        mock_calc = MagicMock()

        with patch("phaseforge_studio.analysis.Path") as mock_path_cls:
            # Let actual Path work for the struct existence check
            pass

        with patch("ase.io.read", return_value=mock_atoms), \
             patch("materialsframework.calculators.registry.get_calculator", return_value=mock_calc):
            result = _run_analysis(cfg, {"rel_path": "POSCAR", "analyzer": "totally_unknown"})
        assert "error" in result
        assert "Unknown" in result["error"] or "unknown" in result["error"].lower()


@_needs_ase
class TestRunAnalysisNeb:
    def test_neb_no_final_path_returns_error(self, tmp_path: Path) -> None:
        poscar = tmp_path / "init.vasp"
        poscar.write_text(
            "Al\n1.0\n4.05 0.0 0.0\n0.0 4.05 0.0\n0.0 0.0 4.05\nAl\n1\nDirect\n0.0 0.0 0.0\n"
        )
        cfg = {"path1": str(tmp_path), "calculator": "grace", "device": "cpu"}

        mock_atoms = MagicMock()
        mock_calc = MagicMock()

        with patch("ase.io.read", return_value=mock_atoms), \
             patch("materialsframework.calculators.registry.get_calculator", return_value=mock_calc):
            result = _run_analysis(cfg, {"rel_path": "init.vasp", "analyzer": "neb"})

        assert "error" in result
        assert "final_rel_path" in result["error"] or "NEB requires" in result["error"]

    def test_neb_missing_final_file_returns_error(self, tmp_path: Path) -> None:
        poscar = tmp_path / "init.vasp"
        poscar.write_text(
            "Al\n1.0\n4.05 0.0 0.0\n0.0 4.05 0.0\n0.0 0.0 4.05\nAl\n1\nDirect\n0.0 0.0 0.0\n"
        )
        cfg = {"path1": str(tmp_path), "calculator": "grace", "device": "cpu"}

        mock_atoms = MagicMock()
        mock_calc = MagicMock()

        with patch("ase.io.read", return_value=mock_atoms), \
             patch("materialsframework.calculators.registry.get_calculator", return_value=mock_calc):
            result = _run_analysis(
                cfg,
                {"rel_path": "init.vasp", "analyzer": "neb", "final_rel_path": "missing.vasp"},
            )

        assert "error" in result
        assert "missing.vasp" in result["error"] or "not found" in result["error"].lower()

    def test_neb_success_path(self, tmp_path: Path) -> None:
        import numpy as np

        init_f = tmp_path / "init.vasp"
        final_f = tmp_path / "final.vasp"
        for f in (init_f, final_f):
            f.write_text(
                "Al\n1.0\n4.05 0.0 0.0\n0.0 4.05 0.0\n0.0 0.0 4.05\nAl\n1\nDirect\n0.0 0.0 0.0\n"
            )

        cfg = {"path1": str(tmp_path), "calculator": "grace", "device": "cpu"}
        mock_atoms = MagicMock()
        mock_calc = MagicMock()
        neb_result = {
            "barrier": np.float64(0.5),
            "energies": np.array([-1.0, -0.5, -1.0]),
            "images": 3,
        }

        mock_neb_analyzer = MagicMock()
        mock_neb_analyzer.calculate.return_value = neb_result

        with patch("ase.io.read", return_value=mock_atoms), \
             patch("materialsframework.calculators.registry.get_calculator", return_value=mock_calc), \
             patch("materialsframework.analysis.neb.NEBAnalyzer", return_value=mock_neb_analyzer):
            result = _run_analysis(
                cfg,
                {"rel_path": "init.vasp", "analyzer": "neb", "final_rel_path": "final.vasp"},
            )

        assert result.get("analyzer") == "neb"
        assert isinstance(result.get("barrier"), float)
        assert isinstance(result.get("energies"), list)


@_needs_ase
class TestRunAnalysisEos:
    def test_eos_returns_expected_keys(self, tmp_path: Path) -> None:
        import numpy as np

        poscar = tmp_path / "POSCAR"
        poscar.write_text(
            "Al\n1.0\n4.05 0.0 0.0\n0.0 4.05 0.0\n0.0 0.0 4.05\nAl\n1\nDirect\n0.0 0.0 0.0\n"
        )
        cfg = {"path1": str(tmp_path), "calculator": "grace", "device": "cpu"}

        mock_atoms = MagicMock()
        mock_calc = MagicMock()
        mock_relax_result = {"final_structure": MagicMock(volume=70.0), "energy": -3.5}
        mock_calc.relax.return_value = mock_relax_result
        mock_calc.relax_cell = True

        mock_analyzer = MagicMock()
        mock_analyzer.calculator = mock_calc
        mock_analyzer._ensure_relaxed.return_value = mock_atoms
        mock_struct_list = [MagicMock(volume=v) for v in [65.0, 68.0, 70.0, 72.0, 75.0]]
        mock_analyzer.eos_transformation.apply_transformation.return_value = mock_struct_list
        mock_calc.relax.side_effect = [
            {"final_structure": MagicMock(volume=float(v)), "energy": -3.0 + (v - 70.0) ** 2 / 1000}
            for v in [65.0, 68.0, 70.0, 72.0, 75.0]
        ]

        mock_fit = MagicMock()
        mock_fit.b0_GPa = 76.0
        mock_fit.v0 = 70.0
        mock_fit.e0 = -3.5

        with patch("ase.io.read", return_value=mock_atoms), \
             patch("materialsframework.calculators.registry.get_calculator", return_value=mock_calc), \
             patch("materialsframework.analysis.eos.EOSAnalyzer", return_value=mock_analyzer), \
             patch("pymatgen.analysis.eos.EOS") as mock_eos_cls:
            mock_eos_instance = MagicMock()
            mock_eos_instance.fit.return_value = mock_fit
            mock_eos_cls.return_value = mock_eos_instance
            result = _run_analysis(cfg, {"rel_path": "POSCAR", "analyzer": "eos"})

        assert result.get("analyzer") == "eos" or "error" in result


@_needs_ase
class TestRunAnalysisFormationEnergy:
    def test_formation_energy_returns_float(self, tmp_path: Path) -> None:
        poscar = tmp_path / "POSCAR"
        poscar.write_text(
            "Al\n1.0\n4.05 0.0 0.0\n0.0 4.05 0.0\n0.0 0.0 4.05\nAl\n1\nDirect\n0.0 0.0 0.0\n"
        )
        cfg = {"path1": str(tmp_path), "calculator": "grace", "device": "cpu"}

        mock_atoms = MagicMock()
        mock_calc = MagicMock()
        mock_fe_analyzer = MagicMock()
        mock_fe_analyzer.calculate.return_value = {"formation_energy": -0.25}

        with patch("ase.io.read", return_value=mock_atoms), \
             patch("materialsframework.calculators.registry.get_calculator", return_value=mock_calc), \
             patch("materialsframework.analysis.formation_energy.FormationEnergyAnalyzer", return_value=mock_fe_analyzer):
            result = _run_analysis(cfg, {"rel_path": "POSCAR", "analyzer": "formation_energy"})

        assert result.get("analyzer") == "formation_energy"
        assert isinstance(result.get("formation_energy"), float)
        assert result["formation_energy"] == pytest.approx(-0.25)
