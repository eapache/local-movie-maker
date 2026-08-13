from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .models import Project, now_iso


class ProjectStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._projects: dict[str, Project] = {}
        self._load()

    def _load(self) -> None:
        for state in self.root.glob("*/project.json"):
            try:
                project = Project.from_dict(json.loads(state.read_text(encoding="utf-8")))
                if project.status in {"queued", "running"}:
                    project.status = "failed"
                    project.error = "The app stopped before this project completed."
                    project.message = project.error
                self._projects[project.id] = project
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue

    def create(self, project: Project) -> Project:
        with self._lock:
            self._projects[project.id] = project
            self.project_dir(project.id).mkdir(parents=True, exist_ok=True)
            self._save(project)
            return project

    def get(self, project_id: str) -> Project | None:
        with self._lock:
            return self._projects.get(project_id)

    def list(self) -> list[Project]:
        with self._lock:
            return sorted(self._projects.values(), key=lambda item: item.created_at, reverse=True)

    def update(self, project_id: str, **changes: Any) -> Project:
        with self._lock:
            project = self._projects[project_id]
            for key, value in changes.items():
                if not hasattr(project, key):
                    raise AttributeError(key)
                setattr(project, key, value)
            project.updated_at = now_iso()
            self._save(project)
            return project

    def project_dir(self, project_id: str) -> Path:
        return self.root / project_id

    def _save(self, project: Project) -> None:
        state = self.project_dir(project.id) / "project.json"
        temp = state.with_suffix(".tmp")
        temp.write_text(json.dumps(project.to_dict(), indent=2), encoding="utf-8")
        temp.replace(state)
