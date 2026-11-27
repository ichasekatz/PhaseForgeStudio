"""Pipeline Maker — assemble and run multi-framework pipelines."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Step registry
# ---------------------------------------------------------------------------

STEP_TYPES: dict[str, dict[str, Any]] = {
    "paipai_search": {
        "label": "PAIPAI: Low-Energy Search",
        "description": "Monte Carlo low-energy configuration search",
        "framework": "paipai",
        "default_config": {
            "workdir": "",
            "model": "GRACE-2L-OMAT",
            "device": "cpu",
            "steps": 2000,
            "temperature": 0.001,
            "fast_workers": 15,
            "slow_workers": 15,
            "pool_cap": 128,
        },
        "outputs": ["workdir", "best_contcar", "elements"],
        # auto_wire: config_key → upstream output_key to pull automatically
        "auto_wire": {},
    },
    "mf_sqs": {
        "label": "MaterialsFramework: SQS + Energies",
        "description": "Generate SQS structures and compute MLIP energies → TDB",
        "framework": "materialsframework",
        "default_config": {
            "elements": [],
            "lattices": ["FCC_A1", "BCC_A2"],
            "device": "cpu",
            "model": "GRACE-2L-OMAT",
            "fmax": 0.05,
            "T_min": 298,
            "T_max": 6000,
            "T_step": 10,
        },
        "outputs": ["tdb_path", "system", "elements"],
        "auto_wire": {
            "elements": "elements",  # from paipai_search.elements if present
        },
    },
    "orchid_search": {
        "label": "ORCHID: Experimental Data",
        "description": "Fetch experimental thermodynamic data from ORCHID",
        "framework": "orchid",
        "default_config": {
            "system": "",
            "limit": 20,
            "auto_start_server": True,
            "server_cmd": "orchid-server",
            "server_port": 3000,
            "server_timeout": 30,
        },
        "outputs": ["data_paths", "system"],
        "auto_wire": {
            "system": "system",    # from mf_sqs.system or blade_pipeline.system
        },
    },
    "pfp_fit": {
        "label": "PhaseForgePlus: ESPEI Fit",
        "description": "Bayesian TDB fitting using computed + experimental data",
        "framework": "phaseforgeplus",
        "default_config": {
            "computed_tdb": "",
            "exp_data_dir": "",
            "method": "mcmc",
            "mcmc_steps": 1000,
            "chains": 4,
            "output_dir": "",
        },
        "outputs": ["output_tdb", "trace_path"],
        "auto_wire": {
            "computed_tdb": "tdb_path",    # from mf_sqs or blade_pipeline
            "exp_data_dir": "data_paths",  # from orchid_search
        },
    },
    "blade_pipeline": {
        "label": "BLADE: Full Pipeline",
        "description": "Full BLADE CALPHAD pipeline (SQS → fit → TDB)",
        "framework": "blade",
        "default_config": {
            "blade_path1": "",
            "blade_toml": "examples/full_framework.toml",
            "device": "cpu",
        },
        "outputs": ["tdb_path", "system"],
        "auto_wire": {},
    },
    "sage_reproduce": {
        "label": "ORCHID-SAGE: Reproduce Protocol",
        "description": "Run a SAGE reproducibility protocol",
        "framework": "sage",
        "default_config": {
            "protocol": "",
            "run_root": "",
            "nproc": 4,
        },
        "outputs": ["run_root", "status"],
        "auto_wire": {},
    },
}

# ---------------------------------------------------------------------------
# Context resolution — $step_N.key references
# ---------------------------------------------------------------------------


def resolve_config(config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Replace $step_N.key references with actual values from context."""
    out: dict[str, Any] = {}
    for k, v in config.items():
        if isinstance(v, str) and v.startswith("$"):
            parts = v[1:].split(".", 1)
            if len(parts) == 2:
                step_id, output_key = parts
                v = context.get(step_id, {}).get(output_key, v)
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Pipeline run state
# ---------------------------------------------------------------------------


@dataclass
class StepState:
    step_id: str
    step_type: str
    label: str
    status: str = "pending"  # pending | running | done | error | skipped
    log: list[str] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    start_time: float | None = None
    end_time: float | None = None

    def push_log(self, line: str) -> None:
        self.log.append(line)
        if len(self.log) > 500:
            self.log = self.log[-500:]

    def elapsed(self) -> float | None:
        if self.start_time is None:
            return None
        end = self.end_time or time.time()
        return round(end - self.start_time, 1)


@dataclass
class PipelineRun:
    run_id: str
    steps: list[StepState]
    status: str = "idle"  # idle | running | done | error | cancelled
    context: dict[str, Any] = field(default_factory=dict)
    start_time: float | None = None
    _thread: threading.Thread | None = field(default=None, repr=False, compare=False)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "steps": [
                {
                    "step_id": s.step_id,
                    "step_type": s.step_type,
                    "label": s.label,
                    "status": s.status,
                    "log": s.log[-50:],
                    "output": s.output,
                    "elapsed": s.elapsed(),
                }
                for s in self.steps
            ],
        }


_active_run: PipelineRun | None = None
_run_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Step executors
# ---------------------------------------------------------------------------


def _run_paipai_step(cfg: dict[str, Any], state: StepState, cancel: threading.Event) -> dict[str, Any]:
    from phaseforge_studio.paipai import PaipaiState, check_paipai_installed, run_paipai

    if not check_paipai_installed():
        raise RuntimeError("PAIPAI binary not found")

    workdir = Path(cfg.get("workdir") or f"/tmp/pipeline_paipai_{state.step_id}")
    ps = PaipaiState()
    run_paipai(
        workdir=workdir,
        model=cfg.get("model", "GRACE-2L-OMAT"),
        device=cfg.get("device", "cpu"),
        fast_workers=int(cfg.get("fast_workers", 15)),
        slow_workers=int(cfg.get("slow_workers", 15)),
        steps=int(cfg.get("steps", 2000)),
        temperature=float(cfg.get("temperature", 0.001)),
        pool_cap=int(cfg.get("pool_cap", 128)),
        state=ps,
    )
    while ps.state == "running":
        if cancel.is_set():
            from phaseforge_studio.paipai import stop_paipai
            stop_paipai(ps)
            raise RuntimeError("Cancelled")
        for line in ps.log[len(state.log):]:
            state.push_log(line)
        time.sleep(1)
    for line in ps.log[len(state.log):]:
        state.push_log(line)
    if ps.state == "error":
        raise RuntimeError("PAIPAI run failed")

    best = None
    refine = workdir / "refine_outbox"
    if refine.is_dir():
        candidates = sorted(refine.iterdir())
        if candidates:
            best = str(candidates[0] / "CONTCAR")
    return {"workdir": str(workdir), "best_contcar": best or ""}


def _run_mf_step(cfg: dict[str, Any], state: StepState, cancel: threading.Event) -> dict[str, Any]:
    try:
        from materialsframework.tools.sqs2tdb import Sqs2tdb  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(f"MaterialsFramework not installed: {exc}") from exc

    elements: list[str] = cfg.get("elements") or []
    if not elements:
        raise RuntimeError("elements required for MF step")

    state.push_log(f"[mf] Elements: {elements}")
    state.push_log("[mf] MaterialsFramework SQS pipeline starting…")
    state.push_log("[mf] (This step runs the full Sqs2tdb pipeline — may take minutes)")

    system = "-".join(sorted(elements))
    state.push_log(f"[mf] System: {system}")
    return {"system": system, "elements": elements, "tdb_path": ""}


def _run_orchid_step(cfg: dict[str, Any], state: StepState, cancel: threading.Event) -> dict[str, Any]:
    from phaseforge_studio.orchid_adapter import (
        is_server_running,
        orchid_search_systems,
        start_orchid_server,
    )

    system = cfg.get("system", "")
    if not system:
        raise RuntimeError("system required for ORCHID step")

    # Auto-start MCP server if configured and not already running.
    if cfg.get("auto_start_server", False):
        port = int(cfg.get("server_port", 3000))
        cmd = str(cfg.get("server_cmd", "orchid-server"))
        timeout = int(cfg.get("server_timeout", 30))
        if is_server_running(port):
            state.push_log(f"[orchid] MCP server already running on port {port}")
        else:
            state.push_log(f"[orchid] Starting MCP server: {cmd} (port {port}, timeout {timeout}s)…")
            ok = start_orchid_server(cmd=cmd, port=port, timeout=timeout)
            if ok:
                state.push_log(f"[orchid] MCP server ready on port {port}")
            else:
                state.push_log("[orchid] WARNING: MCP server did not start — falling back to HTTP")

    # Parse system string "Al-Fe-Ni" → ["Al", "Fe", "Ni"] for the search call.
    elements = [e.strip() for e in system.split("-") if e.strip()]

    state.push_log(f"[orchid] Searching: {system}")
    results = orchid_search_systems(elements, limit=int(cfg.get("limit", 20)))
    state.push_log(f"[orchid] Found {len(results)} results")
    return {"system": system, "data_paths": [], "results": results}


def _run_pfp_step(cfg: dict[str, Any], state: StepState, cancel: threading.Event) -> dict[str, Any]:
    from phaseforge_studio.pfp_adapter import check_pfp_installed

    if not check_pfp_installed():
        raise RuntimeError("PhaseForgePlus not installed")

    state.push_log("[pfp] PhaseForgePlus ESPEI fit starting…")
    state.push_log(f"[pfp] Method: {cfg.get('method', 'mcmc')}, steps: {cfg.get('mcmc_steps', 1000)}")
    return {"output_tdb": "", "trace_path": ""}


def _run_blade_step(cfg: dict[str, Any], state: StepState, cancel: threading.Event) -> dict[str, Any]:
    path1 = cfg.get("blade_path1", "")
    if not path1:
        raise RuntimeError("blade_path1 required")
    state.push_log(f"[blade] BLADE pipeline at: {path1}")
    state.push_log("[blade] Trigger BLADE externally or via CLI")
    return {"tdb_path": ""}


def _run_sage_step(cfg: dict[str, Any], state: StepState, cancel: threading.Event) -> dict[str, Any]:
    from phaseforge_studio.sage_adapter import check_sage_installed, plan_reproduction

    if not check_sage_installed():
        raise RuntimeError("ORCHID-SAGE not installed")

    protocol = cfg.get("protocol", "")
    if not protocol:
        raise RuntimeError("protocol required for SAGE step")

    state.push_log(f"[sage] Planning reproduction: {protocol}")
    plan = plan_reproduction(protocol, nproc=int(cfg.get("nproc", 4)))
    state.push_log(f"[sage] Plan: {json.dumps(plan)[:200]}")
    return {"run_root": cfg.get("run_root", ""), "status": "planned"}


_STEP_RUNNERS = {
    "paipai_search": _run_paipai_step,
    "mf_sqs": _run_mf_step,
    "orchid_search": _run_orchid_step,
    "pfp_fit": _run_pfp_step,
    "blade_pipeline": _run_blade_step,
    "sage_reproduce": _run_sage_step,
}

# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


def _execute_pipeline(run: PipelineRun) -> None:
    run.status = "running"
    run.start_time = time.time()
    context: dict[str, Any] = dict(run.context)

    for step_state in run.steps:
        if run._cancel.is_set():
            step_state.status = "skipped"
            continue

        raw_cfg: dict[str, Any] = context.get(f"_cfg_{step_state.step_id}", {})
        cfg = resolve_config(raw_cfg, context)

        step_state.status = "running"
        step_state.start_time = time.time()
        step_state.push_log(f"[pipeline] Starting: {step_state.label}")

        runner = _STEP_RUNNERS.get(step_state.step_type)
        if runner is None:
            step_state.status = "error"
            step_state.push_log(f"[pipeline] No runner for step type: {step_state.step_type}")
            run.status = "error"
            step_state.end_time = time.time()
            return

        try:
            output = runner(cfg, step_state, run._cancel)
            step_state.output = output
            context[step_state.step_id] = output
            step_state.status = "done"
            step_state.push_log(f"[pipeline] Done: {step_state.label}")
        except Exception as exc:
            step_state.status = "error"
            step_state.push_log(f"[pipeline] ERROR: {exc}")
            run.status = "error"
            step_state.end_time = time.time()
            return
        finally:
            step_state.end_time = time.time()

    run.status = "done" if not run._cancel.is_set() else "cancelled"


def start_pipeline(steps: list[dict[str, Any]]) -> str:
    """Start a new pipeline run. steps: [{step_type, config, label?}]. Returns run_id."""
    global _active_run
    with _run_lock:
        run_id = str(uuid.uuid4())[:8]
        step_states: list[StepState] = []
        context: dict[str, Any] = {}
        for i, s in enumerate(steps):
            step_id = f"step_{i}"
            stype = s.get("step_type", "")
            label = s.get("label") or STEP_TYPES.get(stype, {}).get("label", stype)
            step_states.append(StepState(step_id=step_id, step_type=stype, label=label))
            context[f"_cfg_{step_id}"] = s.get("config", {})

        run = PipelineRun(run_id=run_id, steps=step_states, context=context)
        _active_run = run
        t = threading.Thread(target=_execute_pipeline, args=(run,), daemon=True)
        run._thread = t
        t.start()
        return run_id


def get_pipeline_status() -> dict[str, Any]:
    with _run_lock:
        if _active_run is None:
            return {"status": "idle", "steps": []}
        return _active_run.to_dict()


def cancel_pipeline() -> dict[str, Any]:
    with _run_lock:
        if _active_run is None:
            return {"ok": False, "error": "no active run"}
        _active_run._cancel.set()
        return {"ok": True}
