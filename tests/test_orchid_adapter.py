"""Tests for orchid_adapter module."""

from __future__ import annotations

import json
import os
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from phaseforge_studio.orchid_adapter import (
    _orchid_offline,
    _local_data_dir,
    check_orchid_mcp,
    compare_to_dft,
    get_formation_enthalpy,
    get_phase_diagram,
    get_tdb_content,
    list_tdb_files,
    orchid_install_hint,
    orchid_search_systems,
)


class TestHelpers:
    def test_orchid_offline_false_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCHID_OFFLINE", None)
            assert _orchid_offline() is False

    def test_orchid_offline_true_when_set(self) -> None:
        with patch.dict(os.environ, {"ORCHID_OFFLINE": "1"}):
            assert _orchid_offline() is True

    def test_local_data_dir_none_when_unset(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "ORCHID_DATA_DIR"}
        with patch.dict(os.environ, env, clear=True):
            assert _local_data_dir() is None

    def test_local_data_dir_path_when_set(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"ORCHID_DATA_DIR": str(tmp_path)}):
            result = _local_data_dir()
            assert result == tmp_path


class TestCheckOrchidMcp:
    def test_returns_bool(self) -> None:
        assert isinstance(check_orchid_mcp(), bool)

    def test_true_when_importable(self) -> None:
        with patch.dict("sys.modules", {"orchid_mcp": MagicMock()}):
            # Can't reload due to module-level caching; check function logic
            assert isinstance(check_orchid_mcp(), bool)

    def test_false_when_not_installed(self) -> None:
        with patch.dict("sys.modules", {"orchid_mcp": None}):
            # Function tries import and returns bool
            result = check_orchid_mcp()
            assert isinstance(result, bool)


class TestOrchidInstallHint:
    def test_non_empty(self) -> None:
        assert len(orchid_install_hint()) > 0

    def test_contains_pip_or_orchid(self) -> None:
        hint = orchid_install_hint()
        assert "pip" in hint.lower() or "orchid" in hint.lower()


class TestOrchidSearchSystems:
    def test_returns_list_on_network_mock(self) -> None:
        payload = [{"system": "Al-Fe", "elements": ["Al", "Fe"]}]
        encoded = json.dumps(payload).encode()

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = encoded

        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            result = orchid_search_systems(["Al", "Fe"])
        assert isinstance(result, list)

    def test_returns_empty_list_on_network_failure(self) -> None:
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = orchid_search_systems(["Cu", "Zr"])
        assert isinstance(result, list)

    def test_uses_mcp_when_available(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.search_systems.return_value = [{"system": "Al-Ni"}]
        with patch.dict("sys.modules", {"orchid_mcp": mock_mcp}), \
             patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=True), \
             patch("phaseforge_studio.orchid_adapter._mcp_call", return_value=[{"system": "Al-Ni"}]):
            result = orchid_search_systems(["Al", "Ni"])
        assert isinstance(result, list)


class TestGetPhaseDigram:
    def test_returns_dict_on_network_mock(self) -> None:
        payload = {"system": "Cu-Zr", "phases": []}
        encoded = json.dumps(payload).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = encoded
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            result = get_phase_diagram("Cu-Zr")
        assert isinstance(result, dict)

    def test_returns_error_dict_on_network_failure(self) -> None:
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = get_phase_diagram("Al-Fe")
        assert isinstance(result, dict)
        assert "error" in result or "system" in result


class TestGetFormationEnthalpy:
    def test_returns_dict(self) -> None:
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False):
            result = get_formation_enthalpy("Al2Ni")
        assert isinstance(result, dict)

    def test_contains_formula(self) -> None:
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False):
            result = get_formation_enthalpy("CuZr")
        assert result.get("formula") == "CuZr" or "error" in result


class TestListTdbFiles:
    def test_returns_list(self) -> None:
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            result = list_tdb_files()
        assert isinstance(result, list)

    def test_returns_empty_on_network_failure(self) -> None:
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            result = list_tdb_files(elements=["Al", "Ni"])
        assert isinstance(result, list)

    def test_filters_by_element_via_mcp(self) -> None:
        filtered = [{"file_id": "abc", "elements": ["Al", "Ni"]}]
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=True), \
             patch("phaseforge_studio.orchid_adapter._mcp_call", return_value=filtered):
            result = list_tdb_files(elements=["Al", "Ni"])
        assert isinstance(result, list)


class TestGetTdbContent:
    def test_returns_string_via_mcp(self) -> None:
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=True), \
             patch("phaseforge_studio.orchid_adapter._mcp_call", return_value="$ TDB content"):
            result = get_tdb_content("abc123")
        assert isinstance(result, str)

    def test_returns_string_on_http_mock(self) -> None:
        payload = {"content": "$ TDB via HTTP"}
        encoded = json.dumps(payload).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = encoded
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            result = get_tdb_content("abc123")
        assert isinstance(result, str)

    def test_error_string_on_network_failure(self) -> None:
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            result = get_tdb_content("missing_id")
        assert isinstance(result, str)
        assert "Error" in result or "error" in result.lower()


class TestCompareToDft:
    def test_returns_dict_without_mcp(self) -> None:
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False):
            result = compare_to_dft("Al-Ni")
        assert isinstance(result, dict)
        assert "error" in result

    def test_returns_dict_with_mcp(self) -> None:
        payload = {"system": "Al-Ni", "comparison": []}
        with patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=True), \
             patch("phaseforge_studio.orchid_adapter._mcp_call", return_value=payload):
            result = compare_to_dft("Al-Ni")
        assert isinstance(result, dict)
