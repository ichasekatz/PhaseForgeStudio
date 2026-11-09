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
import json
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

# _job_counter is mutated by the handler; keep a module-level reference.
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
from phaseforge_studio.config import _server_dir  # noqa: E402


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

        elif path.startswith("/files/"):
            rel = unquote(path[len("/files/") :])
            full = _resolve(self.cfg, "path1") / rel
            if not full.is_file():
                self._json({"error": "not found"}, 404)
                return
            ext = full.suffix.lower()
            mime_map = {".tdb": "text/plain", ".png": "image/png", ".gif": "image/gif", ".json": "application/json"}
            self._serve_file(full, mime_map.get(ext, "application/octet-stream"))

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
