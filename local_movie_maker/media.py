from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class MediaError(RuntimeError):
    pass


class MediaTools:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        if shutil.which(ffmpeg) is None:
            raise MediaError(f"FFmpeg executable not found: {ffmpeg}")

    def placeholder(self, destination: Path, width: int, height: int, seed: int) -> Path:
        hue = seed % 360
        # Stable dark colors make demo output distinct without needing Pillow.
        red = 18 + (hue * 37 % 42)
        green = 24 + (hue * 53 % 52)
        blue = 34 + (hue * 71 % 62)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x{red:02x}{green:02x}{blue:02x}:s={width}x{height}",
                "-frames:v",
                "1",
                str(destination),
            ]
        )
        return destination

    def normalize_clip(
        self, source: Path, destination: Path, duration: int, width: int, height: int
    ) -> Path:
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps=24,format=yuv420p"
        )
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(source),
                "-vf",
                vf,
                "-t",
                str(duration),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "19",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(destination),
            ]
        )
        return destination

    def extract_first_frame(self, source: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(source),
                "-frames:v",
                "1",
                str(destination),
            ]
        )
        return destination

    def assemble(self, clips: list[Path], audio: Path | None, destination: Path) -> Path:
        if not clips:
            raise MediaError("There are no clips to assemble.")
        concat_file = destination.parent / "clips.txt"
        concat_file.write_text(
            "".join(f"file '{_concat_escape(path.resolve())}'\n" for path in clips),
            encoding="utf-8",
        )
        joined = destination.with_name("joined.mp4") if audio else destination
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(joined),
            ]
        )
        if audio is None:
            return destination
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(joined),
                "-i",
                str(audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                "-movflags",
                "+faststart",
                str(destination),
            ]
        )
        joined.unlink(missing_ok=True)
        return destination

    def duration(self, path: Path) -> float:
        result = subprocess.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(json.loads(result.stdout)["format"]["duration"])

    @staticmethod
    def _run(command: list[str]) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "Unknown FFmpeg error")[-2_000:]
            raise MediaError(detail.strip()) from exc


def _concat_escape(path: Path) -> str:
    return str(path).replace("'", "'\\''")
