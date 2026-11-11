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

import phaseforge_studio.job as _job_mod  # noqa: E402
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
            if workspace not in ("pf", "mf", "phaseforge", "blade"):
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

    server = ThreadingHTTPServer(("", args.port), StudioHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
