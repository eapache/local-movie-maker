from local_movie_maker.models import ProjectRequest
from local_movie_maker.planning import StoryPlanner
from local_movie_maker.prompting import (
    MediaPromptingGuides,
    detect_media_prompting_guides,
    detect_workflow_family,
)


def test_krea_2_image_workflow_uses_documented_natural_language_guide():
    workflow = {
        "loader": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "krea_2_bf16.safetensors"},
        }
    }

    guides = detect_media_prompting_guides(image=workflow)

    assert detect_workflow_family("image", workflow) == "krea-2"
    assert "Krea 2" in guides.image
    assert "long, detailed natural-language" in guides.image
    assert "visible text in quotes" in guides.image


def test_krea_2_takes_precedence_over_its_qwen_components():
    workflow = {
        "model": "krea-2-turbo.safetensors",
        "text_encoder": "qwen_image_text_encoder.safetensors",
    }

    assert detect_workflow_family("image", workflow) == "krea-2"


def test_minimax_h3_reference_workflow_uses_full_reference_format():
    workflow = {
        "generator": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": {"ref_images.ref_image_0": ["image", 0]},
        }
    }

    guides = detect_media_prompting_guides(video=workflow)

    assert detect_workflow_family("video", workflow) == "minimax-h3-reference"
    assert "playback-order" in guides.video
    assert "<Subject N>" in guides.video
    assert "<d>[English] exact dialogue</d>" in guides.video
    assert "non_diegetic_music: N/A" in guides.video


def test_unknown_workflow_gets_safe_generic_guide():
    guides = detect_media_prompting_guides(video={"class_type": "FutureVideoModel"})

    assert (
        detect_workflow_family("video", {"class_type": "FutureVideoModel"})
        == "generic"
    )
    assert "General video model" in guides.video


class RecordingClient:
    def __init__(self):
        self.prompts = []

    def complete_json(self, _system, prompt):
        self.prompts.append(prompt)
        if "Develop this idea" in prompt:
            return {"title": "Guide Test", "overview": "A tiny film"}
        if "continuity bible" in prompt:
            return {"characters": [], "settings": []}
        if "complete shot list" in prompt:
            return {"shots": [{"action": "A paper bird rises", "duration": 5}]}
        raise AssertionError(prompt)


def test_planner_passes_each_media_guide_to_the_relevant_writer_call():
    client = RecordingClient()
    planner = StoryPlanner(
        client,
        prompting_guides=MediaPromptingGuides(
            image="IMAGE MODEL RULES",
            video="VIDEO MODEL RULES",
            audio="AUDIO MODEL RULES",
        ),
    )

    planner.create(
        ProjectRequest("A paper bird learns to fly", 5, "540p"),
        lambda *_args: None,
    )

    assert "IMAGE MODEL RULES" in client.prompts[1]
    assert "VIDEO MODEL RULES" in client.prompts[2]
    assert "AUDIO MODEL RULES" in client.prompts[2]
    assert "VIDEO MODEL RULES" not in client.prompts[1]
