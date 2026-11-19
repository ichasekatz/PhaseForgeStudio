"""Workflow and action registry for cross-framework data transfer.

Workflows are named chains of framework operations.  Each step declares
its input artifact type and the framework that processes it.  The registry
validates compatibility before execution and routes the transfer call to
the correct backend adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class WorkflowError(RuntimeError):
    """Raised when a workflow step cannot be executed."""


class IncompatibleTransferError(WorkflowError):
    """Raised when source and target are scientifically incompatible."""


@dataclass(frozen=True)
class WorkflowStep:
    """One step in a named workflow.

    Attributes:
        step_id: Stable step identifier.
        label: Human-readable label.
        source_framework: Framework that produces the artifact.
        target_framework: Framework that consumes the artifact.
        input_types: Accepted file-type constants.
        action_id: ``ArtifactAction.action_id`` to execute.
        description: One-sentence description.
    """

    step_id: str
    label: str
    source_framework: str
    target_framework: str
    input_types: frozenset[str]
    action_id: str
    description: str = ""


@dataclass
class Workflow:
    """Named sequence of WorkflowSteps.

    Attributes:
        workflow_id: Stable workflow identifier.
        name: Human-readable name.
        description: Multi-sentence description.
        steps: Ordered list of steps.
    """

    workflow_id: str
    name: str
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Transfer handlers
# ---------------------------------------------------------------------------

# Registered as: (source_framework, target_framework, action_id) → handler fn
# Handler signature: (source_path: Path, target_config: dict) → dict[str, Any]
_transfer_handlers: dict[tuple[str, str, str], Callable[[Path, dict[str, Any]], dict[str, Any]]] = {}


def register_handler(
    source_fw: str,
    target_fw: str,
    action_id: str,
    fn: Callable[[Path, dict[str, Any]], dict[str, Any]],
) -> None:
    """Register a transfer handler for a (source, target, action) triple.

    Args:
        source_fw (str): Source framework key.
        target_fw (str): Target framework key.
        action_id (str): ``ArtifactAction.action_id``.
        fn: Handler callable taking ``(source_path, target_config) → result_dict``.
    """
    _transfer_handlers[(source_fw, target_fw, action_id)] = fn


def execute_transfer(
    source_path: Path,
    source_fw: str,
    action_id: str,
    target_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a cross-framework transfer action.

    Args:
        source_path (Path): Path to the source artifact.
        source_fw (str): Source framework key.
        action_id (str): Action to execute.
        target_config (dict[str, Any] | None): Target-framework configuration.

    Returns:
        Result dict (content depends on the handler).

    Raises:
        WorkflowError: If no handler is registered for this triple.
        IncompatibleTransferError: If the action is scientifically invalid.
    """
    from phaseforge_studio.core.artifact_registry import actions_for_file, detect

    ft = detect(source_path)
    actions = actions_for_file(source_path, ft)
    matched = [a for a in actions if a["action_id"] == action_id]
    if not matched:
        raise IncompatibleTransferError(
            f"Action {action_id!r} is not valid for file type {ft!r} at {source_path}."
        )
    act = matched[0]
    target_fw = act["framework"]
    key = (source_fw, target_fw, action_id)
    handler = _transfer_handlers.get(key)
    if handler is None:
        # Try without source_fw (generic handler)
        handler = _transfer_handlers.get(("*", target_fw, action_id))
    if handler is None:
        raise WorkflowError(
            f"No handler registered for transfer {source_fw!r} → {target_fw!r} action={action_id!r}."
        )
    return handler(source_path, target_config or {})


# ---------------------------------------------------------------------------
# Built-in workflows
# ---------------------------------------------------------------------------

_all_workflows: list[Workflow] = []

from phaseforge_studio.core.file_types import (  # noqa: E402
    FT_CSV,
    FT_EXTXYZ,
    FT_JSON,
    FT_POSCAR,
    FT_TDB,
    FT_XYZ,
)

_all_workflows += [
    Workflow(
        workflow_id="pf_to_paipai",
        name="PhaseForge SQS → PAIPAI",
        description=(
            "Generate an SQS in PhaseForge, select the structure in the file explorer, "
            "convert to PAIPAI struc.in, and run Monte Carlo interstitial search."
        ),
        steps=[
            WorkflowStep(
                step_id="select_sqs",
                label="Select SQS structure",
                source_framework="pf",
                target_framework="paipai",
                input_types=frozenset({FT_POSCAR, FT_XYZ, FT_EXTXYZ}),
                action_id="paipai_set_input",
                description="Send SQS POSCAR/CONTCAR to PAIPAI as the host lattice.",
            ),
        ],
    ),
    Workflow(
        workflow_id="pf_to_blade",
        name="PhaseForge TDB → BLADE Analysis",
        description="Generate a TDB in the MF/BLADE workflow, then open it in BLADE for phase diagram calculations.",
        steps=[
            WorkflowStep(
                step_id="open_tdb",
                label="Open TDB in BLADE",
                source_framework="pf",
                target_framework="blade",
                input_types=frozenset({FT_TDB}),
                action_id="blade_open_tdb",
                description="Load generated TDB into BLADE for Gibbs energy and phase diagram analysis.",
            ),
        ],
    ),
    Workflow(
        workflow_id="orchid_to_blade",
        name="ORCHID Data → BLADE Fitting",
        description="Retrieve literature data via ORCHID, import the TDB, and validate BLADE fitting against experimental measurements.",
        steps=[
            WorkflowStep(
                step_id="import_tdb",
                label="Import ORCHID TDB",
                source_framework="orchid",
                target_framework="blade",
                input_types=frozenset({FT_TDB}),
                action_id="blade_open_tdb",
                description="Import ORCHID TDB into BLADE for fitting comparison.",
            ),
        ],
    ),
    Workflow(
        workflow_id="blade_to_orchid",
        name="BLADE Stability → ORCHID Comparison",
        description="Run BLADE stability calculations and compare results against ORCHID experimental data.",
        steps=[
            WorkflowStep(
                step_id="compare_stability",
                label="Compare stability with ORCHID",
                source_framework="blade",
                target_framework="orchid",
                input_types=frozenset({FT_CSV, FT_JSON}),
                action_id="orchid_compare_stability",
                description="Overlay stability metrics with ORCHID experimental measurements.",
            ),
        ],
    ),
    Workflow(
        workflow_id="paipai_to_mf",
        name="PAIPAI Best Structure → MF Viewer",
        description="Take the lowest-energy PAIPAI output and visualise it in the Materials Framework structure viewer.",
        steps=[
            WorkflowStep(
                step_id="view_best",
                label="View best structure in MF",
                source_framework="paipai",
                target_framework="mf",
                input_types=frozenset({FT_POSCAR}),
                action_id="view_structure",
                description="Load PAIPAI CONTCAR into 3Dmol viewer for inspection.",
            ),
        ],
    ),
]


def list_workflows() -> list[dict[str, Any]]:
    """Return JSON-serialisable summaries of all registered workflows.

    Returns:
        List of dicts with workflow metadata.
    """
    return [
        {
            "workflow_id": w.workflow_id,
            "name": w.name,
            "description": w.description,
            "n_steps": len(w.steps),
            "frameworks": sorted({s.source_framework for s in w.steps} | {s.target_framework for s in w.steps}),
        }
        for w in _all_workflows
    ]


def get_workflow(workflow_id: str) -> Workflow | None:
    """Return a workflow by ID, or None.

    Args:
        workflow_id (str): Workflow identifier.

    Returns:
        ``Workflow`` instance or ``None``.
    """
    return next((w for w in _all_workflows if w.workflow_id == workflow_id), None)
