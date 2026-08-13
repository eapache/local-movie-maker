from dataclasses import replace

from local_movie_maker.config import Settings
from local_movie_maker.models import Project, ProjectRequest
from local_movie_maker.pipeline import (
    MoviePipeline,
    image_values,
    inject_api_workflow,
    references_for_shot,
    video_values,
    workflow_uses_token,
)
from local_movie_maker.store import ProjectStore


def test_pipeline_refuses_to_fake_video_without_a_workflow(tmp_path):
    settings = replace(Settings(), projects_dir=tmp_path, demo_mode=True)
    store = ProjectStore(tmp_path)
    project = Project("a" * 32, ProjectRequest("A mysterious garden", 5, "540p"))
    store.create(project)

    MoviePipeline(settings, store).run(project.id)

    completed = store.get(project.id)
    assert completed is not None
    assert completed.status == "failed"
    assert "video workflow is required" in completed.error.lower()
    assert completed.plan is not None
    assert sum(shot["duration"] for shot in completed.plan["shots"]) == 5


def test_saved_image_workflow_injection_preserves_negative_prompt():
    workflow = {
        "positive": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "old positive"},
        },
        "negative": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "keep this negative"},
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "seed": 1,
            },
        },
        "output": {"class_type": "SaveImage", "inputs": {}},
    }
    values = image_values("new production prompt", 42, "720p", "")

    result = inject_api_workflow(workflow, values)

    assert result["positive"]["inputs"]["text"] == "new production prompt"
    assert result["negative"]["inputs"]["text"] == "keep this negative"
    assert result["sampler"]["inputs"]["seed"] == 42


def test_checkpoint_resolution_is_only_needed_for_tokenized_workflows():
    exported = {"loader": {"inputs": {"unet_name": "model.safetensors"}}}
    fallback = {"loader": {"inputs": {"ckpt_name": "{{CHECKPOINT}}"}}}

    assert not workflow_uses_token(exported, "CHECKPOINT")
    assert workflow_uses_token(fallback, "CHECKPOINT")


def test_reference_inputs_are_injected_by_role():
    workflow = {
        "character": {
            "class_type": "LoadImage",
            "inputs": {"image": "old-character.png"},
            "_meta": {"title": "Character Reference 1"},
        },
        "setting": {
            "class_type": "LoadImage",
            "inputs": {"image": "old-setting.png"},
            "_meta": {"title": "Setting Reference"},
        },
    }
    references = {
        "all": ["frog.png", "mars.png"],
        "characters": ["frog.png"],
        "setting": "mars.png",
    }
    values = video_values("Frog runs", 42, "720p", 6, references)

    result = inject_api_workflow(workflow, values)

    assert result["character"]["inputs"]["image"] == "frog.png"
    assert result["setting"]["inputs"]["image"] == "mars.png"
    assert values["REFERENCE_IMAGES"] == ["frog.png", "mars.png"]


def test_shot_references_are_deterministic():
    uploaded = {
        ("character", "Pip"): "pip.png",
        ("setting", "Mars"): "mars.png",
    }

    references = references_for_shot(
        {"title": "Charge", "characters": ["Pip"], "setting": "Mars"}, uploaded
    )

    assert references["all"] == ["pip.png", "mars.png"]
