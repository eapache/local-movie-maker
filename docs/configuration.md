# Configuration and reference

The [README](../README.md) covers the normal setup: llama.cpp on port 8080,
ComfyUI on port 8188, and Local Movie Maker on port 8090. This document contains
the settings and integration details that are useful after that first run.

## Configuration

Settings are read from environment variables when Local Movie Maker starts. The
most commonly changed values are also listed in [`.env.example`](../.env.example).
The app does not load that file automatically; export the values in your shell or
use your usual environment-file tooling.

### Web server

| Variable | Default | Purpose |
| --- | --- | --- |
| `MOVIE_MAKER_HOST` | `127.0.0.1` | Web server bind address |
| `MOVIE_MAKER_PORT` | `8090` | Web server port |
| `MOVIE_MAKER_PROJECTS_DIR` | `./projects` | Project and generated-media directory |
| `MOVIE_MAKER_DEMO` | `0` | Use synthetic planning and reference placeholders; video generation remains disabled |
| `FFMPEG` | `ffmpeg` | FFmpeg executable path |
| `FFPROBE` | `ffprobe` | ffprobe executable path |

### llama.cpp

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLAMA_URL` | `http://127.0.0.1:8080` | OpenAI-compatible llama.cpp server |
| `LLAMA_MODEL` | discovered | Machine-wide story-model default |
| `LLAMA_SERVER_COMMAND` | unset | Command Local Movie Maker uses to start llama.cpp |
| `LLAMA_UNLOAD_URL` | built-in behavior | Optional POST endpoint for an external model loader |
| `LLAMA_STARTUP_TIMEOUT` | `180` | Managed-server startup timeout in seconds |

The app reads `/v1/models`, including llama.cpp router presets. A router can
autoload the selected model. After planning, current router builds are asked to
release it through `/models/unload`; classic single-model servers fall back to
clearing their context slots. Set `LLAMA_UNLOAD_URL` when a separately managed
loader needs a different release endpoint.

### ComfyUI

| Variable | Default | Purpose |
| --- | --- | --- |
| `COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI server |
| `COMFY_SERVER_COMMAND` | unset | Command Local Movie Maker uses to start ComfyUI |
| `COMFY_STARTUP_TIMEOUT` | `180` | Managed-server startup timeout in seconds |
| `COMFY_TIMEOUT` | `900` | Individual workflow timeout in seconds |
| `COMFY_IMAGE_WORKFLOW` | selected in UI | Reference-image API JSON path |
| `COMFY_VIDEO_WORKFLOW` | selected in UI | Reference-video API JSON path |
| `COMFY_BACKGROUND_AUDIO_WORKFLOW` | selected in UI | Background-audio API JSON path |
| `COMFY_VIDEO_SEGMENT_SECONDS` | `15` | Maximum duration of each independently generated shot |
| `COMFY_CHECKPOINT` | discovered | Value for workflows using `{{CHECKPOINT}}` |

Selections under **Advanced models & workflows** apply only to that film.
Environment variables provide machine-wide defaults and remove the need to make
the corresponding selection in the browser.

## ComfyUI workflow setup

### Export an executable API workflow

ComfyUI's normal **Save** and **Save As** commands create editable UI graphs, but
its remote prompt endpoint requires flattened API graphs.

1. Enable **Dev Mode** in ComfyUI settings.
2. Open and test the workflow.
3. Choose **File → Export (API)**. The command downloads a JSON file; it does not
   add the API graph to ComfyUI's saved-workflow list.
4. Either set the matching `COMFY_*_WORKFLOW` variable to that file, or copy it
   into the active ComfyUI user workflow directory (commonly
   `ComfyUI/user/default/workflows/`). Give it a distinct name such as
   `portrait-api.json` so it does not overwrite the editable graph.
5. If you copied it into ComfyUI, refresh **Advanced models & workflows** in
   Local Movie Maker and select it.

UI-format workflows are displayed but disabled with an **Export API** label.
Local Movie Maker does not attempt to flatten arbitrary custom nodes and
subgraphs because doing so can change graph behavior.

### Workflow types

Every film requires all three of these executable API graphs:

- **Reference image:** a text-to-image workflow used for every character and
  setting.
- **Reference video:** a workflow that begins each shot from text plus character
  and setting references. Pure text-to-video and keyframe-based image-to-video
  graphs may be discovered but are not offered as movie workflows.
- **Background audio:** a text-to-audio workflow used for scene-sized ambience or
  music cues.

ComfyUI installations and video/audio node packs vary substantially, so these
workflows are user-supplied. For ordinary API exports, Local Movie Maker injects
common prompt, reference, duration, frame count, output size, FPS, and seed
fields. Explicit placeholders support graphs with unusual field names.

### Workflow placeholders

Workflow files may contain `{{TOKEN}}` placeholders. A value that consists only
of a placeholder keeps its original number or list type; a placeholder embedded
in a longer string is replaced as text.

Reference-image workflows support:

| Token | Value |
| --- | --- |
| `{{PROMPT}}` | Production-ready visual prompt |
| `{{NEGATIVE_PROMPT}}` | Default quality exclusions |
| `{{SEED}}` | Stable per-asset seed |
| `{{CHECKPOINT}}` | `COMFY_CHECKPOINT` value |
| `{{WIDTH}}`, `{{IMAGE_WIDTH}}` | Generation width |
| `{{HEIGHT}}`, `{{IMAGE_HEIGHT}}` | Generation height |

Reference-video workflows support:

| Token | Value |
| --- | --- |
| `{{PROMPT}}` | Shot prompt |
| `{{REFERENCE_IMAGES}}` | List of relevant uploaded reference filenames |
| `{{REFERENCE_IMAGE}}`, `{{REFERENCE_IMAGE_1}}` … `{{REFERENCE_IMAGE_6}}` | References in character-then-setting order |
| `{{CHARACTER_REFERENCE_1}}` … `{{CHARACTER_REFERENCE_3}}` | Character reference filenames |
| `{{SETTING_REFERENCE}}` | Current setting reference filename |
| `{{DURATION}}` | Shot duration in seconds |
| `{{FRAMES}}` | Shot duration at 24 fps |
| `{{FPS}}` | `24` |
| `{{WIDTH}}`, `{{HEIGHT}}` | Final output dimensions |
| `{{SEED}}` | Stable per-shot seed |

LoadImage nodes may instead be titled **Character Reference 1** or **Setting
Reference** for automatic injection. The standard MiniMax H3
reference-to-video graph is recognized from its `ref_images.ref_image_*`
connections; linked LoadImage nodes are populated in that input order.

Background-audio workflows support:

| Token | Value |
| --- | --- |
| `{{PROMPT}}` | Scene audio prompt |
| `{{DURATION}}`, `{{SECONDS}}` | Cue duration in seconds |
| `{{SEED}}` | Stable per-cue seed |

## Managed service lifecycle

When llama.cpp and ComfyUI share a GPU, Local Movie Maker can own both processes:

```bash
export LLAMA_SERVER_COMMAND='/opt/llama.cpp/llama-server -m /models/writer.gguf --host 127.0.0.1 --port 8080'
export COMFY_SERVER_COMMAND='python3 /opt/ComfyUI/main.py --listen 127.0.0.1 --port 8188'
export COMFY_IMAGE_WORKFLOW="$PWD/workflows/reference-image-api.json"
export COMFY_VIDEO_WORKFLOW="$PWD/workflows/reference-video-api.json"
export COMFY_BACKGROUND_AUDIO_WORKFLOW="$PWD/workflows/background-audio-api.json"
python3 run.py
```

For each queued film, the app starts llama.cpp and finishes all structured
writing before it starts ComfyUI. The ComfyUI process is stopped when the film is
finished. GPU-heavy projects run one at a time.

Films up to five minutes use a compact treatment, bible, and shot-list path.
Longer films use a hierarchical path: a multi-page overview and chapters, a
larger continuity bible, per-chapter scene lists, a screenplay for every scene,
and independently prompted shots for every scene.

## Pipeline behavior

```text
prompt + duration + resolution
             │
             ▼
  overview + chapters → continuity bible              llama.cpp
             │
  scene lists → per-scene scripts → prompted shots     llama.cpp
             │
             ▼  model/context released
  all character + setting reference images            ComfyUI image phase
             │
             ▼
  text + relevant refs → capped video clips            ComfyUI video phase
             └── scene-spanning background audio ───── ComfyUI T2A
                              │
                              ▼
                         final.mp4                      FFmpeg
```

All reference images are generated before video begins, allowing ComfyUI to keep
the image model hot and then transition to video generation once. References are
uploaded once and reused for every matching shot.

Each planned shot is capped at `COMFY_VIDEO_SEGMENT_SECONDS`. Longer action is
expressed as additional independently generated shots; prior-keyframe or
continuation workflows are not used. Audio produced by the video workflow is
preserved for dialogue and diegetic sound. Background tracks are mixed below it
and ducked during dialogue.

Generated state is updated atomically in `projects/<id>/project.json`. If the app
is interrupted, finished work remains available and an in-flight project is
marked failed on the next start instead of silently appearing stuck. No
synthetic media is substituted for a missing model or workflow outside demo
mode.

## HTTP API

- `POST /api/projects` accepts
  `{"prompt":"...","duration":30,"resolution":"720p"}`. It may also include
  `llama_model`, `image_workflow`, `video_workflow`,
  `background_audio_workflow`, and `checkpoint` selections.
- `GET /api/integrations` discovers llama.cpp models, ComfyUI checkpoints, and
  saved workflows.
- `GET /api/projects/<id>` returns status, progress, plan, assets, errors, and the
  final URL.
- `GET /api/projects` returns the 20 most recent projects.
- `GET /media/<id>/...` serves generated project media with video byte-range
  support.

Duration may be from 5 seconds through 90 minutes. Resolution IDs are `540p`,
`720p`, `1080p`, and `square`; the current browser interface presents the three
landscape options.
