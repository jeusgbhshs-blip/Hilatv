"""Decode actual audio bytes and resolve only server-authorized media roots.

There is no synthetic fallback here: a missing or broken asset is an error.
Explicit mock takes are handled separately by N6, with their source retained.
"""

from __future__ import annotations

import array
import io
import shutil
import subprocess
import tempfile
import wave
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from gateway.storage import StorageError, object_store_from_env

AudioProvenance = Literal["live", "mock", "mixed", "unknown"]
SAMPLE_RATE = 48_000
# Includes packaging and beat-aligned holds around a SPEC-limited 180s project.
MAX_AUDIO_SECONDS = 600


class AudioError(ValueError):
    """An audio asset could not be read, decoded, or fitted without losing speech."""


def audio_bytes(uri: str, *, allowed_roots: Sequence[Path], gateway: Any = None) -> bytes:
    from gateway.storage import read_asset_bytes

    stores = []
    if not uri.startswith(("oss://", "s3://")):
        stores = [None]
    else:
        for adapter in (getattr(gateway, "registry", None) or {}).values():
            store = getattr(adapter, "store", None)
            if store is not None and all(store is not item for item in stores):
                stores.append(store)
        configured = object_store_from_env()
        if configured is not None:
            stores.append(configured)
    last: Exception | None = None
    for store in stores:
        try:
            return read_asset_bytes(uri, store=store, allowed_roots=allowed_roots)
        except StorageError as exc:
            last = exc
    raise AudioError(
        "audio asset is missing, unreadable, or outside the authorized roots"
    ) from last


def decode_audio(data: bytes, *, sample_rate: int = SAMPLE_RATE) -> array.array:
    """Return mono PCM16 at a fixed rate, with a bounded decoder process.

    WAV frame lengths are checked before decoding so a truncated RIFF file is
    not silently treated as a shorter successful take by FFmpeg.
    """

    if not data:
        raise AudioError("audio asset is empty")
    if data.startswith(b"RIFF"):
        try:
            with wave.open(io.BytesIO(data), "rb") as source:
                frames = source.getnframes()
                channels = source.getnchannels()
                width = source.getsampwidth()
                rate = source.getframerate()
                if rate <= 0 or frames <= 0 or frames / rate > MAX_AUDIO_SECONDS:
                    raise AudioError("audio duration must be positive and at most 600 seconds")
                raw = source.readframes(frames)
                if len(raw) != frames * channels * width:
                    raise AudioError("audio WAV is truncated")
                if channels == 1 and width == 2 and rate == sample_rate:
                    result = array.array("h")
                    result.frombytes(raw)
                    return result
        except (wave.Error, EOFError, OSError) as exc:
            raise AudioError("audio WAV could not be decoded") from exc
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AudioError("ffmpeg is required to decode the audio asset")
    try:
        # MP4/M4A can put their index after media packets. A seekable input is
        # needed; stdin may appear readable yet drop the audio stream entirely.
        with tempfile.NamedTemporaryFile(suffix=".media", prefix="hilatv-audio-") as source:
            source.write(data)
            source.flush()
            result = subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-xerror",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-format_whitelist",
                    "wav,mp3,flac,ogg,mov,aac,matroska,webm",
                    "-i",
                    source.name,
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    str(sample_rate),
                    "-t",
                    str(MAX_AUDIO_SECONDS + 1),
                    "-f",
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    "pipe:1",
                ],
                capture_output=True,
                check=False,
                timeout=30,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError("audio decoder failed or timed out") from exc
    if result.returncode or not result.stdout or len(result.stdout) % 2:
        raise AudioError("audio asset could not be decoded")
    samples = array.array("h")
    samples.frombytes(result.stdout)
    if len(samples) > sample_rate * MAX_AUDIO_SECONDS:
        raise AudioError("audio duration exceeds 600 seconds")
    return samples


def wav_bytes(samples: array.array, *, sample_rate: int = SAMPLE_RATE) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as dest:
        dest.setnchannels(1)
        dest.setsampwidth(2)
        dest.setframerate(sample_rate)
        dest.writeframes(samples.tobytes())
    return output.getvalue()


def combine_provenance(sources: Sequence[AudioProvenance]) -> AudioProvenance:
    kinds = set(sources)
    if not kinds or "unknown" in kinds:
        return "unknown"
    if "mixed" in kinds or {"live", "mock"}.issubset(kinds):
        return "mixed"
    return next(iter(kinds))
