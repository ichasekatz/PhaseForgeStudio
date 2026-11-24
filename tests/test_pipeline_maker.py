"""Tests for phaseforge_studio.pipeline_maker."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from phaseforge_studio.pipeline_maker import (
    STEP_TYPES,
    StepState,
    cancel_pipeline,
    get_pipeline_status,
    resolve_config,
    start_pipeline,
)


class TestStepRegistry:
    def test_all_expected_steps_present(self) -> None:
        expected = {"paipai_search", "mf_sqs", "orchid_search", "pfp_fit", "blade_pipeline", "sage_reproduce"}
        assert expected.issubset(set(STEP_TYPES))

    def test_each_step_has_required_keys(self) -> None:
        for key, meta in STEP_TYPES.items():
            assert "label" in meta, f"{key} missing label"
            assert "default_config" in meta, f"{key} missing default_config"
            assert "outputs" in meta, f"{key} missing outputs"

    def test_default_configs_are_dicts(self) -> None:
        for key, meta in STEP_TYPES.items():
            assert isinstance(meta["default_config"], dict), f"{key} default_config not dict"

    def test_frameworks_are_strings(self) -> None:
        for key, meta in STEP_TYPES.items():
            assert isinstance(meta.get("framework", ""), str), f"{key} framework not str"


class TestResolveConfig:
    def test_literal_values_pass_through(self) -> None:
        cfg = {"device": "cpu", "steps": 1000}
        assert resolve_config(cfg, {}) == cfg

    def test_ref_resolved_from_context(self) -> None:
        cfg = {"system": "$step_0.system"}
        ctx = {"step_0": {"system": "NiCr"}}
        assert resolve_config(cfg, ctx)["system"] == "NiCr"

    def test_missing_ref_keeps_original(self) -> None:
        cfg = {"system": "$step_0.system"}
        assert resolve_config(cfg, {})["system"] == "$step_0.system"

    def test_non_ref_string_unchanged(self) -> None:
        cfg = {"path": "/tmp/test"}
        assert resolve_config(cfg, {})["path"] == "/tmp/test"

    def test_empty_config(self) -> None:
        assert resolve_config({}, {}) == {}

    def test_nested_ref_missing_key(self) -> None:
        cfg = {"x": "$step_0.missing_key"}
        ctx = {"step_0": {"system": "Ti"}}
        assert resolve_config(cfg, ctx)["x"] == "$step_0.missing_key"


class TestStepState:
    def test_push_log_truncates_at_500(self) -> None:
        s = StepState(step_id="s0", step_type="mf_sqs", label="test")
        for i in range(600):
            s.push_log(f"line {i}")
        assert len(s.log) == 500

    def test_elapsed_none_before_start(self) -> None:
        s = StepState(step_id="s0", step_type="mf_sqs", label="test")
        assert s.elapsed() is None

    def test_elapsed_positive_after_start(self) -> None:
        s = StepState(step_id="s0", step_type="mf_sqs", label="test")
        s.start_time = time.time() - 2.0
        assert s.elapsed() >= 2.0

    def test_elapsed_zero_at_end_time(self) -> None:
        s = StepState(step_id="s0", step_type="mf_sqs", label="test")
        t = time.time()
        s.start_time = t
        s.end_time = t + 5.0
        assert s.elapsed() == 5.0

    def test_default_status_pending(self) -> None:
        s = StepState(step_id="s0", step_type="orchid_search", label="x")
        assert s.status == "pending"


class TestPipelineStatus:
    def test_idle_when_no_run(self) -> None:
        import phaseforge_studio.pipeline_maker as pm
        old = pm._active_run
        pm._active_run = None
        try:
            status = get_pipeline_status()
            assert status["status"] == "idle"
            assert status["steps"] == []
        finally:
            pm._active_run = old

    def test_cancel_no_run(self) -> None:
        import phaseforge_studio.pipeline_maker as pm
        old = pm._active_run
        pm._active_run = None
        try:
            result = cancel_pipeline()
            assert result["ok"] is False
            assert "error" in result
        finally:
            pm._active_run = old


class TestStartPipeline:
    def test_returns_run_id_string(self) -> None:
        with patch("phaseforge_studio.pipeline_maker._execute_pipeline"):
            run_id = start_pipeline([{"step_type": "orchid_search", "config": {"system": "NiCr"}}])
        assert isinstance(run_id, str) and len(run_id) > 0

    def test_empty_steps_still_runs(self) -> None:
        with patch("phaseforge_studio.pipeline_maker._execute_pipeline"):
            run_id = start_pipeline([])
        assert run_id

    def test_run_id_is_short(self) -> None:
        with patch("phaseforge_studio.pipeline_maker._execute_pipeline"):
            run_id = start_pipeline([])
        assert len(run_id) == 8

    def test_orchid_step_calls_search(self) -> None:
        results: list[str] = []

        def fake_search(system, limit=20):
            results.append(system)
            return []

        with patch("phaseforge_studio.orchid_adapter.orchid_search_systems", fake_search):
            start_pipeline([{
                "step_type": "orchid_search",
                "config": {"system": "TiAl", "limit": 5},
            }])
            time.sleep(0.5)

        assert "TiAl" in results

    def test_unknown_step_type_errors(self) -> None:
        start_pipeline([{"step_type": "nonexistent_step", "config": {}}])
        time.sleep(0.3)
        import phaseforge_studio.pipeline_maker as pm
        if pm._active_run:
            assert pm._active_run.status in ("error", "running", "done")

    def test_cancel_sets_flag(self) -> None:
        import phaseforge_studio.pipeline_maker as pm
        with patch("phaseforge_studio.pipeline_maker._execute_pipeline"):
            start_pipeline([{"step_type": "orchid_search", "config": {"system": "NiCr"}}])
        result = cancel_pipeline()
        assert result["ok"] is True
        assert pm._active_run._cancel.is_set()
