"""Artifact registry: maps file types to supported frameworks and actions.

Each framework registers its capabilities once.  The registry then answers
"which actions are available for this file?" without hardcoding every
combination in a separate if/elif chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phaseforge_studio.core.file_types import (
    FT_BESTSQS,
    FT_CIF,
    FT_CSV,
    FT_EXTXYZ,
    FT_IMAGE,
    FT_JSON,
    FT_LAMMPS_DATA,
    FT_LAMMPS_DUMP,
    FT_POSCAR,
    FT_TDB,
    FT_TRAJECTORY_PKL,
    FT_TRAJECTORY_XYZ,
    FT_TSV,
    FT_XYZ,
    detect,
)


@dataclass(frozen=True)
class ArtifactAction:
    """A single action that can be performed on an artifact.

    Attributes:
        action_id: Stable identifier (used as the API ``action`` parameter).
        label: Short human-readable label shown in the context menu.
        framework: Destination framework key (``"mf"``, ``"pf"``, ``"blade"``,
            ``"paipai"``, ``"orchid"``).
        input_types: Set of file-type constants this action accepts.
        description: One-sentence explanation shown as tooltip.
        requires_conversion: True if the file must be converted before use.
        conversion_note: What conversion is applied, if any.
    """

    action_id: str
    label: str
    framework: str
    input_types: frozenset[str]
    description: str = ""
    requires_conversion: bool = False
    conversion_note: str = ""


@dataclass
class Artifact:
    """An artifact: a file produced by or usable by a framework.

    Attributes:
        path: Absolute path to the file.
        ft: Detected file type constant.
        framework: Originating framework key, or ``""`` if unknown.
        label: Display name.
        meta: Optional lightweight metadata (n_atoms, energy, etc.).
        provenance: Optional provenance dict (composition, temperature, etc.).
    """

    path: Path
    ft: str
    framework: str = ""
    label: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Ensure label defaults to filename."""
        if not self.label:
            self.label = self.path.name

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot.

        Returns:
            Dict with path, ft, framework, label, meta, provenance.
        """
        return {
            "path": str(self.path),
            "ft": self.ft,
            "framework": self.framework,
            "label": self.label,
            "meta": self.meta,
            "provenance": self.provenance,
        }


# ---------------------------------------------------------------------------
# Registered actions (populated below)
# ---------------------------------------------------------------------------

_structure_types = frozenset({FT_POSCAR, FT_CIF, FT_XYZ, FT_EXTXYZ, FT_BESTSQS, FT_LAMMPS_DATA})
_trajectory_types = frozenset({FT_TRAJECTORY_PKL, FT_TRAJECTORY_XYZ, FT_LAMMPS_DUMP})

_all_actions: list[ArtifactAction] = [
    # ── Universal ────────────────────────────────────────────────────────
    ArtifactAction(
        action_id="view_structure",
        label="Open in Structure Viewer",
        framework="mf",
        input_types=_structure_types,
        description="Visualise the atomic structure using the 3Dmol viewer.",
    ),
    ArtifactAction(
        action_id="view_trajectory",
        label="Open Trajectory Viewer",
        framework="mf",
        input_types=_trajectory_types,
        description="Step through trajectory frames in the 3Dmol viewer.",
    ),
    # ── PhaseForge ───────────────────────────────────────────────────────
    ArtifactAction(
        action_id="pf_use_as_reference",
        label="Use as PhaseForge Reference Structure",
        framework="pf",
        input_types=_structure_types,
        description="Set this structure as the reference input for SQS generation.",
    ),
    ArtifactAction(
        action_id="pf_open_tdb",
        label="Plot Phase Diagram (PhaseForge)",
        framework="pf",
        input_types=frozenset({FT_TDB}),
        description="Load this TDB into pycalphad and plot binary / ternary phase diagrams.",
    ),
    ArtifactAction(
        action_id="pf_compare_orchid",
        label="Compare with ORCHID Data",
        framework="orchid",
        input_types=frozenset({FT_TDB}),
        description="Cross-reference TDB predictions against ORCHID experimental literature.",
    ),
    # ── BLADE ────────────────────────────────────────────────────────────
    ArtifactAction(
        action_id="blade_open_tdb",
        label="Open in BLADE",
        framework="blade",
        input_types=frozenset({FT_TDB}),
        description="Open this TDB in the BLADE fitting and analysis workspace.",
    ),
    ArtifactAction(
        action_id="blade_gibbs_eval",
        label="Evaluate Gibbs Energies",
        framework="blade",
        input_types=frozenset({FT_TDB}),
        description="Run pycalphad Gibbs energy evaluation over T and composition.",
    ),
    ArtifactAction(
        action_id="blade_phase_fractions",
        label="Calculate Phase Fractions",
        framework="blade",
        input_types=frozenset({FT_TDB}),
        description="Run equilibrium calculation and plot phase fractions vs. T.",
    ),
    # ── PAIPAI ───────────────────────────────────────────────────────────
    ArtifactAction(
        action_id="paipai_set_input",
        label="Use as PAIPAI Input Structure",
        framework="paipai",
        input_types=_structure_types,
        description="Convert to struc.in and populate PAIPAI configuration.",
        requires_conversion=True,
        conversion_note="POSCAR → PAIPAI struc.in",
    ),
    ArtifactAction(
        action_id="paipai_set_poscar",
        label="Paste into PAIPAI POSCAR Field",
        framework="paipai",
        input_types=frozenset({FT_POSCAR, FT_EXTXYZ}),
        description="Pre-fill the PAIPAI POSCAR/struc.in builder with this structure.",
    ),
    # ── ORCHID ───────────────────────────────────────────────────────────
    ArtifactAction(
        action_id="orchid_import_tdb",
        label="Import TDB into ORCHID Workspace",
        framework="orchid",
        input_types=frozenset({FT_TDB}),
        description="Preview this TDB alongside ORCHID literature data for the same system.",
    ),
    ArtifactAction(
        action_id="orchid_compare_stability",
        label="Compare Stability with ORCHID",
        framework="orchid",
        input_types=frozenset({FT_CSV, FT_JSON}),
        description="Overlay stability results with ORCHID experimental measurements.",
    ),
    # ── Visualisation ────────────────────────────────────────────────────
    ArtifactAction(
        action_id="plot_energy_curve",
        label="Plot Energy Curve",
        framework="mf",
        input_types=frozenset({FT_TRAJECTORY_PKL, FT_TRAJECTORY_XYZ}),
        description="Plot energy vs. relaxation step.",
    ),
    ArtifactAction(
        action_id="view_image",
        label="View Image",
        framework="mf",
        input_types=frozenset({FT_IMAGE}),
        description="Open image in the preview panel.",
    ),
    ArtifactAction(
        action_id="plot_csv",
        label="Plot Data",
        framework="mf",
        input_types=frozenset({FT_CSV, FT_TSV}),
        description="Plot numeric data from this CSV/TSV file.",
    ),
    # ── Export / Convert ─────────────────────────────────────────────────
    ArtifactAction(
        action_id="convert_to_xyz",
        label="Export as XYZ",
        framework="mf",
        input_types=frozenset({FT_POSCAR, FT_CIF, FT_LAMMPS_DATA}),
        description="Convert structure to XYZ format.",
        requires_conversion=True,
        conversion_note="POSCAR/CIF → XYZ via ASE",
    ),
    ArtifactAction(
        action_id="convert_to_poscar",
        label="Export as POSCAR",
        framework="mf",
        input_types=frozenset({FT_CIF, FT_XYZ, FT_EXTXYZ, FT_LAMMPS_DATA}),
        description="Convert structure to POSCAR/VASP format.",
        requires_conversion=True,
        conversion_note="CIF/XYZ → POSCAR via ASE",
    ),
]


def actions_for_file(path: Path, ft: str | None = None) -> list[dict[str, Any]]:
    """Return the list of applicable actions for a given file.

    Args:
        path (Path): Path to the file.
        ft (str | None): Pre-detected file type constant, or ``None`` to auto-detect.

    Returns:
        List of dicts with action metadata, ordered by framework then label.
    """
    if ft is None:
        ft = detect(path)

    matched = [
        {
            "action_id": a.action_id,
            "label": a.label,
            "framework": a.framework,
            "description": a.description,
            "requires_conversion": a.requires_conversion,
            "conversion_note": a.conversion_note,
        }
        for a in _all_actions
        if ft in a.input_types
    ]
    # Sort: same-framework actions grouped, then alphabetical within
    matched.sort(key=lambda x: (x["framework"], x["label"]))
    return matched


def frameworks_for_file(path: Path, ft: str | None = None) -> list[str]:
    """Return the unique set of frameworks that can consume a given file.

    Args:
        path (Path): Path to the file.
        ft (str | None): Pre-detected file type constant.

    Returns:
        Sorted list of framework key strings.
    """
    acts = actions_for_file(path, ft)
    return sorted({a["framework"] for a in acts})
