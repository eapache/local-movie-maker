from __future__ import annotations

import hashlib
import re
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .clients import ApiError, ComfyClient, LlamaClient, describe_workflow, replace_workflow_tokens
from .config import RESOLUTIONS, Settings
from .media import MediaTools
from .models import Project, ProjectRequest
from .planning import StoryPlanner
from .services import ManagedService
from .store import ProjectStore


class MoviePipeline:
    def __init__(self, settings: Settings, store: ProjectStore):
        self.settings = settings
        self.store = store

    def run(self, project_id: str) -> None:
        project = self.store.get(project_id)
        if project is None:
            return
        workdir = self.store.project_dir(project_id)
        workdir.mkdir(parents=True, exist_ok=True)
        llama_service: ManagedService | None = None
        comfy_service: ManagedService | None = None
        effective_model = "demo"
        effective_checkpoint = "demo"
        video_workflow: Path | dict[str, Any] | None = self.settings.video_workflow
        video_workflow_name = self.settings.video_workflow.name if self.settings.video_workflow else None
        try:
            self._update(project_id, "planning", 3, "Starting the story engine")
            llama_client: LlamaClient | None = None
            if not self.settings.demo_mode:
                llama_service = ManagedService(
                    "llama",
                    self.settings.llama_url,
                    self.settings.llama_server_command,
                    self.settings.llama_startup_timeout,
                    "/health",
                )
                llama_service.start()
                llama_client = LlamaClient(
                    self.settings.llama_url,
                    project.request.llama_model or self.settings.llama_model,
                )
                effective_model = llama_client.resolve_model()
                self.store.update(
                    project_id,
                    configuration={"llama_model": effective_model},
                )
            planner = StoryPlanner(llama_client, demo=self.settings.demo_mode)
            plan = planner.create(
                project.request,
                lambda progress, message: self._update(
                    project_id, "planning", progress, message
                ),
            )
            self.store.update(project_id, plan=plan)

            # The LLM has finished all text work. Release it before allocating the
            # same GPU to ComfyUI.
            self._update(project_id, "handoff", 27, "Unloading the story engine")
            if llama_service and llama_service.process is not None:
                llama_service.stop()
            elif llama_client:
                llama_client.unload(self.settings.llama_unload_url)
            llama_service = None

            media = MediaTools(self.settings.ffmpeg, self.settings.ffprobe)
            comfy: ComfyClient | None = None
            if not self.settings.demo_mode:
                comfy_service = ManagedService(
                    "comfy",
                    self.settings.comfy_url,
                    self.settings.comfy_server_command,
                    self.settings.comfy_startup_timeout,
                    "/system_stats",
                )
                comfy_service.start()
                comfy = ComfyClient(self.settings.comfy_url, self.settings.comfy_timeout)
                effective_checkpoint = comfy.resolve_checkpoint(
                    project.request.checkpoint or self.settings.checkpoint
                )
                if project.request.video_workflow:
                    if not project.request.video_workflow.startswith("saved:"):
                        raise ApiError("Unknown ComfyUI video workflow selection.")
                    saved_name = project.request.video_workflow.removeprefix("saved:")
                    saved = comfy.load_saved_workflow(saved_name)
                    description = describe_workflow(saved_name, saved)
                    if description["format"] != "api":
                        raise ApiError(
                            f"'{saved_name}' is a ComfyUI UI workflow. Export it with "
                            "Save (API Format), then select the exported workflow."
                        )
                    if description["kind"] not in {"t2v", "i2v"}:
                        raise ApiError(f"'{saved_name}' does not appear to produce video.")
                    video_workflow = saved
                    video_workflow_name = saved_name
                elif isinstance(video_workflow, Path):
                    configured = ComfyClient.load_workflow(video_workflow, {})
                    description = describe_workflow(video_workflow.name, configured)
                    if description["format"] != "api":
                        raise ApiError(
                            f"Configured video workflow '{video_workflow}' is not in "
                            "ComfyUI API format."
                        )
                    video_workflow = configured
                if video_workflow is None:
                    raise ApiError(
                        "No executable ComfyUI video workflow is configured. Export a video "
                        "workflow with Save (API Format), or set COMFY_VIDEO_WORKFLOW."
                    )
                self.store.update(
                    project_id,
                    configuration={
                        "llama_model": effective_model,
                        "checkpoint": effective_checkpoint,
                        "image_workflow": self.settings.image_workflow.name,
                        "video_workflow": video_workflow_name,
                        "audio_workflow": (
                            self.settings.audio_workflow.name
                            if self.settings.audio_workflow
                            else None
                        ),
                    },
                )

            assets = self._generate_assets(
                project, plan, workdir, comfy, media, effective_checkpoint
            )
            self.store.update(project_id, assets=assets)
            self._render(
                project,
                plan,
                workdir,
                comfy,
                media,
                assets,
                effective_checkpoint,
                video_workflow,
            )

            # Publish the completed state and URL atomically so a polling browser
            # can never observe "complete" without a playable result.
            self.store.update(
                project_id,
                status="complete",
                stage="complete",
                progress=100,
                message="Your film is ready",
                error=None,
                video_url=f"/media/{project_id}/final.mp4",
            )
        except Exception as exc:
            traceback.print_exc()
            self.store.update(
                project_id,
                status="failed",
                stage="failed",
                message="Generation stopped",
                error=str(exc),
            )
        finally:
            if llama_service is not None and llama_service.process is not None:
                llama_service.stop()
            if comfy_service is not None and comfy_service.process is not None:
                comfy_service.stop()

    def _generate_assets(
        self,
        project: Project,
        plan: dict[str, Any],
        workdir: Path,
        comfy: ComfyClient | None,
        media: MediaTools,
        checkpoint: str,
    ) -> list[dict[str, Any]]:
        image_dir = workdir / "references"
        image_dir.mkdir(exist_ok=True)
        subjects = [
            ("character", item["name"], item["description"])
            for item in plan["characters"]
        ] + [
            ("setting", item["name"], item["description"])
            for item in plan["settings"]
        ]
        assets: list[dict[str, Any]] = []
        total = max(1, len(subjects))
        for index, (kind, name, description) in enumerate(subjects):
            progress = 30 + round(15 * index / total)
            self._update(project.id, "references", progress, f"Creating {name} reference")
            destination = image_dir / f"{kind}-{slug(name)}.png"
            seed = stable_seed(f"{project.id}:{kind}:{name}")
            prompt = reference_prompt(kind, name, description, plan["visual_style"])
            if comfy is None:
                media.placeholder(destination, 1024, 576, seed)
            else:
                comfy.run_workflow(
                    self.settings.image_workflow,
                    image_values(prompt, seed, project.request.resolution, checkpoint),
                    destination,
                )
            assets.append(
                {
                    "kind": kind,
                    "name": name,
                    "url": f"/media/{project.id}/references/{destination.name}",
                }
            )
            self.store.update(project.id, assets=list(assets))
        return assets

    def _render(
        self,
        project: Project,
        plan: dict[str, Any],
        workdir: Path,
        comfy: ComfyClient | None,
        media: MediaTools,
        assets: list[dict[str, Any]],
        checkpoint: str,
        video_workflow: Path | dict[str, Any] | None,
    ) -> None:
        width, height = RESOLUTIONS[project.request.resolution]
        shot_dir = workdir / "shots"
        shot_dir.mkdir(exist_ok=True)
        clips: list[Path] = []
        total = len(plan["shots"])
        for index, shot in enumerate(plan["shots"]):
            progress = 47 + round(38 * index / max(1, total))
            self._update(
                project.id,
                "shots",
                progress,
                f"Rendering shot {index + 1} of {total}",
            )
            seed = stable_seed(f"{project.id}:shot:{index}")
            still = shot_dir / f"shot-{index + 1:02d}.png"
            prompt = shot_prompt(shot, plan)
            if comfy is None:
                media.placeholder(still, min(width, 1024), min(height, 1024), seed)
            else:
                comfy.run_workflow(
                    self.settings.image_workflow,
                    image_values(prompt, seed, project.request.resolution, checkpoint),
                    still,
                )

            clip = shot_dir / f"clip-{index + 1:02d}.mp4"
            if comfy is not None and video_workflow is not None:
                uploaded = comfy.upload_image(still)
                raw_clip = shot_dir / f"raw-{index + 1:02d}.mp4"
                values = {
                    **image_values(
                        prompt, seed, project.request.resolution, checkpoint
                    ),
                    "IMAGE": uploaded,
                    "DURATION": shot["duration"],
                    "SECONDS": shot["duration"],
                    "FRAMES": shot["duration"] * 24,
                    "FPS": 24,
                    "WIDTH": width,
                    "HEIGHT": height,
                }
                workflow_template = (
                    ComfyClient.load_workflow(video_workflow, {})
                    if isinstance(video_workflow, Path)
                    else video_workflow
                )
                workflow = inject_api_workflow(workflow_template, values)
                comfy.run_workflow(
                    workflow,
                    values,
                    raw_clip,
                )
                media.normalize_clip(raw_clip, clip, shot["duration"], width, height)
            else:
                raise ApiError("A ComfyUI video workflow is required; still-image motion is disabled.")
            clips.append(clip)
            assets.append(
                {
                    "kind": "shot",
                    "name": shot["title"],
                    "url": f"/media/{project.id}/shots/{still.name}",
                }
            )
            self.store.update(project.id, assets=list(assets))

        self._update(project.id, "soundtrack", 87, "Composing the soundtrack")
        score: Path | None = None
        if comfy is not None and self.settings.audio_workflow:
            score = workdir / "score.m4a"
            raw_score = workdir / "generated-score.wav"
            comfy.run_workflow(
                self.settings.audio_workflow,
                {
                    "PROMPT": plan["music_prompt"],
                    "DURATION": project.request.duration,
                    "SECONDS": project.request.duration,
                    "SEED": stable_seed(f"{project.id}:score"),
                },
                raw_score,
            )
            # Re-encode to a consistently supported assembly format.
            media._run(
                [
                    media.ffmpeg,
                    "-y",
                    "-i",
                    str(raw_score),
                    "-t",
                    str(project.request.duration),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    str(score),
                ]
            )

        self._update(project.id, "assembly", 94, "Stitching the final cut")
        media.assemble(clips, score, workdir / "final.mp4")

    def _update(
        self,
        project_id: str,
        stage: str,
        progress: int,
        message: str,
        status: str = "running",
    ) -> None:
        self.store.update(
            project_id,
            status=status,
            stage=stage,
            progress=progress,
            message=message,
            error=None,
        )


class JobManager:
    def __init__(self, pipeline: MoviePipeline, store: ProjectStore):
        self.pipeline = pipeline
        self.store = store
        # A single worker intentionally serializes GPU-heavy jobs.
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="movie-maker")

    def submit(self, request: ProjectRequest) -> Project:
        project = Project(id=uuid.uuid4().hex, request=request)
        self.store.create(project)
        self.executor.submit(self.pipeline.run, project.id)
        return project

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)


def stable_seed(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:4], "big")


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result[:50] or "asset"


def image_size(resolution: str) -> tuple[int, int]:
    width, height = RESOLUTIONS[resolution]
    if width == height:
        return 1024, 1024
    if width > height:
        return 1024, 576
    return 576, 1024


def image_values(prompt: str, seed: int, resolution: str, checkpoint: str) -> dict[str, Any]:
    width, height = image_size(resolution)
    return {
        "PROMPT": prompt,
        "NEGATIVE_PROMPT": "text, subtitles, watermark, logo, duplicate people, malformed hands, low quality",
        "SEED": seed,
        "WIDTH": width,
        "HEIGHT": height,
        "IMAGE_WIDTH": width,
        "IMAGE_HEIGHT": height,
        "CHECKPOINT": checkpoint,
    }


def reference_prompt(kind: str, name: str, description: str, visual_style: str) -> str:
    if kind == "character":
        framing = "character reference sheet, full body and close portrait, neutral pose, plain studio backdrop"
    else:
        framing = "environment concept art, unoccupied establishing view, clear spatial layout"
    return f"{framing}. {name}: {description}. {visual_style}. Consistent production design, no text."


def shot_prompt(shot: dict[str, Any], plan: dict[str, Any]) -> str:
    character_details = {
        item["name"]: item["description"] for item in plan.get("characters", [])
    }
    setting_details = {
        item["name"]: item["description"] for item in plan.get("settings", [])
    }
    cast = "; ".join(
        f"{name}: {character_details.get(name, name)}" for name in shot.get("characters", [])
    )
    setting = setting_details.get(shot.get("setting"), shot.get("setting", ""))
    return (
        f"Film still. {shot['action']} Camera: {shot['camera']}. "
        f"Setting: {setting}. Characters: {cast or 'none'}. "
        f"Visual language: {plan['visual_style']}. Tone: {plan['tone']}. "
        "Cohesive character design, cinematic lighting, no text, no subtitles."
    )


def inject_api_workflow(workflow: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Adapt a saved API workflow using conservative, inspectable conventions.

    Explicit {{TOKENS}} always win. For ordinary API exports, well-known widget
    names and node titles are populated so users do not have to hand-edit JSON.
    """
    result = replace_workflow_tokens(workflow, values)
    prompt = values["PROMPT"]
    for node in result.values():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        inputs = node["inputs"]
        class_type = str(node.get("class_type", "")).lower()
        title = str(node.get("_meta", {}).get("title", "")).lower()
        negative = "negative" in title
        for key in list(inputs):
            lowered = key.lower()
            if lowered in {"seed", "noise_seed"}:
                inputs[key] = values["SEED"]
            elif lowered in {"width", "image_width"}:
                inputs[key] = values["WIDTH"]
            elif lowered in {"height", "image_height"}:
                inputs[key] = values["HEIGHT"]
            elif lowered in {"duration", "seconds"}:
                inputs[key] = values["DURATION"]
            elif lowered in {"frames", "num_frames", "length"}:
                inputs[key] = values["FRAMES"]
            elif lowered in {"fps", "frame_rate"}:
                inputs[key] = values["FPS"]
            elif class_type == "loadimage" and lowered == "image":
                inputs[key] = values["IMAGE"]
            elif lowered in {"prompt", "positive_prompt"}:
                inputs[key] = prompt
            elif lowered in {"text", "value"} and not negative and (
                "prompt" in title
                or "positive" in title
                or "textencode" in class_type
                or "primitivestring" in class_type
            ):
                inputs[key] = prompt
    return result
