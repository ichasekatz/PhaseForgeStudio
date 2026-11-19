"""PhaseForgePlus adapter for PhaseForgeStudio.

PhaseForgePlus is a thermodynamic database optimisation package built on
pycalphad and ESPEI.  It takes an existing TDB file (from PhaseForge or any
other source), experimental Zero Phase Fraction (ZPF) YAML data, and uses
analytic Jansson-derivative gradient descent to fit Gibbs-energy model
parameters.

Installation::

    pip install -e /path/to/PhaseForgePlus/

Upstream source: https://github.com/dogusariturk/PhaseForgePlus
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional-dependency detection
# ---------------------------------------------------------------------------

_pfp_available: bool
try:
    import phaseforgeplus  # noqa: F401

    _pfp_available = True
except ImportError:
    _pfp_available = False


def check_pfp_installed() -> bool:
    """Return True if phaseforgeplus is importable in the current Python env."""
    return _pfp_available


def pfp_install_hint() -> str:
    """Return a human-readable install hint when PFP is missing."""
    return (
        "phaseforgeplus not found.\n"
        "Install from local source:\n"
        "  pip install -e /path/to/PhaseForgePlus/"
    )


# ---------------------------------------------------------------------------
# Supported optimizer methods
# ---------------------------------------------------------------------------

#: Methods supported by scipy.optimize.minimize that PFP exposes.
supported_methods: list[str] = ["CG", "L-BFGS-B", "BFGS"]

_method_descriptions: dict[str, str] = {
    "CG": "Conjugate Gradient — default; analytic Jansson gradient required.",
    "L-BFGS-B": "Limited-memory BFGS with box constraints.",
    "BFGS": "Full BFGS; analytic gradient still used.",
}


def method_info(method: str) -> dict[str, str]:
    """Return display metadata for an optimiser method.

    Args:
        method (str): One of the keys in ``supported_methods``.

    Returns:
        dict with 'name' and 'description' keys.
    """
    return {
        "name": method,
        "description": _method_descriptions.get(method, ""),
    }


# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------


@dataclass
class PfpJob:
    """Mutable state for a single PFP optimisation run.

    Attributes:
        state (str): One of 'idle', 'running', 'done', 'error', 'canceled'.
        log (list[str]): Captured stdout lines from the optimiser.
        result (dict[str, Any] | None): Serialisable result once complete.
        error (str): Last error message, if any.
        thread (threading.Thread | None): Background optimiser thread.
        cancel_flag (threading.Event): Set to request cancellation.
        iterations (list[dict]): Per-iteration callback data for live plots.
    """

    state: str = "idle"
    log: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str = ""
    thread: threading.Thread | None = None
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    iterations: list[dict[str, Any]] = field(default_factory=list)
    start_time: float | None = None
    end_time: float | None = None

    @property
    def elapsed_s(self) -> float | None:
        """Elapsed wall-clock seconds; None before start, frozen after stop."""
        if self.start_time is None:
            return None
        end = self.end_time if self.end_time is not None else time.time()
        return end - self.start_time


# ---------------------------------------------------------------------------
# Iteration callback
# ---------------------------------------------------------------------------


def _make_callback(job: PfpJob) -> Any:
    """Return a scipy callback that records per-iteration data into job.

    Args:
        job (PfpJob): Job whose ``iterations`` list receives each record.

    Returns:
        A callable compatible with ``scipy.optimize.minimize(callback=...)``.
    """
    iteration_counter = [0]

    def _cb(xk: Any) -> bool:
        """Scipy minimise callback — records parameter vector and checks cancel."""
        import numpy as np

        it = iteration_counter[0]
        iteration_counter[0] += 1
        job.iterations.append({"iteration": it, "params": np.asarray(xk).tolist()})
        return job.cancel_flag.is_set()

    return _cb


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------


def _run_pfp(
    job: PfpJob,
    tdb_path: str,
    zpf_dir: str,
    points: list[int],
    pressure: float,
    temperature: float,
    method: str,
    tol: float | None,
    maxiter: int | None,
    output_path: str,
) -> None:
    """Background thread: run PhaseForgePlus optimisation and write output TDB.

    Args:
        job (PfpJob): Job state object updated throughout.
        tdb_path (str): Path to input TDB file.
        zpf_dir (str): Directory containing ZPF YAML files.
        points (list[int]): Point indices for NEQ data generation.
        pressure (float): Pressure in Pa.
        temperature (float): Temperature in K.
        method (str): scipy optimiser method name.
        tol (float | None): Convergence tolerance; None → scipy default.
        maxiter (int | None): Maximum iterations; None → scipy default.
        output_path (str): Where to write the fitted TDB.
    """
    from phaseforgeplus.main import PhaseForgePlus
    from scipy import optimize as scipy_optimize

    job.start_time = time.time()
    job.log.append(f"[pfp] Loading TDB: {tdb_path}")
    job.log.append(f"[pfp] ZPF directory: {zpf_dir}")
    job.log.append(f"[pfp] Method: {method}")

    try:
        pfp = PhaseForgePlus(
            db=tdb_path,
            zpf_path=zpf_dir,
            points=points,
            pressure=pressure,
            temperature=temperature,
        )
    except Exception as exc:
        job.state = "error"
        job.error = f"Initialisation failed: {exc}"
        job.log.append(f"[pfp] ERROR: {exc}")
        job.end_time = time.time()
        return

    initial = pfp.get_initial_values()
    n_params = len(initial)
    job.log.append(f"[pfp] Parameters to fit: {n_params}")
    job.log.append("[pfp] Starting optimisation …")

    options: dict[str, Any] = {"disp": True}
    if maxiter is not None:
        options["maxiter"] = maxiter

    from phaseforgeplus.utils.objective import objective_function

    func = objective_function(pfp.db, pfp.db_zpf, pfp.db_neq)
    callback = _make_callback(job)

    try:
        opt_result: scipy_optimize.OptimizeResult = scipy_optimize.minimize(
            func,
            initial,
            jac=True,
            method=method,
            tol=tol,
            options=options,
            callback=callback,
        )
    except Exception as exc:
        job.state = "error"
        job.error = f"Optimisation failed: {exc}"
        job.log.append(f"[pfp] ERROR: {exc}")
        job.end_time = time.time()
        return

    if job.cancel_flag.is_set():
        job.state = "canceled"
        job.log.append("[pfp] Canceled by user.")
        job.end_time = time.time()
        return

    job.log.append(f"[pfp] Converged: {opt_result.success}  fun={opt_result.fun:.6g}  nit={opt_result.nit}")

    # --- write fitted TDB ---
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from espei.utils import database_symbols_to_fit
        from pycalphad import Database

        symbols = database_symbols_to_fit(pfp.db)
        fitted_db: Database = pfp.db
        for sym, val in zip(symbols, opt_result.x, strict=True):
            fitted_db.symbols[sym] = val
        with out.open("w", encoding="utf-8") as fh:
            fh.write(fitted_db.to_string(fmt="tdb"))
        job.log.append(f"[pfp] Fitted TDB written: {out}")
    except Exception as exc:
        job.log.append(f"[pfp] WARNING: could not write TDB: {exc}")

    job.result = {
        "success": bool(opt_result.success),
        "fun": float(opt_result.fun),
        "nit": int(opt_result.nit),
        "nfev": int(opt_result.nfev),
        "message": str(opt_result.message),
        "n_params": n_params,
        "output_tdb": str(out) if out.exists() else None,
        "iterations": job.iterations,
    }
    job.state = "done" if opt_result.success else "error"
    if not opt_result.success:
        job.error = opt_result.message
    job.end_time = time.time()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def launch_pfp(
    job: PfpJob,
    tdb_path: str,
    zpf_dir: str,
    points: list[int],
    pressure: float,
    temperature: float,
    method: str = "CG",
    tol: float | None = None,
    maxiter: int | None = None,
    output_path: str = "",
) -> None:
    """Start a PhaseForgePlus optimisation in a background thread.

    The job's ``state`` transitions from 'idle' → 'running' immediately;
    the thread updates it to 'done', 'error', or 'canceled' on completion.

    Args:
        job (PfpJob): Mutable job state object.
        tdb_path (str): Path to input TDB file.
        zpf_dir (str): Directory containing ZPF YAML files (searched recursively).
        points (list[int]): Point indices for non-equilibrium data generation.
        pressure (float): Pressure in Pa (default 101325).
        temperature (float): Temperature in K (default 298.15).
        method (str): Scipy optimiser method; one of ``supported_methods``.
        tol (float | None): Convergence tolerance; None → scipy default.
        maxiter (int | None): Max iterations; None → scipy default.
        output_path (str): Where to write the fitted TDB.  Defaults to
            input path with ``_fitted`` suffix.
    """
    if not output_path:
        p = Path(tdb_path)
        output_path = str(p.parent / (p.stem + "_fitted" + p.suffix))

    job.state = "running"
    job.log = []
    job.result = None
    job.error = ""
    job.iterations = []
    job.cancel_flag.clear()
    job.start_time = None
    job.end_time = None

    t = threading.Thread(
        target=_run_pfp,
        args=(job, tdb_path, zpf_dir, points, pressure, temperature, method, tol, maxiter, output_path),
        daemon=True,
    )
    job.thread = t
    t.start()


def cancel_pfp(job: PfpJob) -> None:
    """Signal a running PFP job to stop at the next callback iteration.

    Args:
        job (PfpJob): Job to cancel.
    """
    job.cancel_flag.set()


def pfp_status(job: PfpJob) -> dict[str, Any]:
    """Serialise current job state for the HTTP status endpoint.

    Args:
        job (PfpJob): Current job.

    Returns:
        JSON-serialisable dict with state, log tail, progress, and result.
    """
    return {
        "state": job.state,
        "installed": check_pfp_installed(),
        "log_tail": job.log[-80:],
        "elapsed_s": job.elapsed_s,
        "n_iterations": len(job.iterations),
        "last_iteration": job.iterations[-1] if job.iterations else None,
        "result": job.result,
        "error": job.error,
    }
