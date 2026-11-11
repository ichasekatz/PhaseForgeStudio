"""BLADE dashboard backend logic — filesystem scanners and parsers.

Ported from BLADE/dashboard/server.py for integration into PhaseForge Studio.
All public functions are prefixed to avoid name collisions with the PhaseForge
equivalents already imported in server.py.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Server-side cache (blade-specific key space)
# ---------------------------------------------------------------------------

_blade_cache: dict[str, dict] = {}


def _blade_cached(key: str, ttl: float, fn) -> Any:
    entry = _blade_cache.get(key)
    if entry and (time.time() - entry["ts"]) < ttl:
        return entry["data"]
    data = fn()
    _blade_cache[key] = {"data": data, "ts": time.time()}
    return data


def blade_cache_clear() -> None:
    _blade_cache.clear()


# ---------------------------------------------------------------------------
# ATAT structure parsing
# ---------------------------------------------------------------------------

_ALPHA_ELEMS = [
    "Al",
    "Ba",
    "Ca",
    "Cr",
    "Cu",
    "Fe",
    "Ga",
    "Hf",
    "In",
    "Ir",
    "K",
    "La",
    "Mn",
    "Na",
    "Os",
    "Pd",
    "Pt",
    "Re",
    "Si",
    "Ti",
    "U",
    "V",
    "W",
    "Xe",
    "Y",
    "Zr",
]


def _build_elem_map(rndstr_path: Path) -> dict[str, str]:
    try:
        text = rndstr_path.read_text(errors="ignore")
    except OSError:
        return {}
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        return {}
    mapping: dict[str, str] = {}
    sl_letters = "abcdefghijklmnop"
    sl_idx = 0
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            float(parts[0])
        except ValueError:
            continue
        spec = parts[3]
        if "=" in spec:
            sl = sl_letters[sl_idx] if sl_idx < len(sl_letters) else f"s{sl_idx}"
            for ci, token in enumerate(spec.split(",")):
                elem = token.split("=")[0].strip()
                mapping[f"{sl}_{chr(ord('A') + ci)}"] = elem
            sl_idx += 1
    return mapping


def _atat_species(raw: str, elem_map: dict[str, str] | None, used: set[str] | None) -> str:
    if elem_map and raw in elem_map:
        return elem_map[raw]
    m = re.match(r"^[a-z]_([A-Z])$", raw)
    if m:
        idx = ord(m.group(1)) - ord("A")
        candidate = _ALPHA_ELEMS[idx] if idx < len(_ALPHA_ELEMS) else "Fe"
        if used and candidate in used:
            for alt in _ALPHA_ELEMS:
                if alt not in used:
                    return alt
            return "Xe"
        return candidate
    return raw


def parse_atat_structure(text: str, elem_map: dict[str, str] | None = None) -> str | None:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip() and not ln.startswith("#")]
    if len(lines) < 7:
        return None
    try:
        lat = [[float(x) for x in lines[i].split()[:3]] for i in range(3)]
        _atat_pat = re.compile(r"^[a-z]_[A-Z]$")
        real_elems: set[str] = set()
        for line in lines[6:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                float(parts[0])
                raw = parts[3]
            except ValueError:
                raw = parts[0]
            if not _atat_pat.match(raw) and (not elem_map or raw not in elem_map):
                real_elems.add(raw)
        atoms: list[tuple[str, list[float]]] = []
        for line in lines[6:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                frac = [float(parts[0]), float(parts[1]), float(parts[2])]
                species = _atat_species(parts[3], elem_map, real_elems)
            except ValueError:
                species = _atat_species(parts[0], elem_map, real_elems)
                frac = [float(parts[1]), float(parts[2]), float(parts[3])]
            cart = [
                frac[0] * lat[0][0] + frac[1] * lat[1][0] + frac[2] * lat[2][0],
                frac[0] * lat[0][1] + frac[1] * lat[1][1] + frac[2] * lat[2][1],
                frac[0] * lat[0][2] + frac[1] * lat[1][2] + frac[2] * lat[2][2],
            ]
            atoms.append((species, cart))
        if not atoms:
            return None
        xyz_lines = [str(len(atoms)), "BLADE dashboard"]
        for sp, (x, y, z) in atoms:
            xyz_lines.append(f"{sp} {x:.6f} {y:.6f} {z:.6f}")
        return "\n".join(xyz_lines)
    except Exception:
        return None


def parse_bestcorr(text: str) -> float | None:
    for line in text.strip().splitlines():
        parts = line.strip().split()
        if parts:
            try:
                return float(parts[-1])
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Filesystem scanners
# ---------------------------------------------------------------------------


def scan_sqs(files_dir: Path) -> list[dict]:
    sqs_root = files_dir / "SQS"
    results = []
    if not sqs_root.exists():
        return results
    for sqs_dir in sorted(sqs_root.iterdir()):
        if not sqs_dir.is_dir():
            continue
        by_parent: dict[Path, list] = {}
        for bestcorr in sorted(sqs_dir.rglob("bestcorr*.out")):
            by_parent.setdefault(bestcorr.parent, []).append(bestcorr)
        runs = []
        for parent_dir, corr_files in sorted(by_parent.items()):
            rel = parent_dir.relative_to(sqs_dir)
            for bestcorr in sorted(corr_files):
                ip_str = re.sub(r"\D", "", bestcorr.stem.replace("bestcorr", ""))
                ip = int(ip_str) if ip_str else 0
                obj = None
                with contextlib.suppress(OSError):
                    obj = parse_bestcorr(bestcorr.read_text(errors="ignore"))
                bestsqs = parent_dir / f"bestsqs{ip_str}.out"
                runs.append(
                    {
                        "ip": ip,
                        "subdir": str(rel),
                        "bestcorr_path": str(bestcorr),
                        "bestsqs_path": str(bestsqs) if bestsqs.exists() else None,
                        "objective": obj,
                        "mtime": bestcorr.stat().st_mtime,
                    }
                )
        final = sqs_dir / "bestsqs.out"
        done = final.exists()
        active_comp = None
        if runs:
            latest = max(runs, key=lambda r: r["mtime"])
            active_comp = latest["subdir"]
        results.append(
            {
                "name": sqs_dir.name,
                "path": str(sqs_dir),
                "runs": runs,
                "done": done,
                "final_path": str(final) if done else None,
                "active_comp": active_comp,
            }
        )
    return results


def scan_comps(files_dir: Path, comps_folder: str = "Comps") -> list[dict]:
    comps_root = files_dir / comps_folder
    results = []
    if not comps_root.exists():
        return results
    for comp_dir in sorted(comps_root.iterdir()):
        if not comp_dir.is_dir():
            continue
        tdb_files = list(comp_dir.glob("*.tdb"))
        energy_files = list(comp_dir.rglob("energy"))
        contcar_files = list(comp_dir.rglob("CONTCAR"))
        final_traj = sorted(comp_dir.rglob("relaxation_final.xyz"), key=lambda p: p.stat().st_mtime, reverse=True)
        live_traj = sorted(comp_dir.rglob("relaxation_live.xyz"), key=lambda p: p.stat().st_mtime, reverse=True)
        traj_files = final_traj + live_traj
        results.append(
            {
                "name": comp_dir.name,
                "path": str(comp_dir),
                "tdb_done": bool(tdb_files),
                "tdb_files": [str(f) for f in tdb_files],
                "energy_count": len(energy_files),
                "has_trajectory": bool(traj_files),
                "trajectory_paths": [str(f) for f in traj_files],
                "contcar_paths": [str(f) for f in contcar_files],
                "mtime": comp_dir.stat().st_mtime,
            }
        )
    return results


def scan_plots(files_dir: Path) -> list[dict]:
    comps_dir = files_dir / "Comps"
    if not comps_dir.exists():
        return []
    plots = []
    for ext in ("*.png", "*.gif"):
        for f in sorted(comps_dir.rglob(ext)):
            plots.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "rel": str(f.relative_to(files_dir)),
                    "mtime": f.stat().st_mtime,
                    "size": f.stat().st_size,
                }
            )
    plots.sort(key=lambda x: x["mtime"], reverse=True)
    return plots


def scan_compositions(system_dir: Path) -> list[dict]:
    seen: set[Path] = set()
    results = []

    def _make_entry(parent: Path) -> dict:
        contcar = parent / "CONTCAR"
        traj = sorted(parent.glob("relaxation_final.xyz")) + sorted(parent.glob("relaxation_live.xyz"))
        energy_file = parent / "energy"
        energy = None
        if energy_file.exists():
            with contextlib.suppress(ValueError, IndexError):
                energy = float(energy_file.read_text().strip().split()[0])
        return {
            "name": parent.name,
            "path": str(parent),
            "contcar_path": str(contcar) if contcar.exists() else "",
            "has_trajectory": bool(traj),
            "trajectory_paths": [str(f) for f in traj],
            "energy": energy,
        }

    for contcar in sorted(system_dir.rglob("CONTCAR")):
        parent = contcar.parent
        if parent not in seen:
            seen.add(parent)
            results.append(_make_entry(parent))
    for live in sorted(system_dir.rglob("relaxation_live.xyz")):
        parent = live.parent
        if parent not in seen:
            seen.add(parent)
            results.append(_make_entry(parent))
    results.sort(key=lambda r: r["name"])
    return results


def scan_energy(comp_path: Path) -> list[dict]:
    results = []
    for energy_file in sorted(comp_path.rglob("energy")):
        with contextlib.suppress(OSError, ValueError, IndexError):
            val = float(energy_file.read_text().strip().split()[0])
            results.append(
                {
                    "path": str(energy_file),
                    "energy": val,
                    "rel": str(energy_file.relative_to(comp_path)),
                }
            )
    return results


def infer_stage_status(files_dir: Path) -> dict:
    comps_folder = "Comps"
    sqs_root = files_dir / "SQS"
    comps_root = files_dir / comps_folder
    phase_diag_root = files_dir / "Phase_Diagrams"
    comps = scan_comps(files_dir, comps_folder)
    n_done = sum(1 for c in comps if c["tdb_done"])
    n_total = len(comps)
    oxide_db_root = files_dir / "MaterialsProject_Comps"
    oxide_db_xlsx = files_dir / "blade_generated_data.xlsx"
    oxidation_root = files_dir / "oxidation"
    oxidation_figures = oxidation_root / "figures"
    return {
        "sqs_generation": {
            "started": sqs_root.exists(),
            "dirs": len(list(sqs_root.iterdir())) if sqs_root.exists() else 0,
        },
        "tdb_fitting": {
            "started": comps_root.exists(),
            "systems_total": n_total,
            "systems_done": n_done,
            "all_done": n_total > 0 and n_done == n_total,
        },
        "phase_diagrams": {
            "started": phase_diag_root.exists(),
            "plot_count": len(list(phase_diag_root.rglob("*.png"))) if phase_diag_root.exists() else 0,
        },
        "oxide_database": {
            "started": oxide_db_root.exists() or oxide_db_xlsx.exists(),
            "done": oxide_db_xlsx.exists(),
        },
        "oxidation_graphs": {
            "started": oxidation_root.exists(),
            "done": oxidation_figures.exists() and bool(list(oxidation_figures.rglob("*.png"))),
        },
        "composition_list": (files_dir / "composition_list.xlsx").exists(),
    }


def read_log_tail(log_path: Path | None, n_lines: int = 80) -> list[str]:
    if not log_path or not log_path.exists():
        return []
    try:
        return log_path.read_text(errors="ignore").splitlines()[-n_lines:]
    except OSError:
        return []


def find_live_trajectory(files_dir: Path | None, blade_root: Path | None = None) -> dict | None:
    search_dirs: list[Path] = []
    if files_dir and files_dir.exists():
        search_dirs.append(files_dir)
    if blade_root:
        blade_files = blade_root / "Files"
        if blade_files.exists() and blade_files not in search_dirs:
            search_dirs.append(blade_files)
        parent = blade_root.parent
        for guess in [
            parent / "PhaseForge" / "atat" / "data" / "sqsdb",
            parent / "PhaseForge" / "PhaseForge" / "atat" / "data" / "sqsdb",
            blade_root / "PhaseForge" / "atat" / "data" / "sqsdb",
        ]:
            if guess.exists() and guess not in search_dirs:
                search_dirs.append(guess)
    best_live: tuple[float, Path] | None = None
    best_final: tuple[float, Path] | None = None
    for base in search_dirs:
        for p in base.rglob("relaxation_live.xyz"):
            try:
                st = p.stat()
                if st.st_size > 0 and (best_live is None or st.st_mtime > best_live[0]):
                    best_live = (st.st_mtime, p)
            except OSError:
                continue
        for p in base.rglob("relaxation_final.xyz"):
            try:
                st = p.stat()
                if st.st_size > 0 and (best_final is None or st.st_mtime > best_final[0]):
                    best_final = (st.st_mtime, p)
            except OSError:
                continue
    best = best_live or best_final
    if best:
        p = best[1]
        info: dict = {"path": str(p), "mtime": best[0], "live": best is best_live}
        info_file = p.parent / "relaxation_info.json"
        if info_file.exists():
            with contextlib.suppress(Exception):
                info.update(json.loads(info_file.read_text()))
        return info
    return {"_search_dirs": [str(d) for d in search_dirs]}


def read_toml_parsed(toml_path: Path) -> dict:
    """Read and parse a TOML file, returning a plain dict."""
    import tomllib

    with toml_path.open("rb") as f:
        return tomllib.load(f)


def patch_toml(text: str, section: str, key: str, value) -> str:
    """Replace key = <old> with key = <new> inside [section] block, preserving comments."""
    # Format value as TOML literal
    if isinstance(value, bool):
        toml_val = "true" if value else "false"
    elif isinstance(value, str):
        toml_val = f'"{value}"'
    elif isinstance(value, list):
        parts = []
        for v in value:
            parts.append(f'"{v}"' if isinstance(v, str) else str(v).lower() if isinstance(v, bool) else str(v))
        toml_val = "[" + ", ".join(parts) + "]"
    elif isinstance(value, float):
        toml_val = str(value)
    else:
        toml_val = str(value)

    if section:
        # Find [section] header (not [[section]])
        sec_pat = re.compile(rf"^(\[{re.escape(section)}\])", re.MULTILINE)
        m = sec_pat.search(text)
        if not m:
            return text
        sec_start = m.end()
        # Find next [section] or [[section]] header
        next_sec = re.compile(r"^\[", re.MULTILINE)
        nm = next_sec.search(text, sec_start + 1)
        sec_end = nm.start() if nm else len(text)
        block = text[sec_start:sec_end]
        key_pat = re.compile(rf"^({re.escape(key)}\s*=\s*).*", re.MULTILINE)
        new_block = key_pat.sub(rf"\g<1>{toml_val}", block, count=1)
        return text[:sec_start] + new_block + text[sec_end:]
    else:
        # Top-level key
        key_pat = re.compile(rf"^({re.escape(key)}\s*=\s*).*", re.MULTILINE)
        return key_pat.sub(rf"\g<1>{toml_val}", text, count=1)


def serve_blade_index(blade_index_path: Path, toml_path: str = "") -> bytes:
    """Read BLADE's index.html and rewrite /api/ → /blade/api/ for all fetch calls.

    If toml_path is given, inject a script that pre-fills the TOML path input.
    """
    text = blade_index_path.read_text(encoding="utf-8")
    text = text.replace("fetch('/api/", "fetch('/blade/api/")
    text = text.replace('fetch("/api/', 'fetch("/blade/api/')
    text = text.replace("fetch(`/api/", "fetch(`/blade/api/")
    if toml_path:
        import html as _html

        escaped = _html.escape(toml_path, quote=True)
        inject = (
            f'<script>window.addEventListener("DOMContentLoaded",function(){{'
            f'var el=document.getElementById("toml-path-input");'
            f'if(el&&!el.value){{el.value="{escaped}";}}'
            f"}});</script>"
        )
        text = text.replace("</body>", inject + "\n</body>", 1)
        if "</body>" not in text:
            text += inject
    return text.encode("utf-8")
