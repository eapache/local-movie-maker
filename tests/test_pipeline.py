from dataclasses import replace

from local_movie_maker.config import Settings
from local_movie_maker.models import Project, ProjectRequest
from local_movie_maker.pipeline import MoviePipeline
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
