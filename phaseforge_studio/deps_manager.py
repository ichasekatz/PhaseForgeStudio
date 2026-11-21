"""Dependency discovery and optional auto-install for PhaseForgeStudio.

Python packages are installed via ``uv pip install`` (or ``pip`` fallback)
into the running interpreter's environment.  Binary tools (PAIPAI) cannot be
auto-installed — their paths are configurable via config.json.

Config keys recognised (all optional):

    paipai_binary            absolute path to paipai wrapper
    materialsframework_src   path to MaterialsFramework/src
    phaseforgeplus_src       path to PhaseForgePlus/src
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Python package registry
# ---------------------------------------------------------------------------

_PY_PACKAGES: dict[str, dict[str, Any]] = {
    "orchid_mcp": {
        "import_name": "orchid_mcp",
        "pip_spec": "orchid-mcp",
        "label": "ORCHID MCP",
        "optional": True,
    },
    "orchid_sage": {
        "import_name": "sage_mcp",
        "pip_spec": "git+https://github.com/orchid-calphad/orchid-sage",
        "label": "ORCHID-SAGE",
        "optional": True,
    },
    "materialsframework": {
        "import_name": "materialsframework",
        "pip_spec": "materialsframework",  # on PyPI; source editable install preferred
        "label": "MaterialsFramework",
        "optional": True,
        "source_key": "materialsframework_src",
    },
    "phaseforgeplus": {
        "import_name": "phaseforgeplus",
        "pip_spec": "phaseforgeplus",  # on PyPI; source editable install preferred
        "label": "PhaseForgePlus",
        "optional": True,
        "source_key": "phaseforgeplus_src",
    },
    "ase": {
        "import_name": "ase",
        "pip_spec": "ase",
        "label": "ASE",
        "optional": True,
    },
    "pycalphad": {
        "import_name": "pycalphad",
        "pip_spec": "pycalphad",
        "label": "pycalphad",
        "optional": True,
    },
    "pymatgen": {
        "import_name": "pymatgen",
        "pip_spec": "pymatgen",
        "label": "pymatgen",
        "optional": True,
    },
}


def _importable(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


def check_py_status(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return status for every tracked Python package."""
    cfg = cfg or {}
    out = []
    for key, meta in _PY_PACKAGES.items():
        ok = _importable(meta["import_name"])
        entry: dict[str, Any] = {
            "key": key,
            "label": meta["label"],
            "available": ok,
            "pip_spec": meta.get("pip_spec"),
            "optional": meta.get("optional", True),
            "installable": meta.get("pip_spec") is not None,
        }
        # source-based packages: check whether source dir is present
        src_key = meta.get("source_key")
        if src_key:
            src = cfg.get(src_key) or _guess_src(key)
            entry["source_path"] = src
            entry["source_found"] = bool(src and Path(src).exists())
            # installable if source found OR PyPI spec available
            entry["installable"] = bool(entry["source_found"]) or (meta.get("pip_spec") is not None)
        out.append(entry)
    return out


def _guess_src(key: str) -> str | None:
    """Try to find a source directory adjacent to the GUI directory."""
    gui_dir = Path(__file__).parent.parent
    candidates: dict[str, list[Path]] = {
        "materialsframework": [
            gui_dir / "MaterialsFramework" / "src",
            gui_dir.parent / "MaterialsFramework" / "src",
        ],
        "phaseforgeplus": [
            gui_dir / "PhaseForgePlus" / "src",
            gui_dir.parent / "PhaseForgePlus" / "src",
        ],
    }
    for path in candidates.get(key, []):
        if path.exists():
            return str(path)
    return None


# ---------------------------------------------------------------------------
# Binary tools
# ---------------------------------------------------------------------------

_BINARY_TOOLS: dict[str, dict[str, Any]] = {
    "paipai": {
        "label": "PAIPAI",
        "config_key": "paipai_binary",
        "search_names": ["paipai"],
        "search_paths": [
            Path.home() / "bin" / "paipai",
            Path.home() / ".local" / "bin" / "paipai",
            Path("/usr/local/bin/paipai"),
        ],
        "build_hint": (
            "git clone https://github.com/siyazhu/PAIPAI.git\n"
            "cd PAIPAI && mkdir build && cd build\n"
            "cmake -DCMAKE_INSTALL_PREFIX=$HOME ..\n"
            "cmake --build . --target install\n"
            "# installs to ~/bin/; add ~/bin to PATH or set paipai_binary in config"
        ),
    },
}


def _find_binary(meta: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    override = cfg.get(meta["config_key"])
    if override and Path(override).exists():
        return override
    for name in meta.get("search_names", []):
        found = shutil.which(name)
        if found:
            return found
    for path in meta.get("search_paths", []):
        if path.exists():
            return str(path)
    return None


def check_binary_status(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return status for every tracked binary tool."""
    cfg = cfg or {}
    out = []
    for key, meta in _BINARY_TOOLS.items():
        found = _find_binary(meta, cfg)
        out.append({
            "key": key,
            "label": meta["label"],
            "available": found is not None,
            "path": found,
            "config_key": meta["config_key"],
            "build_hint": meta.get("build_hint"),
        })
    return out


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def _uv_or_pip() -> list[str]:
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "install"]
    return [sys.executable, "-m", "pip", "install"]


def install_package(key: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Install a Python package by registry key.  Returns {ok, output, error}."""
    cfg = cfg or {}
    meta = _PY_PACKAGES.get(key)
    if not meta:
        return {"ok": False, "error": f"unknown package key: {key!r}"}

    pip_spec = meta.get("pip_spec")
    src_key = meta.get("source_key")

    if src_key:
        src = cfg.get(src_key) or _guess_src(key)
        if src and Path(src).exists():
            # preferred: editable install from local source
            src_parent = str(Path(src).parent)
            cmd = [*_uv_or_pip(), "-e", src_parent]
        elif pip_spec:
            # fallback: install from PyPI
            cmd = [*_uv_or_pip(), pip_spec]
        else:
            return {"ok": False, "error": f"source not found for {key} and no PyPI spec available; set {src_key!r} in config"}
    elif pip_spec:
        cmd = [*_uv_or_pip(), pip_spec]
    else:
        return {"ok": False, "error": f"no install spec for {key}"}

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        ok = result.returncode == 0
        return {
            "ok": ok,
            "output": result.stdout + result.stderr,
            "error": result.stderr if not ok else None,
            "cmd": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "install timed out (300 s)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def all_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Combined status for all packages and binaries."""
    return {
        "packages": check_py_status(cfg),
        "binaries": check_binary_status(cfg),
    }
