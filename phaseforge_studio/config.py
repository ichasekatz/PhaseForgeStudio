"""Configuration loading, saving, and defaults for PhaseForge Studio."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_server_dir: Path = Path(__file__).parent.parent
"""Root GUI directory (parent of this package)."""

_default_config: dict[str, Any] = {
    "species": ["Al", "Ni"],
    "lattices": ["FCC_A1"],
    "calculator": "grace",
    "fmax": 0.01,
    "t_min": 298.15,
    "t_max": 6000.0,
    "level": 1,
    "md_temperature": 1000,
    "md_pressure": 1,
    "md_timestep": 1.0,
    "md_scaling_matrix": 2,
    "sro": False,
    "bv": 0.005,
    "phonon": False,
    "open_calphad": False,
    "terms": None,
    "track_trajectory": True,
    "path0": "",
    "path1": "",
    "path2": "",
    "device": "cpu",
}

_fallback_calculators: list[str] = [
    "alignn",
    "alphanet",
    "chgnet",
    "deepmd",
    "eqv2",
    "grace",
    "hienet",
    "m3gnet",
    "mace",
    "mattersim",
    "nequip",
    "orb",
    "sevennet",
    "uma",
]


def _load_config(path: Path) -> dict[str, Any]:
    """Load config JSON, creating it from defaults if absent.

    Args:
        path (Path): Path to config.json.

    Returns:
        Merged config dict (defaults overridden by loaded values).
    """
    if not path.exists():
        path.write_text(json.dumps(_default_config, indent=2))
        return dict(_default_config)
    try:
        loaded = json.loads(path.read_text())
        merged = dict(_default_config)
        merged.update(loaded)
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(_default_config)


def _save_config(path: Path, cfg: dict[str, Any]) -> None:
    """Write config to disk atomically via a temp file.

    Args:
        path (Path): Destination config.json path.
        cfg (dict[str, Any]): Config dict to serialise.
    """
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(path)


def _resolve(cfg: dict[str, Any], key: str) -> Path:
    """Expand ~ and resolve a path string from config.

    Args:
        cfg (dict[str, Any]): Live config dict.
        key (str): Config key whose value is a path string.

    Returns:
        Resolved absolute Path.
    """
    return Path(cfg.get(key, _default_config[key])).expanduser().resolve()
