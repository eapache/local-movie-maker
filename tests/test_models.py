import pytest

from local_movie_maker.models import ProjectRequest
from local_movie_maker.planning import normalize_plan


def test_project_request_validation():
    request = ProjectRequest.from_dict(
        {"prompt": "A small story", "duration": "30", "resolution": "720p"}
    )
    assert request.duration == 30

    with pytest.raises(ValueError, match="Prompt"):
        ProjectRequest.from_dict({"prompt": "x", "duration": 30, "resolution": "720p"})
    with pytest.raises(ValueError, match="Resolution"):
        ProjectRequest.from_dict({"prompt": "valid prompt", "duration": 30, "resolution": "8k"})


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
