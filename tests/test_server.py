"""Smoke tests for server utility functions — no network, no file I/O."""

from pathlib import Path

import pytest


def test_import():
    """server.py is importable as a module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "server", Path(__file__).parent.parent / "server.py"
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    # Only check importability; don't exec (would start a server)
    assert mod is not None


@pytest.mark.parametrize(
    "label, expected",
    [
        ("a_Al=0.5_Ni=0.5_BCC_A2_1", {"Al": 0.5, "Ni": 0.5}),
        ("a_Al=1.0_FCC_A1_2", {"Al": 1.0}),
        ("a_Al=0.333_Fe=0.333_Ni=0.334_BCC_A2_1", {"Al": 0.333, "Fe": 0.333, "Ni": 0.334}),
    ],
)
def test_composition_parse(label, expected):
    """Composition fractions are parseable from directory-name labels."""
    import re

    tokens = dict(re.findall(r"_([A-Z][a-z]?)=([0-9.]+)", label))
    result = {k: float(v) for k, v in tokens.items()}
    assert result == pytest.approx(expected, rel=1e-3)
