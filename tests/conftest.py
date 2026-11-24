"""Shared pytest fixtures for PhaseForgeStudio tests."""

from __future__ import annotations

import sys
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Optional-dependency names grouped by adapter
# ---------------------------------------------------------------------------

_OPTIONAL_MODULES: dict[str, list[str]] = {
    "orchid": ["orchid_mcp", "orchid_mcp.tools"],
    "sage": ["sage_mcp", "sage_mcp.reproduce", "sage_mcp.runner", "calphad_model_guide", "orchid_ids", "orchid_ids.locator"],
    "materialsframework": [
        "materialsframework",
        "materialsframework.tools",
        "materialsframework.tools.sqs2tdb",
        "materialsframework.calculators",
        "materialsframework.calculators.grace",
    ],
    "phaseforgeplus": ["phaseforgeplus", "phaseforgeplus.workflow"],
    "blade": ["blade"],
    "ase": ["ase", "ase.io", "ase.atoms", "ase.build", "ase.optimize"],
    "pycalphad": ["pycalphad"],
    "pymatgen": ["pymatgen", "pymatgen.core"],
}

ALL_OPTIONAL: list[str] = [m for group in _OPTIONAL_MODULES.values() for m in group]


@pytest.fixture()
def no_optional_deps() -> Generator[None, None, None]:
    """Mask every optional package so adapters behave as if nothing is installed."""
    null_map: dict[str, Any] = {mod: None for mod in ALL_OPTIONAL}
    with patch.dict(sys.modules, null_map):
        yield


@pytest.fixture()
def no_orchid() -> Generator[None, None, None]:
    """Mask orchid_mcp only."""
    null_map: dict[str, Any] = {mod: None for mod in _OPTIONAL_MODULES["orchid"]}
    with patch.dict(sys.modules, null_map):
        yield


@pytest.fixture()
def no_sage() -> Generator[None, None, None]:
    """Mask all ORCHID-SAGE modules."""
    null_map: dict[str, Any] = {mod: None for mod in _OPTIONAL_MODULES["sage"]}
    with patch.dict(sys.modules, null_map):
        yield


@pytest.fixture()
def no_materialsframework() -> Generator[None, None, None]:
    """Mask MaterialsFramework."""
    null_map: dict[str, Any] = {mod: None for mod in _OPTIONAL_MODULES["materialsframework"]}
    with patch.dict(sys.modules, null_map):
        yield


@pytest.fixture()
def no_phaseforgeplus() -> Generator[None, None, None]:
    """Mask PhaseForgePlus."""
    null_map: dict[str, Any] = {mod: None for mod in _OPTIONAL_MODULES["phaseforgeplus"]}
    with patch.dict(sys.modules, null_map):
        yield
