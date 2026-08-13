from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MediaPromptingGuides:
    image: str
    video: str
    audio: str


_IMAGE_PROFILES = (
    (
        "krea-2",
        ("krea2", "krea-2", "krea_2", "krea 2"),
        "Krea 2: use a long, detailed natural-language image description; minimal prompts also "
        "work, but added concrete visual detail improves control. Describe subject, composition, "
        "environment, lighting, color, materials, and style. Put any visible text in quotes.",
    ),
    (
        "flux",
        ("flux",),
        "FLUX: use fluent natural-language sentences, not a tag list. Put the main subject "
        "and action first, then composition, environment, lighting, palette, lens, and style. "
        "State desired details positively and avoid prompt weights or negative-prompt syntax.",
    ),
    (
        "qwen-image",
        ("qwen-image", "qwen_image", "qwenimage"),
        "Qwen-Image: use a precise natural-language description with explicit spatial "
        "relationships, composition, lighting, and style. Put any visible text in quotes and "
        "spell it exactly; do not use tag soup.",
    ),
    (
        "sdxl",
        ("sdxl", "stable-diffusion-xl", "stable diffusion xl"),
        "SDXL: lead with the subject and medium, then use compact comma-separated visual "
        "phrases for composition, environment, lighting, color, lens, and finish. Favor concrete "
        "visual attributes over prose or narrative.",
    ),
    (
        "stable-diffusion",
        ("stable diffusion", "stable_diffusion", "sd1.5", "sd15"),
        "Stable Diffusion: use concise comma-separated visual phrases ordered by importance: "
        "subject, appearance, action, setting, composition, lighting, color, and medium. Avoid "
        "story exposition and non-visual instructions.",
    ),
)

_VIDEO_PROFILES = (
    (
        "minimax-h3-reference",
        (
            "minimaxh3referencetovideo",
            "minimaxh3",
            "minimax-h3-reference",
            "minimax_h3_reference",
            "minimax_h3",
            "minimax h3 reference",
        ),
        "MiniMax H3 full-reference: the prompt field must contain these six sections in order: "
        "subject_definitions, summary, retention_analysis, detailed_description, "
        "overall_soundscape, non_diegetic_music. Assign <Subject 1>, <Subject 2>, etc. to the "
        "shot's characters in their listed order and then its setting; keep these <Subject N> "
        "labels aligned with reference-image input order. In detailed_description, write an "
        "explicit playback-order description, not "
        "a plot summary; establish composition, subject appearance and position, environment, "
        "lighting, actions and state changes, camera movement, dialogue, and physical sound. Use "
        "[Shot 1] for the opening and <d>[English] exact dialogue</d> with stable (S1) speaker "
        "IDs. The workflow supplies background music separately, so write "
        "non_diegetic_music: N/A.",
    ),
    (
        "minimax-hailuo",
        ("minimax", "hailuo"),
        "MiniMax/Hailuo: write one continuous shot as camera movement + framing, subject, "
        "clear physical action, environment response, lighting, and visual style. Describe motion "
        "chronologically with strong verbs; do not request edits, cuts, or multiple scenes.",
    ),
    (
        "ltx-video",
        ("ltxvideo", "ltx-video", "ltx_video", "ltxv"),
        "LTX-Video: write a detailed chronological description of a single shot. Begin with "
        "the main action, then movements and gestures, appearance, environment, camera angle and "
        "movement, lighting and colors, and any sudden change. Use one flowing, literal paragraph "
        "under 200 words.",
    ),
    (
        "wan",
        ("wanvideo", "wan_video", "wan2", "wan 2", "wan-i2v", "wan i2v"),
        "Wan: use a dense natural-language shot description ordered as subject and appearance, "
        "expression and posture, action, visual style, spatial relationships, shot scale, and "
        "camera movement. Preserve the intended content, emphasize motion, and give every movement "
        "natural physical attributes.",
    ),
    (
        "kling",
        ("kling",),
        "Kling: use positive natural language describing the subject, precise movement, scene, "
        "camera movement, lighting, and cinematic character. Keep the action coherent and "
        "continuous; avoid negative instructions, cuts, and competing actions.",
    ),
    (
        "hunyuan-video",
        ("hunyuanvideo", "hunyuan-video", "hunyuan_video"),
        "HunyuanVideo: write a rich cinematic caption for one shot: subject identity, physical "
        "motion, scene, shot type, camera movement, lighting, style, and atmosphere, in that core "
        "structure. Use concrete visual language, chronological changes, and quote visible text.",
    ),
    (
        "mochi",
        ("mochi",),
        "Mochi: use a descriptive natural-language caption centered on visible motion. Specify "
        "subject, action, environment, camera framing and movement, lighting, and style, with one "
        "coherent event rather than cuts or a montage.",
    ),
    (
        "cogvideox",
        ("cogvideox", "cogvideo-x", "cogvideo_x"),
        "CogVideoX: use complete natural-language sentences describing subject, action, setting, "
        "camera, lighting, and style. Make spatial relationships and the order of motion explicit, "
        "and keep the prompt to one continuous scene.",
    ),
)

_AUDIO_PROFILES = (
    (
        "ace-step",
        ("ace-step", "ace_step", "acestep"),
        "ACE-Step: specify genre and subgenre, mood, instrumentation, tempo or BPM, arrangement "
        "progression, and production texture. Explicitly request instrumental/no vocals when the "
        "track must remain behind dialogue.",
    ),
    (
        "stable-audio",
        ("stableaudio", "stable-audio", "stable_audio", "stable audio"),
        "Stable Audio: use a compact music-production brief naming genre, mood, instruments, "
        "and how each sounds, mood and energy, and an explicit BPM. Prefix background score with "
        "TrackType: Music, VocalType: Instrumental; include recording texture and arrangement "
        "development, and avoid visual descriptions.",
    ),
    (
        "audioldm",
        ("audioldm", "audio-ldm", "audio_ldm"),
        "AudioLDM: use a concise literal description of the audible event or ambience, including "
        "source, acoustic space, intensity, and temporal evolution. Do not describe visuals.",
    ),
)

_GENERIC = {
    "image": (
        "General image model: describe one reproducible reference image with the subject's exact "
        "appearance, wardrobe or architecture, composition, lighting, palette, and style. Include "
        "only visible details and keep identity traits consistent."
    ),
    "video": (
        "General video model: prompt one continuous shot with subject identity, visible action, "
        "setting, framing, camera movement, lighting, and atmosphere. Describe motion in temporal "
        "order with concrete verbs; never ask for cuts, a montage, or multiple locations."
    ),
    "audio": (
        "General audio model: describe only audible content. For music include genre, mood, "
        "instruments, tempo, texture, and progression; for ambience include sound sources, space, "
        "intensity, and evolution. Keep background cues free of dialogue and vocals."
    ),
}


# Primary sources used to distill the instructions above. Keep these next to the
# profiles so future model revisions can be checked against their upstream guide.
PROMPTING_GUIDE_SOURCES = {
    "krea-2": "https://github.com/krea-ai/krea-2/blob/main/docs/prompting.md",
    "flux": "https://docs.bfl.ai/guides/prompting_guide_flux2",
    "qwen-image": (
        "https://github.com/QwenLM/Qwen-Image/blob/main/src/examples/tools/"
        "prompt_utils.py"
    ),
    "minimax-h3-reference": (
        "https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/"
        "VIDEO_PROMPT_WRITING_GUIDE_ref_en.md"
    ),
    "ltx-video": "https://github.com/Lightricks/LTX-Video#prompt-engineering",
    "wan": "https://github.com/Wan-Video/Wan2.1/blob/main/wan/utils/prompt_extend.py",
    "hunyuan-video": (
        "https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5/blob/main/assets/"
        "HunyuanVideo_1_5_Prompt_Handbook_EN.md"
    ),
    "stable-audio": (
        "https://github.com/Stability-AI/stable-audio-3/blob/main/docs/guides/"
        "prompting.md"
    ),
    "ace-step": (
        "https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/"
        "ace_step_musicians_guide.md"
    ),
}


def detect_media_prompting_guides(
    *, image: Any = None, video: Any = None, audio: Any = None
) -> MediaPromptingGuides:
    return MediaPromptingGuides(
        image=_guide("image", image, _IMAGE_PROFILES),
        video=_guide("video", video, _VIDEO_PROFILES),
        audio=_guide("audio", audio, _AUDIO_PROFILES),
    )


def detect_workflow_family(role: str, source: Any) -> str:
    profiles = {
        "image": _IMAGE_PROFILES,
        "video": _VIDEO_PROFILES,
        "audio": _AUDIO_PROFILES,
    }[role]
    signature = _signature(source)
    for family, markers, _guide_text in profiles:
        if any(marker in signature for marker in markers):
            return family
    return "generic"


def _guide(
    role: str,
    source: Any,
    profiles: tuple[tuple[str, tuple[str, ...], str], ...],
) -> str:
    family = detect_workflow_family(role, source)
    if family == "generic":
        return _GENERIC[role]
    return next(guide for name, _markers, guide in profiles if name == family)


def _signature(source: Any) -> str:
    try:
        return json.dumps(source, ensure_ascii=True, sort_keys=True, default=str).lower()
    except (TypeError, ValueError):
        return str(source).lower()
