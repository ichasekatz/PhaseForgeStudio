"""ORCHID CALPHAD data adapter for PhaseForgeStudio.

ORCHID is an open, provenance-tracked collection of CALPHAD thermodynamic
data (binary systems, v2026.10): 2 912 TDB databases, 73 k+ literature
values, 2 178 expert-drawn phase diagrams.

Integration strategy (two-tier):
1. If ``orchid-mcp`` is installed, call its Python functions directly.
2. Otherwise, fetch static JSON files from data.orchid-project.org via HTTP
   and cache them at ``~/.cache/orchid-mcp/``.

Offline (HPC without network)::

    export ORCHID_DATA_DIR=/path/to/local/orchid-data
    export ORCHID_OFFLINE=1

License: CC BY 4.0 / CC0 / MIT / ODbL per source record.  Per-record
attribution is mandatory when redistributing values.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# MCP server process management
# ---------------------------------------------------------------------------

_orchid_proc: subprocess.Popen | None = None


def is_server_running(port: int = 3000) -> bool:
    """Return True if something answers HTTP on *port*."""
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False


def start_orchid_server(
    cmd: str = "orchid-server",
    port: int = 3000,
    timeout: int = 30,
) -> bool:
    """Start the ORCHID MCP server if not already running. Returns True when ready."""
    global _orchid_proc
    if is_server_running(port):
        return True
    if _orchid_proc and _orchid_proc.poll() is None:
        pass  # process alive but not yet serving — fall through to poll
    else:
        _orchid_proc = subprocess.Popen(
            cmd.split(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_server_running(port):
            return True
        if _orchid_proc.poll() is not None:
            return False  # process died
        time.sleep(1)
    return False


def stop_orchid_server() -> None:
    global _orchid_proc
    if _orchid_proc and _orchid_proc.poll() is None:
        _orchid_proc.terminate()
    _orchid_proc = None

_ORCHID_BASE = "https://data.orchid-project.org"
_CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "orchid-mcp"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _orchid_offline() -> bool:
    return bool(os.environ.get("ORCHID_OFFLINE"))


def _local_data_dir() -> Path | None:
    d = os.environ.get("ORCHID_DATA_DIR")
    return Path(d) if d else None


def _cache_path(url_tail: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = url_tail.lstrip("/").replace("/", "_").replace("?", "_").replace("&", "_")
    if not key.endswith(".json"):
        key += ".json"
    return _CACHE_DIR / key


def _fetch_json(url: str, timeout: int = 20) -> Any:
    """Fetch JSON from URL with disk cache.  Raises RuntimeError on failure."""
    tail = url.replace(_ORCHID_BASE, "")
    cp = _cache_path(tail)
    if cp.exists():
        try:
            return json.loads(cp.read_text())
        except Exception:
            cp.unlink(missing_ok=True)
    if _orchid_offline():
        raise RuntimeError(f"ORCHID offline mode: no cached data for {url}")
    local = _local_data_dir()
    if local:
        local_path = local / tail.lstrip("/")
        if local_path.exists():
            try:
                data = json.loads(local_path.read_text())
                cp.write_text(json.dumps(data))
                return data
            except Exception:
                pass
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            data = json.loads(raw.decode())
        cp.write_text(json.dumps(data))
        return data
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return None  # endpoint doesn't exist — callers treat None as empty
        raise RuntimeError(f"ORCHID HTTP error: {exc}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ORCHID HTTP error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ORCHID: invalid JSON from {url}") from exc


# ---------------------------------------------------------------------------
# orchid-mcp helpers
# ---------------------------------------------------------------------------


def check_orchid_mcp() -> bool:
    """Return True if the ``orchid-mcp`` package is importable."""
    try:
        import orchid_mcp  # noqa: F401
        return True
    except ImportError:
        return False


def orchid_install_hint() -> str:
    return "Install orchid-mcp from the Setup tab"


def _mcp_call(func_name: str, **kwargs: Any) -> Any:
    import orchid_mcp
    fn = getattr(orchid_mcp, func_name)
    return fn(**kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def orchid_search_systems(
    elements: list[str],
    exact: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find binary systems containing *elements*.

    Returns list of dicts with at minimum ``system``, ``n_values`` fields.
    """
    if check_orchid_mcp():
        try:
            return _mcp_call("search_systems", elements=elements, exact=exact, limit=limit)
        except Exception:
            pass
    # HTTP fallback: try canonical system name e.g. "Al-Fe"
    if len(elements) == 2:
        sys_id = "-".join(sorted(e.capitalize() for e in elements))
        try:
            data = _fetch_json(f"{_ORCHID_BASE}/literature/systems/{sys_id}.json")
            if data:
                return [{"system": sys_id, "data": data}]
        except RuntimeError:
            pass
    # Try index endpoint if it exists
    try:
        idx = _fetch_json(f"{_ORCHID_BASE}/literature/index.json")
        if isinstance(idx, list):
            el_set = {e.capitalize() for e in elements}
            return [s for s in idx if any(e in s.get("elements", []) for e in el_set)][:limit]
    except RuntimeError:
        pass
    return []


def get_system_data(
    system: str,
    property_group: str | None = None,
    evidence_class: str | None = None,
) -> dict[str, Any]:
    """Return literature values for a binary system (e.g. ``"Al-Fe"``)."""
    if check_orchid_mcp():
        try:
            kwargs: dict[str, Any] = {"system": system}
            if property_group:
                kwargs["property_group"] = property_group
            if evidence_class:
                kwargs["evidence_class"] = evidence_class
            return _mcp_call("get_system_data", **kwargs)
        except Exception:
            pass
    data = _fetch_json(f"{_ORCHID_BASE}/literature/systems/{system}.json")
    if data is None:
        return {"system": system, "values": [], "available": False}
    return data if isinstance(data, dict) else {"system": system, "data": data}


def get_phase_diagram(
    system: str,
    x_arr: list[float] | None = None,
    t_arr: list[float] | None = None,
) -> dict[str, Any]:
    """Return phase diagram data for a binary system."""
    if check_orchid_mcp():
        try:
            kwargs: dict[str, Any] = {"system": system}
            if x_arr:
                kwargs["x"] = x_arr
            if t_arr:
                kwargs["T"] = t_arr
            return _mcp_call("get_phase_diagram", **kwargs)
        except Exception:
            pass
    data = _fetch_json(f"{_ORCHID_BASE}/diagrams/{system}.json")
    if data is None:
        return {"error": "No phase diagram available via HTTP — install orchid-mcp from the Setup tab", "system": system}
    return data if isinstance(data, dict) else {"system": system, "data": data}


def get_formation_enthalpy(formula: str) -> dict[str, Any]:
    """Return formation enthalpy for a formula, with MP/OQMD comparison."""
    if check_orchid_mcp():
        try:
            return _mcp_call("get_formation_enthalpy", formula=formula)
        except Exception:
            pass
    return {
        "error": "orchid-mcp not installed — use the Setup tab to install it",
        "formula": formula,
        "hint": orchid_install_hint(),
    }


def get_invariant_reactions(
    system: str,
    source: str = "literature",
) -> list[dict[str, Any]]:
    """Return invariant reactions (eutectics, peritectics) for a system."""
    if check_orchid_mcp():
        try:
            return _mcp_call("get_invariant_reactions", system=system, source=source)
        except Exception:
            pass
    return []


def list_tdb_files(
    elements: list[str] | None = None,
    tier: str | None = None,
) -> list[dict[str, Any]]:
    """List available TDB assessments, optionally filtered by element list."""
    if check_orchid_mcp():
        try:
            kwargs: dict[str, Any] = {}
            if elements:
                kwargs["elements"] = elements
            if tier:
                kwargs["tier"] = tier
            return _mcp_call("list_tdb_files", **kwargs)
        except Exception:
            pass
    try:
        data = _fetch_json(f"{_ORCHID_BASE}/tdb/index.json")
        if not isinstance(data, list):
            return []
        if elements:
            el_set = {e.capitalize() for e in elements}
            data = [d for d in data if any(e in d.get("elements", []) for e in el_set)]
        return data
    except RuntimeError:
        return []


def get_tdb_content(file_id: str) -> str:
    """Retrieve TDB file content by ID or hash."""
    if check_orchid_mcp():
        try:
            result = _mcp_call("get_tdb", file=file_id)
            if isinstance(result, str):
                return result
            if isinstance(result, dict):
                return result.get("content", "")
        except Exception:
            pass
    try:
        data = _fetch_json(f"{_ORCHID_BASE}/tdb/{file_id}.json")
        if data is None:
            return f"$ TDB {file_id!r} not found via HTTP — install orchid-mcp from the Setup tab"
        if isinstance(data, dict):
            return data.get("content", "")
        return str(data)
    except RuntimeError as exc:
        return f"$ Error retrieving TDB {file_id!r}: {exc}"


def compare_to_dft(system: str) -> dict[str, Any]:
    """Compare literature HM_FORM values with MP/OQMD DFT data."""
    if check_orchid_mcp():
        try:
            return _mcp_call("compare_to_dft", system=system)
        except Exception:
            pass
    return {
        "error": "orchid-mcp not installed — use the Setup tab to install it",
        "system": system,
        "hint": orchid_install_hint(),
    }
