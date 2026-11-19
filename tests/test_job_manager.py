"""Tests for phaseforge_studio.core.job_manager.

Exercises JobManager in isolation: register, state transitions, cancel,
list, and thread-safety basics.  No HPC filesystem or heavy deps required.
"""

from __future__ import annotations

import threading
import time
from unittest import TestCase

import pytest

from phaseforge_studio.core.job_manager import (
    JobManager,
    JobNotFoundError,
    JobRecord,
)


class TestJobRecord(TestCase):
    """JobRecord dataclass and derived properties."""

    def _make_record(self, state: str = "running") -> JobRecord:
        """Return a minimal JobRecord for testing."""
        return JobRecord(
            job_id="j1",
            framework="mf",
            job_type="sqs_tdb",
            name="test run",
            state=state,
            start_time=time.time(),
        )

    def test_elapsed_increases_while_running(self) -> None:
        """elapsed_s grows while a job is in a running state."""
        rec = self._make_record("running")
        t0 = rec.elapsed_s
        time.sleep(0.05)
        assert rec.elapsed_s > t0

    def test_elapsed_frozen_when_done(self) -> None:
        """elapsed_s does not grow after end_time is set."""
        rec = self._make_record("done")
        rec.end_time = time.time()
        t0 = rec.elapsed_s
        time.sleep(0.05)
        assert rec.elapsed_s == pytest.approx(t0, abs=1e-2)

    def test_elapsed_none_when_no_start_time(self) -> None:
        """elapsed_s is None when start_time is not set."""
        rec = JobRecord(job_id="j1", framework="mf", job_type="x", name="y")
        assert rec.elapsed_s is None

    def test_as_dict_has_required_keys(self) -> None:
        """as_dict() includes job_id, name, state, framework."""
        rec = self._make_record("queued")
        d = rec.as_dict()
        assert {"job_id", "name", "state", "framework"} <= d.keys()


class TestJobManagerRegisterAndGet(TestCase):
    """register() and get() basic behaviour."""

    def setUp(self) -> None:
        """Create a fresh JobManager for each test."""
        self.mgr = JobManager()

    def test_register_returns_job_id_string(self) -> None:
        """register() returns a non-empty string job_id."""
        jid = self.mgr.register(framework="blade", job_type="tdb_gen", name="blade run")
        assert isinstance(jid, str)
        assert jid

    def test_register_job_id_contains_framework(self) -> None:
        """job_id from register() contains the framework prefix."""
        jid = self.mgr.register(framework="pf", job_type="sqs", name="pf run")
        assert jid.startswith("pf:")

    def test_get_returns_registered_job(self) -> None:
        """get() retrieves a job registered with the same id."""
        jid = self.mgr.register(framework="pf", job_type="sqs", name="pf run")
        assert self.mgr.get(jid).name == "pf run"

    def test_get_unknown_raises_not_found(self) -> None:
        """get() raises JobNotFoundError for an unknown id."""
        with pytest.raises(JobNotFoundError):
            self.mgr.get("nonexistent")

    def test_two_registers_produce_distinct_ids(self) -> None:
        """Two registrations in the same framework produce distinct ids."""
        j1 = self.mgr.register(framework="mf", job_type="x", name="a")
        j2 = self.mgr.register(framework="mf", job_type="x", name="b")
        assert j1 != j2


class TestJobManagerStateTransitions(TestCase):
    """set_state() updates job state correctly."""

    def setUp(self) -> None:
        """Create a fresh manager and register one job."""
        self.mgr = JobManager()
        self.jid = self.mgr.register(framework="mf", job_type="sqs", name="job")

    def test_set_state_running(self) -> None:
        """set_state to 'running' updates the record state."""
        self.mgr.set_state(self.jid, "running")
        assert self.mgr.get(self.jid).state == "running"

    def test_set_state_done(self) -> None:
        """set_state to 'done' updates the record state."""
        self.mgr.set_state(self.jid, "done")
        assert self.mgr.get(self.jid).state == "done"

    def test_set_state_unknown_job_raises(self) -> None:
        """set_state raises JobNotFoundError for an unregistered id."""
        with pytest.raises(JobNotFoundError):
            self.mgr.set_state("ghost", "running")

    def test_set_state_with_output_files(self) -> None:
        """set_state records output_files on completion."""
        self.mgr.set_state(self.jid, "done", output_files=["/path/to/result.tdb"])
        assert "/path/to/result.tdb" in self.mgr.get(self.jid).output_files


class TestJobManagerCancel(TestCase):
    """cancel() marks a job as cancelled."""

    def setUp(self) -> None:
        """Create manager with a running job."""
        self.mgr = JobManager()
        self.jid = self.mgr.register(framework="blade", job_type="fit", name="run")
        self.mgr.set_state(self.jid, "running")

    def test_cancel_sets_cancelled_state(self) -> None:
        """cancel() transitions a running job to 'canceled'."""
        self.mgr.cancel(self.jid)
        assert self.mgr.get(self.jid).state == "canceled"

    def test_cancel_unknown_raises(self) -> None:
        """cancel() raises JobNotFoundError for an unknown id."""
        with pytest.raises(JobNotFoundError):
            self.mgr.cancel("ghost")


class TestJobManagerListJobs(TestCase):
    """list_jobs() returns serialisable summaries."""

    def setUp(self) -> None:
        """Create manager with two jobs in different frameworks."""
        self.mgr = JobManager()
        self.mgr.register(framework="blade", job_type="fit", name="blade run")
        self.mgr.register(framework="pf", job_type="sqs", name="pf run")

    def test_list_returns_all_jobs(self) -> None:
        """list_jobs() returns one entry per registered job."""
        assert len(self.mgr.list_jobs()) == 2

    def test_list_job_has_state_key(self) -> None:
        """Every entry from list_jobs() contains a 'state' key."""
        for entry in self.mgr.list_jobs():
            assert "state" in entry

    def test_filter_by_framework(self) -> None:
        """list_jobs(framework='blade') returns only blade jobs."""
        blade_jobs = self.mgr.list_jobs(framework="blade")
        assert all(j["framework"] == "blade" for j in blade_jobs)
        assert len(blade_jobs) == 1


class TestJobManagerThreadSafety(TestCase):
    """register and set_state are safe under concurrent access."""

    def test_concurrent_register_no_data_race(self) -> None:
        """50 threads registering distinct jobs all succeed without error."""
        mgr = JobManager()
        errors: list[str] = []

        def worker(idx: int) -> None:
            try:
                jid = mgr.register(framework="mf", job_type="x", name=f"job {idx}")
                mgr.set_state(jid, "running")
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(mgr.list_jobs()) == 50
