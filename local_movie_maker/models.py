from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .config import RESOLUTIONS


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ProjectRequest:
    prompt: str
    duration: int
    resolution: str
    llama_model: str | None = None
    checkpoint: str | None = None
    image_workflow: str | None = None
    video_workflow: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProjectRequest":
        prompt = str(value.get("prompt", "")).strip()
        if not 3 <= len(prompt) <= 1_000:
            raise ValueError("Prompt must be between 3 and 1,000 characters.")
        try:
            duration = int(value.get("duration", 30))
        except (TypeError, ValueError) as exc:
            raise ValueError("Length must be a whole number of seconds.") from exc
        if not 5 <= duration <= 300:
            raise ValueError("Length must be between 5 seconds and 5 minutes.")
        resolution = str(value.get("resolution", "720p"))
        if resolution not in RESOLUTIONS:
            raise ValueError(f"Resolution must be one of: {', '.join(RESOLUTIONS)}.")
        llama_model = _optional_name(value.get("llama_model"), "llama.cpp model")
        checkpoint = _optional_name(value.get("checkpoint"), "ComfyUI checkpoint")
        image_workflow = _optional_name(
            value.get("image_workflow"), "ComfyUI image workflow"
        )
        video_workflow = _optional_name(value.get("video_workflow"), "ComfyUI video workflow")
        return cls(
            prompt=prompt,
            duration=duration,
            resolution=resolution,
            llama_model=llama_model,
            checkpoint=checkpoint,
            image_workflow=image_workflow,
            video_workflow=video_workflow,
        )


def _optional_name(value: Any, label: str) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    if not result:
        return None
    if len(result) > 500 or any(ord(character) < 32 for character in result):
        raise ValueError(f"{label.capitalize()} is not valid.")
    return result


@dataclass
class Project:
    id: str
    request: ProjectRequest
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    status: str = "queued"
    stage: str = "queued"
    progress: int = 0
    message: str = "Waiting to begin"
    plan: dict[str, Any] | None = None
    assets: list[dict[str, Any]] = field(default_factory=list)
    video_url: str | None = None
    error: str | None = None
    configuration: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["request"] = asdict(self.request)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Project":
        data = dict(value)
        request = dict(data["request"])
        # Older projects may contain this retired field. Keep them readable
        # without carrying the continuation workflow forward.
        request.pop("continuation_workflow", None)
        data["request"] = ProjectRequest(**request)
        return cls(**data)
