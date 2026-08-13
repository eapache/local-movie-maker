from dataclasses import replace
from pathlib import Path

from local_movie_maker.app import missing_required_integrations
from local_movie_maker.config import Settings
from local_movie_maker.models import ProjectRequest


def test_all_four_integrations_are_required_without_configured_defaults():
    settings = replace(
        Settings(),
        llama_model=None,
        image_workflow=None,
        video_workflow=None,
        background_audio_workflow=None,
    )
    request = ProjectRequest("A small story", 30, "720p")

    assert missing_required_integrations(request, settings) == [
        "story model",
        "reference image workflow",
        "reference video workflow",
        "background audio workflow",
    ]


def test_configured_defaults_satisfy_required_integrations():
    settings = replace(
        Settings(),
        llama_model="writer",
        image_workflow=Path("image.json"),
        video_workflow=Path("video.json"),
        background_audio_workflow=Path("audio.json"),
    )
    request = ProjectRequest("A small story", 30, "720p")

    assert missing_required_integrations(request, settings) == []
