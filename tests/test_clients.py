import json

import pytest

from local_movie_maker.clients import ApiError, ComfyClient, describe_workflow, parse_json_object


def test_parse_json_object_accepts_fenced_response():
    assert parse_json_object('```json\n{"title": "Film"}\n```') == {"title": "Film"}


def test_parse_json_object_rejects_non_json():
    with pytest.raises(ApiError):
        parse_json_object("Certainly! Here is the result.")


def test_workflow_token_substitution_preserves_numeric_types(tmp_path):
    workflow = tmp_path / "workflow.json"
    workflow.write_text(
        json.dumps({"1": {"inputs": {"seed": "{{SEED}}", "text": "Film: {{PROMPT}}"}}})
    )
    result = ComfyClient.load_workflow(workflow, {"SEED": 123, "PROMPT": "sunrise"})
    assert result["1"]["inputs"] == {"seed": 123, "text": "Film: sunrise"}


def test_saved_workflow_classification_distinguishes_t2v_and_i2v():
    t2v = {"nodes": [{"type": "SaveVideo", "inputs": []}], "definitions": {}}
    i2v = {
        "nodes": [
            {"type": "LoadImage", "inputs": []},
            {"type": "SaveVideo", "inputs": []},
        ],
        "definitions": {},
    }
    assert describe_workflow("t2v.json", t2v)["kind"] == "t2v"
    assert describe_workflow("i2v.json", i2v)["kind"] == "i2v"
