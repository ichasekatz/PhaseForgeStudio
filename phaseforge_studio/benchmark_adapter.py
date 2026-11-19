"""MLIP Phase Diagram Benchmarking orchestrator for PhaseForgeStudio.

For each selected MLIP, dispatches PhaseForge (sqscal), waits for TDB output,
generates phase diagrams via pycalphad, and computes metrics against an optional
reference TDB.

Benchmark Mode B (default, ``mode="relaxed"``): each MLIP independently relaxes
the same starting composition grid via sqscal.

Benchmark Mode A (``mode="fixed"``): all MLIPs evaluate identical structures
without relaxation.  Requires upstream PhaseForge support; currently runs the
same sqscal pipeline and documents the limitation.

Directory layout produced under ``<workdir>/benchmarks/<system>_<id>/``::

    benchmark_config.json
    reference/           (copied reference TDB if provided)
    mlips/
        <mlip_name>/     (sqscal workdir per MLIP)
    tdb/                 (symlinks or copies of fitted TDBs)
    phase_diagrams/      (PNG outputs)
    metrics/             (per-MLIP metric JSON files)
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from phaseforge_studio.benchmark_metrics import compute_metrics
from phaseforge_studio.plotting import _phase_diagram_from_tdb


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkConfig:
    """Immutable parameters for one benchmark run.

    Attributes:
        benchmark_id (str): Short UUID identifying this run.
        system (str): Chemical system name, e.g. ``"Cu-Zr"``.
        elements (list[str]): Element symbols.
        mlips (list[str]): MLIP calculator names to benchmark.
        phases (list[str]): Lattice/phase names passed to sqscal via ``-l``.
        level (int): SQS level passed to sqscal via ``-lv``.
        t_min (float): Minimum temperature in K for phase diagrams.
        t_max (float): Maximum temperature in K for phase diagrams.
        t_step (float): Temperature grid step in K for metrics.
        x_step (float): Composition grid step (mole fraction) for metrics.
        mode (str): ``"relaxed"`` (Mode B) or ``"fixed"`` (Mode A).
        reference_tdb (str): Path to reference TDB; empty string if none.
        workdir (str): Base directory; run lives under ``<workdir>/benchmarks/``.
        created_at (float): Unix timestamp of run creation.
    """

    benchmark_id: str
    system: str
    elements: list[str]
    mlips: list[str]
    phases: list[str]
    level: int
    t_min: float
    t_max: float
    t_step: float
    x_step: float
    mode: str
    reference_tdb: str
    workdir: str
    created_at: float


@dataclass
class MlipJobState:
    """Mutable state for one MLIP within a benchmark run.

    Attributes:
        mlip (str): Calculator name, e.g. ``"grace"``.
        state (str): One of ``idle``, ``running``, ``done``, ``error``.
        log (list[str]): Captured stdout lines from sqscal.
        tdb_path (str | None): Absolute path to discovered TDB file.
        png_paths (list[str]): Absolute paths to generated phase diagram PNGs.
        metrics (dict | None): Output of ``compute_metrics`` or ``None``.
        start_time (float | None): Unix timestamp when sqscal started.
        end_time (float | None): Unix timestamp when job finished.
    """

    mlip: str
    state: str = "idle"
    log: list[str] = field(default_factory=list)
    tdb_path: str | None = None
    png_paths: list[str] = field(default_factory=list)
    metrics: dict[str, Any] | None = None
    start_time: float | None = None
    end_time: float | None = None

    @property
    def elapsed_s(self) -> float | None:
        """Elapsed wall-clock seconds; None before start, frozen after end."""
        if self.start_time is None:
            return None
        end = self.end_time if self.end_time is not None else time.time()
        return end - self.start_time


@dataclass
class BenchmarkRun:
    """Container for one complete benchmark run.

    Attributes:
        config (BenchmarkConfig): Immutable run parameters.
        mlip_jobs (dict[str, MlipJobState]): Per-MLIP job state.
        state (str): Overall run state: ``idle/running/done/error/canceled``.
        cancel_flag (threading.Event): Set to request cancellation.
        thread (threading.Thread | None): Orchestration thread.
        run_dir (Path | None): Root directory of this benchmark run.
    """

    config: BenchmarkConfig
    mlip_jobs: dict[str, MlipJobState]
    state: str = "idle"
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    run_dir: Path | None = None


# ---------------------------------------------------------------------------
# In-memory registry
# ---------------------------------------------------------------------------


class _BenchmarkRegistry:
    """Thread-safe in-memory store of benchmark runs keyed by benchmark_id."""

    def __init__(self) -> None:
        """Initialise empty registry."""
        self._runs: dict[str, BenchmarkRun] = {}
        self._lock = threading.Lock()

    def add(self, run: BenchmarkRun) -> None:
        """Register a new run.

        Args:
            run (BenchmarkRun): Run to register.
        """
        with self._lock:
            self._runs[run.config.benchmark_id] = run

    def get(self, benchmark_id: str) -> BenchmarkRun | None:
        """Return run by id or None.

        Args:
            benchmark_id (str): Benchmark identifier.

        Returns:
            Matching BenchmarkRun or None.
        """
        with self._lock:
            return self._runs.get(benchmark_id)

    def list_all(self) -> list[BenchmarkRun]:
        """Return all runs, most-recent first.

        Returns:
            List of BenchmarkRun objects ordered by created_at descending.
        """
        with self._lock:
            return sorted(
                self._runs.values(),
                key=lambda r: r.config.created_at,
                reverse=True,
            )

    def remove(self, benchmark_id: str) -> bool:
        """Remove a run from the registry.

        Args:
            benchmark_id (str): Benchmark identifier.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            return self._runs.pop(benchmark_id, None) is not None


_registry = _BenchmarkRegistry()


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------


def _make_run_dir(config: BenchmarkConfig) -> Path:
    """Create the benchmark run directory tree and return root path.

    Args:
        config (BenchmarkConfig): Run config.

    Returns:
        Root Path for this run (``<workdir>/benchmarks/<system>_<id>/``).
    """
    base = Path(config.workdir).expanduser().resolve() / "benchmarks"
    run_dir = base / f"{config.system}_{config.benchmark_id}"
    for subdir in ["reference", "tdb", "phase_diagrams", "metrics"]:
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)
    for mlip in config.mlips:
        (run_dir / "mlips" / _safe_name(mlip)).mkdir(parents=True, exist_ok=True)
    return run_dir


def _safe_name(s: str) -> str:
    """Convert string to filesystem-safe name.

    Args:
        s (str): Input string.

    Returns:
        String with spaces and slashes replaced by underscores.
    """
    return s.replace(" ", "_").replace("/", "_")


def _write_config(run_dir: Path, config: BenchmarkConfig) -> None:
    """Serialise BenchmarkConfig to benchmark_config.json.

    Args:
        run_dir (Path): Root directory for this run.
        config (BenchmarkConfig): Config to serialise.
    """
    cfg_path = run_dir / "benchmark_config.json"
    cfg_path.write_text(json.dumps(asdict(config), indent=2))


# ---------------------------------------------------------------------------
# Per-MLIP job execution
# ---------------------------------------------------------------------------


def _run_mlip_job(
    run: BenchmarkRun,
    job: MlipJobState,
) -> None:
    """Execute sqscal for one MLIP inside the benchmark run.

    Streams stdout to job.log, discovers generated TDB, renders phase diagrams,
    and optionally computes metrics.  Checks ``run.cancel_flag`` before starting.

    Args:
        run (BenchmarkRun): Parent benchmark run.
        job (MlipJobState): Per-MLIP state updated in place.
    """
    if run.cancel_flag.is_set():
        job.state = "error"
        job.log.append(f"[benchmark] {job.mlip}: canceled before start")
        return

    config = run.config
    assert run.run_dir is not None
    mlip_dir = run.run_dir / "mlips" / _safe_name(job.mlip)

    cmd = [
        "sqscal",
        "-e", ",".join(config.elements),
        "-l", ",".join(config.phases),
        "-lv", str(config.level),
        "-mlip", job.mlip,
    ]
    if config.mode == "fixed":
        # Mode A: request static (no-relax) evaluation when upstream supports it.
        # sqscal does not currently expose a -norelax flag; we document this.
        job.log.append("[benchmark] NOTE: Mode A (fixed-structure) not yet supported by sqscal; running Mode B.")

    job.state = "running"
    job.start_time = time.time()
    job.log.append(f"[benchmark] {job.mlip}: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(mlip_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        job.state = "error"
        job.log.append(f"[benchmark] {job.mlip}: sqscal not found on PATH")
        job.end_time = time.time()
        return
    except OSError as exc:
        job.state = "error"
        job.log.append(f"[benchmark] {job.mlip}: launch failed: {exc}")
        job.end_time = time.time()
        return

    assert proc.stdout is not None
    for line in proc.stdout:
        if run.cancel_flag.is_set():
            proc.terminate()
            break
        job.log.append(line.rstrip("\n"))
    proc.wait()

    if run.cancel_flag.is_set():
        job.state = "error"
        job.log.append(f"[benchmark] {job.mlip}: canceled")
        job.end_time = time.time()
        return

    if proc.returncode != 0:
        job.state = "error"
        job.log.append(f"[benchmark] {job.mlip}: sqscal exited {proc.returncode}")
        job.end_time = time.time()
        return

    # Discover TDB output
    tdb_files = sorted(mlip_dir.rglob("*.tdb"))
    if not tdb_files:
        job.state = "error"
        job.log.append(f"[benchmark] {job.mlip}: no TDB found after sqscal")
        job.end_time = time.time()
        return

    tdb_path = tdb_files[0]
    job.tdb_path = str(tdb_path)
    job.log.append(f"[benchmark] {job.mlip}: TDB → {tdb_path.name}")

    # Copy TDB to run-level tdb/ directory
    dst_tdb = run.run_dir / "tdb" / f"{_safe_name(job.mlip)}.tdb"
    try:
        import shutil
        shutil.copy2(tdb_path, dst_tdb)
    except OSError:
        pass

    # Phase diagram PNGs
    try:
        pngs = _phase_diagram_from_tdb(tdb_path, t_min=config.t_min, t_max=config.t_max)
        # Copy PNGs to phase_diagrams/
        for png in pngs:
            dst = run.run_dir / "phase_diagrams" / f"{_safe_name(job.mlip)}_{png.name}"
            try:
                import shutil as _sh
                _sh.copy2(png, dst)
                job.png_paths.append(str(png))
            except OSError:
                job.png_paths.append(str(png))
        job.log.append(f"[benchmark] {job.mlip}: {len(pngs)} phase diagram(s) generated")
    except Exception as exc:
        job.log.append(f"[benchmark] {job.mlip}: phase diagram failed: {exc}")

    # Metrics vs reference TDB
    if config.reference_tdb:
        ref_path = Path(config.reference_tdb).expanduser().resolve()
        try:
            m = compute_metrics(
                tdb_path,
                ref_path,
                config.elements,
                t_min=config.t_min,
                t_max=config.t_max,
                t_step=config.t_step,
                x_step=config.x_step,
            )
            job.metrics = m
            # Save to metrics/ dir
            metrics_file = run.run_dir / "metrics" / f"{_safe_name(job.mlip)}.json"
            metrics_file.write_text(json.dumps(m, indent=2))
            job.log.append(f"[benchmark] {job.mlip}: metrics saved")
        except Exception as exc:
            job.metrics = {"available": False, "error": str(exc)}
    else:
        job.metrics = {"available": False, "error": "No reference TDB provided"}

    job.state = "done"
    job.end_time = time.time()
    job.log.append(f"[benchmark] {job.mlip}: done")


# ---------------------------------------------------------------------------
# Orchestration thread
# ---------------------------------------------------------------------------


def _orchestrate(run: BenchmarkRun) -> None:
    """Orchestration thread: run each MLIP job sequentially.

    Sequential execution avoids GPU memory conflicts between MLIP models.
    Sets ``run.state`` to ``"done"`` if all succeed, ``"error"`` on any failure,
    ``"canceled"`` if the cancel flag is set.

    Args:
        run (BenchmarkRun): The benchmark run to orchestrate.
    """
    run.state = "running"
    any_error = False

    for mlip in run.config.mlips:
        if run.cancel_flag.is_set():
            run.state = "canceled"
            return
        job = run.mlip_jobs[mlip]
        _run_mlip_job(run, job)
        if job.state == "error":
            any_error = True

    if run.cancel_flag.is_set():
        run.state = "canceled"
    elif any_error:
        run.state = "error"
    else:
        run.state = "done"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_and_launch_benchmark(
    elements: list[str],
    mlips: list[str],
    phases: list[str],
    workdir: str,
    *,
    level: int = 2,
    t_min: float = 300.0,
    t_max: float = 3000.0,
    t_step: float = 100.0,
    x_step: float = 0.02,
    mode: str = "relaxed",
    reference_tdb: str = "",
) -> str:
    """Create a benchmark run and start background orchestration.

    Args:
        elements (list[str]): Element symbols, e.g. ``["Cu", "Zr"]``.
        mlips (list[str]): MLIP names, e.g. ``["grace", "mace"]``.
        phases (list[str]): Lattice names for sqscal ``-l`` flag.
        workdir (str): Base directory; benchmark files go under
            ``<workdir>/benchmarks/``.
        level (int): SQS level for sqscal ``-lv``.
        t_min (float): Minimum temperature in K.
        t_max (float): Maximum temperature in K.
        t_step (float): Temperature step in K for metrics grid.
        x_step (float): Composition step for metrics grid.
        mode (str): ``"relaxed"`` (Mode B) or ``"fixed"`` (Mode A).
        reference_tdb (str): Path to reference TDB file.

    Returns:
        benchmark_id (str): 8-character hex ID for polling.
    """
    benchmark_id = str(uuid.uuid4())[:8]
    system = "-".join(sorted(e.capitalize() for e in elements))
    config = BenchmarkConfig(
        benchmark_id=benchmark_id,
        system=system,
        elements=elements,
        mlips=mlips,
        phases=phases,
        level=level,
        t_min=t_min,
        t_max=t_max,
        t_step=t_step,
        x_step=x_step,
        mode=mode,
        reference_tdb=reference_tdb,
        workdir=workdir,
        created_at=time.time(),
    )

    mlip_jobs = {m: MlipJobState(mlip=m) for m in mlips}
    run = BenchmarkRun(config=config, mlip_jobs=mlip_jobs)

    run.run_dir = _make_run_dir(config)
    _write_config(run.run_dir, config)
    _registry.add(run)

    t = threading.Thread(target=_orchestrate, args=(run,), daemon=True)
    run.thread = t
    t.start()
    return benchmark_id


def get_benchmark_status(benchmark_id: str) -> dict[str, Any] | None:
    """Serialise current benchmark state for the HTTP status endpoint.

    Args:
        benchmark_id (str): Benchmark identifier.

    Returns:
        JSON-serialisable dict or None if not found.
    """
    run = _registry.get(benchmark_id)
    if run is None:
        return None

    mlip_statuses: dict[str, Any] = {}
    for mlip, job in run.mlip_jobs.items():
        mlip_statuses[mlip] = {
            "state": job.state,
            "log_tail": job.log[-30:],
            "tdb_path": job.tdb_path,
            "png_paths": job.png_paths,
            "metrics": job.metrics,
            "elapsed_s": job.elapsed_s,
        }

    return {
        "benchmark_id": benchmark_id,
        "system": run.config.system,
        "state": run.state,
        "mlip_jobs": mlip_statuses,
        "created_at": run.config.created_at,
        "run_dir": str(run.run_dir) if run.run_dir else None,
        "config": asdict(run.config),
    }


def list_benchmarks() -> list[dict[str, Any]]:
    """Return summary list of all benchmark runs.

    Returns:
        List of dicts with ``benchmark_id``, ``system``, ``state``,
        ``created_at``, ``n_mlips``.
    """
    return [
        {
            "benchmark_id": r.config.benchmark_id,
            "system": r.config.system,
            "state": r.state,
            "created_at": r.config.created_at,
            "n_mlips": len(r.config.mlips),
            "mlips": r.config.mlips,
        }
        for r in _registry.list_all()
    ]


def cancel_benchmark(benchmark_id: str) -> bool:
    """Signal a running benchmark to stop after the current MLIP job.

    Args:
        benchmark_id (str): Benchmark identifier.

    Returns:
        True if benchmark found, False otherwise.
    """
    run = _registry.get(benchmark_id)
    if run is None:
        return False
    run.cancel_flag.set()
    return True


def delete_benchmark(benchmark_id: str) -> bool:
    """Remove a benchmark from the registry.

    Does not delete files from disk.

    Args:
        benchmark_id (str): Benchmark identifier.

    Returns:
        True if removed, False if not found.
    """
    return _registry.remove(benchmark_id)


def benchmark_tdb_path(benchmark_id: str, mlip: str) -> Path | None:
    """Return absolute TDB path for a completed MLIP job.

    Args:
        benchmark_id (str): Benchmark identifier.
        mlip (str): MLIP name.

    Returns:
        Path to TDB or None.
    """
    run = _registry.get(benchmark_id)
    if run is None:
        return None
    job = run.mlip_jobs.get(mlip)
    if job is None or job.tdb_path is None:
        return None
    return Path(job.tdb_path)


def benchmark_png_paths(benchmark_id: str, mlip: str) -> list[Path]:
    """Return PNG paths for a completed MLIP job's phase diagrams.

    Args:
        benchmark_id (str): Benchmark identifier.
        mlip (str): MLIP name.

    Returns:
        List of PNG Paths.
    """
    run = _registry.get(benchmark_id)
    if run is None:
        return []
    job = run.mlip_jobs.get(mlip)
    if job is None:
        return []
    return [Path(p) for p in job.png_paths]
