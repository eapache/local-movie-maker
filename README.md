# Local Movie Maker

A small, local-first web studio that turns a short prompt into a finished video. It uses:

- **llama.cpp** for the treatment, continuity bible, characters, locations, and shot script.
- **ComfyUI** for reference art, shot keyframes, and optionally native video and music.
- **FFmpeg** for consistent clip formatting, soundtrack fallback, and final assembly.

The browser shows live progress, the generated production book, reference images, shot list, and a downloadable MP4. Projects and intermediate media are kept on disk in `projects/`.

## Quick start

Python 3.11+ and FFmpeg are required. The app itself has no third-party Python runtime dependencies.

With llama.cpp already listening on port 8080 and ComfyUI on port 8188:

```bash
python3 run.py
```

Open <http://127.0.0.1:8090>. The app discovers llama.cpp models and ComfyUI image/video workflows. Open **Advanced models & workflows** to override its selections.

Run the tests with:

```bash
pytest -q
```

## Connect llama.cpp and ComfyUI

No model names are hard-coded. By default the app reads llama.cpp's `/v1/models` (including router presets) and ComfyUI's saved workflows. Executable T2I workflows are preferred for reference images and shot keyframes; the included checkpoint-based image workflow remains the fallback. A choice in the Advanced panel applies to that film; environment variables set machine-wide defaults.

The easiest setup when the services are not already running and both systems share a GPU is to let this app own their processes:

```bash
export LLAMA_SERVER_COMMAND='/opt/llama.cpp/llama-server -m /models/writer.gguf --host 127.0.0.1 --port 8080'
export COMFY_SERVER_COMMAND='python3 /opt/ComfyUI/main.py --listen 127.0.0.1 --port 8188'
export COMFY_VIDEO_WORKFLOW="$PWD/workflows/my-video-api.json"
python3 run.py
```

For every queued film, the app starts llama.cpp, makes three structured planning calls, and terminates it. Only then does it start ComfyUI. The ComfyUI process is also stopped when the film is finished. GPU-heavy projects run one at a time.

If the services run elsewhere, use `LLAMA_URL` and `COMFY_URL`. With current llama.cpp router builds, the selected model is autoloaded and then released through `/models/unload` before ComfyUI rendering. Classic single-model servers fall back to clearing their context slots; `LLAMA_UNLOAD_URL` can override that behavior. See [.env.example](.env.example) for every option.

## ComfyUI workflows

The included [`workflows/image.json`](workflows/image.json) uses standard ComfyUI nodes and whichever installed checkpoint is selected. It is a fallback: when the app discovers an executable saved T2I workflow, the browser selects that workflow instead. Set `COMFY_IMAGE_WORKFLOW` to an exported API JSON file to replace the built-in fallback; it remains available as **Use configured image workflow** in the Advanced panel.

### Exporting API workflows

The app lists workflows from ComfyUI's `userdata` API and recognizes T2I, image-to-video, and text-to-video graphs. ComfyUI's normal **Save** and **Save As** commands store editable UI graphs; its remote prompt endpoint requires a flattened API graph.

1. Enable **Dev Mode** in ComfyUI settings.
2. Open and test the image or video workflow.
3. Open ComfyUI's **File** menu and choose **Export (API)**. If that is the API export action you already see, it is the correct one—current ComfyUI does not call it **Save (API Format)**. Export downloads a JSON file; it does not add the API graph to ComfyUI's saved-workflow list.
4. Set the corresponding workflow environment variable to that downloaded file, or copy it into the active ComfyUI user workflow directory (commonly `ComfyUI/user/default/workflows/`) under a distinct name such as `portrait-api.json` so it does not overwrite the editable UI graph.
5. If you copied it into ComfyUI, open **Advanced models & workflows** in Local Movie Maker, refresh, and select it.

UI-format workflows are shown but disabled with an “Export API” label. This is intentional: silently guessing how to flatten arbitrary custom nodes and subgraphs can change a graph's behavior. A native video workflow is required; there is no still-image motion fallback.

Workflow files are ordinary ComfyUI API JSON with `{{TOKEN}}` placeholders. An exact placeholder retains its number type; placeholders embedded in longer strings are replaced as text.

Image workflows can use:

| Token | Meaning |
| --- | --- |
| `{{PROMPT}}` | Production-ready visual prompt |
| `{{NEGATIVE_PROMPT}}` | Default quality exclusions |
| `{{SEED}}` | Stable per-asset seed |
| `{{CHECKPOINT}}` | `COMFY_CHECKPOINT` value |
| `{{WIDTH}}`, `{{IMAGE_WIDTH}}` | Generation width |
| `{{HEIGHT}}`, `{{IMAGE_HEIGHT}}` | Generation height |

The primary video workflow begins each shot from text plus the generated character
and setting references. It receives:

| Token | Meaning |
| --- | --- |
| `{{REFERENCE_IMAGES}}` | List of relevant uploaded reference filenames |
| `{{REFERENCE_IMAGE}}`, `{{REFERENCE_IMAGE_1}}` … `{{REFERENCE_IMAGE_6}}` | Relevant references in character-then-setting order |
| `{{CHARACTER_REFERENCE_1}}` … `{{CHARACTER_REFERENCE_3}}` | Character reference filenames |
| `{{SETTING_REFERENCE}}` | Current setting reference filename |
| `{{DURATION}}` | Shot length in seconds |
| `{{FRAMES}}` | Shot length at 24 fps |
| `{{FPS}}` | `24` |
| `{{WIDTH}}`, `{{HEIGHT}}` | Final output dimensions |

The optional continuation workflow receives all of the same values plus
`{{KEYFRAME_IMAGE}}` (also available as the legacy `{{IMAGE}}` alias). It is used
only when a planned shot is longer than `COMFY_VIDEO_SEGMENT_SECONDS`; the
keyframe is extracted from the prior segment's final frame rather than generated
independently. LoadImage nodes may alternatively be titled **Character Reference
1**, **Setting Reference**, or **Continuation Keyframe** for automatic injection.

Audio workflows receive `{{PROMPT}}`, `{{DURATION}}`, `{{SECONDS}}`, and `{{SEED}}`.

Set the optional workflow paths before starting the app:

```bash
export COMFY_VIDEO_WORKFLOW="$PWD/workflows/my-video-api.json"
export COMFY_CONTINUATION_WORKFLOW="$PWD/workflows/my-continuation-api.json"
export COMFY_AUDIO_WORKFLOW="$PWD/workflows/my-audio-api.json"
python3 run.py
```

ComfyUI installations and video/audio node packs vary substantially, which is why those workflows are user-supplied. Pure T2V and ordinary keyframe-only I2V graphs are discovered but are not offered as primary movie workflows: the primary graph must accept references, and the continuation graph must accept references plus a keyframe. For ordinary saved API exports, the app injects common prompt, reference, duration/frame-count, size, FPS, and seed fields. Explicit `{{TOKEN}}` placeholders remain available when a graph uses unusual names.

All character and setting images are generated before any video job is queued, so
ComfyUI can keep the image model hot and then transition to video generation only
once. References are uploaded once and reused across every matching shot. Audio
produced by a video workflow is preserved; an optional audio workflow can supply
a separate score. No synthetic media is substituted for missing generative models.

## Pipeline

```text
prompt + duration + resolution
             │
             ▼
  treatment → continuity bible → timed shot script     llama.cpp
             │
             ▼  model/context released
  all character + setting reference images            ComfyUI image phase
             │
             ▼
  text + relevant refs → video clips                   ComfyUI video phase
             │                │ long shot only
             │                └─ last frame → continuation
             └──────── score ───────────────────────── ComfyUI or fallback
                              │
                              ▼
                         final.mp4                      FFmpeg
```

Generated state is updated atomically in `projects/<id>/project.json`. If the app is interrupted, completed work remains available and an in-flight project is marked failed on the next start instead of silently appearing stuck.

## HTTP API

- `POST /api/projects` — accepts `{"prompt":"...","duration":30,"resolution":"720p"}` plus optional `llama_model`, `image_workflow`, `checkpoint`, `video_workflow`, and `continuation_workflow` selections.
- `GET /api/integrations` — discovers llama.cpp models, ComfyUI checkpoints, and saved workflows.
- `GET /api/projects/<id>` — returns status, progress, plan, assets, errors, and final URL.
- `GET /api/projects` — returns the 20 most recent projects.
- `GET /media/<id>/...` — serves generated project media with video byte-range support.

Resolution ids are `540p`, `720p`, `1080p`, `vertical`, and `square`; the current UI presents the first four.
