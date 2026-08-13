import pytest

from local_movie_maker.config import RESOLUTIONS, Settings
from local_movie_maker.models import ProjectRequest
from local_movie_maker.planning import StoryPlanner, normalize_plan


def test_project_request_validation():
    request = ProjectRequest.from_dict(
        {
            "prompt": "A small story",
            "duration": "30",
            "resolution": "720p",
            "image_workflow": "saved:portrait-api.json",
            "background_audio_workflow": "saved:ambience-api.json",
        }
    )
    assert request.duration == 30
    assert request.image_workflow == "saved:portrait-api.json"
    assert request.background_audio_workflow == "saved:ambience-api.json"

    with pytest.raises(ValueError, match="Prompt"):
        ProjectRequest.from_dict({"prompt": "x", "duration": 30, "resolution": "720p"})
    with pytest.raises(ValueError, match="Resolution"):
        ProjectRequest.from_dict({"prompt": "valid prompt", "duration": 30, "resolution": "8k"})
    with pytest.raises(ValueError, match="90 minutes"):
        ProjectRequest.from_dict(
            {"prompt": "valid prompt", "duration": 5_401, "resolution": "720p"}
        )


def test_image_workflow_has_no_bundled_fallback(monkeypatch):
    monkeypatch.delenv("COMFY_IMAGE_WORKFLOW", raising=False)

    assert Settings().image_workflow is None


def test_portrait_resolution_is_not_available():
    assert "vertical" not in RESOLUTIONS
    with pytest.raises(ValueError, match="Resolution"):
        ProjectRequest.from_dict(
            {"prompt": "A portrait story", "duration": 30, "resolution": "vertical"}
        )


def test_normalized_shot_durations_match_requested_length():
    request = ProjectRequest("A compact story", 17, "720p")
    result = normalize_plan(
        request,
        {"title": "Test"},
        {"characters": [], "settings": []},
        {
            "shots": [
                {"action": "First", "duration": 8},
                {"action": "Second", "duration": 8},
                {"action": "Third", "duration": 8},
            ]
        },
    )
    assert sum(shot["duration"] for shot in result["shots"]) == 17
    assert all(shot["duration"] >= 1 for shot in result["shots"])


def test_normalized_shots_never_exceed_video_workflow_limit():
    request = ProjectRequest("A patient observation", 47, "720p")
    result = normalize_plan(
        request,
        {"title": "Test"},
        {"characters": [], "settings": []},
        {"shots": [{"title": "Long take", "action": "The day slowly changes"}]},
        max_shot_seconds=15,
    )
    assert sum(shot["duration"] for shot in result["shots"]) == 47
    assert max(shot["duration"] for shot in result["shots"]) <= 15
    assert len(result["shots"]) == 4


class LongFormClient:
    def complete_json(self, _system, prompt):
        if "multi-page story overview" in prompt:
            return {
                "title": "A Long Test",
                "overview": "A detailed story across two chapters.",
                "chapters": [
                    {"title": "Arrival", "summary": "The traveler arrives", "duration": 150},
                    {"title": "Return", "summary": "The traveler returns", "duration": 151},
                ],
            }
        if "continuity and production bible" in prompt:
            return {
                "characters": [{"name": "Traveler", "description": "Ochre coat"}],
                "settings": [{"name": "Station", "description": "Rainy platform"}],
            }
        if "Create the scene list" in prompt:
            return {
                "scenes": [
                    {"title": "First", "summary": "A choice", "duration": 75, "setting": "Station"},
                    {"title": "Second", "summary": "A consequence", "duration": 75, "setting": "Station"},
                ]
            }
        if "Write this scene" in prompt:
            return {
                "scene_text": "The Traveler crosses the platform and makes a choice.",
                "background_audio_prompt": "Rain and restrained strings",
            }
        if "Convert this written scene" in prompt:
            return {
                "shots": [
                    {
                        "title": "Platform",
                        "duration": 75,
                        "setting": "Station",
                        "characters": ["Traveler"],
                        "action": "The Traveler crosses the platform",
                        "prompt": "Ochre-coated traveler crossing a rainy platform",
                    }
                ]
            }
        raise AssertionError(prompt)


def test_long_form_planner_scaffolds_scenes_and_independent_shots():
    progress = []
    request = ProjectRequest("A traveler faces a long journey", 301, "720p")
    planner = StoryPlanner(LongFormClient(), max_shot_seconds=15)

    plan = planner.create(request, lambda stage, value, message: progress.append(stage))

    assert len(plan["chapters"]) == 2
    assert len(plan["scenes"]) == 4
    assert len(plan["background_audio"]) == 4
    assert sum(shot["duration"] for shot in plan["shots"]) == 301
    assert max(shot["duration"] for shot in plan["shots"]) <= 15
    assert all(shot["prompt"] for shot in plan["shots"])
    assert {"overview", "bible", "screenplay", "shotlist"} <= set(progress)
