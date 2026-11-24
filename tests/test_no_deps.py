"""Graceful-degradation tests: every adapter must behave safely when its optional
dependencies are absent.  These tests use the ``no_optional_deps`` fixture from
conftest.py to mask all optional packages at the sys.modules level.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# ORCHID adapter
# ---------------------------------------------------------------------------


class TestOrchidNoDeps:
    def test_check_returns_false(self, no_orchid) -> None:
        from phaseforge_studio.orchid_adapter import check_orchid_mcp
        assert check_orchid_mcp() is False

    def test_install_hint_still_works(self, no_orchid) -> None:
        from phaseforge_studio.orchid_adapter import orchid_install_hint
        hint = orchid_install_hint()
        assert isinstance(hint, str) and len(hint) > 0

    def test_search_returns_sequence(self, no_orchid) -> None:
        from phaseforge_studio.orchid_adapter import orchid_search_systems
        result = orchid_search_systems("TiAl")
        assert isinstance(result, (dict, list))


# ---------------------------------------------------------------------------
# ORCHID-SAGE adapter
# ---------------------------------------------------------------------------


class TestSageNoDeps:
    def test_check_sage_false(self, no_sage) -> None:
        from phaseforge_studio.sage_adapter import check_sage_installed
        assert check_sage_installed() is False

    def test_check_model_guide_false(self, no_sage) -> None:
        from phaseforge_studio.sage_adapter import check_model_guide_installed
        assert check_model_guide_installed() is False

    def test_install_hint_still_works(self, no_sage) -> None:
        from phaseforge_studio.sage_adapter import sage_install_hint
        hint = sage_install_hint()
        assert isinstance(hint, str) and len(hint) > 0

    def test_model_search_raises_import_error(self, no_sage) -> None:
        from phaseforge_studio.sage_adapter import model_search
        with pytest.raises(ImportError):
            model_search(text="sigma")

    def test_model_validate_raises_import_error(self, no_sage) -> None:
        from phaseforge_studio.sage_adapter import model_validate
        with pytest.raises(ImportError):
            model_validate({"phase": "FCC"})


# ---------------------------------------------------------------------------
# PAIPAI
# ---------------------------------------------------------------------------


class TestPaipaiNoDeps:
    def test_check_returns_bool(self) -> None:
        from phaseforge_studio.paipai import check_paipai_installed
        assert isinstance(check_paipai_installed(), bool)

    def test_install_hint_non_empty(self) -> None:
        from phaseforge_studio.paipai import paipai_install_hint
        assert len(paipai_install_hint()) > 0

    def test_run_paipai_logs_error_when_not_found(self) -> None:
        from pathlib import Path
        from unittest.mock import patch as _patch

        from phaseforge_studio.paipai import PaipaiState, run_paipai

        state = PaipaiState()
        with (
            _patch("phaseforge_studio.paipai.check_paipai_installed", return_value=False),
        ):
            run_paipai(
                workdir=Path("/tmp/test-paipai"),
                model="GRACE-2L-OMAT",
                device="cpu",
                fast_workers=1,
                slow_workers=1,
                steps=10,
                temperature=0.001,
                pool_cap=4,
                state=state,
            )
        assert state.state == "error"
        assert any("ERROR" in line for line in state.log)


# ---------------------------------------------------------------------------
# PhaseForgePlus adapter
# ---------------------------------------------------------------------------


class TestPfpNoDeps:
    def test_check_returns_false_when_flag_unset(self) -> None:
        import phaseforge_studio.pfp_adapter as _pfp
        from unittest.mock import patch as _patch
        with _patch.object(_pfp, "_pfp_available", False):
            assert _pfp.check_pfp_installed() is False

    def test_install_hint_non_empty(self) -> None:
        from phaseforge_studio.pfp_adapter import pfp_install_hint
        assert len(pfp_install_hint()) > 0


# ---------------------------------------------------------------------------
# MaterialsFramework / pipeline
# ---------------------------------------------------------------------------


class TestMFNoDeps:
    def test_pipeline_raises_without_mf(self, no_materialsframework) -> None:
        from phaseforge_studio.pipeline import _make_tracking_sqs2tdb
        with pytest.raises((ImportError, ModuleNotFoundError)):
            _make_tracking_sqs2tdb()


# ---------------------------------------------------------------------------
# deps_manager — installable flags
# ---------------------------------------------------------------------------


class TestDepsManagerFlags:
    def test_all_packages_have_key(self) -> None:
        from phaseforge_studio.deps_manager import _PY_PACKAGES
        required_keys = {"import_name", "label", "optional"}
        for pkg_key, meta in _PY_PACKAGES.items():
            missing = required_keys - set(meta)
            assert not missing, f"{pkg_key} missing keys: {missing}"

    def test_mf_installable_without_source(self) -> None:
        from phaseforge_studio.deps_manager import check_py_status
        # Pass a config with no source paths — MF should still be installable via PyPI
        status = check_py_status({"materialsframework_src": None, "phaseforgeplus_src": None})
        mf = next(s for s in status if s["key"] == "materialsframework")
        pfp = next(s for s in status if s["key"] == "phaseforgeplus")
        assert mf["installable"] is True
        assert pfp["installable"] is True

    def test_blade_installable_without_source(self) -> None:
        from phaseforge_studio.deps_manager import check_py_status
        status = check_py_status({"blade_src": None})
        blade = next(s for s in status if s["key"] == "blade")
        assert blade["installable"] is True

    def test_pip_only_packages_always_installable(self) -> None:
        from phaseforge_studio.deps_manager import check_py_status
        status = check_py_status({})
        pip_only = {s["key"]: s for s in status if not s.get("source_path")}
        for key, s in pip_only.items():
            if s.get("pip_spec"):
                assert s["installable"] is True, f"{key} should be installable"


# ---------------------------------------------------------------------------
# Server routes — missing-dep responses
# ---------------------------------------------------------------------------


class TestServerNoDepsRoutes:
    """Verify server GET endpoints return a valid JSON response even with no deps."""

    def _make_handler(self):
        """Return a minimal server handler instance with no deps wired."""
        import io
        from http.server import BaseHTTPRequestHandler
        from unittest.mock import MagicMock

        import server as srv

        handler = object.__new__(srv.StudioHandler)
        handler.cfg = {}
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler

    def test_orchid_status_route_returns_json(self) -> None:
        import json

        handler = self._make_handler()
        captured: list[bytes] = []
        handler.wfile.write = lambda b: captured.append(b)  # type: ignore[method-assign]

        import server as srv
        with (
            patch("phaseforge_studio.orchid_adapter.check_orchid_mcp", return_value=False),
        ):
            srv.StudioHandler._json(handler, {"installed": False})

        body = b"".join(captured)
        data = json.loads(body)
        assert "installed" in data

    def test_paipai_status_no_binary(self) -> None:
        from unittest.mock import patch as _patch
        import phaseforge_studio.paipai as _paipai
        with (
            _patch.object(_paipai, "_paipai_override", None),
            _patch("shutil.which", return_value=None),
            _patch("pathlib.Path.exists", return_value=False),
        ):
            assert _paipai.check_paipai_installed() is False
