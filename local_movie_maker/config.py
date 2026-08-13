from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("MOVIE_MAKER_HOST", "127.0.0.1")
    port: int = int(os.getenv("MOVIE_MAKER_PORT", "8090"))
    projects_dir: Path = Path(os.getenv("MOVIE_MAKER_PROJECTS_DIR", ROOT / "projects"))
    demo_mode: bool = _bool("MOVIE_MAKER_DEMO")

    llama_url: str = os.getenv("LLAMA_URL", "http://127.0.0.1:8080")
    # Empty means: discover the loaded model from llama.cpp at job start.
    llama_model: str | None = os.getenv("LLAMA_MODEL") or None
    llama_server_command: str | None = os.getenv("LLAMA_SERVER_COMMAND")
    llama_unload_url: str | None = os.getenv("LLAMA_UNLOAD_URL")
    llama_startup_timeout: int = int(os.getenv("LLAMA_STARTUP_TIMEOUT", "180"))

    comfy_url: str = os.getenv("COMFY_URL", "http://127.0.0.1:8188")
    comfy_server_command: str | None = os.getenv("COMFY_SERVER_COMMAND")
    comfy_startup_timeout: int = int(os.getenv("COMFY_STARTUP_TIMEOUT", "180"))
    comfy_timeout: int = int(os.getenv("COMFY_TIMEOUT", "900"))
    image_workflow: Path = Path(
        os.getenv("COMFY_IMAGE_WORKFLOW", ROOT / "workflows" / "image.json")
    )
    video_workflow: Path | None = (
        Path(value) if (value := os.getenv("COMFY_VIDEO_WORKFLOW")) else None
    )
    audio_workflow: Path | None = (
        Path(value) if (value := os.getenv("COMFY_AUDIO_WORKFLOW")) else None
    )
    # Empty means: discover the first installed checkpoint from ComfyUI.
    checkpoint: str | None = os.getenv("COMFY_CHECKPOINT") or None

    ffmpeg: str = os.getenv("FFMPEG", "ffmpeg")
    ffprobe: str = os.getenv("FFPROBE", "ffprobe")


RESOLUTIONS: dict[str, tuple[int, int]] = {
    "540p": (960, 540),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "vertical": (1080, 1920),
    "square": (1080, 1080),
}
