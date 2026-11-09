"""Job state machine, log capture, and module-level job singletons."""

from __future__ import annotations

import io
import threading
import time
from collections import deque
from typing import Any


class JobState:
    """Thread-safe state machine for a single background pipeline job."""

    def __init__(self) -> None:
        """Initialise with idle state and empty log."""
        self._lock = threading.Lock()
        self.state: str = "idle"
        self.job_id: str | None = None
        self.job_name: str | None = None
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.log: deque[str] = deque(maxlen=2000)
        self._thread: threading.Thread | None = None

    def push_log(self, line: str) -> None:
        """Append a log line thread-safely.

        Args:
            line (str): Log line to append.
        """
        with self._lock:
            self.log.append(line)

    def set_state(self, state: str) -> None:
        """Update job state and record end time for terminal states.

        Args:
            state (str): New state string (``"running"``, ``"done"``, ``"error"``, ``"idle"``).
        """
        with self._lock:
            self.state = state
            if state in ("done", "error", "idle") and self.start_time and not self.end_time:
                self.end_time = time.time()

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of job state.

        Returns:
            Dict with state, job_id, job_name, and elapsed_s.
        """
        with self._lock:
            elapsed = (time.time() - self.start_time) if self.start_time else None
            return {
                "state": self.state,
                "job_id": self.job_id,
                "job_name": self.job_name,
                "elapsed_s": round(elapsed, 1) if elapsed is not None else None,
            }

    def is_running(self) -> bool:
        """Return True if the job is currently in the running state.

        Returns:
            bool: True if state == ``"running"``.
        """
        with self._lock:
            return self.state == "running"

    def stop(self) -> None:
        """Transition to idle and record end time."""
        with self._lock:
            self.state = "idle"
            if self.start_time and not self.end_time:
                self.end_time = time.time()


class _LogCapture(io.TextIOBase):
    """TextIO shim that forwards writes to JobState.push_log.

    Args:
        job (JobState): Job whose log receives forwarded lines.
    """

    def __init__(self, job: JobState) -> None:
        """Initialise with the target job.

        Args:
            job (JobState): Job to forward log lines to.
        """
        super().__init__()
        self._job = job
        self._buf = ""

    def write(self, s: str) -> int:
        """Buffer incoming text and push complete lines to the job log.

        Args:
            s (str): Text written by the redirected stream.

        Returns:
            Number of characters written.
        """
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._job.push_log(line)
        return len(s)

    def flush(self) -> None:
        """Flush any remaining buffered text as a final log line."""
        if self._buf:
            self._job.push_log(self._buf)
            self._buf = ""


# ---------------------------------------------------------------------------
# Module-level singletons shared across HTTP handler and pipeline thread
# ---------------------------------------------------------------------------

_job: JobState = JobState()
_job_history: list[dict[str, Any]] = []
_job_counter: int = 0
