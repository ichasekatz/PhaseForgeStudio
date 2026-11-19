"""PAIPAI adapter for PhaseForgeStudio.

PAIPAI is a C++ Monte Carlo + Python-worker pipeline for low-energy atomic
configuration search (interstitials, vacancies).  There is no pip package —
the ``paipai`` bash wrapper and ``mc_paipai`` C++ binary must be on PATH.

Build from source::

    git clone https://github.com/siyazhu/PAIPAI.git
    cd PAIPAI && mkdir build && cd build
    cmake -DCMAKE_INSTALL_PREFIX=$HOME ..
    cmake --build . --target install
    # adds ~/bin/paipai, ~/bin/mc_paipai, ~/bin/fast_worker.py, ~/bin/slow_worker.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PAIPAI_BINARY = "paipai"


# ---------------------------------------------------------------------------
# Detection / install hints
# ---------------------------------------------------------------------------


def check_paipai_installed() -> bool:
    """Return True if the ``paipai`` wrapper is on PATH."""
    return shutil.which(_PAIPAI_BINARY) is not None


def paipai_install_hint() -> str:
    return (
        "PAIPAI not found on PATH.\n"
        "Build from source:\n"
        "  git clone https://github.com/siyazhu/PAIPAI.git\n"
        "  cd PAIPAI && mkdir build && cd build\n"
        "  cmake -DCMAKE_INSTALL_PREFIX=$HOME ..\n"
        "  cmake --build . --target install\n"
        "Then ensure ~/bin is on your PATH (add to ~/.bashrc)."
    )


# ---------------------------------------------------------------------------
# struc.in writer
# ---------------------------------------------------------------------------



def write_struc_in(
    workdir: Path,
    lattice_name: str,
    scale: float,
    lattice_vectors: list[list[float]],
    host_elements: list[str],
    host_counts: list[int],
    interstitial_elements: list[str],
    interstitial_counts: list[int],
    coords: list[tuple[float, float, float, str]],
    coord_type: str = "Shuffle",
) -> Path:  # noqa: PLR0917
    """Write a PAIPAI struc.in input file and return its path."""
    workdir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [lattice_name, str(scale)]
    for vec in lattice_vectors:
        lines.append("  ".join(f"{v:.8f}" for v in vec))
    lines.append("  ".join(host_elements))
    lines.append("  ".join(str(c) for c in host_counts))
    if interstitial_elements:
        lines.append("  ".join(interstitial_elements))
        lines.append("  ".join(str(c) for c in interstitial_counts))
    else:
        lines.append("")
        lines.append("0")
    total_sites = sum(host_counts) + sum(interstitial_counts)
    lines.append(str(total_sites))
    lines.append(coord_type)
    for x, y, z, elem in coords:
        lines.append(f"  {x:.8f}  {y:.8f}  {z:.8f}  {elem}")
    out = workdir / "struc.in"
    out.write_text("\n".join(lines) + "\n")
    return out


def struc_in_from_poscar(
    workdir: Path,
    poscar_text: str,
    lattice_name: str,
    interstitial_elements: list[str] | None = None,
    interstitial_counts: list[int] | None = None,
) -> Path:
    """Convert a POSCAR/CONTCAR string to struc.in and write it."""
    raw_lines = poscar_text.splitlines()
    # Strip blank lines while preserving index
    lines = list(raw_lines)
    if len(lines) < 8:
        raise ValueError("POSCAR text too short — need at least 8 lines")

    scale = float(lines[1].strip())
    vecs: list[list[float]] = []
    for i in range(3):
        vecs.append([float(x) for x in lines[2 + i].split()])
    host_els = lines[5].split()
    host_counts = [int(x) for x in lines[6].split()]

    # Optional selective-dynamics line
    coord_line_idx = 7
    if lines[7].strip().lower().startswith("s"):
        coord_line_idx = 8

    coord_start = coord_line_idx + 1
    coords: list[tuple[float, float, float, str]] = []
    idx = 0
    for elem, count in zip(host_els, host_counts, strict=True):
        for _ in range(count):
            parts = lines[coord_start + idx].split()
            coords.append((float(parts[0]), float(parts[1]), float(parts[2]), elem))
            idx += 1

    return write_struc_in(
        workdir=workdir,
        lattice_name=lattice_name,
        scale=scale,
        lattice_vectors=vecs,
        host_elements=host_els,
        host_counts=host_counts,
        interstitial_elements=interstitial_elements or [],
        interstitial_counts=interstitial_counts or [],
        coords=coords,
        coord_type="Shuffle",
    )


# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------


@dataclass
class PaipaiState:
    proc: subprocess.Popen | None = None
    state: str = "idle"  # idle | running | done | error | stopped
    log: list[str] = field(default_factory=list)
    workdir: Path | None = None
    start_time: float | None = None

    def push_log(self, line: str) -> None:
        self.log.append(line)
        if len(self.log) > 2000:
            self.log = self.log[-2000:]

    def reset(self) -> None:
        self.log = []
        self.state = "idle"
        self.proc = None
        self.workdir = None
        self.start_time = None


_paipai = PaipaiState()


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _stream_proc(proc: subprocess.Popen, state: PaipaiState) -> None:
    """Drain proc stdout into state.log and set terminal state."""
    assert proc.stdout is not None
    for line in proc.stdout:
        state.push_log(line.rstrip())
    proc.wait()
    if state.state == "running":
        state.state = "done" if proc.returncode == 0 else "error"
    state.push_log(f"[paipai] Exit code: {proc.returncode}")
    state.proc = None


def run_paipai(
    workdir: Path,
    model: str,
    device: str,
    fast_workers: int,
    slow_workers: int,
    steps: int,
    temperature: float,
    pool_cap: int,
    state: PaipaiState,
) -> None:
    """Launch paipai in a background thread and stream output into *state*."""
    if not check_paipai_installed():
        state.state = "error"
        state.push_log("[paipai] ERROR: " + paipai_install_hint())
        return

    state.state = "running"
    state.workdir = workdir
    state.start_time = time.time()
    workdir.mkdir(parents=True, exist_ok=True)

    cmd = [
        _PAIPAI_BINARY,
        "-i", str(workdir / "struc.in"),
        "--model", model,
        "--device", device,
        "--fast", str(fast_workers),
        "--slow", str(slow_workers),
        "--steps", str(steps),
        "--temp", str(temperature),
        "--pool-cap", str(pool_cap),
        "--root", str(workdir),
    ]
    state.push_log(f"[paipai] $ {' '.join(cmd)}")

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(workdir),
        )
        state.proc = proc
        t = threading.Thread(target=_stream_proc, args=(proc, state), daemon=True)
        t.start()
    except Exception as exc:
        state.state = "error"
        state.push_log(f"[paipai] ERROR launching process: {exc}")


def stop_paipai(state: PaipaiState) -> None:
    """Terminate a running PAIPAI process."""
    if state.proc is not None:
        try:
            state.proc.terminate()
        except Exception:
            pass
        state.push_log("[paipai] Terminated by user.")
        state.state = "stopped"


# ---------------------------------------------------------------------------
# Output scanning
# ---------------------------------------------------------------------------


def scan_paipai_outputs(workdir: Path) -> list[dict[str, Any]]:
    """Scan refine_outbox/ and reports/ for completed structures, sorted by energy."""
    results: list[dict[str, Any]] = []

    refine_dir = workdir / "refine_outbox"
    if refine_dir.is_dir():
        for task_dir in sorted(refine_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            entry: dict[str, Any] = {
                "task_id": task_dir.name,
                "has_contcar": (task_dir / "CONTCAR").exists(),
                "source": "refine_outbox",
                "rel_contcar": str((task_dir / "CONTCAR").relative_to(workdir))
                if (task_dir / "CONTCAR").exists()
                else None,
            }
            meta_path = task_dir / "meta.json"
            if meta_path.exists():
                try:
                    entry["meta"] = json.loads(meta_path.read_text())
                    entry["energy"] = entry["meta"].get("energy_final")
                except Exception:
                    pass
            energy_path = task_dir / "energy"
            if energy_path.exists() and "energy" not in entry:
                try:
                    entry["energy"] = float(energy_path.read_text().strip())
                except Exception:
                    pass
            results.append(entry)

    reports_dir = workdir / "reports"
    if reports_dir.is_dir():
        seen = {r["task_id"] for r in results}
        for rpt in sorted(reports_dir.glob("*.json")):
            tid = rpt.stem
            if tid in seen:
                continue
            try:
                data = json.loads(rpt.read_text())
                results.append({
                    "task_id": tid,
                    "source": "reports",
                    "meta": data,
                    "energy": data.get("energy_final"),
                    "has_contcar": False,
                    "rel_contcar": None,
                })
            except Exception:
                pass

    results.sort(key=lambda x: (x.get("energy") is None, x.get("energy") or float("inf")))
    return results


def get_paipai_progress(workdir: Path) -> dict[str, Any]:
    """Read counter files to report MC progress."""
    counters: dict[str, int] = {}
    counters_dir = workdir / "counters"
    if counters_dir.is_dir():
        for ctr in counters_dir.iterdir():
            try:
                counters[ctr.name] = int(ctr.read_text().strip())
            except Exception:
                pass
    n_refine = 0
    refine_dir = workdir / "refine_outbox"
    if refine_dir.is_dir():
        n_refine = sum(1 for p in refine_dir.iterdir() if p.is_dir())
    return {"counters": counters, "n_refined": n_refine}
