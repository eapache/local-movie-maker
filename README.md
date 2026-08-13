# Local Movie Maker

Local Movie Maker turns a short prompt into a finished video using AI services on
your own machine:

- [llama.cpp](https://github.com/ggml-org/llama.cpp) writes the story and shot plan.
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) creates reference art,
  video clips, dialogue, and background audio.
- [FFmpeg](https://ffmpeg.org/) mixes the audio and assembles the final MP4.

The web interface shows progress, the production book, reference images, the
shot list, and the finished video. Everything is stored locally in `projects/`.

## Quick start

This guide assumes llama.cpp and ComfyUI run locally on their usual ports:

| Service | Address |
| --- | --- |
| llama.cpp | `http://127.0.0.1:8080` |
| ComfyUI | `http://127.0.0.1:8188` |
| Local Movie Maker | `http://127.0.0.1:8090` |

You will need Python 3.11 or newer, FFmpeg, a llama.cpp-compatible language
model, and working ComfyUI image, reference-video, and audio workflows. The app
itself has no third-party Python runtime dependencies.

### 1. Start llama.cpp

From your llama.cpp installation, load a model and listen on port 8080:

```bash
./llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 8080
```

A llama.cpp router on the same port works too. Local Movie Maker discovers its
available models automatically.

### 2. Start ComfyUI

From your ComfyUI installation, listen on port 8188:

```bash
python3 main.py --listen 127.0.0.1 --port 8188
```

Local Movie Maker needs three executable ComfyUI workflows:

- a text-to-image workflow for character and setting references;
- a text-and-reference-to-video workflow for each shot;
- a text-to-audio workflow for background music or ambience.

If those workflows are already saved in API format, you are ready. Otherwise,
open each working graph in ComfyUI, enable **Dev Mode**, choose **File → Export
(API)**, and put the downloaded JSON in your active ComfyUI user workflow folder
(commonly `ComfyUI/user/default/workflows/`). Use a distinct filename so you do
not overwrite the editable UI graph.

### 3. Start Local Movie Maker

From this repository:

```bash
python3 run.py
```

Open <http://127.0.0.1:8090>. Expand **Advanced models & workflows**, then select:

1. the llama.cpp story model;
2. the reference image workflow;
3. the reference video workflow;
4. the background audio workflow.

For a quick first run, choose a short duration and 540p resolution, enter a
prompt, and click **Make film**. GPU-heavy projects are processed one at a time.

> If a workflow appears as **UI format (Export API)**, ComfyUI cannot execute it
> through its remote prompt API. Export that workflow as described above, copy
> the resulting JSON into the workflow folder, and refresh the selections.

## What happens after you click Make film

```text
prompt → story, continuity, scenes, and shots             llama.cpp
       → character and setting reference images           ComfyUI
       → video clips plus scene-sized background audio    ComfyUI
       → mixed and assembled final.mp4                     FFmpeg
```

The video workflow's own audio is kept for dialogue and diegetic sound.
Background tracks are mixed underneath it and ducked during dialogue. Completed
work remains in `projects/<id>/` if a run is interrupted.

<details>
<summary><strong>Use non-default service addresses</strong></summary>

Set the service URLs before starting the app:

```bash
export LLAMA_URL=http://192.168.1.20:8080
export COMFY_URL=http://192.168.1.21:8188
python3 run.py
```

See [Configuration and reference](docs/configuration.md) for persistent workflow
defaults, managed service commands, timeouts, and every other setting.

</details>

<details>
<summary><strong>Let Local Movie Maker start and stop the AI services</strong></summary>

This is useful when llama.cpp and ComfyUI share one GPU. Configure commands for
both services and default workflow files, then run the app normally:

```bash
export LLAMA_SERVER_COMMAND='/opt/llama.cpp/llama-server -m /models/writer.gguf --host 127.0.0.1 --port 8080'
export COMFY_SERVER_COMMAND='python3 /opt/ComfyUI/main.py --listen 127.0.0.1 --port 8188'
export COMFY_IMAGE_WORKFLOW="$PWD/workflows/reference-image-api.json"
export COMFY_VIDEO_WORKFLOW="$PWD/workflows/reference-video-api.json"
export COMFY_BACKGROUND_AUDIO_WORKFLOW="$PWD/workflows/background-audio-api.json"
python3 run.py
```

Local Movie Maker runs all llama.cpp planning first, releases that model, starts
ComfyUI for media generation, and stops ComfyUI when the film is complete.

</details>

## More documentation

- [Configuration and reference](docs/configuration.md) — workflow requirements,
  placeholders, environment variables, service lifecycle, pipeline details, and
  HTTP API.
- [.env.example](.env.example) — copyable list of common settings.

## Development

Run the test suite with:

```bash
pytest -q
```
