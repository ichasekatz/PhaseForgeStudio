#!/usr/bin/env python3
"""PhaseForge Studio server.

Bidirectional web UI for MaterialsFramework / BLADE / PhaseForge pipelines.
Runs on HPC; access via SSH port forwarding.

Usage:
    python server.py
    python server.py --port 8081
    python server.py --port 8081 --config /path/to/config.json
"""

from __future__ import annotations

import argparse
import base64 as _b64
import json
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# ---------------------------------------------------------------------------
# Inject local MaterialsFramework source so the editable install is found
# even in environments where .pth processing is unreliable.
# ---------------------------------------------------------------------------
_gui_dir = Path(__file__).parent
for _src in [_gui_dir / "MaterialsFramework" / "src"]:
    _s = str(_src)
    if _src.exists() and _s not in sys.path:
        sys.path.insert(0, _s)

import phaseforge_studio.job as _job_mod  # noqa: E402, I001
from phaseforge_studio import (  # noqa: E402
    _job,
    _job_history,
    _json_default,
    _load_config,
    _phase_diagram_from_tdb,
    _poscar_to_xyz,
    _resolve,
    _run_analysis,
    _run_pipeline,
    _save_config,
    analyzer_info,
    browse_path,
    get_live_structure,
    get_structure_by_label,
    get_system_step_energies,
    get_trajectory_data,
    get_trajectory_frame,
    get_trajectory_xyz,
    list_available_calculators,
    list_available_lattices,
    scan_energies,
    scan_latest_structure,
    scan_outputs,
    scan_structures,
)
from phaseforge_studio.blade import (  # noqa: E402
    _blade_cached,
    _build_elem_map,
    find_live_trajectory,
    infer_stage_status,
    parse_atat_structure,
    patch_toml,
    read_log_tail,
    read_toml_parsed,
    scan_compositions,
    scan_comps,
    scan_energy,
    scan_plots,
    scan_sqs,
    serve_blade_index,
)
from phaseforge_studio.config import _server_dir  # noqa: E402
from phaseforge_studio.core.artifact_registry import actions_for_file  # noqa: E402
from phaseforge_studio.core.file_types import detect  # noqa: E402
from phaseforge_studio.core.job_manager import _manager as _job_manager  # noqa: E402
from phaseforge_studio.core.projects import Project, _registry as _project_registry  # noqa: E402
from phaseforge_studio.core.workflows import list_workflows  # noqa: E402
from phaseforge_studio.filesystem import (  # noqa: E402
    list_roots,
    register_root,
    search_files,
    universal_browse,
)
from phaseforge_studio.orchid_adapter import (  # noqa: E402
    check_orchid_mcp,
    compare_to_dft,
    get_formation_enthalpy,
    get_invariant_reactions,
    get_phase_diagram,
    get_system_data,
    get_tdb_content,
    list_tdb_files,
    orchid_install_hint,
    orchid_search_systems,
)
from phaseforge_studio.paipai import (  # noqa: E402
    _paipai,
    check_paipai_installed,
    get_paipai_progress,
    run_paipai,
    scan_paipai_outputs,
    stop_paipai,
    struc_in_from_poscar,
    write_struc_in,
)


class _PfState:
    proc: subprocess.Popen | None = None
    state: str = "idle"  # idle | running | done | error
    log: list[str] = []


_pf = _PfState()


class StudioHandler(BaseHTTPRequestHandler):
    """HTTP request handler for PhaseForge Studio."""

    config_path: Path
    cfg: dict[str, Any]

    def log_message(self, fmt: str, *args: Any) -> None:
        """Suppress default access log output."""

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, content_type: str = "text/plain") -> None:
        try:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._json({"error": "not found"}, 404)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        """Route all GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._serve_file(Path(__file__).parent / "index.html", "text/html; charset=utf-8")

        elif path == "/api/config":
            self._json(self.cfg)

        elif path == "/api/calculators":
            self._json(list_available_calculators())

        elif path == "/api/lattices":
            self._json(list_available_lattices(_resolve(self.cfg, "path2")))

        elif path == "/api/status":
            self._json(_job.as_dict())

        elif path == "/api/jobs":
            current = _job.as_dict() if _job.job_id else None
            self._json({"current": current, "history": list(reversed(_job_history))})

        elif path == "/api/stream":
            self._handle_sse()

        elif path == "/api/structure":
            label = qs.get("label", [""])[0]
            path1 = _resolve(self.cfg, "path1")
            if label:
                self._json(get_structure_by_label(path1, label))
            else:
                self._json(scan_latest_structure(path1))

        elif path == "/api/structures":
            self._json(scan_structures(_resolve(self.cfg, "path1")))

        elif path == "/api/energies":
            self._json(scan_energies(_resolve(self.cfg, "path1")))

        elif path == "/api/energies/system":
            label = qs.get("label", [""])[0]
            curves = get_system_step_energies(_resolve(self.cfg, "path1"), label)
            self._json({"curves": curves})

        elif path == "/api/phase_diagram":
            rel = qs.get("path", [""])[0]
            path1 = _resolve(self.cfg, "path1")
            tdb_path = (path1 / rel).resolve()
            if not str(tdb_path).startswith(str(path1)) or not tdb_path.exists():
                self._json({"error": "not found"}, 404)
            else:
                try:
                    pngs = _phase_diagram_from_tdb(
                        tdb_path,
                        t_min=float(self.cfg.get("t_min", 300)),
                        t_max=float(self.cfg.get("t_max", 3000)),
                    )
                    rel_pngs = [str(p.relative_to(path1)) for p in pngs]
                    self._json({"ok": True, "pngs": rel_pngs})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)

        elif path == "/api/outputs":
            self._json(scan_outputs(_resolve(self.cfg, "path1")))

        elif path == "/api/browse":
            rel = qs.get("path", [""])[0]
            self._json(browse_path(_resolve(self.cfg, "path1"), rel))

        elif path == "/api/trajectory":
            label = qs.get("label", [""])[0]
            data = get_trajectory_data(_resolve(self.cfg, "path1"), label)
            if data is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(data)

        elif path == "/api/trajectory/frame":
            label = qs.get("label", [""])[0]
            try:
                frame = int(qs.get("frame", ["0"])[0])
            except (ValueError, IndexError):
                frame = 0
            data = get_trajectory_frame(_resolve(self.cfg, "path1"), label, frame)
            if data is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(data)

        elif path == "/api/trajectory/xyz":
            label = qs.get("label", [""])[0]
            xyz_text = get_trajectory_xyz(_resolve(self.cfg, "path1"), label)
            if xyz_text is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json({"label": label, "xyz": xyz_text})

        elif path == "/api/analyzers":
            self._json(analyzer_info)

        elif path == "/api/convert_xyz":
            rel = qs.get("path", [""])[0]
            if not rel:
                self._json({"error": "no path"}, 400)
                return
            full = _resolve(self.cfg, "path1") / rel
            if not full.is_file():
                self._json({"error": "not found"}, 404)
                return
            try:
                text = full.read_text(errors="ignore")
                xyz = _poscar_to_xyz(text)
                if xyz:
                    self._json({"xyz": xyz, "format": "xyz"})
                else:
                    self._json({"xyz": text, "format": "vasp"})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/live_structure":
            self._json(get_live_structure(_resolve(self.cfg, "path1")))

        # ── Universal file explorer ──────────────────────────────────────────
        elif path == "/api/fs/roots":
            self._json({"roots": list_roots()})

        elif path == "/api/fs/browse":
            root = qs.get("root", ["mf"])[0]
            rel = qs.get("path", [""])[0]
            self._json(universal_browse(root, rel))

        elif path == "/api/fs/search":
            root = qs.get("root", ["mf"])[0]
            query = qs.get("q", [""])[0]
            limit = int(qs.get("limit", ["50"])[0])
            self._json({"results": search_files(root, query, max_results=limit)})

        elif path == "/api/fs/actions":
            abs_path_str = qs.get("path", [""])[0]
            if not abs_path_str:
                self._json({"error": "path required"}, 400)
                return
            p = Path(abs_path_str)
            if not p.exists():
                self._json({"error": "not found"}, 404)
                return
            ft = detect(p)
            self._json({"path": str(p), "ft": ft, "actions": actions_for_file(p, ft)})

        elif path == "/api/fs/read_text":
            abs_path_str = qs.get("path", [""])[0]
            max_bytes = int(qs.get("max_bytes", ["16384"])[0])
            if not abs_path_str:
                self._json({"error": "path required"}, 400)
                return
            p = Path(abs_path_str)
            if not p.is_file():
                self._json({"error": "not found"}, 404)
                return
            try:
                text = p.read_text(errors="ignore")[:max_bytes]
                self._json({"path": str(p), "content": text, "truncated": len(p.read_bytes()) > max_bytes})
            except OSError as exc:
                self._json({"error": str(exc)}, 500)

        # ── Unified job manager ──────────────────────────────────────────────
        elif path == "/api/jobs/all":
            framework = qs.get("framework", [None])[0]
            active_only = qs.get("active_only", ["false"])[0].lower() == "true"
            self._json({"jobs": _job_manager.list_jobs(framework=framework, active_only=active_only)})

        elif path == "/api/jobs/status":
            job_id = qs.get("job_id", [""])[0]
            if not job_id:
                self._json({"error": "job_id required"}, 400)
                return
            try:
                self._json(_job_manager.get(job_id).as_dict())
            except KeyError:
                self._json({"error": "not found"}, 404)

        # ── Projects ─────────────────────────────────────────────────────────
        elif path == "/api/projects":
            self._json({"projects": _project_registry.list_projects()})

        elif path == "/api/workflows":
            self._json({"workflows": list_workflows()})

        # ── ORCHID GET endpoints (query-string based) ────────────────────────
        elif path == "/api/orchid/search":
            elements = qs.get("elements", [])
            system = qs.get("system", [""])[0]
            if not elements and not system:
                self._json({"error": "elements or system required"}, 400)
                return
            if system and not elements:
                elements = system.split("-")
            try:
                results = orchid_search_systems(
                    elements=elements,
                    exact=qs.get("exact", ["false"])[0].lower() == "true",
                    limit=int(qs.get("limit", ["50"])[0]),
                )
                self._json({"results": results})
            except Exception as exc:
                self._json({"error": str(exc), "results": []})

        elif path == "/api/orchid/system":
            system = qs.get("system", [""])[0]
            if not system:
                self._json({"error": "system required"}, 400)
                return
            try:
                data = get_system_data(
                    system=system,
                    property_group=qs.get("property_group", [None])[0],
                    evidence_class=qs.get("evidence_class", [None])[0],
                )
                self._json(data)
            except Exception as exc:
                self._json({"error": str(exc), "system": system})

        elif path == "/api/orchid/phase_diagram":
            system = qs.get("system", [""])[0]
            if not system:
                self._json({"error": "system required"}, 400)
                return
            try:
                self._json(get_phase_diagram(system=system))
            except Exception as exc:
                self._json({"error": str(exc), "system": system})

        elif path == "/api/orchid/invariant":
            system = qs.get("system", [""])[0]
            if not system:
                self._json({"error": "system required"}, 400)
                return
            try:
                self._json({"reactions": get_invariant_reactions(system, qs.get("source", ["literature"])[0])})
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/orchid/compare_dft":
            system = qs.get("system", [""])[0]
            if not system:
                self._json({"error": "system required"}, 400)
                return
            try:
                self._json(compare_to_dft(system))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/orchid/tdb_list":
            elements = qs.get("elements", [])
            try:
                tdbs = list_tdb_files(elements=elements if elements else None)
                self._json({"tdbs": tdbs})
            except Exception as exc:
                self._json({"error": str(exc), "tdbs": []})

        elif path == "/api/orchid/get_tdb":
            file_id = qs.get("file_id", [""])[0]
            if not file_id:
                self._json({"error": "file_id required"}, 400)
                return
            try:
                self._json({"content": get_tdb_content(file_id), "file_id": file_id})
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path in ("/blade", "/blade/", "/blade/index.html"):
            blade_root = (
                _resolve(self.cfg, "path1")
                if self.cfg.get("active_workspace") == "blade"
                else Path(self.cfg.get("blade_path1", "")).expanduser().resolve()
            )
            blade_idx = blade_root / "dashboard" / "index.html"
            if not blade_idx.is_file():
                self._json({"error": "BLADE dashboard not found — set blade_path1 in config"}, 404)
                return
            data = serve_blade_index(blade_idx, toml_path=self.cfg.get("blade_toml", ""))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        elif path.startswith("/blade/api/"):
            blade_root = Path(self.cfg.get("blade_path1", "")).expanduser().resolve()
            files_dir = blade_root / "Files"
            blade_path = path[len("/blade") :]  # strip /blade prefix → /api/...
            blade_qs = qs

            if blade_path == "/api/status":
                sqs = _blade_cached("sqs", 4, lambda: scan_sqs(files_dir))
                comps = _blade_cached("comps", 4, lambda: scan_comps(files_dir))
                stages = _blade_cached("stages", 4, lambda: infer_stage_status(files_dir))
                self._json({"stages": stages, "sqs": sqs, "systems": comps, "timestamp": time.time()})

            elif blade_path == "/api/sqs":
                self._json(_blade_cached("sqs", 4, lambda: scan_sqs(files_dir)))

            elif blade_path == "/api/structure":
                file_path = blade_qs.get("path", [None])[0]
                if not file_path:
                    self._json({"error": "missing path"}, 400)
                    return
                p = Path(file_path)
                if not p.exists():
                    self._json({"error": "not found"}, 404)
                    return
                elem_map = _build_elem_map(p.parent / "rndstr.in")
                xyz = parse_atat_structure(p.read_text(errors="ignore"), elem_map)
                self._json({"xyz": xyz, "path": str(p)})

            elif blade_path == "/api/trajectory":
                file_path = blade_qs.get("path", [None])[0]
                if not file_path:
                    self._json({"error": "missing path"}, 400)
                    return
                p = Path(file_path)
                if not p.exists():
                    self._json({"error": "not found"}, 404)
                    return
                self._json({"xyz": p.read_text(errors="ignore"), "path": str(p)})

            elif blade_path == "/api/compositions":
                dir_path = blade_qs.get("dir", [None])[0]
                if not dir_path:
                    self._json({"error": "missing dir"}, 400)
                    return
                self._json(scan_compositions(Path(dir_path)))

            elif blade_path == "/api/energy":
                dir_path = blade_qs.get("dir", [None])[0]
                if not dir_path:
                    self._json({"error": "missing dir"}, 400)
                    return
                self._json(scan_energy(Path(dir_path)))

            elif blade_path == "/api/plots":
                self._json(_blade_cached("plots", 30, lambda: scan_plots(files_dir)))

            elif blade_path == "/api/image":
                file_path = blade_qs.get("path", [None])[0]
                if not file_path:
                    self._json({"error": "missing path"}, 400)
                    return
                p = Path(file_path)
                if not p.exists():
                    self._json({"error": "not found"}, 404)
                    return
                ext = p.suffix.lower()
                mime = "image/gif" if ext == ".gif" else "image/png"
                b64 = _b64.b64encode(p.read_bytes()).decode()
                self._json({"data": b64, "mime": mime, "name": p.name})

            elif blade_path == "/api/live_trajectory":
                result = find_live_trajectory(files_dir, blade_root)
                if result and result.get("path"):
                    p = Path(result["path"])
                    self._json(
                        {
                            "xyz": p.read_text(errors="ignore"),
                            "path": result["path"],
                            "mtime": result["mtime"],
                            "live": result.get("live", True),
                            "nsteps": result.get("nsteps"),
                            "converged": result.get("converged"),
                            "composition": p.parent.name,
                        }
                    )
                else:
                    self._json({"xyz": None, "path": None, "search_dirs": (result or {}).get("_search_dirs", [])})

            elif blade_path == "/api/log":
                log_path = blade_root / "nohup.out"
                self._json({"lines": read_log_tail(log_path if log_path.exists() else None)})

            elif blade_path == "/api/config":
                self._json(
                    {
                        "files_dir": str(files_dir),
                        "blade_root": str(blade_root),
                        "elements": {},
                        "tdb": {},
                        "stages": {},
                    }
                )

            elif blade_path == "/api/toml":
                rel = blade_qs.get("path", [""])[0]
                if not rel:
                    self._json({"error": "missing path"}, 400)
                    return
                candidate = Path(rel)
                if not candidate.is_absolute():
                    candidate = (blade_root / rel).resolve()
                if not str(candidate).startswith(str(blade_root)):
                    self._json({"error": "forbidden"}, 403)
                    return
                if not candidate.is_file():
                    self._json({"error": "not found"}, 404)
                    return
                self._json({"content": candidate.read_text(errors="ignore"), "path": str(candidate)})

            elif blade_path == "/api/toml_read":
                rel = blade_qs.get("path", [""])[0]
                if not rel:
                    self._json({"error": "missing path"}, 400)
                    return
                candidate = Path(rel) if Path(rel).is_absolute() else (blade_root / rel).resolve()
                if not str(candidate).startswith(str(blade_root)) or not candidate.is_file():
                    self._json({"error": "not found"}, 404)
                    return
                try:
                    self._json({"data": read_toml_parsed(candidate)})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)

            else:
                self._json({"error": "not found"}, 404)

        elif path == "/api/pf_status":
            self._json({"state": _pf.state, "log_tail": _pf.log[-40:]})

        elif path.startswith("/files/"):
            rel = unquote(path[len("/files/") :])
            full = _resolve(self.cfg, "path1") / rel
            if not full.is_file():
                self._json({"error": "not found"}, 404)
                return
            ext = full.suffix.lower()
            mime_map = {".tdb": "text/plain", ".png": "image/png", ".gif": "image/gif", ".json": "application/json"}
            self._serve_file(full, mime_map.get(ext, "application/octet-stream"))

        elif path.startswith("/pf_file/"):
            rel = unquote(path[len("/pf_file/") :])
            workdir = Path(self.cfg.get("pf_workdir", "")).expanduser().resolve()
            if not str(workdir) or workdir == Path().resolve():
                self._json({"error": "pf_workdir not set"}, 400)
                return
            target = (workdir / rel).resolve()
            if not str(target).startswith(str(workdir)):
                self._json({"error": "forbidden"}, 403)
                return
            if not target.exists():
                self._json({"error": "not found"}, 404)
                return
            ctype = "image/png" if target.suffix == ".png" else "application/octet-stream"
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        """Route all POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/config":
            try:
                body = json.loads(self._read_body())
                self.cfg.update(body)
                _save_config(self.config_path, self.cfg)
                StudioHandler.cfg = self.cfg
                self._json({"ok": True})
            except (json.JSONDecodeError, OSError) as e:
                self._json({"error": str(e)}, 400)

        elif path == "/api/run":
            if _job.is_running():
                self._json({"error": "job already running"}, 409)
                return
            cfg_snapshot = dict(self.cfg)
            if _job.job_id and _job.state in ("done", "error", "idle"):
                _job_history.append(
                    {
                        "job_id": _job.job_id,
                        "job_name": _job.job_name,
                        "state": _job.state,
                        "start_time": _job.start_time,
                        "end_time": _job.end_time,
                    }
                )
            _job_mod._job_counter += 1  # noqa: SLF001
            species_str = "".join(cfg_snapshot.get("species", []))
            lattice_str = "-".join(cfg_snapshot.get("lattices", []))
            readable_name = f"{species_str} {lattice_str} #{_job_mod._job_counter}"  # noqa: SLF001
            _job.state = "running"
            _job.job_id = str(uuid.uuid4())[:8]
            _job.job_name = readable_name
            _job.start_time = time.time()
            _job.end_time = None
            _job.log.clear()
            t = threading.Thread(target=_run_pipeline, args=(cfg_snapshot, _job), daemon=True)
            _job._thread = t  # noqa: SLF001
            t.start()
            self._json({"ok": True, "job_id": _job.job_id, "job_name": _job.job_name})

        elif path == "/api/stop":
            _job.stop()
            self._json({"ok": True})

        elif path == "/api/delete":
            import shutil

            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            paths = body.get("paths", [])
            if not paths:
                self._json({"error": "no paths"}, 400)
                return
            path1 = _resolve(self.cfg, "path1")
            errors: list[str] = []
            deleted: list[str] = []
            for rel in paths:
                # Sanitize: strip leading slashes and block traversal
                safe_rel = rel.strip("/").replace("..", "")
                target = (path1 / safe_rel).resolve()
                # Must stay inside path1
                if not str(target).startswith(str(path1) + "/") and target != path1:
                    errors.append(f"forbidden: {rel}")
                    continue
                try:
                    if target.is_dir():
                        shutil.rmtree(target)
                    elif target.exists():
                        target.unlink()
                    deleted.append(rel)
                except OSError as e:
                    errors.append(str(e))
            self._json({"ok": not errors, "deleted": deleted, "errors": errors})

        elif path == "/api/switch_workspace":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            workspace = body.get("workspace", "mf")
            if workspace not in ("pf", "mf", "phaseforge", "blade", "paipai", "orchid"):
                self._json({"error": "unknown workspace"}, 400)
                return
            self.cfg["active_workspace"] = workspace
            StudioHandler.cfg = self.cfg
            _save_config(self.config_path, self.cfg)
            self._json({"ok": True, "active_workspace": workspace})

        elif path == "/api/pf_run":
            if _pf.proc is not None and _pf.proc.poll() is None:
                self._json({"error": "sqscal already running"}, 409)
                return
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            elements = body.get("elements", [])
            lattices = body.get("lattices", [])
            level = int(body.get("level", 2))
            mlip = body.get("mlip", "grace")
            model = body.get("model", "")
            vib = bool(body.get("vib", False))
            sro = bool(body.get("sro", False))
            workdir_str = body.get("workdir", "") or self.cfg.get("pf_workdir", "")
            workdir = Path(workdir_str).expanduser().resolve() if workdir_str else None
            if not elements or not lattices:
                self._json({"error": "elements and lattices required"}, 400)
                return
            cmd = ["sqscal", "-e", ",".join(elements), "-l", ",".join(lattices), "-lv", str(level), "-mlip", mlip]
            if model:
                cmd += ["-model", model]
            if vib:
                cmd.append("-vib")
            if sro:
                cmd.append("-sro")
            _pf.log = []
            _pf.state = "running"
            try:
                _pf.proc = subprocess.Popen(
                    cmd,
                    cwd=str(workdir) if workdir and workdir.is_dir() else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError:
                _pf.state = "error"
                self._json({"error": "sqscal not found on PATH"}, 500)
                return
            except OSError as exc:
                _pf.state = "error"
                self._json({"error": str(exc)}, 500)
                return

            def _stream(proc: subprocess.Popen) -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    _pf.log.append(line.rstrip("\n"))
                proc.wait()
                _pf.state = "done" if proc.returncode == 0 else "error"

            threading.Thread(target=_stream, args=(_pf.proc,), daemon=True).start()
            self._json({"ok": True, "command": " ".join(cmd)})

        elif path == "/api/pf_stop":
            if _pf.proc is not None and _pf.proc.poll() is None:
                _pf.proc.terminate()
            _pf.state = "idle"
            self._json({"ok": True})

        elif path == "/api/pf_outputs":
            workdir_str = self.cfg.get("pf_workdir", "")
            if not workdir_str:
                self._json({"tdb": [], "png": []})
                return
            workdir = Path(workdir_str).expanduser().resolve()
            if not workdir.is_dir():
                self._json({"tdb": [], "png": []})
                return
            tdb_files = sorted(str(p.relative_to(workdir)) for p in workdir.rglob("*.tdb"))
            png_files = sorted(str(p.relative_to(workdir)) for p in workdir.rglob("*.png"))
            self._json({"tdb": tdb_files, "png": png_files})

        # ── PAIPAI endpoints ─────────────────────────────────────────────────
        elif path == "/api/paipai_status":
            wd = _paipai.workdir
            progress: dict[str, Any] = {}
            if wd and wd.is_dir():
                try:
                    progress = get_paipai_progress(wd)
                except Exception:
                    pass
            self._json({
                "state": _paipai.state,
                "installed": check_paipai_installed(),
                "log_tail": _paipai.log[-60:],
                "progress": progress,
            })

        elif path == "/api/paipai_run":
            if _paipai.state == "running":
                self._json({"error": "PAIPAI already running"}, 409)
                return
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            workdir_str = body.get("workdir") or self.cfg.get("paipai_workdir", "")
            if not workdir_str:
                self._json({"error": "paipai_workdir not set"}, 400)
                return
            workdir = Path(workdir_str).expanduser().resolve()
            # Validate path is not system-sensitive
            if str(workdir).startswith("/etc") or str(workdir).startswith("/usr"):
                self._json({"error": "invalid workdir"}, 400)
                return
            # Build struc.in from request or existing POSCAR
            poscar_text = body.get("poscar_text", "")
            if poscar_text:
                try:
                    struc_in_from_poscar(
                        workdir=workdir,
                        poscar_text=poscar_text,
                        lattice_name=body.get("lattice_name", self.cfg.get("paipai_lattice_name", "FCC")),
                        interstitial_elements=body.get("interstitial_elements") or self.cfg.get("paipai_interstitial_elements", []),
                        interstitial_counts=body.get("interstitial_counts") or self.cfg.get("paipai_interstitial_counts", []),
                    )
                except Exception as exc:
                    self._json({"error": f"struc.in generation failed: {exc}"}, 400)
                    return
            elif not (workdir / "struc.in").exists():
                self._json({"error": "struc.in not found and no poscar_text supplied"}, 400)
                return
            # Save config
            for key in ("workdir", "lattice_name", "model", "device", "fast", "slow",
                        "steps", "temperature", "pool_cap"):
                cfg_key = f"paipai_{key}"
                if key in body:
                    self.cfg[cfg_key] = body[key]
            StudioHandler.cfg = self.cfg
            _save_config(self.config_path, self.cfg)
            _paipai.reset()
            threading.Thread(
                target=run_paipai,
                args=(
                    workdir,
                    body.get("model", self.cfg.get("paipai_model", "GRACE-2L-OMAT")),
                    body.get("device", self.cfg.get("paipai_device", "cpu")),
                    int(body.get("fast", self.cfg.get("paipai_fast", 15))),
                    int(body.get("slow", self.cfg.get("paipai_slow", 15))),
                    int(body.get("steps", self.cfg.get("paipai_steps", 2000))),
                    float(body.get("temperature", self.cfg.get("paipai_temperature", 0.001))),
                    int(body.get("pool_cap", self.cfg.get("paipai_pool_cap", 128))),
                    _paipai,
                ),
                daemon=True,
            ).start()
            self._json({"ok": True, "state": "running"})

        elif path == "/api/paipai_stop":
            stop_paipai(_paipai)
            self._json({"ok": True})

        elif path == "/api/paipai_outputs":
            workdir_str = self.cfg.get("paipai_workdir", "")
            if not workdir_str:
                self._json({"outputs": [], "installed": check_paipai_installed()})
                return
            workdir = Path(workdir_str).expanduser().resolve()
            outputs = scan_paipai_outputs(workdir) if workdir.is_dir() else []
            self._json({"outputs": outputs, "installed": check_paipai_installed()})

        elif path == "/api/paipai_write_struc":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            workdir_str = body.get("workdir") or self.cfg.get("paipai_workdir", "")
            if not workdir_str:
                self._json({"error": "paipai_workdir not set"}, 400)
                return
            workdir = Path(workdir_str).expanduser().resolve()
            try:
                p = write_struc_in(
                    workdir=workdir,
                    lattice_name=body.get("lattice_name", "FCC"),
                    scale=float(body.get("scale", 1.0)),
                    lattice_vectors=body.get("lattice_vectors", [[3.52,0,0],[0,3.52,0],[0,0,3.52]]),
                    host_elements=body.get("host_elements", ["Ni"]),
                    host_counts=[int(x) for x in body.get("host_counts", [1])],
                    interstitial_elements=body.get("interstitial_elements", []),
                    interstitial_counts=[int(x) for x in body.get("interstitial_counts", [])],
                    coords=[(c[0], c[1], c[2], c[3]) for c in body.get("coords", [[0,0,0,"Ni"]])],
                    coord_type=body.get("coord_type", "Shuffle"),
                )
                self._json({"ok": True, "path": str(p)})
            except Exception as exc:
                self._json({"error": str(exc)}, 400)

        # ── ORCHID endpoints ─────────────────────────────────────────────────
        elif path == "/api/orchid/status":
            self._json({
                "mcp_available": check_orchid_mcp(),
                "hint": orchid_install_hint() if not check_orchid_mcp() else None,
            })

        elif path == "/api/orchid/search":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            elements = body.get("elements", [])
            if not elements:
                self._json({"error": "elements required"}, 400)
                return
            try:
                results = orchid_search_systems(
                    elements=elements,
                    exact=body.get("exact", False),
                    limit=int(body.get("limit", 50)),
                )
                self._json({"results": results})
            except Exception as exc:
                self._json({"error": str(exc), "results": []})

        elif path == "/api/orchid/system":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            system = body.get("system", "")
            if not system:
                self._json({"error": "system required"}, 400)
                return
            try:
                data = get_system_data(
                    system=system,
                    property_group=body.get("property_group"),
                    evidence_class=body.get("evidence_class"),
                )
                self._json(data)
            except Exception as exc:
                self._json({"error": str(exc), "system": system})

        elif path == "/api/orchid/phase_diagram":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            system = body.get("system", "")
            if not system:
                self._json({"error": "system required"}, 400)
                return
            try:
                data = get_phase_diagram(
                    system=system,
                    x_arr=body.get("x"),
                    t_arr=body.get("T"),
                )
                self._json(data)
            except Exception as exc:
                self._json({"error": str(exc), "system": system})

        elif path == "/api/orchid/formation_enthalpy":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            formula = body.get("formula", "")
            if not formula:
                self._json({"error": "formula required"}, 400)
                return
            try:
                self._json(get_formation_enthalpy(formula))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/orchid/tdb_list":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                body = {}
            try:
                files = list_tdb_files(
                    elements=body.get("elements"),
                    tier=body.get("tier"),
                )
                self._json({"files": files})
            except Exception as exc:
                self._json({"error": str(exc), "files": []})

        elif path == "/api/orchid/get_tdb":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            file_id = body.get("file_id", "")
            if not file_id:
                self._json({"error": "file_id required"}, 400)
                return
            content = get_tdb_content(file_id)
            self._json({"content": content, "file_id": file_id})

        elif path == "/api/orchid/import_tdb":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            content = body.get("content", "")
            filename = body.get("filename", "orchid_imported.tdb")
            # Validate filename - no path traversal
            if "/" in filename or "\\" in filename or ".." in filename:
                self._json({"error": "invalid filename"}, 400)
                return
            save_dir = _resolve(self.cfg, "path1") / "Files"
            save_dir.mkdir(parents=True, exist_ok=True)
            dest = save_dir / filename
            try:
                dest.write_text(content)
                self._json({"ok": True, "saved_to": str(dest)})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

        elif path == "/api/orchid/invariant":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            system = body.get("system", "")
            if not system:
                self._json({"error": "system required"}, 400)
                return
            try:
                self._json({"reactions": get_invariant_reactions(system, body.get("source", "literature"))})
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/orchid/compare_dft":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            system = body.get("system", "")
            if not system:
                self._json({"error": "system required"}, 400)
                return
            try:
                self._json(compare_to_dft(system))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/analyze":
            try:
                params = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                params = {}
            result = _run_analysis(self.cfg, params)
            body = json.dumps(result, default=_json_default).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        # ── Unified job manager (POST) ───────────────────────────────────────
        elif path == "/api/jobs/cancel":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            job_id = body.get("job_id", "")
            if not job_id:
                self._json({"error": "job_id required"}, 400)
                return
            try:
                _job_manager.cancel(job_id)
                self._json({"ok": True, "job_id": job_id})
            except KeyError:
                self._json({"error": "not found"}, 404)

        # ── Projects (POST) ──────────────────────────────────────────────────
        elif path == "/api/projects/create":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            root = body.get("root", "")
            name = body.get("name", "")
            if not root or not name:
                self._json({"error": "root and name required"}, 400)
                return
            try:
                proj = Project.create(root=root, name=name, description=body.get("description", ""))
                _project_registry.register(proj)
                self._json({"ok": True, "project": proj.as_dict()})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

        elif path == "/api/projects/open":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            root = body.get("root", "")
            if not root:
                self._json({"error": "root required"}, 400)
                return
            try:
                proj = Project.load(root)
                _project_registry.register(proj)
                self._json({"ok": True, "project": proj.as_dict()})
            except Exception as exc:
                self._json({"error": str(exc)}, 404)

        # ── Cross-framework transfer ──────────────────────────────────────────
        elif path == "/api/transfer":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            abs_path_str = body.get("path", "")
            action_id = body.get("action_id", "")
            if not abs_path_str or not action_id:
                self._json({"error": "path and action_id required"}, 400)
                return
            p = Path(abs_path_str)
            if not p.exists():
                self._json({"error": "file not found"}, 404)
                return
            ft = detect(p)
            valid_actions = {a["action_id"] for a in actions_for_file(p, ft)}
            if action_id not in valid_actions:
                self._json({"error": f"action {action_id!r} not valid for {ft!r}"}, 400)
                return
            try:
                if action_id == "paipai_set_input":
                    # Send structure to PAIPAI workdir as struc.in
                    workdir_str = self.cfg.get("paipai_workdir", "")
                    lattice_name = self.cfg.get("paipai_lattice_name", "FCC")
                    if not workdir_str:
                        self._json({"error": "paipai_workdir not configured"}, 400)
                        return
                    workdir = Path(workdir_str).expanduser().resolve()
                    poscar_text = p.read_text(errors="ignore")
                    struc_in_from_poscar(
                        workdir=workdir,
                        poscar_text=poscar_text,
                        lattice_name=lattice_name,
                        interstitial_elements=self.cfg.get("paipai_interstitial_elements", []),
                        interstitial_counts=self.cfg.get("paipai_interstitial_counts", []),
                    )
                    self._json({"ok": True, "target": "paipai", "struc_in": str(workdir / "struc.in")})

                elif action_id == "view_structure":
                    # Return XYZ for 3Dmol viewer
                    from phaseforge_studio.structure import _poscar_to_xyz
                    text = p.read_text(errors="ignore")
                    xyz = _poscar_to_xyz(text) or text
                    self._json({"ok": True, "target": "mf", "xyz": xyz, "format": "xyz", "label": p.name})

                elif action_id in ("blade_open_tdb", "pf_open_tdb"):
                    # Return TDB content for BLADE/PF viewer
                    content = p.read_text(errors="ignore")
                    self._json({"ok": True, "target": action_id.split("_")[0], "content": content, "path": str(p)})

                elif action_id in ("convert_to_xyz", "convert_to_poscar"):
                    from phaseforge_studio.core.converters import convert_file
                    target_fmt = "xyz" if action_id == "convert_to_xyz" else "poscar"
                    converted = convert_file(p, target_fmt)
                    self._json({"ok": True, "content": converted, "format": target_fmt})

                else:
                    self._json({"ok": True, "action_id": action_id, "path": str(p), "ft": ft,
                                "note": "generic transfer — handle on client side"})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

        elif path == "/blade/api/toml_write":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            rel = body.get("path", "")
            updates = body.get("updates", {})  # {section: {key: value}} or {"": {key: value}} for top-level
            blade_root = Path(self.cfg.get("blade_path1", "")).expanduser().resolve()
            candidate = Path(rel) if Path(rel).is_absolute() else (blade_root / rel).resolve()
            if not str(candidate).startswith(str(blade_root)) or not candidate.is_file():
                self._json({"error": "not found"}, 404)
                return
            try:
                text = candidate.read_text(encoding="utf-8")
                for section, kv in updates.items():
                    for key, value in kv.items():
                        text = patch_toml(text, section, key, value)
                tmp = candidate.with_suffix(".tmp")
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(candidate)
                self._json({"ok": True})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

        else:
            self._json({"error": "not found"}, 404)

    def _handle_sse(self) -> None:
        """Hold connection open and push log lines via Server-Sent Events."""
        heartbeat_interval = 15.0
        poll_sleep = 0.25

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        last_idx = len(_job.log)
        last_state = _job.state
        last_heartbeat = time.time()
        last_contcar_count = 0
        path1 = _resolve(StudioHandler.cfg, "path1")

        def _send(payload: str) -> bool:
            try:
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        _send(json.dumps({"type": "status", "state": _job.state}))

        while True:
            time.sleep(poll_sleep)

            now = time.time()
            log_snapshot = list(_job.log)
            new_lines = log_snapshot[last_idx:]
            last_idx = len(log_snapshot)

            for line in new_lines:
                if not _send(json.dumps({"type": "log", "line": line})):
                    return

            current_state = _job.state
            if current_state != last_state:
                if not _send(json.dumps({"type": "status", "state": current_state})):
                    return
                last_state = current_state

            if current_state == "running":
                try:
                    structs = scan_structures(path1)
                    if len(structs) != last_contcar_count:
                        last_contcar_count = len(structs)
                        if structs:
                            latest = structs[0]
                            if not _send(json.dumps({"type": "structure_updated", "label": latest["label"]})):
                                return
                except Exception:
                    pass

            if now - last_heartbeat >= heartbeat_interval:
                try:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    last_heartbeat = now
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return


def main() -> None:
    """Parse args, load config, and serve."""
    parser = argparse.ArgumentParser(description="PhaseForge Studio server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--config", type=Path, default=_server_dir / "config.json")
    args = parser.parse_args()

    cfg = _load_config(args.config)

    print("PhaseForge Studio")
    print(f"  config : {args.config}")
    print(f"  path1  : {cfg.get('path1')}")
    print(f"  path2  : {cfg.get('path2')}")
    print(f"  http://localhost:{args.port}")
    print()

    StudioHandler.config_path = args.config
    StudioHandler.cfg = cfg

    # Register universal file browser roots from config
    _root_keys = {
        "mf": "path1",
        "pf": "pf_workdir",
        "blade": "blade_path1",
        "paipai": "paipai_workdir",
        "orchid": "orchid_data_dir",
    }
    for label, cfg_key in _root_keys.items():
        raw = cfg.get(cfg_key, "")
        if raw:
            p = Path(raw).expanduser().resolve()
            if p.exists():
                register_root(label, p)
                print(f"  fs root [{label:7s}]: {p}")

    # Scan for projects in known directories
    project_roots = [cfg.get("path1", ""), cfg.get("blade_path1", ""), cfg.get("pf_workdir", "")]
    scan_dirs = [Path(r).expanduser().resolve().parent for r in project_roots if r]
    _project_registry.scan(scan_dirs)
    if _project_registry.list_projects():
        print(f"  projects: {len(_project_registry.list_projects())} found")

    server = ThreadingHTTPServer(("", args.port), StudioHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
