from __future__ import annotations

import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class ApiError(RuntimeError):
    pass


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any] | list[Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1_000]
        raise ApiError(f"{method} {url} returned {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ApiError(f"Could not call {url}: {exc}") from exc


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ApiError("llama.cpp returned text without a JSON object.")
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ApiError(f"llama.cpp returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ApiError("llama.cpp returned JSON, but it was not an object.")
    return value


class LlamaClient:
    def __init__(self, base_url: str, model: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def loaded_models(self, timeout: int = 30) -> list[str]:
        response = request_json(f"{self.base_url}/v1/models", timeout=timeout)
        return _model_ids(response)

    def available_models(self, timeout: int = 30) -> list[str]:
        # Current llama.cpp routers expose the full cache at /models, while a
        # classic single-model llama-server exposes its loaded model at
        # /v1/models. Return loaded models first and support both variants.
        loaded: list[str] = []
        available: list[str] = []
        first_error: ApiError | None = None
        try:
            loaded = self.loaded_models(timeout)
        except ApiError as exc:
            first_error = exc
        try:
            available = _model_ids(request_json(f"{self.base_url}/models", timeout=timeout))
        except ApiError:
            if not loaded and first_error is not None:
                raise first_error
        return list(dict.fromkeys([*loaded, *available]))

    def resolve_model(self) -> str:
        if self.model:
            return self.model
        models = self.loaded_models()
        if not models:
            models = self.available_models()
        if not models:
            raise ApiError(
                "llama.cpp reported no models. Load one with llama-server -m, "
                "or set LLAMA_MODEL."
            )
        self.model = models[0]
        return self.model

    def complete_json(self, system: str, prompt: str, *, max_tokens: int = 4_096) -> dict[str, Any]:
        model = self.resolve_model()
        response = request_json(
            f"{self.base_url}/v1/chat/completions",
            method="POST",
            payload={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=300,
        )
        try:
            content = response["choices"][0]["message"]["content"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError) as exc:
            raise ApiError("llama.cpp returned an unexpected chat-completions response.") from exc
        return parse_json_object(str(content))

    def unload(self, unload_url: str | None = None) -> None:
        if unload_url:
            request_json(unload_url, method="POST", payload={}, timeout=30)
            return
        # Router-mode llama.cpp has a real model lifecycle API. Prefer it so GPU
        # weights are released before ComfyUI work begins.
        if self.model:
            try:
                request_json(
                    f"{self.base_url}/models/unload",
                    method="POST",
                    payload={"model": self.model},
                    timeout=30,
                )
                return
            except ApiError:
                pass
        # An external llama-server cannot unload its weights through the OpenAI API.
        # Clear each slot so the expensive prompt context is released. A managed
        # server is terminated by ManagedService instead.
        try:
            slots = request_json(f"{self.base_url}/slots", timeout=10)
            if isinstance(slots, list):
                for slot in slots:
                    slot_id = slot.get("id") if isinstance(slot, dict) else None
                    if slot_id is not None:
                        request_json(
                            f"{self.base_url}/slots/{slot_id}?action=erase",
                            method="POST",
                            payload={},
                            timeout=10,
                        )
        except ApiError:
            # Slot cleanup is best-effort for llama.cpp builds without /slots.
            pass


class ComfyClient:
    def __init__(self, base_url: str, timeout: int = 900):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex

    def available_checkpoints(self, timeout: int = 30) -> list[str]:
        try:
            response = request_json(f"{self.base_url}/models/checkpoints", timeout=timeout)
            if isinstance(response, list):
                names = [str(item) for item in response if isinstance(item, str)]
                if names:
                    return names
        except ApiError:
            pass
        info = request_json(
            f"{self.base_url}/object_info/CheckpointLoaderSimple", timeout=timeout
        )
        try:
            node = info["CheckpointLoaderSimple"]  # type: ignore[index]
            options = node["input"]["required"]["ckpt_name"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ApiError("ComfyUI did not report any CheckpointLoaderSimple models.") from exc
        if not isinstance(options, list):
            raise ApiError("ComfyUI returned an unexpected checkpoint list.")
        return [str(item) for item in options]

    def resolve_checkpoint(self, preferred: str | None = None) -> str:
        checkpoints = self.available_checkpoints()
        if preferred:
            if preferred not in checkpoints:
                raise ApiError(
                    f"ComfyUI checkpoint '{preferred}' is not installed. Available: "
                    f"{', '.join(checkpoints) or 'none'}."
                )
            return preferred
        if not checkpoints:
            raise ApiError(
                "ComfyUI reported no checkpoints. Install one under models/checkpoints, "
                "or set COMFY_CHECKPOINT."
            )
        return checkpoints[0]

    def saved_workflows(self, timeout: int = 30) -> list[dict[str, Any]]:
        response = request_json(
            f"{self.base_url}/userdata?dir=workflows&recurse=true", timeout=timeout
        )
        if not isinstance(response, list):
            raise ApiError("ComfyUI returned an unexpected saved-workflow list.")
        result: list[dict[str, Any]] = []
        for item in response:
            if not isinstance(item, str) or not item.lower().endswith(".json"):
                continue
            try:
                workflow = self.load_saved_workflow(item, timeout=timeout)
                result.append(describe_workflow(item, workflow))
            except ApiError as exc:
                result.append(
                    {
                        "id": f"saved:{item}",
                        "name": item,
                        "format": "unknown",
                        "kind": "unknown",
                        "executable": False,
                        "error": str(exc),
                    }
                )
        return result

    def load_saved_workflow(self, name: str, timeout: int = 30) -> dict[str, Any]:
        if not name or name.startswith(("/", ".")) or ".." in name.split("/"):
            raise ApiError("Invalid saved ComfyUI workflow name.")
        path = urllib.parse.quote(f"workflows/{name}", safe="")
        response = request_json(f"{self.base_url}/userdata/{path}", timeout=timeout)
        if not isinstance(response, dict):
            raise ApiError(f"Saved ComfyUI workflow is not a JSON object: {name}")
        return response

    @staticmethod
    def load_workflow(path: Path, values: dict[str, Any]) -> dict[str, Any]:
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ApiError(f"ComfyUI workflow not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ApiError(f"ComfyUI workflow is not valid JSON: {path}: {exc}") from exc

        tokens = {f"{{{{{key}}}}}": value for key, value in values.items()}

        def replace(item: Any) -> Any:
            if isinstance(item, dict):
                return {key: replace(value) for key, value in item.items()}
            if isinstance(item, list):
                return [replace(value) for value in item]
            if isinstance(item, str):
                if item in tokens:
                    return tokens[item]
                result = item
                for token, value in tokens.items():
                    result = result.replace(token, str(value))
                return result
            return item

        result = replace(workflow)
        if not isinstance(result, dict):
            raise ApiError(f"ComfyUI workflow root must be an object: {path}")
        return result

    def run_workflow(
        self,
        workflow_path: Path | dict[str, Any],
        values: dict[str, Any],
        destination: Path,
    ) -> Path:
        if isinstance(workflow_path, Path):
            workflow = self.load_workflow(workflow_path, values)
        else:
            workflow = replace_workflow_tokens(workflow_path, values)
        queued = request_json(
            f"{self.base_url}/prompt",
            method="POST",
            payload={"prompt": workflow, "client_id": self.client_id},
            timeout=30,
        )
        try:
            prompt_id = str(queued["prompt_id"])  # type: ignore[index]
        except (KeyError, TypeError) as exc:
            raise ApiError(f"ComfyUI did not return a prompt id: {queued}") from exc

        output = self._wait_for_output(prompt_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        query = urllib.parse.urlencode(
            {
                "filename": output["filename"],
                "subfolder": output.get("subfolder", ""),
                "type": output.get("type", "output"),
            }
        )
        try:
            with urllib.request.urlopen(f"{self.base_url}/view?{query}", timeout=120) as response:
                destination.write_bytes(response.read())
        except (urllib.error.URLError, OSError) as exc:
            raise ApiError(f"Could not download ComfyUI output: {exc}") from exc
        return destination

    def _wait_for_output(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            history = request_json(f"{self.base_url}/history/{prompt_id}", timeout=30)
            record = history.get(prompt_id) if isinstance(history, dict) else None
            if record:
                status = record.get("status", {})
                if status.get("status_str") == "error":
                    raise ApiError(f"ComfyUI workflow failed: {status}")
                outputs = record.get("outputs", {})
                for node in outputs.values():
                    if not isinstance(node, dict):
                        continue
                    for key in ("gifs", "videos", "audio", "images"):
                        candidates = node.get(key)
                        if candidates and isinstance(candidates, list):
                            return candidates[0]
                if status.get("completed"):
                    raise ApiError("ComfyUI completed without a downloadable output.")
            time.sleep(1)
        raise ApiError(f"ComfyUI did not finish within {self.timeout} seconds.")

    def upload_image(self, path: Path) -> str:
        boundary = f"----localmoviemaker{uuid.uuid4().hex}"
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
        body.extend(path.read_bytes())
        body.extend(f"\r\n--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue')
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            f"{self.base_url}/upload/image",
            data=bytes(body),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.loads(response.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise ApiError(f"Could not upload reference image to ComfyUI: {exc}") from exc
        return str(result.get("name", path.name))


def _model_ids(response: dict[str, Any] | list[Any]) -> list[str]:
    records: Any = response.get("data", []) if isinstance(response, dict) else response
    if not isinstance(records, list):
        return []
    result: list[str] = []
    for item in records:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and item.get("id"):
            result.append(str(item["id"]))
    return result


def replace_workflow_tokens(workflow: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Replace explicit tokens in an already-loaded API workflow."""
    tokens = {f"{{{{{key}}}}}": value for key, value in values.items()}

    def replace(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: replace(value) for key, value in item.items()}
        if isinstance(item, list):
            return [replace(value) for value in item]
        if isinstance(item, str):
            if item in tokens:
                return tokens[item]
            result = item
            for token, value in tokens.items():
                result = result.replace(token, str(value))
            return result
        return item

    result = replace(workflow)
    if not isinstance(result, dict):
        raise ApiError("ComfyUI workflow root must be an object.")
    return result


def describe_workflow(name: str, workflow: dict[str, Any]) -> dict[str, Any]:
    if isinstance(workflow.get("nodes"), list):
        workflow_format = "ui"
        nodes = list(workflow.get("nodes", []))
        for subgraph in workflow.get("definitions", {}).get("subgraphs", []):
            if isinstance(subgraph, dict):
                nodes.extend(subgraph.get("nodes", []))
        types = {str(node.get("type", "")) for node in nodes if isinstance(node, dict)}
        inputs = [
            str(value).lower()
            for node in nodes
            if isinstance(node, dict)
            for inp in node.get("inputs", [])
            if isinstance(inp, dict)
            for value in (inp.get("name", ""), inp.get("label", ""))
        ]
    elif workflow and all(
        isinstance(node, dict) and "class_type" in node for node in workflow.values()
    ):
        workflow_format = "api"
        types = {str(node.get("class_type", "")) for node in workflow.values()}
        inputs = [
            str(key).lower()
            for node in workflow.values()
            for key in node.get("inputs", {}).keys()
        ]
    else:
        workflow_format = "unknown"
        types = set()
        inputs = []

    lowered_types = " ".join(types).lower()
    has_video = any("video" in item.lower() for item in types)
    has_audio = any("audio" in item.lower() for item in types)
    # An IMAGE-typed edge is common inside both T2V and I2V graphs; an actual
    # LoadImage node is the reliable signal that the workflow needs a keyframe.
    has_image_input = "LoadImage" in types
    has_image_output = any(item in types for item in ("SaveImage", "PreviewImage"))
    if has_video:
        kind = "i2v" if has_image_input else "t2v"
    elif has_audio and any("save" in item.lower() for item in types):
        kind = "audio"
    elif has_image_output or "sampler" in lowered_types:
        kind = "image"
    else:
        kind = "unknown"
    return {
        "id": f"saved:{name}",
        "name": name,
        "format": workflow_format,
        "kind": kind,
        "executable": workflow_format == "api",
        "error": (
            None
            if workflow_format == "api"
            else "Saved in UI format; use File → Export (API) to make it executable."
        ),
    }
