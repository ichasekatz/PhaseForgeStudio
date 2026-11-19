"""Unified job manager for all PhaseForgeStudio frameworks.

Tracks every background job regardless of originating framework with a
consistent state model: queued → running → done | error | canceled.

This module wraps the existing ``phaseforge_studio.job.JobState`` for each
framework and adds a cross-framework job registry for the centralized job
monitor panel.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from phaseforge_studio.job import JobState


class JobNotFoundError(KeyError):
    """Raised when a job_id does not exist in the registry."""


@dataclass
class JobRecord:
    """Full record for one background job.

    Attributes:
        job_id: Stable unique identifier (framework:counter).
        framework: Originating framework key.
        job_type: Short type string (e.g. ``"sqs_tdb"``, ``"mc_paipai"``).
        name: Human-readable job name.
        workdir: Working directory path.
        state: ``"queued"``, ``"running"``, ``"done"``, ``"error"``, ``"canceled"``.
        start_time: Unix timestamp of job start, or None.
        end_time: Unix timestamp of terminal state, or None.
        log: Bounded deque-like log captured from the job's output.
        input_files: List of input file paths.
        output_files: List of output file paths (populated after completion).
        progress: Optional structured progress dict (framework-specific).
        error_msg: First error message if state == ``"error"``.
        job_state: Reference to the underlying ``JobState`` singleton, if any.
    """

    job_id: str
    framework: str
    job_type: str
    name: str
    workdir: str = ""
    state: str = "queued"
    start_time: float | None = None
    end_time: float | None = None
    log: list[str] = field(default_factory=list)
    input_files: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    progress: dict[str, Any] = field(default_factory=dict)
    error_msg: str = ""
    job_state: JobState | None = field(default=None, repr=False)

    @property
    def elapsed_s(self) -> float | None:
        """Elapsed time in seconds since job start.

        Returns:
            Elapsed seconds, or None if the job has not started.
        """
        if self.start_time is None:
            return None
        end = self.end_time or time.time()
        return round(end - self.start_time, 1)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot.

        Returns:
            Dict with all public fields plus ``elapsed_s``.
        """
        log_tail = self.log[-80:] if self.log else []
        if self.job_state is not None:
            live = list(self.job_state.log)
            if live:
                log_tail = live[-80:]
        return {
            "job_id": self.job_id,
            "framework": self.framework,
            "job_type": self.job_type,
            "name": self.name,
            "workdir": self.workdir,
            "state": self.state,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "elapsed_s": self.elapsed_s,
            "log_tail": log_tail,
            "input_files": self.input_files,
            "output_files": self.output_files,
            "progress": self.progress,
            "error_msg": self.error_msg,
        }


class JobManager:
    """Thread-safe registry of all background jobs across all frameworks.

    Usage::

        mgr = JobManager()
        job_id = mgr.register(framework="mf", job_type="sqs_tdb", name="Ni-Re FCC",
                              workdir="/path/to/run", job_state=existing_job_state)
        mgr.set_state(job_id, "running")
        # ... later ...
        mgr.set_state(job_id, "done", output_files=["/path/to/result.tdb"])
    """

    def __init__(self) -> None:
        """Initialise empty job registry with per-framework counters."""
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}
        self._counters: dict[str, int] = {}

    def _next_id(self, framework: str) -> str:
        """Return the next job_id for a framework.

        Args:
            framework (str): Framework key.

        Returns:
            ID string like ``"mf:0001"``.
        """
        n = self._counters.get(framework, 0)
        self._counters[framework] = n + 1
        return f"{framework}:{n:04d}"

    def register(
        self,
        framework: str,
        job_type: str,
        name: str,
        workdir: str = "",
        input_files: list[str] | None = None,
        job_state: JobState | None = None,
    ) -> str:
        """Register a new job and return its job_id.

        Args:
            framework (str): Originating framework key.
            job_type (str): Short job type string.
            name (str): Human-readable job name.
            workdir (str): Working directory path.
            input_files (list[str] | None): Input file paths.
            job_state (JobState | None): Underlying ``JobState`` singleton.

        Returns:
            Unique job_id string.
        """
        with self._lock:
            jid = self._next_id(framework)
            self._jobs[jid] = JobRecord(
                job_id=jid,
                framework=framework,
                job_type=job_type,
                name=name,
                workdir=workdir,
                state="queued",
                start_time=time.time(),
                input_files=input_files or [],
                job_state=job_state,
            )
        return jid

    def set_state(
        self,
        job_id: str,
        state: str,
        *,
        output_files: list[str] | None = None,
        error_msg: str = "",
        progress: dict[str, Any] | None = None,
    ) -> None:
        """Update the state of a registered job.

        Args:
            job_id (str): Job identifier.
            state (str): New state string.
            output_files (list[str] | None): Output files if completed.
            error_msg (str): Error message if state == ``"error"``.
            progress (dict[str, Any] | None): Updated progress dict.

        Raises:
            JobNotFoundError: If job_id is not registered.
        """
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise JobNotFoundError(job_id)
            rec.state = state
            if state == "running" and rec.start_time is None:
                rec.start_time = time.time()
            if state in ("done", "error", "canceled") and rec.end_time is None:
                rec.end_time = time.time()
            if output_files is not None:
                rec.output_files = output_files
            if error_msg:
                rec.error_msg = error_msg
            if progress is not None:
                rec.progress.update(progress)

    def cancel(self, job_id: str) -> None:
        """Cancel a running job.

        Terminates the underlying process if the ``job_state`` has a live proc,
        then marks the record as canceled.

        Args:
            job_id (str): Job identifier.

        Raises:
            JobNotFoundError: If job_id is not registered.
        """
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise JobNotFoundError(job_id)
            if rec.state not in ("running", "queued"):
                return
            js = rec.job_state
        # Terminate outside lock to avoid deadlock
        if js is not None:
            js.stop()
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is not None:
                rec.state = "canceled"
                rec.end_time = time.time()

    def get(self, job_id: str) -> JobRecord:
        """Return the ``JobRecord`` for a job_id.

        Args:
            job_id (str): Job identifier.

        Returns:
            ``JobRecord`` instance.

        Raises:
            JobNotFoundError: If job_id is not registered.
        """
        with self._lock:
            rec = self._jobs.get(job_id)
        if rec is None:
            raise JobNotFoundError(job_id)
        return rec

    def list_jobs(
        self,
        framework: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return a list of job snapshots, newest first.

        Args:
            framework (str | None): Filter by framework key, or None for all.
            active_only (bool): If True, return only running/queued jobs.
            limit (int): Maximum number of records to return.

        Returns:
            List of dicts from ``JobRecord.as_dict()``.
        """
        with self._lock:
            jobs = list(self._jobs.values())
        if framework:
            jobs = [j for j in jobs if j.framework == framework]
        if active_only:
            jobs = [j for j in jobs if j.state in ("running", "queued")]
        jobs.sort(key=lambda j: j.start_time or 0, reverse=True)
        return [j.as_dict() for j in jobs[:limit]]

    def sync_from_job_state(self, job_id: str) -> None:
        """Pull the current state from the underlying ``JobState`` singleton.

        Call this periodically to keep the ``JobRecord`` state consistent when
        the framework manages its own ``JobState`` directly.

        Args:
            job_id (str): Job identifier.
        """
        with self._lock:
            rec = self._jobs.get(job_id)
        if rec is None or rec.job_state is None:
            return
        js_snap = rec.job_state.as_dict()
        new_state = js_snap.get("state", rec.state)
        with self._lock:
            rec.state = new_state


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: JobManager = JobManager()
