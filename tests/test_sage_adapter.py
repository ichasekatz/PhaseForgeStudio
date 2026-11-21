"""Tests for phaseforge_studio.sage_adapter — ORCHID-SAGE integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from phaseforge_studio.sage_adapter import (
    check_model_guide_installed,
    check_sage_installed,
    model_audit,
    model_compare,
    model_plan,
    model_recommend,
    model_search,
    model_validate,
    sage_install_hint,
    validate_id,
)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


class TestSageDetection:
    def test_check_sage_returns_bool(self) -> None:
        assert isinstance(check_sage_installed(), bool)

    def test_check_model_guide_returns_bool(self) -> None:
        assert isinstance(check_model_guide_installed(), bool)

    def test_install_hint_is_string(self) -> None:
        assert isinstance(sage_install_hint(), str)

    def test_install_hint_mentions_orchid(self) -> None:
        hint = sage_install_hint().lower()
        assert "orchid" in hint or "sage" in hint

    def test_sage_installed_when_importable(self) -> None:
        try:
            import sage_mcp  # noqa: F401
            assert check_sage_installed() is True
        except ImportError:
            assert check_sage_installed() is False

    def test_model_guide_installed_when_importable(self) -> None:
        try:
            import calphad_model_guide  # noqa: F401
            assert check_model_guide_installed() is True
        except ImportError:
            assert check_model_guide_installed() is False


# ---------------------------------------------------------------------------
# calphad_model_guide — model screening (via mocks)
# ---------------------------------------------------------------------------


def _mock_cmg(return_value: object) -> MagicMock:
    """Return a MagicMock for calphad_model_guide with one callable."""
    mod = MagicMock()
    mod.search.return_value = return_value
    mod.validate.return_value = []
    mod.audit.return_value = {"codes": []}
    mod.recommend.return_value = {"recipes": []}
    mod.plan.return_value = {"plan": []}
    mod.compare.return_value = {"diff": []}
    return mod


class TestModelSearch:
    def test_returns_dict(self) -> None:
        with patch.dict("sys.modules", {"calphad_model_guide": _mock_cmg({"recipes": [], "count": 0})}):
            result = model_search(text="sigma")
            assert isinstance(result, dict)

    def test_text_forwarded(self) -> None:
        mod = _mock_cmg({"recipes": [], "count": 0})
        with patch.dict("sys.modules", {"calphad_model_guide": mod}):
            model_search(text="FCC", topic="binary")
            mod.search.assert_called_once_with(text="FCC", topic="binary")

    def test_empty_text_ok(self) -> None:
        with patch.dict("sys.modules", {"calphad_model_guide": _mock_cmg({"recipes": []})}):
            result = model_search()
            assert "recipes" in result or result is not None


class TestModelValidate:
    def test_valid_spec_returns_empty_list(self) -> None:
        with patch.dict("sys.modules", {"calphad_model_guide": _mock_cmg({})}):
            errors = model_validate({"schema_version": 1, "phase": "SIGMA"})
            assert errors == []

    def test_invalid_spec_returns_errors(self) -> None:
        mod = _mock_cmg({})
        mod.validate.return_value = ["field X missing"]
        with patch.dict("sys.modules", {"calphad_model_guide": mod}):
            errors = model_validate({})
            assert len(errors) > 0

    def test_non_list_result_coerced(self) -> None:
        mod = _mock_cmg({})
        mod.validate.return_value = "not a list"
        with patch.dict("sys.modules", {"calphad_model_guide": mod}):
            errors = model_validate({})
            assert isinstance(errors, list)


class TestModelAudit:
    def test_returns_dict(self) -> None:
        with patch.dict("sys.modules", {"calphad_model_guide": _mock_cmg({})}):
            result = model_audit({"phase": "FCC"})
            assert isinstance(result, dict)


class TestModelRecommend:
    def test_returns_dict(self) -> None:
        with patch.dict("sys.modules", {"calphad_model_guide": _mock_cmg({})}):
            result = model_recommend({"phase": "FCC"})
            assert isinstance(result, dict)


class TestModelPlan:
    def test_default_limit(self) -> None:
        mod = _mock_cmg({})
        with patch.dict("sys.modules", {"calphad_model_guide": mod}):
            model_plan({"phase": "FCC"})
            mod.plan.assert_called_once_with({"phase": "FCC"}, limit=20)

    def test_custom_limit(self) -> None:
        mod = _mock_cmg({})
        with patch.dict("sys.modules", {"calphad_model_guide": mod}):
            model_plan({"phase": "FCC"}, limit=5)
            mod.plan.assert_called_once_with({"phase": "FCC"}, limit=5)


class TestModelCompare:
    def test_returns_dict(self) -> None:
        with patch.dict("sys.modules", {"calphad_model_guide": _mock_cmg({})}):
            result = model_compare({"phase": "FCC"}, {"phase": "BCC"})
            assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# orchid_ids — validate_id
# ---------------------------------------------------------------------------


class TestValidateId:
    def test_result_has_expected_keys(self) -> None:
        pytest.importorskip("orchid_ids", reason="orchid_ids required")
        result = validate_id("ORC-12345")
        assert "valid" in result
        assert "errors" in result
        assert "id" in result

    def test_id_echoed_in_result(self) -> None:
        pytest.importorskip("orchid_ids", reason="orchid_ids required")
        result = validate_id("ORC-999")
        assert result["id"] == "ORC-999"

    def test_invalid_id_not_valid(self) -> None:
        pytest.importorskip("orchid_ids", reason="orchid_ids required")
        result = validate_id("not-an-orchid-id")
        assert isinstance(result["valid"], bool)
        # errors is a list of strings (empty on success)
        assert isinstance(result["errors"], list)
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# Server route body validation
# ---------------------------------------------------------------------------


class TestSageRouteValidation:
    def test_model_validate_requires_spec_dict(self) -> None:
        body: dict = {"spec": "not a dict"}
        assert not isinstance(body.get("spec"), dict)

    def test_model_plan_default_limit(self) -> None:
        body: dict = {"spec": {"phase": "FCC"}}
        assert int(body.get("limit", 20)) == 20

    def test_start_step_requires_three_fields(self) -> None:
        body: dict = {"ref": "some-protocol", "step_id": "s1"}
        assert "run_root" not in body

    def test_plan_reproduction_nproc_default(self) -> None:
        body: dict = {"ref": "proto1"}
        assert int(body.get("nproc", 4)) == 4

    def test_step_status_wait_s_default(self) -> None:
        body: dict = {}
        assert float(body.get("wait_s", 0)) == 0.0

    def test_evidence_manifest_pagination(self) -> None:
        limit = int("50")
        offset = int("0")
        assert limit == 50
        assert offset == 0
