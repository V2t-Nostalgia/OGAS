from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .service import ObservationService


WEB_ROOT = Path(__file__).with_name("web")


class DashboardHandler(BaseHTTPRequestHandler):
    service: ObservationService
    server_version = "IAGObserveDashboard/1"

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'",
        )
        self.end_headers()

    def send_json(self, value: Any, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self._headers(status, "application/json; charset=utf-8", len(payload))
        self.wfile.write(payload)

    def send_static(self, name: str) -> None:
        allowed = {"index.html", "app.js", "styles.css"}
        if name not in allowed:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = WEB_ROOT / name
        try:
            payload = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self._headers(200, content_type, len(payload))
        self.wfile.write(payload)

    @staticmethod
    def _one(query: dict[str, list[str]], name: str, default: str) -> str:
        values = query.get(name)
        return values[-1] if values else default

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = unquote(parsed.path)
        try:
            if path in {"/", "/index.html"}:
                self.send_static("index.html")
            elif path == "/app.js":
                self.send_static("app.js")
            elif path == "/styles.css":
                self.send_static("styles.css")
            elif path == "/api/status":
                self.send_json(self.service.status())
            elif path == "/api/mods":
                self.send_json(self.service.mods())
            elif path == "/api/correlation":
                self.send_json(self.service.correlation())
            elif path == "/api/windows":
                limit = int(self._one(query, "limit", "100"))
                self.send_json({"windows": self.service.store.list_windows(limit)})
            elif path == "/api/history":
                limit = int(self._one(query, "limit", "2000"))
                self.send_json({"history": self.service.store.history(limit)})
            elif path == "/api/hotspot-history":
                limit = int(self._one(query, "limit", "60"))
                top = int(self._one(query, "top", "6"))
                thread = self._one(query, "thread", "all")
                self.send_json(
                    self.service.store.hotspot_history(
                        window_limit=limit, top=top, thread=thread
                    )
                )
            elif path.startswith("/api/windows/"):
                self._get_window(path, query)
            elif path == "/api/compare":
                baseline = self._one(query, "baseline", "")
                comparison = self._one(query, "comparison", "")
                thread = self._one(query, "thread", "all")
                if not baseline or not comparison:
                    raise ValueError("baseline and comparison are required")
                self.send_json(
                    self.service.store.compare(baseline, comparison, thread)
                )
            else:
                self.send_json({"error": "not_found"}, status=404)
        except (ValueError, KeyError) as error:
            self.send_json({"error": str(error)}, status=400)
        except Exception as error:
            self.send_json({"error": str(error)}, status=500)

    def _get_window(self, path: str, query: dict[str, list[str]]) -> None:
        parts = path.strip("/").split("/")
        if len(parts) not in {3, 4}:
            self.send_json({"error": "not_found"}, status=404)
            return
        window_id = parts[2]
        if len(parts) == 3:
            value = self.service.store.get_window(window_id)
            if value is None:
                self.send_json({"error": "not_found"}, status=404)
            else:
                aggregate = self.service.store.load_aggregate(window_id)
                value["threads"] = aggregate.get("threads", [])
                self.send_json(value)
            return
        thread = self._one(query, "thread", "all")
        if parts[3] == "hotspots":
            sort = self._one(query, "sort", "self")
            self.send_json(
                {
                    "window": window_id,
                    "thread": thread,
                    "sort": sort,
                    "hotspots": self.service.store.hotspots(window_id, thread, sort),
                }
            )
        elif parts[3] == "flame":
            self.send_json(self.service.store.flame(window_id, thread))
        else:
            self.send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 64 * 1024:
            self.send_json({"error": "request_too_large"}, status=413)
            return
        if length:
            self.rfile.read(length)
        try:
            if path == "/api/profiler/start":
                result = self.service.profiler.start()
            elif path == "/api/profiler/pause":
                result = self.service.profiler.pause()
            elif path == "/api/profiler/resume":
                result = self.service.profiler.resume()
            elif path == "/api/profiler/stop":
                result = self.service.profiler.stop()
            elif path == "/api/mods/refresh":
                result = self.service.refresh_mods()
            else:
                self.send_json({"error": "not_found"}, status=404)
                return
            self.send_json(result)
        except Exception as error:
            self.send_json({"error": str(error)}, status=400)

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(service: ObservationService, host: str, port: int) -> None:
    handler = type("BoundDashboardHandler", (DashboardHandler,), {"service": service})
    server = ThreadingHTTPServer((host, port), handler)
    service.start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        service.stop()
