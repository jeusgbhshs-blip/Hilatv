"""Loudness, clipping, and character-error rate for a voiceover take.

Loudness is RMS in dBFS. That stands in for integrated LUFS without an extra
dependency. A full-scale sample is clipping even when the average is still fine.
"""

from __future__ import annotations

import io
import math
import struct
import unicodedata
import wave
from collections.abc import Sequence
from dataclasses import dataclass

FRAME_S = 1 / 30
CER_LIMIT = 0.02
LOUDNESS_MIN_DB = -28.0
LOUDNESS_MAX_DB = -12.0
FULL_SCALE = 32767


@dataclass(frozen=True)
class AudioLevel:
    loudness_dbfs: float
    clipped: bool
    duration_s: float


def pcm_samples(data: bytes) -> tuple[list[int], int]:
    try:
        with wave.open(io.BytesIO(data)) as handle:
            rate = handle.getframerate()
            width = handle.getsampwidth()
            channels = handle.getnchannels()
            raw = handle.readframes(handle.getnframes())
    except wave.Error as exc:
        raise ValueError("wav could not be decoded") from exc
    if width != 2 or rate <= 0 or channels < 1:
        raise ValueError("expected 16-bit wav")
    count = len(raw) // 2
    samples = list(struct.unpack("<" + "h" * count, raw))
    if channels > 1:
        samples = samples[::channels]
    return samples, rate


def is_clipped(samples: Sequence[int]) -> bool:
    """True when any sample sits on the 16-bit rail."""

    return any(sample <= -FULL_SCALE or sample >= FULL_SCALE for sample in samples)


def loudness_dbfs(samples: Sequence[int], *, full_scale: float = 32768.0) -> float:
    if not samples:
        return -100.0
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    if mean_square <= 0:
        return -100.0
    rms = math.sqrt(mean_square)
    return 20 * math.log10(rms / full_scale)


def analyze_wav(data: bytes) -> AudioLevel:
    samples, rate = pcm_samples(data)
    duration = len(samples) / rate if rate else 0.0
    return AudioLevel(
        loudness_dbfs=round(loudness_dbfs(samples), 3),
        clipped=is_clipped(samples),
        duration_s=round(duration, 3),
    )


def normalize_transcript(text: str) -> str:
    """Drop whitespace and punctuation so the comparison is about the words."""

    chars: list[str] = []
    for char in text.casefold():
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith(("P", "S")):
            continue
        chars.append(char)
    return "".join(chars)


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, start=1):
        current = [index]
        for column, right_char in enumerate(right, start=1):
            insert = current[column - 1] + 1
            delete = previous[column] + 1
            replace = previous[column - 1] + (left_char != right_char)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Substitutions, insertions, and deletions over the reference length."""

    expected = normalize_transcript(reference)
    heard = normalize_transcript(hypothesis)
    if not expected:
        return 0.0 if not heard else 1.0
    return levenshtein(expected, heard) / len(expected)
