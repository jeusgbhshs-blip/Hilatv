"""Clipped audio must be detected. Character error rate uses the 2% line."""

from __future__ import annotations

import io
import math
import struct
import wave

from workers.nodes.n06_voiceover.audio import (
    CER_LIMIT,
    analyze_wav,
    character_error_rate,
    is_clipped,
    pcm_samples,
)


def _wav(samples: list[int], rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
    return buf.getvalue()


def _tone(count: int = 1600) -> list[int]:
    return [int(6000 * math.sin(2 * math.pi * 220 * index / 16000)) for index in range(count)]


def test_planted_full_scale_samples_are_clipped() -> None:
    tone = _tone()
    clean = _wav(tone)
    planted = _wav([*tone, 32767, *tone[:10]])
    assert is_clipped(pcm_samples(clean)[0]) is False
    assert is_clipped(pcm_samples(planted)[0]) is True
    clipped = analyze_wav(planted)
    assert clipped.clipped is True
    quiet = analyze_wav(clean)
    assert quiet.clipped is False
    assert -28.0 <= quiet.loudness_dbfs <= -12.0


def test_negative_rail_is_clipped() -> None:
    assert is_clipped([-32768, 0, 1000]) is True
    assert is_clipped([32766, -32766]) is False


def test_character_error_rate_threshold() -> None:
    perfect = "柱塞泵压力三十兆帕。"
    assert character_error_rate(perfect, perfect) == 0
    assert character_error_rate(perfect, "柱塞泵压力三十兆帕") == 0
    reference = "测" * 100
    one = ("测" * 99) + "错"
    assert character_error_rate(reference, one) == 0.01
    assert character_error_rate(reference, one) < CER_LIMIT
    fifty = "测" * 50
    one_in_fifty = ("测" * 49) + "错"
    rate = character_error_rate(fifty, one_in_fifty)
    assert rate == 0.02
    assert rate >= CER_LIMIT
    assert character_error_rate("泵体参数", "完全不同") > CER_LIMIT
    assert character_error_rate("Built for 30 MPa.", "built for 30 mpa") == 0
