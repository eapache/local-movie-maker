from __future__ import annotations

import hashlib
import re
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .clients import (
    ApiError,
    ComfyClient,
    LlamaClient,
    describe_workflow,
    reference_image_node_ids,
    replace_workflow_tokens,
)
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
        image_workflow: Path | dict[str, Any] | None = self.settings.image_workflow
        image_workflow_name = (
            self.settings.image_workflow.name if self.settings.image_workflow else None
        )
        video_workflow: Path | dict[str, Any] | None = self.settings.video_workflow
        video_workflow_name = self.settings.video_workflow.name if self.settings.video_workflow else None
        background_audio_workflow: Path | dict[str, Any] | None = (
            self.settings.background_audio_workflow
        )
        background_audio_workflow_name = (
            self.settings.background_audio_workflow.name
            if self.settings.background_audio_workflow
            else None
        )
        try:
            self._update(project_id, "overview", 3, "Starting the story engine")
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
            planner = StoryPlanner(
                llama_client,
                demo=self.settings.demo_mode,
                max_shot_seconds=self.settings.video_segment_seconds,
            )
            plan = planner.create(
                project.request,
                lambda stage, progress, message: self._update(
                    project_id, stage, progress, message
                ),
            )
            self.store.update(project_id, plan=plan)

            # The LLM has finished all text work. Release it before allocating the
            # same GPU to ComfyUI.
            self._update(
                project_id,
                "references",
                27,
                "Switching from writing to visual references",
            )
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
                if project.request.image_workflow:
                    if not project.request.image_workflow.startswith("saved:"):
                        raise ApiError("Unknown ComfyUI image workflow selection.")
                    saved_name = project.request.image_workflow.removeprefix("saved:")
                    saved = comfy.load_saved_workflow(saved_name)
                    description = describe_workflow(saved_name, saved)
                    if description["format"] != "api":
                        raise ApiError(api_export_message(saved_name))
                    if description["kind"] != "image":
                        raise ApiError(f"'{saved_name}' does not appear to produce images.")
                    image_workflow = saved
                    image_workflow_name = saved_name
                elif isinstance(image_workflow, Path):
                    configured_image = ComfyClient.load_workflow(image_workflow, {})
                    description = describe_workflow(image_workflow.name, configured_image)
                    if description["format"] != "api" or description["kind"] != "image":
                        raise ApiError(
                            f"Configured image workflow '{image_workflow}' is not an "
                            "executable ComfyUI image API graph."
                        )
                    image_workflow = configured_image
                if image_workflow is None:
                    raise ApiError(
                        "No reference image workflow is configured. Select an executable "
                        "ComfyUI image API graph or set COMFY_IMAGE_WORKFLOW."
                    )

                checkpoint = project.request.checkpoint or self.settings.checkpoint
                # Exported API workflows normally contain their own model loaders.
                # Resolve a raw checkpoint only when the graph explicitly requests
                # our CHECKPOINT token or the legacy API supplied an override.
                effective_checkpoint = (
                    comfy.resolve_checkpoint(checkpoint)
                    if checkpoint or workflow_uses_token(image_workflow, "CHECKPOINT")
                    else ""
                )
                video_workflow, video_workflow_name = resolve_video_workflow(
                    comfy,
                    project.request.video_workflow,
                    video_workflow,
                    role="reference",
                )
                if video_workflow is None:
                    raise ApiError(
                        "No text-and-reference video workflow is configured. Export a "
                        "ComfyUI API graph with reference-image inputs, then select it or "
                        "set COMFY_VIDEO_WORKFLOW."
                    )
                background_audio_workflow, background_audio_workflow_name = (
                    resolve_audio_workflow(
                        comfy,
                        project.request.background_audio_workflow,
                        background_audio_workflow,
                    )
                )
                if background_audio_workflow is None:
                    raise ApiError(
                        "No background audio workflow is configured. Select an executable "
                        "ComfyUI audio API graph or set COMFY_BACKGROUND_AUDIO_WORKFLOW."
                    )
                if any(
                    shot["duration"] > self.settings.video_segment_seconds
                    for shot in plan["shots"]
                ):
                    raise ApiError(
                        "The planned shot list exceeds the configured video workflow "
                        f"limit of {self.settings.video_segment_seconds} seconds per shot."
                    )
                self.store.update(
                    project_id,
                    configuration={
                        "llama_model": effective_model,
                        "checkpoint": effective_checkpoint or None,
                        "image_workflow": image_workflow_name,
                        "video_workflow": video_workflow_name,
                        "video_segment_seconds": self.settings.video_segment_seconds,
                        "background_audio_workflow": background_audio_workflow_name,
                    },
                )

            assets, reference_files = self._generate_assets(
                project,
                plan,
                workdir,
                comfy,
                media,
                effective_checkpoint,
                image_workflow,
            )
            self.store.update(project_id, assets=assets)
            uploaded_references = (
                {
                    key: comfy.upload_image(path)
                    for key, path in reference_files.items()
                }
                if comfy is not None
                else {}
            )
            self._render(
                project,
                plan,
                workdir,
                comfy,
                media,
                assets,
                video_workflow,
                background_audio_workflow,
                uploaded_references,
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
        image_workflow: Path | dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], dict[tuple[str, str], Path]]:
        image_dir = workdir / "references"
        image_dir.mkdir(exist_ok=True)
        subjects = [
            ("character", item["name"], item["description"])
            for item in plan["characters"]
        ] + [
            ("setting", item["name"], item["description"])
            for item in plan["settings"]
        ]
        if not any(kind == "setting" for kind, _, _ in subjects):
            subjects.append(("setting", "Main setting", plan["overview"]))
        assets: list[dict[str, Any]] = []
        reference_files: dict[tuple[str, str], Path] = {}
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
                if image_workflow is None:
                    raise ApiError("A ComfyUI reference image workflow is required.")
                values = image_values(
                    prompt, seed, project.request.resolution, checkpoint
                )
                workflow = (
                    image_workflow
                    if isinstance(image_workflow, Path)
                    else inject_api_workflow(image_workflow, values)
                )
                comfy.run_workflow(
                    workflow,
                    values,
                    destination,
                )
            assets.append(
                {
                    "kind": kind,
                    "name": name,
                    "url": f"/media/{project.id}/references/{destination.name}",
                }
            )
            reference_files[(kind, name)] = destination
            self.store.update(project.id, assets=list(assets))
        return assets, reference_files

    def _render(
        self,
        project: Project,
        plan: dict[str, Any],
        workdir: Path,
        comfy: ComfyClient | None,
        media: MediaTools,
        assets: list[dict[str, Any]],
        video_workflow: Path | dict[str, Any] | None,
        background_audio_workflow: Path | dict[str, Any] | None,
        uploaded_references: dict[tuple[str, str], str],
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
            prompt = shot_prompt(shot, plan)
            if comfy is not None and video_workflow is not None:
                references = references_for_shot(shot, uploaded_references)
                preview = shot_dir / f"shot-{index + 1:02d}.png"
                seed = stable_seed(f"{project.id}:shot:{index}")
                values = video_values(
                    prompt,
                    seed,
                    project.request.resolution,
                    shot["duration"],
                    references,
                )
                workflow = inject_api_workflow(video_workflow, values)
                raw_clip = shot_dir / f"raw-{index + 1:02d}.mp4"
                clip = shot_dir / f"clip-{index + 1:02d}.mp4"
                comfy.run_workflow(workflow, values, raw_clip)
                media.normalize_clip(raw_clip, clip, shot["duration"], width, height)
                media.extract_first_frame(clip, preview)
                clips.append(clip)
            else:
                raise ApiError("A ComfyUI video workflow is required; still-image motion is disabled.")
            assets.append(
                {
                    "kind": "shot",
                    "name": shot["title"],
                    "url": f"/media/{project.id}/shots/{preview.name}",
                }
            )
            self.store.update(project.id, assets=list(assets))

        self._update(project.id, "soundtrack", 87, "Creating background audio")
        background_layers: list[tuple[Path, float, float]] = []
        if comfy is not None and background_audio_workflow is not None:
            for cue_index, cue in enumerate(planned_audio_cues(plan)):
                self._update(
                    project.id,
                    "soundtrack",
                    87 + round(5 * cue_index / max(1, len(plan["background_audio"]))),
                    f"Creating background track {cue_index + 1}",
                )
                raw_track = workdir / f"background-{cue_index + 1:02d}.wav"
                track = workdir / f"background-{cue_index + 1:02d}.m4a"
                values = {
                    "PROMPT": cue["prompt"],
                    "DURATION": cue["duration"],
                    "SECONDS": cue["duration"],
                    "SEED": stable_seed(f"{project.id}:background:{cue_index}"),
                }
                workflow = inject_api_workflow(background_audio_workflow, values)
                comfy.run_workflow(workflow, values, raw_track)
                media.normalize_audio(raw_track, track, cue["duration"])
                background_layers.append((track, cue["start"], cue["duration"]))

        self._update(project.id, "assembly", 94, "Stitching the final cut")
        media.assemble(clips, background_layers, workdir / "final.mp4")

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


def resolve_video_workflow(
    comfy: ComfyClient,
    selection: str | None,
    configured: Path | dict[str, Any] | None,
    *,
    role: str,
) -> tuple[dict[str, Any] | None, str | None]:
    workflow = configured
    name = configured.name if isinstance(configured, Path) else None
    if selection:
        if not selection.startswith("saved:"):
            raise ApiError(f"Unknown ComfyUI {role} video workflow selection.")
        name = selection.removeprefix("saved:")
        workflow = comfy.load_saved_workflow(name)
    elif isinstance(workflow, Path):
        workflow = ComfyClient.load_workflow(workflow, {})
    if workflow is None:
        return None, None

    description = describe_workflow(name or f"configured-{role}.json", workflow)
    if description["format"] != "api":
        raise ApiError(api_export_message(name or role))
    capabilities = description["capabilities"]
    if not capabilities["video"] or not capabilities["references"]:
        raise ApiError(
            f"'{name or role}' must produce video and accept reference images. "
            "Use REFERENCE_IMAGES tokens or title its LoadImage nodes as references."
        )
    if capabilities["keyframe"]:
        raise ApiError(
            f"'{name or role}' also requires a keyframe. The primary workflow must use "
            "text and references without a starting frame."
        )
    return workflow, name


def resolve_audio_workflow(
    comfy: ComfyClient,
    selection: str | None,
    configured: Path | dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    workflow = configured
    name = configured.name if isinstance(configured, Path) else None
    if selection:
        if not selection.startswith("saved:"):
            raise ApiError("Unknown ComfyUI background audio workflow selection.")
        name = selection.removeprefix("saved:")
        workflow = comfy.load_saved_workflow(name)
    elif isinstance(workflow, Path):
        workflow = ComfyClient.load_workflow(workflow, {})
    if workflow is None:
        return None, None
    description = describe_workflow(name or "configured-background-audio.json", workflow)
    if description["format"] != "api":
        raise ApiError(api_export_message(name or "background audio"))
    if description["kind"] != "audio":
        raise ApiError(f"'{name or 'background audio'}' must produce audio.")
    return workflow, name


def api_export_message(name: str) -> str:
    return (
        f"'{name}' is a ComfyUI UI workflow. Enable Dev Mode, use File → "
        "Export (API), put the downloaded JSON in ComfyUI's active user workflow "
        "folder, then refresh and select it."
    )


def planned_audio_cues(plan: dict[str, Any]) -> list[dict[str, Any]]:
    shots = plan.get("shots", [])
    result: list[dict[str, Any]] = []
    for cue in plan.get("background_audio", []):
        if not isinstance(cue, dict) or not shots:
            continue
        start_index = max(0, min(len(shots) - 1, int(cue.get("start_shot", 1)) - 1))
        end_index = max(start_index, min(len(shots) - 1, int(cue.get("end_shot", len(shots))) - 1))
        prompt = str(cue.get("prompt", "")).strip()
        if not prompt:
            continue
        result.append(
            {
                "prompt": prompt,
                "start": sum(shot["duration"] for shot in shots[:start_index]),
                "duration": sum(
                    shot["duration"] for shot in shots[start_index : end_index + 1]
                ),
            }
        )
    return result


def references_for_shot(
    shot: dict[str, Any], uploaded: dict[tuple[str, str], str]
) -> dict[str, Any]:
    characters = [
        uploaded[("character", name)]
        for name in shot.get("characters", [])
        if ("character", name) in uploaded
    ]
    setting = uploaded.get(("setting", str(shot.get("setting", ""))))
    if setting is None:
        setting = next(
            (filename for (kind, _), filename in uploaded.items() if kind == "setting"),
            None,
        )
    references = [*characters, *([setting] if setting else [])]
    if not references:
        raise ApiError(f"No generated references match shot '{shot.get('title', '')}'.")
    return {"all": references, "characters": characters, "setting": setting}


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


def video_values(
    prompt: str,
    seed: int,
    resolution: str,
    duration: int,
    references: dict[str, Any],
) -> dict[str, Any]:
    width, height = RESOLUTIONS[resolution]
    all_references = list(references["all"])
    character_references = list(references["characters"])
    setting_reference = references.get("setting") or all_references[-1]
    values: dict[str, Any] = {
        "PROMPT": prompt,
        "NEGATIVE_PROMPT": (
            "text, subtitles, watermark, logo, duplicate people, malformed hands, "
            "low quality"
        ),
        "SEED": seed,
        "DURATION": duration,
        "SECONDS": duration,
        "FRAMES": duration * 24,
        "FPS": 24,
        "WIDTH": width,
        "HEIGHT": height,
        "IMAGE_WIDTH": width,
        "IMAGE_HEIGHT": height,
        "REFERENCE_IMAGES": all_references,
        "REFERENCE_IMAGE": all_references[0],
        "SETTING_REFERENCE": setting_reference,
    }
    for index in range(1, 7):
        values[f"REFERENCE_IMAGE_{index}"] = all_references[
            min(index - 1, len(all_references) - 1)
        ]
    if character_references:
        for index in range(1, 4):
            values[f"CHARACTER_REFERENCE_{index}"] = character_references[
                min(index - 1, len(character_references) - 1)
            ]
    return values


def workflow_uses_token(value: Any, name: str) -> bool:
    token = f"{{{{{name}}}}}"

    def uses_token(item: Any) -> bool:
        if isinstance(item, dict):
            return any(uses_token(child) for child in item.values())
        if isinstance(item, list):
            return any(uses_token(child) for child in item)
        return isinstance(item, str) and token in item

    return uses_token(value)


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
    direction = shot.get("prompt") or (
        f"{shot['action']} Camera: {shot['camera']}."
    )
    return (
        f"Film shot. {direction} "
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
    positive_nodes: set[str] = set()
    negative_nodes: set[str] = set()
    reference_cursor = 1
    character_cursor = 1
    linked_reference_nodes = {
        node_id: index
        for index, node_id in enumerate(reference_image_node_ids(result), start=1)
    }
    for node in result.values():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        for key, targets in (("positive", positive_nodes), ("negative", negative_nodes)):
            link = node["inputs"].get(key)
            if isinstance(link, list) and link:
                targets.add(str(link[0]))

    for node_id, node in result.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        inputs = node["inputs"]
        class_type = str(node.get("class_type", "")).lower()
        title = str(node.get("_meta", {}).get("title", "")).lower()
        negative = str(node_id) in negative_nodes or "negative" in title
        positive = str(node_id) in positive_nodes or "positive" in title or "prompt" in title
        for key in list(inputs):
            lowered = key.lower()
            if lowered in {"seed", "noise_seed"}:
                inputs[key] = values["SEED"]
            elif lowered in {"width", "image_width"} and "WIDTH" in values:
                inputs[key] = values["WIDTH"]
            elif lowered in {"height", "image_height"} and "HEIGHT" in values:
                inputs[key] = values["HEIGHT"]
            elif lowered in {"duration", "seconds"} and "DURATION" in values:
                inputs[key] = values["DURATION"]
            elif lowered in {"frames", "num_frames", "length"} and "FRAMES" in values:
                inputs[key] = values["FRAMES"]
            elif lowered in {"fps", "frame_rate"} and "FPS" in values:
                inputs[key] = values["FPS"]
            elif class_type == "loadimage" and lowered == "image":
                if "setting" in title and "SETTING_REFERENCE" in values:
                    inputs[key] = values["SETTING_REFERENCE"]
                elif "character" in title:
                    match = re.search(r"(\d+)", title)
                    index = int(match.group(1)) if match else character_cursor
                    token = f"CHARACTER_REFERENCE_{index}"
                    if token in values:
                        inputs[key] = values[token]
                    character_cursor += 1
                elif "reference" in title:
                    match = re.search(r"(\d+)", title)
                    index = int(match.group(1)) if match else reference_cursor
                    token = f"REFERENCE_IMAGE_{index}"
                    if token in values:
                        inputs[key] = values[token]
                    reference_cursor += 1
                elif str(node_id) in linked_reference_nodes:
                    token = f"REFERENCE_IMAGE_{linked_reference_nodes[str(node_id)]}"
                    if token in values:
                        inputs[key] = values[token]
            elif lowered in {"prompt", "positive_prompt"}:
                inputs[key] = prompt
            elif lowered in {"text", "value"} and not negative and (
                positive or "textencode" in class_type or "primitivestring" in class_type
            ):
                inputs[key] = prompt
    return result
