import json

import pytest

import local_movie_maker.clients as clients
from local_movie_maker.clients import (
    ApiError,
    ComfyClient,
    LlamaClient,
    describe_workflow,
    parse_json_object,
)


def test_parse_json_object_accepts_fenced_response():
    assert parse_json_object('```json\n{"title": "Film"}\n```') == {"title": "Film"}


def test_parse_json_object_rejects_non_json():
    with pytest.raises(ApiError):
        parse_json_object("Certainly! Here is the result.")


def test_llama_json_completion_preserves_reasoning_with_unlimited_budget(monkeypatch):
    seen = {}

    def fake_request_json(url, **kwargs):
        if url.endswith("/v1/models"):
            return {"data": [{"id": "writer"}]}
        seen.update(kwargs["payload"])
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": '{"title":"Film"}'}}
            ]
        }

    monkeypatch.setattr(clients, "request_json", fake_request_json)

    result = LlamaClient("http://llama.test").complete_json("system", "prompt")

    assert result == {"title": "Film"}
    assert seen["max_tokens"] == -1
    assert "reasoning_effort" not in seen
    assert "chat_template_kwargs" not in seen


def test_llama_json_completion_explains_reasoning_budget_exhaustion(monkeypatch):
    def fake_request_json(url, **kwargs):
        if url.endswith("/v1/models"):
            return {"data": [{"id": "writer"}]}
        return {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "", "reasoning_content": "Still thinking"},
                }
            ]
        }

    monkeypatch.setattr(clients, "request_json", fake_request_json)

    with pytest.raises(ApiError, match="context limit while reasoning"):
        LlamaClient("http://llama.test").complete_json("system", "prompt")


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
