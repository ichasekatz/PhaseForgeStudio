"""ORCHID-SAGE adapter for PhaseForgeStudio.

ORCHID-SAGE (Sariturk et al., arXiv:2611.16308) is an open standard and
toolset for fully reproducible CALPHAD phase diagram assessments.  It wraps:

- ``calphad_model_guide`` — deterministic CALPHAD model screening
- ``sage_mcp.reproduce``   — protocol management and step execution
- ``sage_mcp.runner``      — job lifecycle (start, poll, wait)
- ``orchid_ids``           — identifier computation/validation

Install::

    pip install git+https://github.com/orchid-calphad/orchid-sage
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def check_sage_installed() -> bool:
    """Return True if the ``sage_mcp`` package is importable."""
    try:
        import sage_mcp  # noqa: F401
        return True
    except ImportError:
        return False


def check_model_guide_installed() -> bool:
    """Return True if ``calphad_model_guide`` is importable."""
    try:
        import calphad_model_guide  # noqa: F401
        return True
    except ImportError:
        return False


def sage_install_hint() -> str:
    return "pip install git+https://github.com/orchid-calphad/orchid-sage"


# ---------------------------------------------------------------------------
# calphad_model_guide — model screening
# ---------------------------------------------------------------------------


def model_library() -> dict[str, Any]:
    """Return the full CALPHAD model recipe catalog."""
    import calphad_model_guide
    return calphad_model_guide.library()


def model_search(text: str = "", topic: str | None = None) -> dict[str, Any]:
    """Search model recipes by keyword and/or topic."""
    import calphad_model_guide
    return calphad_model_guide.search(text=text, topic=topic)


def model_validate(spec: dict[str, Any]) -> list[str]:
    """Validate a versioned CALPHAD model spec.  Returns error list (empty = valid)."""
    import calphad_model_guide
    result = calphad_model_guide.validate(spec)
    if isinstance(result, list):
        return result
    return []


def model_audit(spec: dict[str, Any]) -> dict[str, Any]:
    """Audit a model spec; returns codes, severities, messages."""
    import calphad_model_guide
    return calphad_model_guide.audit(spec)


def model_recommend(spec: dict[str, Any]) -> dict[str, Any]:
    """Suggest compatible model recipes for a given spec."""
    import calphad_model_guide
    return calphad_model_guide.recommend(spec)


def model_plan(spec: dict[str, Any], limit: int = 20) -> dict[str, Any]:
    """Generate a fitting plan for a model spec."""
    import calphad_model_guide
    return calphad_model_guide.plan(spec, limit=limit)


def model_compare(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Compare two model specs and return a diff summary."""
    import calphad_model_guide
    return calphad_model_guide.compare(left, right)


# ---------------------------------------------------------------------------
# sage_mcp.reproduce — protocol management
# ---------------------------------------------------------------------------


def list_protocols() -> dict[str, Any]:
    """List all SAGE protocols in the repository."""
    from sage_mcp import reproduce
    return reproduce.list_protocols()


def get_protocol(protocol: str, fields: str = "summary") -> dict[str, Any]:
    """Return detail for one protocol by ref."""
    from sage_mcp import reproduce
    return reproduce.get_protocol(protocol, fields=fields)


def get_steps(protocol: str, section: str | None = None) -> dict[str, Any]:
    """Return steps for a protocol, optionally filtered to one section."""
    from sage_mcp import reproduce
    return reproduce.get_steps(protocol, section=section)


def get_step(protocol: str, step_id: str) -> dict[str, Any]:
    """Return a single step with its run-card history."""
    from sage_mcp import reproduce
    return reproduce.get_step(protocol, step_id)


def validate_document(document: str | None = None) -> dict[str, Any]:
    """Validate a protocol document (path or inline JSON)."""
    from sage_mcp import reproduce
    return reproduce.validate(document=document)


def verify_inputs(protocol: str, detail: bool = False) -> dict[str, Any]:
    """Check that all protocol input files are present and correct."""
    from sage_mcp import reproduce
    return reproduce.verify_inputs(protocol, detail=detail)


def get_dashboard(assessment: str, section: str | None = None, max_items: int = 50) -> dict[str, Any]:
    """Return assessment dashboard data (evidence, decisions, open questions)."""
    from sage_mcp import reproduce
    return reproduce.get_dashboard_data(assessment, section=section, max_items=max_items)


def get_evidence_manifest(
    assessment: str,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return evidence manifest for an assessment."""
    from sage_mcp import reproduce
    return reproduce.get_evidence_manifest(assessment, kind=kind, limit=limit, offset=offset)


def plan_reproduction(
    protocol: str,
    run_root: str | None = None,
    python: str | None = None,
    pfp: str | None = None,
    nproc: int = 4,
) -> dict[str, Any]:
    """Plan reproduction: resolve inputs, build job list, estimate cost."""
    from sage_mcp import reproduce
    return reproduce.plan_reproduction(protocol, run_root=run_root, python=python, pfp=pfp, nproc=nproc)


def start_step(
    protocol: str,
    step_id: str,
    run_root: str,
    confirm: bool = False,
    allow_long: bool = False,
    env_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Start a protocol step as a detached background job."""
    from sage_mcp import reproduce
    return reproduce.start_step(
        protocol,
        step_id,
        run_root,
        confirm=confirm,
        allow_long=allow_long,
        env_extra=env_extra,
    )


def step_status(protocol: str, run_root: str, step_id: str | None = None, wait_s: float = 0) -> dict[str, Any]:
    """Poll status of one or all steps in a run."""
    from sage_mcp import reproduce
    return reproduce.step_status(protocol, run_root, step_id=step_id, wait_s=wait_s)


def compare_outputs(protocol: str, run_root: str, python: str | None = None) -> dict[str, Any]:
    """Compare outputs against reference checksums."""
    from sage_mcp import reproduce
    return reproduce.compare_outputs(protocol, run_root, python=python)


def get_open_questions(ids: list[str] | None = None) -> dict[str, Any]:
    """Return open scientific questions in the assessment repository."""
    from sage_mcp import reproduce
    return reproduce.get_open_questions(ids=ids)


# ---------------------------------------------------------------------------
# orchid_ids — identifier utilities
# ---------------------------------------------------------------------------


def compute_ids(
    pid: str | None = None,
    locator: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    observation_key: str | None = None,
) -> dict[str, Any]:
    """Compute ORC- and C-/S- identifiers for an observation."""
    import orchid_ids
    return orchid_ids.compute_ids(pid=pid, locator=locator, state=state, observation_key=observation_key)


def validate_id(orchid_id: str) -> dict[str, Any]:
    """Check whether an ORCHID identifier string is well-formed."""
    from orchid_ids import locator as _loc
    result = _loc.validate_id(orchid_id)
    # real orchid_ids returns {ok, kind, error}; normalise to {id, valid, errors, ...}
    if isinstance(result, dict):
        ok = bool(result.get("ok", False))
        errors = [] if ok else [result.get("error", "invalid")]
        return {"id": orchid_id, "valid": ok, "errors": errors, **result}
    # fallback: older API returned list of error strings
    errors_list: list[str] = result if isinstance(result, list) else []
    return {"id": orchid_id, "valid": not errors_list, "errors": errors_list}
