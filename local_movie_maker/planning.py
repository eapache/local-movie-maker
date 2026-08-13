from __future__ import annotations

import json
import math
import re
from typing import Any, Callable

from .clients import LlamaClient
from .models import ProjectRequest


Progress = Callable[[int, str], None]


SYSTEM = """You are a concise film writer and production planner. Design stories that can be
made by a small generative-video pipeline. Keep the cast and locations limited, maintain visual
continuity, and return only the JSON object requested. Do not use Markdown."""


class StoryPlanner:
    def __init__(
        self,
        client: LlamaClient | None,
        demo: bool = False,
        max_shot_seconds: int = 15,
    ):
        self.client = client
        self.demo = demo
        self.max_shot_seconds = max(1, max_shot_seconds)

    def create(self, request: ProjectRequest, progress: Progress) -> dict[str, Any]:
        if self.demo:
            progress(15, "Drafting the concept")
            return demo_plan(request, self.max_shot_seconds)
        if self.client is None:
            raise RuntimeError("A llama.cpp client is required outside demo mode.")

        width_hint = "vertical framing" if request.resolution == "vertical" else "cinematic framing"
        progress(8, "Expanding the idea into a film treatment")
        concept = self.client.complete_json(
            SYSTEM,
            f"""Develop this idea into a coherent {request.duration}-second short film using {width_hint}:
{request.prompt}

Return this shape:
{{"title":"...","logline":"...","overview":"...","genre":"...","tone":"...",
"visual_style":"specific production-ready visual direction","ending":"..."}}""",
        )

        progress(15, "Designing characters and locations")
        bible = self.client.complete_json(
            SYSTEM,
            f"""Create a compact continuity bible for this short film.
Concept: {json.dumps(concept, ensure_ascii=False)}

Return this shape:
{{"characters":[{{"name":"...","role":"...","description":"age, face, hair, wardrobe, silhouette and colors","voice":"..."}}],
"settings":[{{"name":"...","description":"architecture, light, palette, weather and recurring objects"}}]}}
Use at most 3 characters and 3 settings. Descriptions must let an image model reproduce them.""",
        )

        progress(23, "Writing the shot-by-shot script")
        script = self.client.complete_json(
            SYSTEM,
            f"""Write the complete shot list for a {request.duration}-second generative short film.
Concept: {json.dumps(concept, ensure_ascii=False)}
Continuity bible: {json.dumps(bible, ensure_ascii=False)}

Return this shape:
{{"shots":[{{"title":"...","duration":4,"setting":"exact setting name","characters":["exact character name"],
"action":"visible action during this shot","camera":"framing and camera movement","dialogue":"spoken line or empty string",
"sound":"diegetic sound","transition":"cut, dissolve, etc."}}],
"background_audio_prompt":"ambience, music, instrumentation, tempo, mood and progression","credits":"short credit line"}}
Their durations must total exactly {request.duration} seconds. No shot may exceed
{self.max_shot_seconds} seconds; add cuts instead of continuing a shot. Keep every shot visually achievable.""",
        )
        return normalize_plan(
            request, concept, bible, script, max_shot_seconds=self.max_shot_seconds
        )


def normalize_plan(
    request: ProjectRequest,
    concept: dict[str, Any],
    bible: dict[str, Any],
    script: dict[str, Any],
    max_shot_seconds: int = 15,
) -> dict[str, Any]:
    characters = _object_list(bible.get("characters"), ["name", "description"], limit=3)
    settings = _object_list(bible.get("settings"), ["name", "description"], limit=3)
    raw_shots = _object_list(
        script.get("shots"),
        ["action"],
        limit=max(12, math.ceil(request.duration / max(1, max_shot_seconds)) * 2),
    )
    if not raw_shots:
        raw_shots = [
            {
                "title": "The moment",
                "duration": request.duration,
                "setting": settings[0]["name"] if settings else "Main setting",
                "characters": [item["name"] for item in characters],
                "action": str(concept.get("overview") or request.prompt),
                "camera": "A composed cinematic wide shot with a slow push in",
                "dialogue": "",
                "sound": "Natural ambience",
                "transition": "cut",
            }
        ]
    raw_shots, durations = _fit_and_cap_shots(
        raw_shots, request.duration, max(1, max_shot_seconds)
    )
    shots: list[dict[str, Any]] = []
    for index, (shot, duration) in enumerate(zip(raw_shots, durations, strict=True), 1):
        cast = shot.get("characters", [])
        if not isinstance(cast, list):
            cast = [str(cast)] if cast else []
        shots.append(
            {
                "id": index,
                "title": _text(shot.get("title"), f"Shot {index}"),
                "duration": duration,
                "setting": _text(shot.get("setting"), settings[0]["name"] if settings else "Main setting"),
                "characters": [str(item) for item in cast[:3]],
                "action": _text(shot.get("action"), request.prompt),
                "camera": _text(shot.get("camera"), "Cinematic medium shot, gentle camera movement"),
                "dialogue": _text(shot.get("dialogue"), ""),
                "sound": _text(shot.get("sound"), "Natural ambience"),
                "transition": _text(shot.get("transition"), "cut"),
            }
        )
    title = _text(concept.get("title"), "Untitled Short")
    return {
        "title": title,
        "logline": _text(concept.get("logline"), request.prompt),
        "overview": _text(concept.get("overview"), request.prompt),
        "genre": _text(concept.get("genre"), "Short film"),
        "tone": _text(concept.get("tone"), "Cinematic"),
        "visual_style": _text(
            concept.get("visual_style"),
            "cinematic natural light, cohesive color grade, realistic detail",
        ),
        "ending": _text(concept.get("ending"), "A resonant final image"),
        "characters": characters,
        "settings": settings,
        "shots": shots,
        "background_audio": [
            {
                "start_shot": 1,
                "end_shot": len(shots),
                "prompt": _text(
                    script.get("background_audio_prompt") or script.get("music_prompt"),
                    "Subtle cinematic ambience and score",
                ),
            }
        ],
        "credits": _text(script.get("credits"), "Created with Local Movie Maker"),
    }


def _text(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _object_list(value: Any, required: list[str], limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        if all(_text(item.get(key), "") for key in required):
            result.append(item)
    return result


def _fit_durations(shots: list[dict[str, Any]], target: int) -> list[int]:
    count = min(len(shots), target)
    shots[:] = shots[:count]
    weights: list[float] = []
    for shot in shots:
        try:
            weights.append(max(1.0, float(shot.get("duration", 1))))
        except (TypeError, ValueError):
            weights.append(1.0)
    remaining = target - count
    if remaining <= 0:
        return [1] * count
    total = sum(weights)
    extras = [math.floor(remaining * weight / total) for weight in weights]
    missing = remaining - sum(extras)
    fractions = sorted(
        range(count),
        key=lambda index: (remaining * weights[index] / total) - extras[index],
        reverse=True,
    )
    for index in fractions[:missing]:
        extras[index] += 1
    return [extra + 1 for extra in extras]


def _fit_and_cap_shots(
    shots: list[dict[str, Any]], target: int, maximum: int
) -> tuple[list[dict[str, Any]], list[int]]:
    durations = _fit_durations(shots, target)
    capped_shots: list[dict[str, Any]] = []
    capped_durations: list[int] = []
    for shot, duration in zip(shots, durations, strict=True):
        part_count = max(1, math.ceil(duration / maximum))
        base, extra = divmod(duration, part_count)
        for part_index in range(part_count):
            item = dict(shot)
            if part_count > 1:
                item["title"] = f"{_text(shot.get('title'), 'Shot')} — part {part_index + 1}"
            capped_shots.append(item)
            capped_durations.append(base + (1 if part_index < extra else 0))
    return capped_shots, capped_durations


def demo_plan(request: ProjectRequest, max_shot_seconds: int = 15) -> dict[str, Any]:
    words = re.findall(r"[A-Za-z0-9']+", request.prompt)
    name = " ".join(words[:5]).title() or "A Small Wonder"
    concept = {
        "title": name,
        "logline": request.prompt,
        "overview": f"A compact visual story inspired by: {request.prompt}",
        "genre": "Cinematic vignette",
        "tone": "Warm, curious, quietly wondrous",
        "visual_style": "35mm film, soft volumetric light, teal and amber palette, tactile detail",
        "ending": "The discovery resolves in a calm, memorable final image.",
    }
    bible = {
        "characters": [
            {
                "name": "The Traveler",
                "role": "protagonist",
                "description": "Curious young adult, dark wavy hair, weathered ochre coat, canvas satchel, expressive eyes",
                "voice": "soft and thoughtful",
            }
        ],
        "settings": [
            {
                "name": "The Hidden Place",
                "description": "An intimate overgrown space at blue hour, warm practical lights, drifting dust, moss and old stone",
            }
        ],
    }
    shot_count = max(2, min(6, round(request.duration / 5)))
    actions = [
        "The Traveler enters and notices a faint, unusual glow.",
        "They follow the glow through layered foreground details.",
        "A small discovery changes the atmosphere around them.",
        "They reach out carefully as light gathers in the frame.",
        "The wider world responds with a subtle wave of motion.",
        "The Traveler pauses, smiling, as the image settles into stillness.",
    ]
    script = {
        "shots": [
            {
                "title": f"Discovery {index + 1}",
                "duration": request.duration / shot_count,
                "setting": "The Hidden Place",
                "characters": ["The Traveler"],
                "action": actions[index],
                "camera": [
                    "Wide establishing shot, slow dolly forward",
                    "Shoulder-height tracking shot through foreground leaves",
                    "Close-up with a gentle rack focus",
                    "Medium profile shot, slow orbit",
                    "High wide shot, gradual crane upward",
                    "Intimate close-up, nearly still",
                ][index],
                "dialogue": "",
                "sound": "Wind, leaves, and a delicate tonal shimmer",
                "transition": "dissolve" if index else "fade in",
            }
            for index in range(shot_count)
        ],
        "background_audio_prompt": "Gentle felt piano, airy strings and natural ambience, 72 BPM, growing wonder, soft resolved ending",
        "credits": "Created locally with Local Movie Maker",
    }
    return normalize_plan(
        request, concept, bible, script, max_shot_seconds=max_shot_seconds
    )
