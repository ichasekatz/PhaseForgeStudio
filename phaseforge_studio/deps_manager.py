"""Dependency discovery and optional install for PhaseForgeStudio.

Source-based packages (BLADE, MaterialsFramework, PhaseForgePlus) are cloned
into ``<gui_root>/frameworks/<Name>/`` on first install if no existing path is
configured.  Packages are installed as editable into the running interpreter.

Config keys (all optional — auto-detected if absent):

    blade_src                path to BLADE repo root
    materialsframework_src   path to MaterialsFramework root
    phaseforgeplus_src       path to PhaseForgePlus root
    paipai_binary            absolute path to paipai binary
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_GUI_DIR = Path(__file__).parent.parent
_FRAMEWORKS_DIR = _GUI_DIR / "frameworks"

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
        "pip_spec": "materialsframework",
        "label": "MaterialsFramework",
        "optional": True,
        "source_key": "materialsframework_src",
        "git_url": "https://github.com/dogusariturk/MaterialsFramework",
        "frameworks_name": "MaterialsFramework",
        "src_subdir": "src",  # installable root is repo/src/
    },
    "phaseforgeplus": {
        "import_name": "phaseforgeplus",
        "pip_spec": "phaseforgeplus",
        "label": "PhaseForgePlus",
        "optional": True,
        "source_key": "phaseforgeplus_src",
        "git_url": "https://github.com/dogusariturk/PhaseForgePlus",
        "frameworks_name": "PhaseForgePlus",
        "src_subdir": "src",
    },
    "blade": {
        "import_name": "blade",
        "pip_spec": "git+https://github.com/ichasekatz/BLADE",
        "label": "BLADE",
        "optional": True,
        "source_key": "blade_src",
        "git_url": "https://github.com/ichasekatz/BLADE",
        "frameworks_name": "BLADE",
        "no_deps": True,  # GUI doesn't need torch/pymatgen — skip heavy deps
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


def _frameworks_path(key: str) -> Path:
    """Canonical frameworks/ location for a source package."""
    fname = _PY_PACKAGES.get(key, {}).get("frameworks_name", key)
    return _FRAMEWORKS_DIR / fname


def _guess_src(key: str, cfg: dict[str, Any] | None = None) -> str | None:
    """Find the best source directory for a package, checking frameworks/ first."""
    cfg = cfg or {}
    meta = _PY_PACKAGES.get(key, {})
    src_key = meta.get("source_key")

    # 1. Explicit config override
    if src_key and cfg.get(src_key):
        p = Path(cfg[src_key])
        if p.exists():
            return str(p)

    # 2. frameworks/<Name>/ — canonical GUI-local location
    fw = _frameworks_path(key)
    if fw.exists():
        sub = meta.get("src_subdir")
        candidate = fw / sub if sub else fw
        if candidate.exists():
            return str(candidate)
        return str(fw)

    # 3. Legacy locations (existing installs alongside GUI)
    legacy: dict[str, list[Path]] = {
        "blade": [
            _GUI_DIR / "BLADE",
            _GUI_DIR.parent / "BLADE",
        ],
        "materialsframework": [
            _GUI_DIR / "MaterialsFramework" / "src",
            _GUI_DIR / "MaterialsFramework",
            _GUI_DIR.parent / "MaterialsFramework" / "src",
        ],
        "phaseforgeplus": [
            _GUI_DIR / "PhaseForgePlus" / "src",
            _GUI_DIR / "PhaseForgePlus",
            _GUI_DIR.parent / "PhaseForgePlus" / "src",
        ],
    }
    for path in legacy.get(key, []):
        if path.exists():
            return str(path)

    return None


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
            "can_clone": bool(meta.get("git_url")),
        }
        src_key = meta.get("source_key")
        if src_key:
            fw = _frameworks_path(key)
            explicit = cfg.get(src_key, "").strip()
            # UI always shows frameworks path (or explicit config override) —
            # never a legacy adjacent path the user didn't choose
            entry["source_path"] = explicit if explicit else str(fw)
            entry["source_found"] = bool(_guess_src(key, cfg))
            entry["installable"] = True
        out.append(entry)
    return out


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
    """Return pip install prefix targeting the running interpreter's environment."""
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--python", sys.executable]
    return [sys.executable, "-m", "pip", "install"]


def _clone_repo(git_url: str, dest: Path) -> dict[str, Any]:
    """Clone *git_url* into *dest* (first time only — never touches existing dirs)."""
    if dest.exists():
        return {"ok": True, "output": f"Already exists: {dest}", "cmd": ""}
    _FRAMEWORKS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["git", "clone", "--depth=1", git_url, str(dest)],
            capture_output=True, text=True, timeout=300,
        )
        ok = result.returncode == 0
        return {
            "ok": ok,
            "output": result.stdout + result.stderr,
            "error": result.stderr if not ok else None,
            "cmd": f"git clone --depth=1 {git_url} {dest}",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git clone timed out (5 min)"}
    except FileNotFoundError:
        return {"ok": False, "error": "git not found on PATH"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _run_pip(cmd: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        ok = result.returncode == 0
        return {
            "ok": ok,
            "output": result.stdout + result.stderr,
            "error": result.stderr if not ok else None,
            "cmd": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "install timed out (30 min)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def install_package(
    key: str,
    cfg: dict[str, Any] | None = None,
    override_spec: str | None = None,
) -> dict[str, Any]:
    """Install a package by registry key.  Returns {ok, output, error, cmd}.

    If *override_spec* is given it is used directly (local path → editable
    install; anything else → pip spec).  Otherwise the registry + config
    determine the source: existing local path → editable; no path found →
    clone from git_url into frameworks/ then editable; pip_spec fallback.
    """
    cfg = cfg or {}
    meta = _PY_PACKAGES.get(key)
    if not meta:
        return {"ok": False, "error": f"unknown package key: {key!r}"}

    no_deps_flag = ["--no-deps"] if meta.get("no_deps") else []

    # -- explicit override from UI field --------------------------------------
    if override_spec:
        override_spec = override_spec.strip()
        op = Path(override_spec)
        if op.exists() and op.is_dir():
            root = op if (op / "pyproject.toml").exists() or (op / "setup.py").exists() else op.parent
            cmd = [*_uv_or_pip(), *no_deps_flag, "-e", str(root)]
        else:
            cmd = [*_uv_or_pip(), *no_deps_flag, override_spec]
        return _run_pip(cmd)

    pip_spec = meta.get("pip_spec")
    src_key = meta.get("source_key")

    # -- source-based package -------------------------------------------------
    if src_key:
        src = _guess_src(key, cfg)

        # No source found — try to clone into frameworks/
        if not src:
            git_url = meta.get("git_url")
            if git_url:
                fw = _frameworks_path(key)
                clone_result = _clone_repo(git_url, fw)
                if not clone_result["ok"]:
                    return clone_result
                # After clone, resolve install root
                sub = meta.get("src_subdir")
                src = str(fw / sub if sub and (fw / sub).exists() else fw)
            elif pip_spec:
                return _run_pip([*_uv_or_pip(), *no_deps_flag, pip_spec])
            else:
                return {"ok": False, "error": f"no source and no git_url/pip_spec for {key}"}

        src_path = Path(src)
        install_root = (
            src_path
            if (src_path / "pyproject.toml").exists() or (src_path / "setup.py").exists()
            else src_path.parent
        )
        cmd = [*_uv_or_pip(), *no_deps_flag, "-e", str(install_root)]
        result = _run_pip(cmd)
        result["cloned_to"] = str(_frameworks_path(key)) if not _guess_src(key, cfg) else None
        return result

    # -- simple pip package ---------------------------------------------------
    if pip_spec:
        return _run_pip([*_uv_or_pip(), *no_deps_flag, pip_spec])

    return {"ok": False, "error": f"no install spec for {key}"}


def all_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Combined status for all packages and binaries."""
    return {
        "packages": check_py_status(cfg),
        "binaries": check_binary_status(cfg),
    }
