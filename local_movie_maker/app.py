from __future__ import annotations

import json
import mimetypes
import re
import signal
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .clients import ApiError, ComfyClient, LlamaClient
from .config import RESOLUTIONS, ROOT, Settings
from .models import ProjectRequest
from .pipeline import JobManager, MoviePipeline
from .store import ProjectStore


PROJECT_ROUTE = re.compile(r"^/api/projects/([a-f0-9]{32})$")
MEDIA_ROUTE = re.compile(r"^/media/([a-f0-9]{32})/(.+)$")


class MovieMakerApp:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.store = ProjectStore(self.settings.projects_dir)
        self.pipeline = MoviePipeline(self.settings, self.store)
        self.jobs = JobManager(self.pipeline, self.store)

    def handler(self) -> type[BaseHTTPRequestHandler]:
        app = self

        class Handler(MovieMakerHandler):
            pass

        Handler.app = app
        return Handler

    def shutdown(self) -> None:
        self.jobs.shutdown()


class MovieMakerHandler(BaseHTTPRequestHandler):
    app: MovieMakerApp
    server_version = "LocalMovieMaker/0.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._serve_file(ROOT / "static" / "index.html")
            return
        if path.startswith("/static/"):
            self._serve_static(path.removeprefix("/static/"))
            return
        if path == "/api/config":
            self._json(
                {
                    "demo_mode": self.app.settings.demo_mode,
                    "resolutions": [
                        {"id": key, "width": size[0], "height": size[1]}
                        for key, size in RESOLUTIONS.items()
                    ],
                    "video_workflow": bool(self.app.settings.video_workflow),
                    "audio_workflow": bool(self.app.settings.audio_workflow),
                    "llama_model": self.app.settings.llama_model,
                    "checkpoint": self.app.settings.checkpoint,
                }
            )
            return
        if path == "/api/integrations":
            self._integration_options()
            return
        if path == "/api/projects":
            projects = [item.to_dict() for item in self.app.store.list()[:20]]
            self._json({"projects": projects})
            return
        if match := PROJECT_ROUTE.match(path):
            project = self.app.store.get(match.group(1))
            if project is None:
                self._error(HTTPStatus.NOT_FOUND, "Project not found")
            else:
                self._json(project.to_dict())
            return
        if match := MEDIA_ROUTE.match(path):
            self._serve_media(match.group(1), unquote(match.group(2)))
            return
        self._error(HTTPStatus.NOT_FOUND, "Not found")

    def _integration_options(self) -> None:
        settings = self.app.settings
        result: dict[str, Any] = {
            "llama": {
                "url": settings.llama_url,
                "configured": settings.llama_model,
                "models": [],
                "error": None,
            },
            "comfy": {
                "url": settings.comfy_url,
                "configured": settings.checkpoint,
                "checkpoints": [],
                "error": None,
                "workflows": {
                    "image": settings.image_workflow.name,
                    "video": settings.video_workflow.name if settings.video_workflow else None,
                    "audio": settings.audio_workflow.name if settings.audio_workflow else None,
                },
                "saved_workflows": [],
            },
        }
        if settings.demo_mode:
            self._json(result)
            return

        def discover_comfy() -> tuple[list[str], list[dict[str, Any]]]:
            comfy = ComfyClient(settings.comfy_url)
            return comfy.available_checkpoints(timeout=5), comfy.saved_workflows(timeout=5)

        # The services are independent. Probe them together so an unavailable
        # llama.cpp instance does not delay the ComfyUI result (or vice versa).
        with ThreadPoolExecutor(max_workers=2) as executor:
            llama_future = executor.submit(
                LlamaClient(settings.llama_url).available_models, timeout=5
            )
            comfy_future = executor.submit(discover_comfy)
            try:
                result["llama"]["models"] = llama_future.result()
            except ApiError as exc:
                result["llama"]["error"] = str(exc)
            try:
                checkpoints, saved_workflows = comfy_future.result()
                result["comfy"]["checkpoints"] = checkpoints
                result["comfy"]["saved_workflows"] = saved_workflows
            except ApiError as exc:
                result["comfy"]["error"] = str(exc)
        self._json(result)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/projects":
            self._error(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Request body must contain a small JSON object.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            request = ProjectRequest.from_dict(payload)
            if (
                not self.app.settings.demo_mode
                and not request.video_workflow
                and self.app.settings.video_workflow is None
            ):
                raise ValueError(
                    "Choose an executable ComfyUI video workflow under Advanced settings, "
                    "or set COMFY_VIDEO_WORKFLOW."
                )
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        project = self.app.jobs.submit(request)
        self._json(project.to_dict(), status=HTTPStatus.ACCEPTED)

    def _serve_static(self, relative: str) -> None:
        root = (ROOT / "static").resolve()
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Not found")
            return
        # This app is commonly updated and restarted in place. Revalidate assets so
        # a fresh HTML document cannot be paired with an hour-old script or stylesheet.
        self._serve_file(candidate, cache="no-cache")

    def _serve_media(self, project_id: str, relative: str) -> None:
        project = self.app.store.get(project_id)
        if project is None:
            self._error(HTTPStatus.NOT_FOUND, "Project not found")
            return
        root = self.app.store.project_dir(project_id).resolve()
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Media not found")
            return
        self._serve_file(candidate, cache="private, max-age=86400", ranges=True)

    def _serve_file(self, path: Path, cache: str = "no-cache", ranges: bool = False) -> None:
        try:
            size = path.stat().st_size
            start, end = 0, size - 1
            status = HTTPStatus.OK
            if ranges and (header := self.headers.get("Range")):
                match = re.match(r"bytes=(\d*)-(\d*)$", header)
                if match:
                    if match.group(1):
                        start = int(match.group(1))
                    if match.group(2):
                        end = min(int(match.group(2)), size - 1)
                    if start > end or start >= size:
                        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    status = HTTPStatus.PARTIAL_CONTENT
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            if ranges:
                self.send_header("Accept-Ranges", "bytes")
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except OSError as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status=status)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def run(settings: Settings | None = None) -> None:
    app = MovieMakerApp(settings)
    server = ThreadingHTTPServer((app.settings.host, app.settings.port), app.handler())
    server.daemon_threads = True

    def stop(_signum: int, _frame: Any) -> None:
        # shutdown() must run outside the signal handler's serve_forever frame.
        import threading

        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    mode = "demo" if app.settings.demo_mode else "local services"
    print(f"Local Movie Maker ({mode}) is running at http://{app.settings.host}:{app.settings.port}")
    try:
        server.serve_forever()
    finally:
        app.shutdown()
        server.server_close()
