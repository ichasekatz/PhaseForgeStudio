"""Background pipeline runner and trajectory-tracking Sqs2tdb factory."""

from __future__ import annotations

import contextlib
import os
import traceback
from pathlib import Path
from typing import Any

from phaseforge_studio.filesystem import list_available_calculators
from phaseforge_studio.job import JobState, _LogCapture
from phaseforge_studio.plotting import _generate_phase_diagrams


def _make_tracking_sqs2tdb() -> type:
    """Return a Sqs2tdb subclass that saves trajectory.pkl per sqs_lev subdir.

    The subclass overrides ``_calculate`` to set ``calculator.traj_file``
    before each relaxation so BaseCalculator writes per-step trajectory data.

    Returns:
        A dynamically-created subclass of ``materialsframework.tools.sqs2tdb.Sqs2tdb``.
    """
    from materialsframework.tools.sqs2tdb import Sqs2tdb

    class _TrackingSqs2tdb(Sqs2tdb):
        def _calculate(self, subdir: Path, relax: bool = True) -> None:
            self.calculator.traj_file = str(subdir / "trajectory.pkl")
            try:
                super()._calculate(subdir, relax)
            finally:
                self.calculator.traj_file = None

    return _TrackingSqs2tdb


def _run_pipeline(cfg: dict[str, Any], job: JobState) -> None:
    """Run the full Sqs2tdb pipeline in a background thread.

    Imports materialsframework lazily, sets up the calculator, runs
    ``Sqs2tdb.fit()``, then generates phase diagrams. All stdout/stderr
    is redirected to the job log via ``_LogCapture``.

    Args:
        cfg (dict[str, Any]): Config snapshot taken at job start.
        job (JobState): Active job for state management and log forwarding.
    """
    capture = _LogCapture(job)
    origin = Path.cwd()
    try:
        job.push_log(f"[studio] Starting pipeline — job {job.job_id}")
        job.push_log(f"[studio] species={cfg['species']} lattices={cfg['lattices']}")
        job.push_log(f"[studio] calculator={cfg['calculator']} device={cfg.get('device', 'cpu')} fmax={cfg['fmax']}")

        from materialsframework.calculators.registry import get_calculator
        from materialsframework.tools.sqs2tdb import Sqs2tdb

        sqs_cls = _make_tracking_sqs2tdb() if cfg.get("track_trajectory") else Sqs2tdb

        path1 = Path(cfg["path1"]).expanduser().resolve()

        system_name = "".join(cfg["species"])
        work_dir = path1 / "Jobs" / job.job_id / system_name
        work_dir.mkdir(parents=True, exist_ok=True)
        job.push_log(f"[studio] Work dir: {work_dir}")

        _device_calcs = {m["name"] for m in list_available_calculators() if m["supports_device"]}
        calc_kwargs: dict[str, Any] = {}
        if cfg.get("device") and cfg["calculator"] in _device_calcs:
            calc_kwargs["device"] = cfg["device"]
        calculator = get_calculator(cfg["calculator"], **calc_kwargs)

        # Pre-warm the underlying ASE calculator so heavy imports (tensorflow, etc.)
        # happen BEFORE stdout/stderr are redirected to _LogCapture (which lacks fileno()).
        try:
            _ = calculator.calculator
            job.push_log(f"[studio] Calculator loaded: {type(_).__name__}")
        except Exception as _pre_e:
            job.push_log(f"[studio] Calculator pre-load warning: {_pre_e}")

        pipeline = sqs_cls(
            fmax=cfg["fmax"],
            calculator=calculator,
            md_temperature=cfg.get("md_temperature", 1000),
            md_pressure=cfg.get("md_pressure", 1),
            md_timestep=cfg.get("md_timestep", 1.0),
            md_scaling_matrix=cfg.get("md_scaling_matrix", 2),
            verbose=True,
        )

        os.chdir(work_dir)
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            pipeline.fit(
                species=cfg["species"],
                lattices=cfg.get("lattices"),
                level=cfg.get("level", 1),
                t_min=cfg.get("t_min", 298.15),
                t_max=cfg.get("t_max", 6000.0),
                sro=cfg.get("sro", False),
                bv=cfg.get("bv", 5e-3),
                phonon=cfg.get("phonon", False),
                open_calphad=cfg.get("open_calphad", False),
                terms=cfg.get("terms") or None,
            )

        if job.is_running():
            job.push_log("[studio] Pipeline complete — generating phase diagrams...")
            _generate_phase_diagrams(work_dir, cfg["species"], cfg.get("lattices", []), job)
            job.set_state("done")

    except ImportError as e:
        job.push_log(f"[studio] Import error: {e}")
        job.push_log(traceback.format_exc()[:2000])
        job.set_state("error")
    except Exception as e:
        job.push_log(f"[studio] Error: {e}")
        capture.write(traceback.format_exc())
        capture.flush()
        job.set_state("error")
    finally:
        os.chdir(origin)
