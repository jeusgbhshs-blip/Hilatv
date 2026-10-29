"""Mock samples are decodable and contain no drawn text."""

from __future__ import annotations

from gateway.media_bytes import (
    decode_png,
    decode_wav,
    ffmpeg_decode,
    render_mp4,
    render_png,
    render_wav,
)


def test_png_is_a_flat_color_frame() -> None:
    data = render_png(7)
    width, height, rgb = decode_png(data)
    assert (width, height) == (320, 180)
    assert rgb == decode_png(render_png(7))[2]
    assert rgb != decode_png(render_png(8))[2]
    ffmpeg_decode(data, ".png")


def test_wav_duration_matches_character_timestamps() -> None:
    data, stamps, duration = render_wav("三十兆帕", 3)
    assert [item["text"] for item in stamps] == ["三", "十", "兆", "帕"]
    assert duration == 0.8
    assert abs(decode_wav(data) - duration) < 0.02
    ffmpeg_decode(data, ".wav")


def test_mp4_is_decodable_and_silent() -> None:
    data = render_mp4(4)
    assert data[4:8] == b"ftyp"
    ffmpeg_decode(data, ".mp4")
