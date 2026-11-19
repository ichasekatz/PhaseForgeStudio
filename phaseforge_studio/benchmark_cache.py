"""Dependency-aware file-based cache for benchmark calculations.

Each cache entry is keyed by a SHA-256 hash of its inputs (MLIP name, model
version, structure content, calculator settings) and stored as a JSON file in
a ``.bm_cache/`` directory inside the benchmark run directory.

Cache entries include a ``created_at`` timestamp for age-based expiry and a
``cache_key`` field for self-verification.

Usage::

    key = make_cache_key(mlip="grace", structure_hash="abc", settings={"fmax": 0.01})
    if is_cache_valid(key, cache_dir):
        data = load_from_cache(key, cache_dir)
    else:
        data = compute_something(...)
        save_to_cache(key, data, cache_dir)
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

#: Maximum cache age in seconds before an entry is considered stale.
_default_max_age_s: int = 60 * 60 * 24 * 30  # 30 days


def make_cache_key(
    mlip: str,
    *,
    model_version: str = "",
    structure_hash: str = "",
    calculator_settings: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Generate a deterministic cache key from calculation inputs.

    Args:
        mlip (str): MLIP calculator name.
        model_version (str): Model checkpoint or version string.
        structure_hash (str): SHA-256 of the structure file contents.
        calculator_settings (dict | None): Calculator parameters dict.
        extra (dict | None): Any additional distinguishing parameters.

    Returns:
        32-character hex digest (SHA-256 truncated to 128 bits).
    """
    payload = json.dumps(
        {
            "mlip": mlip,
            "model_version": model_version,
            "structure_hash": structure_hash,
            "calculator_settings": calculator_settings or {},
            "extra": extra or {},
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def hash_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file's contents.

    Args:
        path (Path): File to hash.

    Returns:
        64-character hex digest, or empty string if the file is unreadable.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def hash_structure_dir(directory: Path) -> str:
    """Compute a combined hash for all structure files in a directory.

    Traverses the directory for POSCAR, CIF, and XYZ files, sorts by name
    for determinism, and hashes filenames + contents together.

    Args:
        directory (Path): Root directory to scan.

    Returns:
        32-character hex digest of combined file hashes.
    """
    h = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in (".poscar", ".cif", ".xyz", ""):
            h.update(path.name.encode())
            try:
                h.update(path.read_bytes())
            except OSError:
                pass
    return h.hexdigest()[:32]


def _cache_path(key: str, cache_dir: Path) -> Path:
    """Return the JSON file path for a cache key.

    Args:
        key (str): Cache key from ``make_cache_key``.
        cache_dir (Path): Directory holding cache files.

    Returns:
        Absolute path to the cache file.
    """
    return cache_dir / f"{key}.json"


def save_to_cache(
    key: str,
    data: dict[str, Any],
    cache_dir: Path,
) -> None:
    """Write a result dict to the cache.

    Args:
        key (str): Cache key.
        data (dict[str, Any]): JSON-serialisable result dict.
        cache_dir (Path): Cache directory; created if absent.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "cache_key": key,
        "created_at": time.time(),
        "data": data,
    }
    path = _cache_path(key, cache_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, indent=2))
    tmp.replace(path)


def load_from_cache(key: str, cache_dir: Path) -> dict[str, Any] | None:
    """Load a cached result, or return None if absent or corrupt.

    Args:
        key (str): Cache key.
        cache_dir (Path): Cache directory.

    Returns:
        Result dict (the ``data`` field of the entry), or None.
    """
    path = _cache_path(key, cache_dir)
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text())
        if entry.get("cache_key") != key:
            return None
        return entry.get("data")
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def is_cache_valid(
    key: str,
    cache_dir: Path,
    max_age_s: int = _default_max_age_s,
) -> bool:
    """Return True if a valid, non-stale cache entry exists.

    Args:
        key (str): Cache key.
        cache_dir (Path): Cache directory.
        max_age_s (int): Maximum acceptable age in seconds.

    Returns:
        True when the entry exists, is parseable, and is within max_age_s.
    """
    path = _cache_path(key, cache_dir)
    if not path.exists():
        return False
    try:
        entry = json.loads(path.read_text())
        if entry.get("cache_key") != key:
            return False
        age = time.time() - float(entry.get("created_at", 0))
        return age <= max_age_s
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def invalidate_cache(key: str, cache_dir: Path) -> bool:
    """Delete a specific cache entry.

    Args:
        key (str): Cache key to remove.
        cache_dir (Path): Cache directory.

    Returns:
        True if deleted, False if not found.
    """
    path = _cache_path(key, cache_dir)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def list_cache_entries(cache_dir: Path) -> list[dict[str, Any]]:
    """Return summary of all cache entries in a directory.

    Args:
        cache_dir (Path): Cache directory to scan.

    Returns:
        List of dicts with ``key``, ``created_at``, ``age_s``, ``size_bytes``.
    """
    if not cache_dir.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    now = time.time()
    for path in sorted(cache_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text())
            created = float(raw.get("created_at", 0))
            entries.append({
                "key": raw.get("cache_key", path.stem),
                "created_at": created,
                "age_s": now - created,
                "size_bytes": path.stat().st_size,
            })
        except (OSError, json.JSONDecodeError, ValueError):
            entries.append({
                "key": path.stem,
                "created_at": 0.0,
                "age_s": now,
                "size_bytes": 0,
            })
    return entries


def clear_cache(cache_dir: Path) -> int:
    """Delete all cache entries in a directory.

    Args:
        cache_dir (Path): Cache directory to clear.

    Returns:
        Number of files deleted.
    """
    if not cache_dir.is_dir():
        return 0
    count = 0
    for path in cache_dir.glob("*.json"):
        try:
            path.unlink()
            count += 1
        except OSError:
            pass
    return count
