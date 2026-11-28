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
# Ensure venv packages (orchid-mcp, sage_mcp, etc.) and editable installs
# (MaterialsFramework, PhaseForgePlus) are importable regardless of which
# Python launched the server.
# ---------------------------------------------------------------------------
_gui_dir = Path(__file__).parent
_venv_sp = _gui_dir / ".venv" / "lib" / "python3.12" / "site-packages"
if _venv_sp.exists():
    _vs = str(_venv_sp)
    if _vs not in sys.path:
        sys.path.insert(0, _vs)
    # Process .pth files the site module may have skipped
    import site as _site
    _site.addsitedir(_vs)

for _src in [
    _gui_dir / "MaterialsFramework" / "src",
    _gui_dir / "PhaseForgePlus" / "src",
]:
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
from phaseforge_studio.pfp_adapter import (  # noqa: E402
    PfpJob,
    cancel_pfp,
    check_pfp_installed,
    launch_pfp,
    pfp_install_hint,
    pfp_status,
    supported_methods as _pfp_methods,
)
from phaseforge_studio.benchmark_adapter import (  # noqa: E402
    cancel_benchmark,
    create_and_launch_benchmark,
    delete_benchmark,
    get_benchmark_status,
    list_benchmarks,
)
from phaseforge_studio.benchmark_templates import list_templates, apply_template  # noqa: E402
from phaseforge_studio.benchmark_report import build_json_export, build_text_report  # noqa: E402
from phaseforge_studio.deps_manager import all_status as deps_all_status, install_package as deps_install, check_py_status as _deps_check_py  # noqa: E402
from phaseforge_studio.pipeline_maker import (  # noqa: E402
    STEP_TYPES as pipeline_step_types,
    cancel_pipeline,
    get_pipeline_status,
    start_pipeline,
)
from phaseforge_studio.paipai import set_paipai_override  # noqa: E402
from phaseforge_studio.sage_adapter import (  # noqa: E402
    check_sage_installed,
    check_model_guide_installed,
    sage_install_hint,
    model_library,
    model_search,
    model_validate,
    model_audit,
    model_recommend,
    model_plan,
    model_compare,
    list_protocols,
    get_protocol,
    get_steps,
    get_step,
    validate_document,
    verify_inputs,
    get_dashboard,
    get_evidence_manifest,
    plan_reproduction,
    start_step,
    step_status,
    compare_outputs,
    get_open_questions,
    compute_ids,
    validate_id,
)

_pfp_job = PfpJob()

# ── Async install job registry ────────────────────────────────────────────────
_install_jobs: dict[str, dict] = {}  # job_id → {status, result}
_install_lock = threading.Lock()
_startup_jobs: dict[str, dict] = {}  # pkg_key → {job_id, label}


def _run_install_job(
    job_id: str, key: str, cfg: dict, override_spec: str | None = None
) -> None:
    result = deps_install(key, cfg, override_spec)
    with _install_lock:
        _install_jobs[job_id]["status"] = "done"
        _install_jobs[job_id]["result"] = result


def _auto_install_on_startup(cfg: dict) -> None:
    """Install missing installable packages in background threads on server start."""
    from phaseforge_studio.deps_manager import check_py_status as _check
    missing = [p for p in _check(cfg) if not p["available"] and p["installable"]]
    for pkg in missing:
        job_id = str(uuid.uuid4())[:8]
        with _install_lock:
            _install_jobs[job_id] = {"status": "running", "result": None}
            _startup_jobs[pkg["key"]] = {"job_id": job_id, "label": pkg["label"]}
        t = threading.Thread(
            target=_run_install_job, args=(job_id, pkg["key"], cfg), daemon=True
        )
        t.start()
        print(f"  auto-installing: {pkg['label']} (job {job_id})")


_files_dir = _server_dir / "Files"


def _auto_workdir(workspace: str) -> Path:
    """Return and create an auto-generated job directory under GUI/Files/<workspace>/."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    p = _files_dir / workspace / f"job_{ts}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _fmt_or_blank(value: float | None, digits: int = 6) -> str:
    """Format a float for CSV export, returning empty string for None."""
    if value is None:
        return ""
    return f"{value:.{digits}g}"


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

        # ── PAIPAI status (GET) ───────────────────────────────────────────────
        elif path == "/api/paipai_status":
            from phaseforge_studio.paipai import _paipai as _pp, get_paipai_progress
            wd = _pp.workdir
            progress: dict[str, Any] = {}
            if wd and wd.is_dir():
                try:
                    progress = get_paipai_progress(wd)
                except Exception:
                    pass
            self._json({
                "state": _pp.state,
                "installed": check_paipai_installed(),
                "log_tail": _pp.log[-60:],
                "progress": progress,
            })

        # ── Dependency status / install ───────────────────────────────────────
        elif path == "/api/deps/status":
            self._json(deps_all_status(self.cfg))

        elif path == "/api/deps/install_status":
            job_id = qs.get("job_id", [""])[0]
            with _install_lock:
                job = _install_jobs.get(job_id)
            if job is None:
                self._json({"error": "unknown job"}, 404)
                return
            self._json({"job_id": job_id, "status": job["status"], "result": job["result"]})

        elif path == "/api/auto_path":
            workspace = qs.get("workspace", [""])[0] or "misc"
            p = _files_dir / workspace
            self._json({"path": str(p), "workspace": workspace})

        elif path == "/api/deps/startup_jobs":
            with _install_lock:
                out = {}
                for key, info in _startup_jobs.items():
                    jid = info["job_id"]
                    job = _install_jobs.get(jid, {})
                    out[key] = {
                        "job_id": jid,
                        "label": info["label"],
                        "status": job.get("status", "unknown"),
                        "result": job.get("result"),
                    }
            self._json(out)

        # ── Pipeline Maker GET endpoints ─────────────────────────────────────
        elif path == "/api/pipeline/steps":
            self._json({"steps": pipeline_step_types})
        elif path == "/api/pipeline/status":
            self._json(get_pipeline_status())

        # ── ORCHID GET endpoints (query-string based) ────────────────────────
        elif path == "/api/orchid/status":
            self._json({
                "mcp_available": check_orchid_mcp(),
                "hint": orchid_install_hint() if not check_orchid_mcp() else None,
            })

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

        # ------------------------------------------------------------------
        # ORCHID-SAGE routes
        # ------------------------------------------------------------------

        elif path == "/api/sage/status":
            self._json({
                "sage_installed": check_sage_installed(),
                "model_guide_installed": check_model_guide_installed(),
                "hint": sage_install_hint(),
            })

        elif path == "/api/sage/model_library":
            try:
                self._json(model_library())
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/model_search":
            text = qs.get("text", [""])[0]
            topic = qs.get("topic", [None])[0]
            try:
                self._json(model_search(text=text, topic=topic))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/model_validate":
            body = self._body_json()
            spec = body.get("spec")
            if not isinstance(spec, dict):
                self._json({"error": "spec object required"}, 400)
                return
            try:
                errors = model_validate(spec)
                self._json({"valid": not errors, "errors": errors})
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/model_audit":
            body = self._body_json()
            spec = body.get("spec")
            if not isinstance(spec, dict):
                self._json({"error": "spec object required"}, 400)
                return
            try:
                self._json(model_audit(spec))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/model_recommend":
            body = self._body_json()
            spec = body.get("spec")
            if not isinstance(spec, dict):
                self._json({"error": "spec object required"}, 400)
                return
            try:
                self._json(model_recommend(spec))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/model_plan":
            body = self._body_json()
            spec = body.get("spec")
            if not isinstance(spec, dict):
                self._json({"error": "spec object required"}, 400)
                return
            limit = int(body.get("limit", 20))
            try:
                self._json(model_plan(spec, limit=limit))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/model_compare":
            body = self._body_json()
            left, right = body.get("left"), body.get("right")
            if not isinstance(left, dict) or not isinstance(right, dict):
                self._json({"error": "left and right spec objects required"}, 400)
                return
            try:
                self._json(model_compare(left, right))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/list_protocols":
            try:
                self._json(list_protocols())
            except Exception as exc:
                self._json({"error": str(exc), "protocols": []})

        elif path == "/api/sage/get_protocol":
            ref = qs.get("ref", [""])[0]
            if not ref:
                self._json({"error": "ref required"}, 400)
                return
            fields = qs.get("fields", ["summary"])[0]
            try:
                self._json(get_protocol(ref, fields=fields))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/get_steps":
            ref = qs.get("ref", [""])[0]
            if not ref:
                self._json({"error": "ref required"}, 400)
                return
            section = qs.get("section", [None])[0]
            try:
                self._json(get_steps(ref, section=section))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/get_step":
            ref = qs.get("ref", [""])[0]
            step_id = qs.get("step_id", [""])[0]
            if not ref or not step_id:
                self._json({"error": "ref and step_id required"}, 400)
                return
            try:
                self._json(get_step(ref, step_id))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/validate_document":
            body = self._body_json()
            doc = body.get("document")
            try:
                self._json(validate_document(document=doc))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/verify_inputs":
            body = self._body_json()
            ref = body.get("ref", "")
            if not ref:
                self._json({"error": "ref required"}, 400)
                return
            try:
                self._json(verify_inputs(ref, detail=bool(body.get("detail", False))))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/dashboard":
            assessment = qs.get("assessment", [""])[0]
            if not assessment:
                self._json({"error": "assessment required"}, 400)
                return
            try:
                self._json(get_dashboard(
                    assessment,
                    section=qs.get("section", [None])[0],
                    max_items=int(qs.get("max_items", ["50"])[0]),
                ))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/evidence_manifest":
            assessment = qs.get("assessment", [""])[0]
            if not assessment:
                self._json({"error": "assessment required"}, 400)
                return
            try:
                self._json(get_evidence_manifest(
                    assessment,
                    kind=qs.get("kind", [None])[0],
                    limit=int(qs.get("limit", ["50"])[0]),
                    offset=int(qs.get("offset", ["0"])[0]),
                ))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/plan_reproduction":
            body = self._body_json()
            ref = body.get("ref", "")
            if not ref:
                self._json({"error": "ref required"}, 400)
                return
            try:
                self._json(plan_reproduction(
                    ref,
                    run_root=body.get("run_root"),
                    python=body.get("python"),
                    pfp=body.get("pfp"),
                    nproc=int(body.get("nproc", 4)),
                ))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/start_step":
            body = self._body_json()
            ref = body.get("ref", "")
            step_id = body.get("step_id", "")
            run_root = body.get("run_root", "")
            if not ref or not step_id or not run_root:
                self._json({"error": "ref, step_id, and run_root required"}, 400)
                return
            try:
                self._json(start_step(
                    ref,
                    step_id,
                    run_root,
                    confirm=bool(body.get("confirm", False)),
                    allow_long=bool(body.get("allow_long", False)),
                    env_extra=body.get("env_extra"),
                ))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/step_status":
            body = self._body_json()
            ref = body.get("ref", "")
            run_root = body.get("run_root", "")
            if not ref or not run_root:
                self._json({"error": "ref and run_root required"}, 400)
                return
            try:
                self._json(step_status(
                    ref,
                    run_root,
                    step_id=body.get("step_id"),
                    wait_s=float(body.get("wait_s", 0)),
                ))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/compare_outputs":
            body = self._body_json()
            ref = body.get("ref", "")
            run_root = body.get("run_root", "")
            if not ref or not run_root:
                self._json({"error": "ref and run_root required"}, 400)
                return
            try:
                self._json(compare_outputs(ref, run_root, python=body.get("python")))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/open_questions":
            ids = qs.get("ids", None)
            try:
                self._json(get_open_questions(ids=ids if ids else None))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/compute_ids":
            body = self._body_json()
            try:
                self._json(compute_ids(
                    pid=body.get("pid"),
                    locator=body.get("locator"),
                    state=body.get("state"),
                    observation_key=body.get("observation_key"),
                ))
            except Exception as exc:
                self._json({"error": str(exc)})

        elif path == "/api/sage/validate_id":
            orchid_id = qs.get("id", [""])[0]
            if not orchid_id:
                self._json({"error": "id required"}, 400)
                return
            try:
                self._json(validate_id(orchid_id))
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

        elif path == "/api/pfp_status":
            self._json(pfp_status(_pfp_job))

        elif path == "/api/pfp_methods":
            self._json({"methods": _pfp_methods, "installed": check_pfp_installed()})

        elif path == "/api/benchmark/list":
            self._json({"benchmarks": list_benchmarks()})

        elif path == "/api/benchmark/templates":
            self._json({"templates": list_templates()})

        elif path.startswith("/api/benchmark/template/"):
            tmpl_name = path[len("/api/benchmark/template/"):]
            try:
                result = apply_template(tmpl_name)
                self._json({"ok": True, "config": result})
            except KeyError as exc:
                self._json({"error": str(exc)}, 404)

        elif path.startswith("/api/benchmark/status/"):
            bm_id = path[len("/api/benchmark/status/"):]
            status = get_benchmark_status(bm_id)
            if status is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(status)

        elif path.startswith("/api/benchmark/report/"):
            bm_id = path[len("/api/benchmark/report/"):]
            status = get_benchmark_status(bm_id)
            if status is None:
                self._json({"error": "not found"}, 404)
            else:
                text = build_text_report(status)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="benchmark_{bm_id}.txt"')
                self.end_headers()
                self.wfile.write(text.encode())

        elif path.startswith("/api/benchmark/export_json/"):
            bm_id = path[len("/api/benchmark/export_json/"):]
            status = get_benchmark_status(bm_id)
            if status is None:
                self._json({"error": "not found"}, 404)
            else:
                export = build_json_export(
                    status,
                    energy_result=status.get("energy_result"),
                    stability_result=status.get("stability_result"),
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", f'attachment; filename="benchmark_{bm_id}.json"')
                self.end_headers()
                import json as _json
                self.wfile.write(_json.dumps(export, indent=2).encode())

        elif path.startswith("/api/benchmark/csv/"):
            bm_id = path[len("/api/benchmark/csv/"):]
            status = get_benchmark_status(bm_id)
            if status is None:
                self._json({"error": "not found"}, 404)
            else:
                import csv as _csv
                import io as _io
                buf = _io.StringIO()
                writer = _csv.writer(buf)
                writer.writerow([
                    "mlip", "state", "elapsed_s", "energy_mae", "energy_rmse",
                    "force_mae", "f1", "accuracy", "precision", "recall",
                    "jaccard", "mad_t", "rmsd_t", "n_boundaries",
                    "composite_score", "pareto",
                ])
                ranking_map = {r.get("mlip", ""): r for r in (status.get("ranking") or [])}
                for mlip, job in status.get("mlip_jobs", {}).items():
                    m = job.get("metrics") or {}
                    cls = m.get("classification", {}) if m.get("available") else {}
                    bnd = m.get("boundary", {}) if m.get("available") else {}
                    em = (status.get("energy_result") or {}).get("mlips", {}).get(mlip, {})
                    rk = ranking_map.get(mlip, {})
                    writer.writerow([
                        mlip,
                        job.get("state", ""),
                        _fmt_or_blank(job.get("elapsed_s")),
                        _fmt_or_blank(em.get("energy_mae")),
                        _fmt_or_blank(em.get("energy_rmse")),
                        _fmt_or_blank(em.get("force_mae")),
                        _fmt_or_blank(cls.get("f1")),
                        _fmt_or_blank(cls.get("accuracy")),
                        _fmt_or_blank(cls.get("precision")),
                        _fmt_or_blank(cls.get("recall")),
                        _fmt_or_blank(cls.get("jaccard")),
                        _fmt_or_blank(bnd.get("mad_t")),
                        _fmt_or_blank(bnd.get("rmsd_t")),
                        bnd.get("n_boundaries_matched", ""),
                        _fmt_or_blank(rk.get("composite_score")),
                        str(rk.get("pareto", False)).lower(),
                    ])
                csv_text = buf.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="benchmark_{bm_id}.csv"')
                self.end_headers()
                self.wfile.write(csv_text.encode())

        elif path.startswith("/benchmark_file/"):
            # Serve files from benchmark run directories.
            # Format: /benchmark_file/<benchmark_id>/<mlip>/<filename>
            rel = unquote(path[len("/benchmark_file/"):])
            parts = rel.split("/", 2)
            if len(parts) < 3:
                self._json({"error": "invalid path"}, 400)
                return
            bm_id, mlip_raw, filename = parts[0], parts[1], parts[2]
            bm_workdir_str = self.cfg.get("benchmark_workdir", "")
            bm_base = (
                Path(bm_workdir_str).expanduser().resolve() / "benchmarks"
                if bm_workdir_str
                else _files_dir / "benchmark"
            )
            target: Path | None = None
            if bm_base.is_dir():
                for d in bm_base.iterdir():
                    if bm_id in d.name and d.is_dir():
                        candidate = d / "mlips" / mlip_raw / filename
                        if candidate.is_file():
                            target = candidate
                            break
                        # Also check phase_diagrams/
                        candidate2 = d / "phase_diagrams" / filename
                        if candidate2.is_file():
                            target = candidate2
                            break
            if target is None or not target.is_file():
                self._json({"error": "not found"}, 404)
                return
            ext = target.suffix.lower()
            mime = {".png": "image/png", ".tdb": "text/plain", ".json": "application/json"}.get(ext, "application/octet-stream")
            self._serve_file(target, mime)

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
            if workspace not in ("pf", "mf", "phaseforge", "blade", "paipai", "orchid", "pfp", "benchmark", "sage", "setup", "pipeline"):
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
            checkrelax = bool(body.get("checkrelax", False))
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
            if checkrelax:
                cmd.append("-checkrelax")
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

        # ── Dependency install (POST) ─────────────────────────────────────────
        elif path == "/api/deps/install":
            body = self._body_json()
            key = body.get("key", "")
            local_path = (body.get("local_path") or "").strip() or None
            if not key:
                self._json({"error": "key required"}, 400)
                return
            import uuid as _uuid
            job_id = str(_uuid.uuid4())[:8]
            with _install_lock:
                _install_jobs[job_id] = {"status": "running", "result": None}
            t = threading.Thread(
                target=_run_install_job,
                args=(job_id, key, dict(self.cfg), local_path),
                daemon=True,
            )
            t.start()
            self._json({"ok": True, "job_id": job_id, "status": "running"})

        elif path == "/api/deps/set_source":
            body = self._body_json()
            key = body.get("key", "")
            local_path = (body.get("local_path") or "").strip()
            if not key:
                self._json({"error": "key required"}, 400)
                return
            from phaseforge_studio.deps_manager import _PY_PACKAGES as _pkgs
            meta = _pkgs.get(key)
            src_key = meta.get("source_key") if meta else None
            if not src_key:
                # No source_key — store under key_src convention for pip spec override
                src_key = f"{key}_pip_spec_override"
            # Update in-memory config
            self.cfg[src_key] = local_path
            StudioHandler.cfg[src_key] = local_path
            # Persist to config.json
            try:
                cfg_data: dict = {}
                if self.config_path.exists():
                    cfg_data = json.loads(self.config_path.read_text())
                cfg_data[src_key] = local_path
                self.config_path.write_text(json.dumps(cfg_data, indent=2))
                self._json({"ok": True, "src_key": src_key, "value": local_path})
            except Exception as exc:
                self._json({"error": str(exc)})

        # ── Pipeline Maker POST endpoints ────────────────────────────────────
        elif path == "/api/pipeline/start":
            body = json.loads(self._read_body())
            steps = body.get("steps", [])
            if not steps:
                self._json({"error": "steps required"}, 400)
                return
            run_id = start_pipeline(steps)
            self._json({"ok": True, "run_id": run_id})
        elif path == "/api/pipeline/cancel":
            self._json(cancel_pipeline())

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
                workdir_str = str(_auto_workdir("paipai"))
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

        elif path == "/api/orchid/compute_diagram":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            tdb_content = body.get("tdb_content", "")
            tdb_path = body.get("tdb_path", "")
            elements = body.get("elements", [])
            if not elements or len(elements) < 2:
                self._json({"error": "Need at least 2 elements"}, 400)
                return
            try:
                from phaseforge_studio.diagram_utils import (
                    compute_binary_diagram,
                    compute_diagram_from_file,
                )
                if tdb_content:
                    data = compute_binary_diagram(
                        tdb_content, elements,
                        T_min=float(body.get("T_min", 300)),
                        T_max=float(body.get("T_max", 2000)),
                        n_T=int(body.get("n_T", 60)),
                        n_X=int(body.get("n_X", 50)),
                    )
                elif tdb_path:
                    data = compute_diagram_from_file(
                        tdb_path, elements,
                        T_min=float(body.get("T_min", 300)),
                        T_max=float(body.get("T_max", 2000)),
                        n_T=int(body.get("n_T", 60)),
                        n_X=int(body.get("n_X", 50)),
                    )
                else:
                    data = {"error": "tdb_content or tdb_path required"}
                self._json(data)
            except Exception as exc:
                self._json({"error": str(exc)})

        # ── BLADE run endpoint ───────────────────────────────────────────────
        elif path == "/api/blade/run":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            blade_path1 = body.get("blade_path1", "").strip()
            if not blade_path1:
                self._json({"error": "blade_path1 (BLADE root path) required"}, 400)
                return
            custom_toml = body.get("blade_toml", "") or ""
            if custom_toml:
                self._json({
                    "message": f"BLADE configured with custom TOML: {custom_toml}",
                    "run_cmd": f"cd {blade_path1} && pixi run python examples/tdb_gen.py {custom_toml}",
                })
                return
            # Generate TOML from form fields
            elements = body.get("elements", [])
            lattices = body.get("lattices", ["FCC_A1", "BCC_A2"])
            model = body.get("model", "GRACE-2L-OMAT")
            device = body.get("device", "cpu")
            fmax = float(body.get("fmax", 0.05))
            T_min = int(body.get("T_min", 298))
            T_max = int(body.get("T_max", 6000))
            T_step = int(body.get("T_step", 10))
            if not elements:
                self._json({"error": "elements required"}, 400)
                return
            el_list = "[" + ", ".join(f'"{e}"' for e in elements) + "]"
            lat_list = "[" + ", ".join(f'"{l}"' for l in lattices) + "]"
            toml_content = f"""# Generated by PhaseForge Studio
[system]
elements = {el_list}
lattices = {lat_list}

[calculator]
model = "{model}"
device = "{device}"
fmax = {fmax}

[calphad]
T_min = {T_min}
T_max = {T_max}
T_step = {T_step}
"""
            import pathlib
            blade_root = pathlib.Path(blade_path1).expanduser()
            toml_out = blade_root / "pfs_generated.toml"
            try:
                toml_out.write_text(toml_content)
                toml_path_str = str(toml_out)
            except OSError:
                toml_path_str = "(could not write — check BLADE Root path)"
            run_cmd = f"cd {blade_path1} && pixi run python examples/tdb_gen.py {toml_path_str}"
            self._json({
                "message": f"TOML generated at {toml_path_str}",
                "toml_path": toml_path_str,
                "toml_content": toml_content,
                "run_cmd": run_cmd,
            })

        # ── PhaseForgePlus endpoints ─────────────────────────────────────────
        elif path == "/api/pfp_run":
            if _pfp_job.state == "running":
                self._json({"error": "PFP optimisation already running"}, 409)
                return
            if not check_pfp_installed():
                self._json({"error": pfp_install_hint()}, 503)
                return
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            tdb_path = body.get("tdb_path") or self.cfg.get("pfp_tdb_path", "")
            zpf_dir = body.get("zpf_dir") or self.cfg.get("pfp_zpf_dir", "")
            if not tdb_path or not zpf_dir:
                self._json({"error": "tdb_path and zpf_dir are required"}, 400)
                return
            if not Path(tdb_path).expanduser().is_file():
                self._json({"error": f"TDB not found: {tdb_path}"}, 400)
                return
            if not Path(zpf_dir).expanduser().is_dir():
                self._json({"error": f"ZPF directory not found: {zpf_dir}"}, 400)
                return
            points_raw = body.get("points", self.cfg.get("pfp_points", [0, 1, 2, 3, 4]))
            points = [int(p) for p in points_raw]
            pressure = float(body.get("pressure", self.cfg.get("pfp_pressure", 101325.0)))
            temperature = float(body.get("temperature", self.cfg.get("pfp_temperature", 298.15)))
            method = str(body.get("method", self.cfg.get("pfp_method", "CG")))
            tol_raw = body.get("tol", self.cfg.get("pfp_tol"))
            tol = float(tol_raw) if tol_raw is not None else None
            maxiter_raw = body.get("maxiter", self.cfg.get("pfp_maxiter"))
            maxiter = int(maxiter_raw) if maxiter_raw is not None else None
            output_path = body.get("output_path", self.cfg.get("pfp_output_path", ""))
            launch_pfp(
                _pfp_job,
                tdb_path=str(Path(tdb_path).expanduser()),
                zpf_dir=str(Path(zpf_dir).expanduser()),
                points=points,
                pressure=pressure,
                temperature=temperature,
                method=method,
                tol=tol,
                maxiter=maxiter,
                output_path=str(Path(output_path).expanduser()) if output_path else "",
            )
            self._json({"ok": True, "method": method, "n_points": len(points)})

        elif path == "/api/pfp_stop":
            cancel_pfp(_pfp_job)
            self._json({"ok": True})

        elif path == "/api/pfp_initial_values":
            if not check_pfp_installed():
                self._json({"error": pfp_install_hint()}, 503)
                return
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            tdb_path = body.get("tdb_path", "")
            if not tdb_path or not Path(tdb_path).expanduser().is_file():
                self._json({"error": "tdb_path required and must exist"}, 400)
                return
            try:
                from espei.utils import database_symbols_to_fit, unpack_piecewise
                from phaseforgeplus.io import load_tdb
                db = load_tdb(str(Path(tdb_path).expanduser()))
                symbols = database_symbols_to_fit(db)
                values = [float(unpack_piecewise(db.symbols[s])) for s in symbols]
                self._json({"symbols": list(symbols), "initial_values": values})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

        elif path == "/api/pfp_phase_diagram":
            # Generate before/after phase diagrams from a fitted TDB
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            tdb_path_str = body.get("tdb_path", "")
            if not tdb_path_str:
                self._json({"error": "tdb_path required"}, 400)
                return
            tdb_path = Path(tdb_path_str).expanduser().resolve()
            if not tdb_path.is_file():
                self._json({"error": f"TDB not found: {tdb_path}"}, 400)
                return
            t_min = float(body.get("t_min", 300.0))
            t_max = float(body.get("t_max", 3000.0))
            try:
                pngs = _phase_diagram_from_tdb(tdb_path, t_min=t_min, t_max=t_max)
                self._json({"ok": True, "pngs": [str(p) for p in pngs]})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

        # ── PhaseForge additional commands ───────────────────────────────────
        elif path == "/api/pf_relax":
            # MLIPrelax: relax structures in workdir using MLIP
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            mlip = body.get("mlip", "")
            model = body.get("model", "")
            if not mlip or not model:
                self._json({"error": "mlip and model required"}, 400)
                return
            workdir_str = body.get("workdir", "") or self.cfg.get("pf_workdir", "")
            workdir = Path(workdir_str).expanduser().resolve() if workdir_str else None
            if workdir and not workdir.is_dir():
                self._json({"error": f"workdir not found: {workdir}"}, 400)
                return
            cmd = ["MLIPrelax", f"-mlip={mlip}", f"-model={model}"]
            _pf.log = []
            _pf.state = "running"
            try:
                _pf.proc = subprocess.Popen(
                    cmd,
                    cwd=str(workdir) if workdir else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError:
                _pf.state = "error"
                self._json({"error": "MLIPrelax not found on PATH"}, 500)
                return
            except OSError as exc:
                _pf.state = "error"
                self._json({"error": str(exc)}, 500)
                return

            def _stream_pf(proc: subprocess.Popen) -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    _pf.log.append(line.rstrip("\n"))
                proc.wait()
                _pf.state = "done" if proc.returncode == 0 else "error"

            threading.Thread(target=_stream_pf, args=(_pf.proc,), daemon=True).start()
            self._json({"ok": True, "command": " ".join(cmd)})

        elif path == "/api/pf_calc":
            # MLIPcalc: single-point energy calculations in workdir
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            mlip = body.get("mlip", "")
            model = body.get("model", "")
            if not mlip or not model:
                self._json({"error": "mlip and model required"}, 400)
                return
            workdir_str = body.get("workdir", "") or self.cfg.get("pf_workdir", "")
            workdir = Path(workdir_str).expanduser().resolve() if workdir_str else None
            if workdir and not workdir.is_dir():
                self._json({"error": f"workdir not found: {workdir}"}, 400)
                return
            cmd = ["MLIPcalc", f"-mlip={mlip}", f"-model={model}"]
            _pf.log = []
            _pf.state = "running"
            try:
                _pf.proc = subprocess.Popen(
                    cmd,
                    cwd=str(workdir) if workdir else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError:
                _pf.state = "error"
                self._json({"error": "MLIPcalc not found on PATH"}, 500)
                return
            except OSError as exc:
                _pf.state = "error"
                self._json({"error": str(exc)}, 500)
                return
            threading.Thread(target=_stream_pf, args=(_pf.proc,), daemon=True).start()
            self._json({"ok": True, "command": " ".join(cmd)})

        elif path == "/api/pf_runstruct":
            # runstruct_MLIP: evaluate structures using MLIP, optionally static
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            mlip = body.get("mlip", "")
            model = body.get("model", "")
            if not mlip or not model:
                self._json({"error": "mlip and model required"}, 400)
                return
            workdir_str = body.get("workdir", "") or self.cfg.get("pf_workdir", "")
            workdir = Path(workdir_str).expanduser().resolve() if workdir_str else None
            if workdir and not workdir.is_dir():
                self._json({"error": f"workdir not found: {workdir}"}, 400)
                return
            cmd = ["runstruct_MLIP", f"-mlip={mlip}", f"-model={model}"]
            if body.get("static"):
                cmd.append("-static")
            if body.get("checkrelaxcutoff"):
                cmd.append(f"-checkrelaxcutoff={body['checkrelaxcutoff']}")
            _pf.log = []
            _pf.state = "running"
            try:
                _pf.proc = subprocess.Popen(
                    cmd,
                    cwd=str(workdir) if workdir else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError:
                _pf.state = "error"
                self._json({"error": "runstruct_MLIP not found on PATH"}, 500)
                return
            except OSError as exc:
                _pf.state = "error"
                self._json({"error": str(exc)}, 500)
                return
            threading.Thread(target=_stream_pf, args=(_pf.proc,), daemon=True).start()
            self._json({"ok": True, "command": " ".join(cmd)})

        elif path == "/api/pf_extract":
            # extract_MLIP: extract energies from CONTCAR/force_temp.out in workdir
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            workdir_str = body.get("workdir", "") or self.cfg.get("pf_workdir", "")
            workdir = Path(workdir_str).expanduser().resolve() if workdir_str else None
            if not workdir or not workdir.is_dir():
                self._json({"error": "workdir required and must exist"}, 400)
                return
            cmd = ["extract_MLIP"]
            _pf.log = []
            _pf.state = "running"
            try:
                _pf.proc = subprocess.Popen(
                    cmd,
                    cwd=str(workdir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError:
                _pf.state = "error"
                self._json({"error": "extract_MLIP not found on PATH"}, 500)
                return
            except OSError as exc:
                _pf.state = "error"
                self._json({"error": str(exc)}, 500)
                return
            threading.Thread(target=_stream_pf, args=(_pf.proc,), daemon=True).start()
            self._json({"ok": True, "command": " ".join(cmd)})

        elif path == "/api/pf_md":
            # MLIPmd: molecular dynamics run using MLIP
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            mlip = body.get("mlip", "")
            model = body.get("model", "")
            temperature = body.get("temperature", "")
            if not mlip or not model or not temperature:
                self._json({"error": "mlip, model, and temperature required"}, 400)
                return
            workdir_str = body.get("workdir", "") or self.cfg.get("pf_workdir", "")
            workdir = Path(workdir_str).expanduser().resolve() if workdir_str else None
            if workdir and not workdir.is_dir():
                self._json({"error": f"workdir not found: {workdir}"}, 400)
                return
            cmd = ["MLIPmd", f"-mlip={mlip}", f"-model={model}", f"-temp={temperature}"]
            if body.get("norun"):
                cmd.append("-nr")
            _pf.log = []
            _pf.state = "running"
            try:
                _pf.proc = subprocess.Popen(
                    cmd,
                    cwd=str(workdir) if workdir else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError:
                _pf.state = "error"
                self._json({"error": "MLIPmd not found on PATH"}, 500)
                return
            except OSError as exc:
                _pf.state = "error"
                self._json({"error": str(exc)}, 500)
                return
            threading.Thread(target=_stream_pf, args=(_pf.proc,), daemon=True).start()
            self._json({"ok": True, "command": " ".join(cmd)})

        elif path == "/api/pf_liquid":
            # MLIPliquid: liquid-state calculations using MLIP
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            mlip = body.get("mlip", "")
            model = body.get("model", "")
            dt = body.get("dt", "")  # temperature offset
            if not mlip or not model or not dt:
                self._json({"error": "mlip, model, and dt (temperature offset) required"}, 400)
                return
            workdir_str = body.get("workdir", "") or self.cfg.get("pf_workdir", "")
            workdir = Path(workdir_str).expanduser().resolve() if workdir_str else None
            if workdir and not workdir.is_dir():
                self._json({"error": f"workdir not found: {workdir}"}, 400)
                return
            cmd = ["MLIPliquid", f"-mlip={mlip}", f"-model={model}", f"-dt={dt}"]
            if body.get("norun"):
                cmd.append("-nr")
            if body.get("lammps"):
                cmd.append("-LAMMPS")
            _pf.log = []
            _pf.state = "running"
            try:
                _pf.proc = subprocess.Popen(
                    cmd,
                    cwd=str(workdir) if workdir else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError:
                _pf.state = "error"
                self._json({"error": "MLIPliquid not found on PATH"}, 500)
                return
            except OSError as exc:
                _pf.state = "error"
                self._json({"error": str(exc)}, 500)
                return
            threading.Thread(target=_stream_pf, args=(_pf.proc,), daemon=True).start()
            self._json({"ok": True, "command": " ".join(cmd)})

        elif path == "/api/pf_lammps":
            # MLIPlammps: LAMMPS-based calculations using MLIP
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            mlip = body.get("mlip", "")
            model = body.get("model", "")
            temperature = body.get("temperature", "")
            if not mlip or not model or not temperature:
                self._json({"error": "mlip, model, and temperature required"}, 400)
                return
            workdir_str = body.get("workdir", "") or self.cfg.get("pf_workdir", "")
            workdir = Path(workdir_str).expanduser().resolve() if workdir_str else None
            if workdir and not workdir.is_dir():
                self._json({"error": f"workdir not found: {workdir}"}, 400)
                return
            cmd = ["MLIPlammps", f"-mlip={mlip}", f"-model={model}", f"-temp={temperature}"]
            if body.get("norun"):
                cmd.append("-nr")
            _pf.log = []
            _pf.state = "running"
            try:
                _pf.proc = subprocess.Popen(
                    cmd,
                    cwd=str(workdir) if workdir else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except FileNotFoundError:
                _pf.state = "error"
                self._json({"error": "MLIPlammps not found on PATH"}, 500)
                return
            except OSError as exc:
                _pf.state = "error"
                self._json({"error": str(exc)}, 500)
                return
            threading.Thread(target=_stream_pf, args=(_pf.proc,), daemon=True).start()
            self._json({"ok": True, "command": " ".join(cmd)})

        elif path == "/api/mf_slab":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "Invalid JSON body"}, 400)
                return
            rel_path: str = body.get("rel_path", "")
            if not rel_path:
                self._json({"error": "rel_path required"}, 400)
                return
            miller_index: list[int] = body.get("miller_index", [1, 0, 0])
            min_slab: float = float(body.get("min_slab_size", 7.0))
            min_vac: float = float(body.get("min_vacuum_size", 15.0))
            center_slab: bool = bool(body.get("center_slab", True))
            in_unit_planes: bool = bool(body.get("in_unit_planes", False))
            max_normal_search: int = int(body.get("max_normal_search", 1))
            reorient: bool = bool(body.get("reorient_lattice", True))

            path1 = Path(_cfg["path1"]).expanduser().resolve()
            struct_path = path1 / rel_path
            if not struct_path.exists():
                self._json({"error": f"File not found: {rel_path}"}, 404)
                return
            try:
                from pymatgen.core import Structure as PmgStructure
                from pymatgen.core.surface import SlabGenerator

                bulk = PmgStructure.from_file(str(struct_path))
                gen = SlabGenerator(
                    bulk,
                    miller_index=miller_index,
                    min_slab_size=min_slab,
                    min_vacuum_size=min_vac,
                    center_slab=center_slab,
                    in_unit_planes=in_unit_planes,
                    max_normal_search=max_normal_search,
                    reorient_lattice=reorient,
                )
                slabs = gen.get_slabs()
                # Write slabs to staging dir and return paths
                slab_dir = struct_path.parent / "slabs" / f"{''.join(str(h) for h in miller_index)}"
                slab_dir.mkdir(parents=True, exist_ok=True)
                out_paths: list[str] = []
                for i, slab in enumerate(slabs):
                    sp = slab_dir / f"slab_{i:03d}.vasp"
                    slab.to(fmt="poscar", filename=str(sp))
                    out_paths.append(str(sp.relative_to(path1)))
                self._json({
                    "ok": True,
                    "miller_index": miller_index,
                    "n_slabs": len(slabs),
                    "slab_paths": out_paths,
                })
            except ImportError:
                self._json({"error": "pymatgen not installed — cannot generate slabs"}, 500)
            except Exception as exc:
                import traceback as tb
                self._json({"error": str(exc), "traceback": tb.format_exc()}, 500)

        elif path == "/api/mf_md":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "Invalid JSON body"}, 400)
                return
            rel_path: str = body.get("rel_path", "")
            if not rel_path:
                self._json({"error": "rel_path required"}, 400)
                return
            steps: int = int(body.get("steps", 100))
            calc_name: str = body.get("calculator", _cfg.get("calculator", "grace"))
            model: str = body.get("model", "")
            device: str = body.get("device", _cfg.get("device", "cpu"))
            ensemble: str = body.get("ensemble", "nvt_nose_hoover")
            temperature: int = int(body.get("temperature", 300))
            timestep: float = float(body.get("timestep", 1.0))
            pressure: float = float(body.get("pressure", 1.0))
            ttime: float = float(body.get("ttime", 10.0))
            interval: int = int(body.get("interval", 1))

            path1 = Path(_cfg["path1"]).expanduser().resolve()
            struct_path = path1 / rel_path
            if not struct_path.exists():
                self._json({"error": f"File not found: {rel_path}"}, 404)
                return

            def _run_mf_md() -> None:
                import sys
                import traceback as tb

                import numpy as np

                from phaseforge_studio.analysis import _json_default

                mf_src = Path(__file__).parent / "MaterialsFramework" / "src"
                if str(mf_src) not in sys.path:
                    sys.path.insert(0, str(mf_src))

                try:
                    from ase.io import read as ase_read

                    atoms = ase_read(str(struct_path))

                    from materialsframework.calculators.registry import get_calculator

                    _device_calcs = {"grace", "mace", "chgnet", "orb", "sevennet", "m3gnet", "mattersim"}
                    calc_kwargs: dict[str, Any] = {
                        "ensemble": ensemble,
                        "timestep": timestep,
                        "temperature": temperature,
                        "pressure": pressure,
                        "ttime": ttime,
                        "interval": interval,
                    }
                    if model:
                        calc_kwargs["model"] = model
                    if device and calc_name in _device_calcs:
                        calc_kwargs["device"] = device

                    calculator = get_calculator(calc_name, **calc_kwargs)
                    result = calculator.run(atoms, steps)

                    # Serialise numpy arrays
                    serialisable: dict[str, Any] = {}
                    for k, v in result.items():
                        if k == "final_structure":
                            try:
                                serialisable[k] = v.as_dict()
                            except AttributeError:
                                serialisable[k] = str(v)
                        elif hasattr(v, "tolist"):
                            serialisable[k] = v.tolist()
                        elif isinstance(v, list) and v and hasattr(v[0], "tolist"):
                            serialisable[k] = [x.tolist() for x in v]
                        else:
                            serialisable[k] = v

                    # Write trajectory XYZ for replay UI
                    traj_rel: str | None = None
                    try:
                        from ase import Atoms as AseAtoms
                        from ase.io import write as ase_write
                        from materialsframework.utils import to_atoms

                        traj_dir = struct_path.parent / "md_trajectories"
                        traj_dir.mkdir(parents=True, exist_ok=True)
                        stem = struct_path.stem
                        traj_path = traj_dir / f"{stem}_{ensemble}_{temperature}K.xyz"
                        # Reconstruct Atoms frames from trajectory data
                        symbols = atoms.get_chemical_symbols()
                        pe_list = result.get("potential_energy", [])
                        pos_list = result.get("forces", [])  # forces shape: (n_frames, n_atoms, 3)
                        # Write via ASE if we have positions; otherwise skip
                        if hasattr(result.get("final_structure"), "as_dict"):
                            # Only write final structure if per-frame positions unavailable
                            final_atoms = to_atoms(result["final_structure"])
                            final_atoms.info["energy"] = float(pe_list[-1]) if pe_list else 0.0
                            ase_write(str(traj_path), final_atoms, format="extxyz")
                            traj_rel = str(traj_path.relative_to(path1))
                    except Exception:
                        pass  # trajectory write failure is non-fatal

                    _mf_md_results["last"] = {
                        "ok": True,
                        "steps": steps,
                        "ensemble": ensemble,
                        "temperature": temperature,
                        "traj_rel": traj_rel,
                        **serialisable,
                    }
                except Exception as exc:
                    _mf_md_results["last"] = {"error": str(exc), "traceback": tb.format_exc()}

            _mf_md_results: dict[str, Any] = {}
            t = threading.Thread(target=_run_mf_md, daemon=True)
            t.start()
            t.join(timeout=float(body.get("timeout", 300)))
            if t.is_alive():
                self._json({"error": "MD timed out — still running in background"}, 202)
                return
            self._json(_mf_md_results.get("last", {"error": "No result"}))

        elif path == "/api/mf_traj":
            # Serve an arbitrary XYZ trajectory file for replay UI
            rel = qs.get("path", [""])[0]
            if not rel:
                self._json({"error": "path query param required"}, 400)
                return
            path1 = Path(_cfg["path1"]).expanduser().resolve()
            traj_path = path1 / rel
            if not traj_path.exists():
                self._json({"error": f"Trajectory not found: {rel}"}, 404)
                return
            try:
                xyz_text = traj_path.read_text(encoding="utf-8", errors="replace")
                self._json({"rel": rel, "xyz": xyz_text})
            except OSError as exc:
                self._json({"error": str(exc)}, 500)

        # ------------------------------------------------------------------ #
        # Stage 3 — new MF tool exposure                                      #
        # ------------------------------------------------------------------ #

        elif path == "/api/mf_sqsgen":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "Invalid JSON body"}, 400)
                return
            composition_dict: dict[str, float] = body.get("composition", {})
            if not composition_dict:
                self._json({"error": "composition dict required, e.g. {\"Al\": 0.5, \"Ni\": 0.5}"}, 400)
                return
            crystal_structure: str = body.get("crystal_structure", "fcc")
            supercell_size: list[int] = body.get("supercell_size", [2, 2, 2])
            cutoff_distance: float = float(body.get("cutoff_distance", 6.0))
            n_structures: int = int(body.get("n_structures", 1))
            try:
                import sys
                mf_src = Path(__file__).parent / "MaterialsFramework" / "src"
                if str(mf_src) not in sys.path:
                    sys.path.insert(0, str(mf_src))
                from pymatgen.core import Composition as PmgComposition
                from materialsframework.tools.sqsgen import SqsGenerator
                comp = PmgComposition(composition_dict)
                gen = SqsGenerator(
                    composition=comp,
                    crystal_structure=crystal_structure,
                    supercell_size=tuple(supercell_size),
                    cutoff_distance=cutoff_distance,
                    n_structures=n_structures,
                )
                result = gen.generate()
                struct = result.get("structure")
                struct_dict = struct.as_dict() if struct and hasattr(struct, "as_dict") else {}
                self._json({
                    "ok": True,
                    "objective": float(result.get("objective", 0.0)),
                    "structure": struct_dict,
                })
            except ImportError as exc:
                self._json({"error": f"Missing dependency: {exc}"}, 500)
            except Exception as exc:
                import traceback as tb
                self._json({"error": str(exc), "traceback": tb.format_exc()}, 500)

        elif path == "/api/mf_stability_map":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "Invalid JSON body"}, 400)
                return
            elements: list[str] = body.get("elements", [])
            if len(elements) < 2:
                self._json({"error": "elements list with at least 2 elements required"}, 400)
                return
            calc_name: str = body.get("calculator", _cfg.get("calculator", "grace"))
            model: str = body.get("model", "")
            device: str = body.get("device", _cfg.get("device", "cpu"))
            step: float = float(body.get("step", 0.1))
            try:
                import sys
                mf_src = Path(__file__).parent / "MaterialsFramework" / "src"
                if str(mf_src) not in sys.path:
                    sys.path.insert(0, str(mf_src))
                from materialsframework.calculators.registry import get_calculator
                from materialsframework.tools.stability_map import StabilityMap
                _device_calcs = {"grace", "mace", "chgnet", "orb", "sevennet", "m3gnet", "mattersim"}
                calc_kwargs: dict[str, Any] = {}
                if model:
                    calc_kwargs["model"] = model
                if device and calc_name in _device_calcs:
                    calc_kwargs["device"] = device
                calculator = get_calculator(calc_name, **calc_kwargs)
                sm = StabilityMap(calculator=calculator, elements=elements, step=step)
                sm.fit()
                self._json({"ok": True, "elements": elements, "step": step})
            except ImportError as exc:
                self._json({"error": f"Missing dependency: {exc}"}, 500)
            except Exception as exc:
                import traceback as tb
                self._json({"error": str(exc), "traceback": tb.format_exc()}, 500)

        elif path == "/api/mf_cluster_expansion":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "Invalid JSON body"}, 400)
                return
            structures_paths: list[str] = body.get("structures", [])
            energies: list[float] = body.get("energies", [])
            if not structures_paths or not energies:
                self._json({"error": "structures (list of rel paths) and energies (list of eV values) required"}, 400)
                return
            calc_name: str = body.get("calculator", _cfg.get("calculator", "grace"))
            model: str = body.get("model", "")
            device: str = body.get("device", _cfg.get("device", "cpu"))
            try:
                import sys
                from ase.io import read as ase_read
                mf_src = Path(__file__).parent / "MaterialsFramework" / "src"
                if str(mf_src) not in sys.path:
                    sys.path.insert(0, str(mf_src))
                from materialsframework.calculators.registry import get_calculator
                from materialsframework.tools.cluster_expansion import ClusterExpansion
                path1 = Path(_cfg["path1"]).expanduser().resolve()
                structures = [ase_read(str(path1 / p)) for p in structures_paths]
                _device_calcs = {"grace", "mace", "chgnet", "orb", "sevennet", "m3gnet", "mattersim"}
                calc_kwargs: dict[str, Any] = {}
                if model:
                    calc_kwargs["model"] = model
                if device and calc_name in _device_calcs:
                    calc_kwargs["device"] = device
                calculator = get_calculator(calc_name, **calc_kwargs)
                ce = ClusterExpansion(calculator=calculator, structures=structures, energies=energies)
                result = ce.fit()
                import numpy as np
                serialisable = {k: (v.tolist() if hasattr(v, "tolist") else float(v) if isinstance(v, (int, float, np.floating)) else str(v)) for k, v in (result or {}).items()}
                self._json({"ok": True, **serialisable})
            except ImportError as exc:
                self._json({"error": f"Missing dependency: {exc}"}, 500)
            except Exception as exc:
                import traceback as tb
                self._json({"error": str(exc), "traceback": tb.format_exc()}, 500)

        elif path == "/api/mf_bond_lattice_parameter":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "Invalid JSON body"}, 400)
                return
            elements: list[str] = body.get("elements", [])
            lattice_parameters: dict[str, float] = body.get("lattice_parameters", {})
            calc_name: str = body.get("calculator", _cfg.get("calculator", "grace"))
            model: str = body.get("model", "")
            device: str = body.get("device", _cfg.get("device", "cpu"))
            if not elements:
                self._json({"error": "elements list required"}, 400)
                return
            try:
                import sys
                import numpy as np
                mf_src = Path(__file__).parent / "MaterialsFramework" / "src"
                if str(mf_src) not in sys.path:
                    sys.path.insert(0, str(mf_src))
                from materialsframework.calculators.registry import get_calculator
                from materialsframework.tools.bond_lattice_parameter import BondLatticeParameter
                _device_calcs = {"grace", "mace", "chgnet", "orb", "sevennet", "m3gnet", "mattersim"}
                calc_kwargs: dict[str, Any] = {}
                if model:
                    calc_kwargs["model"] = model
                if device and calc_name in _device_calcs:
                    calc_kwargs["device"] = device
                calculator = get_calculator(calc_name, **calc_kwargs)
                blp = BondLatticeParameter(calculator=calculator, elements=elements, lattice_parameters=lattice_parameters or None)
                result = blp.fit() if hasattr(blp, "fit") else {}
                serialisable = {k: (v.tolist() if hasattr(v, "tolist") else float(v) if isinstance(v, (int, float, np.floating)) else str(v)) for k, v in (result or {}).items()}
                self._json({"ok": True, **serialisable})
            except ImportError as exc:
                self._json({"error": f"Missing dependency: {exc}"}, 500)
            except Exception as exc:
                import traceback as tb
                self._json({"error": str(exc), "traceback": tb.format_exc()}, 500)

        elif path == "/api/mf_cahn_hilliard":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "Invalid JSON body"}, 400)
                return
            nx: int = int(body.get("nx", 64))
            ny: int = int(body.get("ny", 64))
            dx: float = float(body.get("dx", 1.0))
            dy: float = float(body.get("dy", 1.0))
            dt: float = float(body.get("dt", 0.01))
            n_steps: int = int(body.get("n_steps", 1000))
            kappa: float = float(body.get("kappa", 0.5))
            a: float = float(body.get("a", 1.0))
            mobility: float = float(body.get("mobility", 1.0))
            c0: float = float(body.get("c0", 0.5))
            noise: float = float(body.get("noise", 0.01))
            try:
                import sys
                mf_src = Path(__file__).parent / "MaterialsFramework" / "src"
                if str(mf_src) not in sys.path:
                    sys.path.insert(0, str(mf_src))
                from materialsframework.tools.cahn_hilliard import MaterialParameters, PhaseFieldModel, SimulationGrid
                grid = SimulationGrid(nx=nx, ny=ny, dx=dx, dy=dy)
                mat = MaterialParameters(kappa=kappa, a=a, mobility=mobility, c0=c0, noise=noise)
                model = PhaseFieldModel(grid=grid, material=mat, dt=dt)
                model.run_simulation(plot=False)
                # Return final composition field stats
                import numpy as np
                phi = model.phi if hasattr(model, "phi") else None
                result: dict[str, Any] = {
                    "ok": True,
                    "n_steps": n_steps,
                    "nx": nx,
                    "ny": ny,
                }
                if phi is not None:
                    result["phi_mean"] = float(np.mean(phi))
                    result["phi_std"] = float(np.std(phi))
                    result["phi_min"] = float(np.min(phi))
                    result["phi_max"] = float(np.max(phi))
                self._json(result)
            except ImportError as exc:
                self._json({"error": f"Missing dependency: {exc}"}, 500)
            except Exception as exc:
                import traceback as tb
                self._json({"error": str(exc), "traceback": tb.format_exc()}, 500)

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

        elif path == "/api/benchmark/create":
            try:
                body = json.loads(self._read_body())
            except (json.JSONDecodeError, ValueError):
                self._json({"error": "invalid JSON"}, 400)
                return
            elements = body.get("elements", [])
            mlips = body.get("mlips", [])
            phases = body.get("phases", [])
            workdir_str = body.get("workdir", "") or self.cfg.get("benchmark_workdir", "")
            if not workdir_str:
                workdir_str = str(_auto_workdir("benchmark"))
            if not elements or not mlips or not phases:
                self._json({"error": "elements, mlips, and phases are required"}, 400)
                return
            bm_id = create_and_launch_benchmark(
                elements=elements,
                mlips=mlips,
                phases=phases,
                workdir=workdir_str,
                level=int(body.get("level", 2)),
                t_min=float(body.get("t_min", 300.0)),
                t_max=float(body.get("t_max", 3000.0)),
                t_step=float(body.get("t_step", 100.0)),
                x_step=float(body.get("x_step", 0.02)),
                mode=body.get("mode", "relaxed"),
                reference_tdb=body.get("reference_tdb", "") or self.cfg.get("benchmark_reference_tdb", ""),
                benchmark_mode=body.get("benchmark_mode", "phase_diagram"),
                structures_dir=body.get("structures_dir", ""),
                energy_reference_path=body.get("energy_reference_path", ""),
                device=body.get("device", "cpu"),
            )
            self._json({"ok": True, "benchmark_id": bm_id})

        elif path.startswith("/api/benchmark/cancel/"):
            bm_id = path[len("/api/benchmark/cancel/"):]
            ok = cancel_benchmark(bm_id)
            self._json({"ok": ok})

        elif path.startswith("/api/benchmark/delete/"):
            bm_id = path[len("/api/benchmark/delete/"):]
            ok = delete_benchmark(bm_id)
            self._json({"ok": ok})

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

    # Wire config-specified binary overrides
    set_paipai_override(cfg.get("paipai_binary"))

    # Register universal file browser roots from config
    _root_keys = {
        "mf": "path1",
        "pf": "pf_workdir",
        "pfp": "pfp_tdb_path",  # registered as parent dir of TDB
        "blade": "blade_path1",
        "paipai": "paipai_workdir",
        "orchid": "orchid_data_dir",
        "benchmark": "benchmark_workdir",
    }
    for label, cfg_key in _root_keys.items():
        raw = cfg.get(cfg_key, "")
        if raw:
            p = Path(raw).expanduser().resolve()
            # pfp_tdb_path is a file — register its parent directory
            if label == "pfp" and p.is_file():
                p = p.parent
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
