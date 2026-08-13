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

    def normalize_audio(
        self, source: Path, destination: Path, duration: float
    ) -> Path:
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(source),
                "-t",
                str(duration),
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(destination),
            ]
        )
        return destination

    def assemble(
        self,
        clips: list[Path],
        background_audio: list[tuple[Path, float, float]],
        destination: Path,
    ) -> Path:
        if not clips:
            raise MediaError("There are no clips to assemble.")
        concat_file = destination.parent / "clips.txt"
        concat_file.write_text(
            "".join(f"file '{_concat_escape(path.resolve())}'\n" for path in clips),
            encoding="utf-8",
        )
        joined = destination.with_name("joined.mp4") if background_audio else destination
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
        if not background_audio:
            return destination
        total_duration = sum(self.duration(clip) for clip in clips)
        command = [self.ffmpeg, "-y", "-i", str(joined)]
        filters: list[str] = []
        labels: list[str] = []
        for index, (path, start, duration) in enumerate(background_audio, 1):
            command.extend(["-i", str(path)])
            delay = max(0, round(start * 1_000))
            label = f"background{index}"
            filters.append(
                f"[{index}:a]atrim=0:{duration},asetpts=PTS-STARTPTS,"
                f"adelay={delay}|{delay},volume=0.28[{label}]"
            )
            labels.append(f"[{label}]")
        if len(labels) == 1:
            filters.append(f"{labels[0]}anull[background]")
        else:
            filters.append(
                f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:"
                "dropout_transition=0[background]"
            )
        if self.has_audio(joined):
            filters.extend(
                [
                    "[background][0:a]sidechaincompress=threshold=0.04:ratio=8:"
                    "attack=20:release=400[ducked]",
                    "[0:a][ducked]amix=inputs=2:normalize=0:duration=first[mixed]",
                ]
            )
        else:
            filters.append("[background]anull[mixed]")
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "0:v:0",
                "-map",
                "[mixed]",
                "-t",
                str(total_duration),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(destination),
            ]
        )
        self._run(command)
        joined.unlink(missing_ok=True)
        return destination

    def has_audio(self, path: Path) -> bool:
        result = subprocess.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())

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
