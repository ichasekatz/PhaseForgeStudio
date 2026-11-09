"""Filesystem scanners and browser utilities for PhaseForge Studio."""

from __future__ import annotations

import ast
import contextlib
import re
from pathlib import Path
from typing import Any

from phaseforge_studio.structure import _build_elem_map, _parse_atat_structure, _poscar_to_xyz

_lattice_pattern = re.compile(r"^[A-Za-z0-9_]+_\d+$")


def list_available_calculators() -> list[dict[str, Any]]:
    """Return calculator metadata from the materialsframework registry.

    Falls back to a static list when materialsframework is not installed.

    Returns:
        List of dicts with keys ``name``, ``supports_device``, ``supports_model``.
    """
    from phaseforge_studio.config import _fallback_calculators

    try:
        import materialsframework.calculators as _calc_pkg
        from materialsframework.calculators.registry import list_calculators

        calc_dir = Path(_calc_pkg.__file__).parent
        names = list_calculators()
    except Exception:
        return [{"name": n, "supports_device": False, "supports_model": False} for n in sorted(_fallback_calculators)]

    result = []
    for name in sorted(names):
        supports_device = False
        supports_model = False
        py = calc_dir / f"{name}.py"
        if py.exists():
            try:
                tree = ast.parse(py.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                                args = [a.arg for a in item.args.args + item.args.kwonlyargs]
                                supports_device = "device" in args
                                supports_model = "model" in args
            except Exception:
                pass
        result.append({"name": name, "supports_device": supports_device, "supports_model": supports_model})
    return result


def list_available_lattices(sqsdb_path: Path) -> list[str]:
    """Scan sqsdb directory and return unique lattice base names.

    Args:
        sqsdb_path (Path): Path to the sqsdb base directory.

    Returns:
        Sorted list of lattice names, e.g. ``["BCC_A2", "FCC_A1"]``.
        Returns a minimal fallback list when the directory is absent.
    """
    if not sqsdb_path.is_dir():
        return ["BCC_A2", "FCC_A1", "LIQUID"]

    seen: set[str] = set()
    for entry in sqsdb_path.iterdir():
        if not entry.is_dir():
            continue
        name = re.sub(r"_\d+$", "", entry.name)
        if name:
            seen.add(name)

    return sorted(seen) if seen else ["BCC_A2", "FCC_A1", "LIQUID"]


def scan_latest_structure(path1: Path) -> dict[str, Any]:
    """Find the most recently modified CONTCAR or bestsqs*.out across job outputs.

    Args:
        path1 (Path): BLADE root directory.

    Returns:
        Dict with ``structure`` (str or None), ``format``, ``source``, ``label``.
    """
    search_roots = [path1 / "Jobs", path1 / "Files" / "SQS", path1 / "Files" / "Comps"]
    best_contcar: tuple[float, Path] | None = None
    best_bestsqs: tuple[float, Path] | None = None

    for root in search_roots:
        if not root.is_dir():
            continue
        for p in root.rglob("CONTCAR"):
            try:
                st = p.stat()
                if st.st_size > 0 and (best_contcar is None or st.st_mtime > best_contcar[0]):
                    best_contcar = (st.st_mtime, p)
            except OSError:
                continue
        for p in root.rglob("bestsqs*.out"):
            try:
                st = p.stat()
                if st.st_size > 0 and (best_bestsqs is None or st.st_mtime > best_bestsqs[0]):
                    best_bestsqs = (st.st_mtime, p)
            except OSError:
                continue

    if best_contcar and (best_bestsqs is None or best_contcar[0] >= best_bestsqs[0]):
        p = best_contcar[1]
        text = p.read_text(errors="ignore")
        if text.strip():
            xyz = _poscar_to_xyz(text)
            if xyz:
                return {"structure": xyz, "format": "xyz", "source": "CONTCAR", "label": p.parent.name}
            return {"structure": text, "format": "vasp", "source": "CONTCAR", "label": p.parent.name}

    if best_bestsqs:
        p = best_bestsqs[1]
        rndstr = p.parent / "rndstr.in"
        elem_map = _build_elem_map(rndstr)
        xyz = _parse_atat_structure(p.read_text(errors="ignore"), elem_map)
        if xyz:
            return {"structure": xyz, "format": "xyz", "source": "bestsqs", "label": p.parent.name}

    return {"structure": None, "format": None, "source": "none", "label": ""}


def scan_energies(path1: Path) -> dict[str, Any]:
    """Read per-structure energies from ATAT 'energy' files.

    Scans Jobs/ and Files/SQS/ and sorts results by composition (element
    fractions) so structures with the same composition sit adjacent regardless
    of SQS level.

    Args:
        path1 (Path): BLADE root directory.

    Returns:
        Dict with ``labels`` (list[str]) and ``energies`` (list[float]).
    """
    roots = [path1 / "Jobs", path1 / "Files" / "SQS"]
    energy_files: list[Path] = []
    for root in roots:
        if root.is_dir():
            energy_files.extend(root.rglob("energy"))

    records: list[tuple[dict[str, float], str, Path]] = []
    all_elements: set[str] = set()
    for ef in energy_files:
        tokens = re.findall(r"a_([A-Za-z]+)=([\d.]+)", ef.parent.name)
        fracs = {el: round(float(f), 6) for el, f in tokens}
        all_elements.update(fracs.keys())
        records.append((fracs, ef.parent.name, ef))

    sorted_els = sorted(all_elements)

    def _key(rec: tuple) -> tuple:
        fracs, dirname, _ = rec
        return tuple(fracs.get(el, 0.0) for el in sorted_els) + (dirname,)

    energies: list[float] = []
    labels: list[str] = []
    for _fracs, dirname, ef in sorted(records, key=_key):
        try:
            val = float(ef.read_text().strip())
            energies.append(val)
            labels.append(dirname)
        except (OSError, ValueError):
            continue

    return {"labels": labels, "energies": energies}


def scan_outputs(path1: Path) -> list[dict[str, Any]]:
    """List TDB and PNG output files from Jobs/ and Files/.

    Args:
        path1 (Path): BLADE root directory.

    Returns:
        List of dicts with ``name``, ``rel_path``, ``file_type``, ``mtime``, ``size``.
    """
    results: list[dict[str, Any]] = []
    roots = [path1 / "Jobs", path1 / "Files"]
    for root in roots:
        if not root.is_dir():
            continue
        for tdb in sorted(root.rglob("*.tdb"), key=lambda p: p.stat().st_mtime, reverse=True):
            with contextlib.suppress(OSError):
                results.append(
                    {
                        "name": tdb.name,
                        "rel_path": str(tdb.relative_to(path1)),
                        "file_type": "tdb",
                        "mtime": tdb.stat().st_mtime,
                        "size": tdb.stat().st_size,
                    }
                )
        for png in sorted(root.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
            with contextlib.suppress(OSError):
                results.append(
                    {
                        "name": png.name,
                        "rel_path": str(png.relative_to(path1)),
                        "file_type": "png",
                        "mtime": png.stat().st_mtime,
                        "size": png.stat().st_size,
                    }
                )
    return results


def browse_path(path1: Path, rel: str) -> dict[str, Any]:
    """List directory contents relative to path1 for the file browser.

    Args:
        path1 (Path): BLADE root directory.
        rel (str): Relative path under path1 to list (empty = list path1 root).

    Returns:
        Dict with ``path`` (the requested rel path) and ``entries`` list.
    """
    safe_rel = rel.strip("/").replace("..", "")
    target = path1 / safe_rel if safe_rel else path1
    display_path = safe_rel if safe_rel else "/"
    if not target.exists() or not target.is_dir():
        return {"path": display_path, "entries": []}

    _root_output_dirs = {"Files", "Jobs", "Comps", "SQS", "Phase_Diagrams", "BCC_Benchmark", "Outputs"}

    entries: list[dict[str, Any]] = []
    try:
        items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return {"path": display_path, "entries": []}

    for item in items:
        if item.name.startswith("."):
            continue
        if not safe_rel:
            if item.is_dir() and item.name not in _root_output_dirs:
                continue
            if item.is_file():
                continue
        try:
            st = item.stat()
        except OSError:
            continue
        ext = item.suffix.lower()
        if item.is_dir():
            kind = "dir"
        elif item.name in ("CONTCAR", "POSCAR") or (ext == ".out" and "bestsqs" in item.name):
            kind = "structure"
        elif ext == ".tdb":
            kind = "tdb"
        elif ext == ".png":
            kind = "png"
        elif item.name == "energy":
            kind = "energy"
        elif item.name == "trajectory.pkl":
            kind = "trajectory"
        elif item.name in (
            "energy",
            "force.out",
            "stress.out",
            "str_relax.out",
            "str.out",
            "str_hint.out",
            "rndstr.in",
            "sqscell.out",
            "bestsqs.out",
            "mcsqs.log",
        ) or ext in (".py", ".toml", ".lock", ".yaml", ".yml", ".md", ".cff", ".txt", ".cfg", ".ini", ".rst"):
            kind = "file"
        else:
            kind = "file"

        entries.append(
            {
                "name": item.name,
                "kind": kind,
                "rel_path": str(item.relative_to(path1)),
                "size": st.st_size,
                "mtime": st.st_mtime,
            }
        )

    return {"path": str(target.relative_to(path1)), "entries": entries}


def scan_structures(path1: Path) -> list[dict[str, Any]]:
    """List all CONTCAR files across all job subdirs, newest first.

    Args:
        path1 (Path): BLADE root directory.

    Returns:
        List of dicts with ``label``, ``rel_path``, ``source``, ``format``, ``mtime``.
    """
    results: list[dict[str, Any]] = []
    roots = [path1 / "Jobs", path1 / "Files"]
    for root in roots:
        if not root.is_dir():
            continue
        for contcar in root.rglob("CONTCAR"):
            try:
                st = contcar.stat()
                if st.st_size == 0:
                    continue
                results.append(
                    {
                        "label": contcar.parent.name,
                        "rel_path": str(contcar.relative_to(path1)),
                        "source": "CONTCAR",
                        "format": "vasp",
                        "mtime": st.st_mtime,
                    }
                )
            except OSError:
                continue
    return sorted(results, key=lambda x: x["mtime"], reverse=True)


def get_structure_by_label(path1: Path, label: str) -> dict[str, Any]:
    """Return structure text and format for a specific label.

    Args:
        path1 (Path): BLADE root directory.
        label (str): CONTCAR parent directory name.

    Returns:
        Dict with ``structure``, ``format``, ``source``, ``label``.
    """
    roots = [path1 / "Jobs", path1 / "Files"]
    for root in roots:
        if not root.is_dir():
            continue
        for contcar in root.rglob("CONTCAR"):
            if contcar.parent.name == label:
                try:
                    text = contcar.read_text(errors="ignore")
                    if text.strip():
                        xyz = _poscar_to_xyz(text)
                        if xyz:
                            return {"structure": xyz, "format": "xyz", "source": "CONTCAR", "label": label}
                        return {"structure": text, "format": "vasp", "source": "CONTCAR", "label": label}
                except OSError:
                    pass
    return {"structure": None, "format": None, "source": "none", "label": label}


def get_live_structure(path1: Path) -> dict[str, Any]:
    """Find the most recently updated trajectory.xyz and return its latest frame.

    trajectory.xyz is written per step by BaseCalculator.relax() when
    traj_file is set.

    Args:
        path1 (Path): BLADE root directory.

    Returns:
        Dict with ``xyz``, ``full_xyz``, ``frame``, ``total_frames``, ``path``,
        and optionally ``label``.
    """
    from phaseforge_studio.trajectory import _split_xyz_frames

    roots = [path1 / "Jobs", path1 / "Files"]
    best: tuple[float, Path] | None = None

    for root in roots:
        if not root.is_dir():
            continue
        for xyz_path in root.rglob("trajectory.xyz"):
            try:
                st = xyz_path.stat()
                if st.st_size > 0 and (best is None or st.st_mtime > best[0]):
                    best = (st.st_mtime, xyz_path)
            except OSError:
                continue

    if best is None:
        return {"xyz": None, "full_xyz": None, "frame": 0, "total_frames": 0, "path": ""}

    xyz_path = best[1]
    try:
        text = xyz_path.read_text(errors="ignore")
        frames = _split_xyz_frames(text)
        if not frames:
            return {"xyz": None, "full_xyz": None, "frame": 0, "total_frames": 0, "path": ""}
        return {
            "xyz": frames[-1],
            "full_xyz": text,
            "frame": len(frames) - 1,
            "total_frames": len(frames),
            "path": str(xyz_path.relative_to(path1)),
            "label": xyz_path.parent.name,
        }
    except Exception:
        return {"xyz": None, "full_xyz": None, "frame": 0, "total_frames": 0, "path": ""}
