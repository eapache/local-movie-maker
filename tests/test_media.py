from local_movie_maker.media import MediaTools


def media_tools() -> MediaTools:
    tools = object.__new__(MediaTools)
    tools.ffmpeg = "ffmpeg"
    tools.ffprobe = "ffprobe"
    return tools


def test_background_audio_is_loudness_normalized(tmp_path):
    tools = media_tools()
    commands: list[list[str]] = []
    tools._run = commands.append  # type: ignore[method-assign]

    tools.normalize_audio(tmp_path / "raw.wav", tmp_path / "track.m4a", 12)

    command = commands[0]
    assert command[command.index("-af") + 1] == (
        "loudnorm=I=-24:TP=-2:LRA=7,aresample=48000"
    )


def test_native_clip_audio_is_dialogue_normalized(tmp_path):
    tools = media_tools()
    commands: list[list[str]] = []
    tools._run = commands.append  # type: ignore[method-assign]

    tools.normalize_clip(
        tmp_path / "raw.mp4", tmp_path / "clip.mp4", 12, 1280, 720
    )

    command = commands[0]
    assert command[command.index("-af") + 1] == (
        "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"
    )


def test_final_mix_ducks_voice_band_and_limits_peaks(tmp_path):
    tools = media_tools()
    commands: list[list[str]] = []
    tools._run = commands.append  # type: ignore[method-assign]
    tools.duration = lambda _path: 5.0  # type: ignore[method-assign]
    tools.has_audio = lambda _path: True  # type: ignore[method-assign]

    tools.assemble(
        [tmp_path / "clip.mp4"],
        [(tmp_path / "music.m4a", 0, 5)],
        tmp_path / "final.mp4",
    )

    mix_command = commands[1]
    graph = mix_command[mix_command.index("-filter_complex") + 1]
    assert "volume=0.28" not in graph
    assert "highpass=f=120,lowpass=f=4000" in graph
    assert "sidechaincompress=threshold=0.03:ratio=8" in graph
    assert "alimiter=limit=0.95" in graph
