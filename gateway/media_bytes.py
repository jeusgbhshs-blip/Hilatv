"""Tiny decodable media samples. Frames are flat color; nothing draws text."""

from __future__ import annotations

import io
import math
import shutil
import struct
import subprocess
import tempfile
import wave
import zlib
from pathlib import Path

from gateway.errors import AdapterError

MOCK_WIDTH = 320
MOCK_HEIGHT = 180
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def color_rgb(seed: int | None) -> tuple[int, int, int]:
    value = 0 if seed is None else int(seed)
    return (
        32 + (value * 17) % 160,
        48 + (value * 29) % 160,
        64 + (value * 43) % 160,
    )


def speech_units(text: str) -> list[str]:
    """Split narration into characters (CJK) or whitespace-delimited words."""
    parts: list[str] = []
    word: list[str] = []
    for char in text.strip():
        if char.isspace():
            if word:
                parts.append("".join(word))
                word = []
            continue
        if ord(char) > 127:
            if word:
                parts.append("".join(word))
                word = []
            parts.append(char)
            continue
        word.append(char)
    if word:
        parts.append("".join(word))
    return parts or [" "]


def speech_timestamps(
    text: str, *, seconds_per_unit: float = 0.2
) -> tuple[list[dict[str, object]], float]:
    units = speech_units(text)
    stamps: list[dict[str, object]] = []
    for index, unit in enumerate(units):
        start = round(index * seconds_per_unit, 3)
        end = round((index + 1) * seconds_per_unit, 3)
        stamps.append({"text": unit, "start_s": start, "end_s": end})
    duration = round(max(seconds_per_unit, len(units) * seconds_per_unit), 3)
    return stamps, duration


def prosody_timing(
    text: str,
    *,
    speed: float = 1.0,
    pause_s: float = 0.0,
    seconds_per_unit: float = 0.2,
) -> tuple[list[dict[str, object]], float]:
    """Scale word timings by speech rate and append a trailing pause.

    Duration is rounded to milliseconds so a 16 kHz WAV of that length matches.
    """

    stamps, spoken = speech_timestamps(text, seconds_per_unit=seconds_per_unit)
    rate = speed if speed > 0 else 1.0
    scale = 1.0 / rate
    scaled: list[dict[str, object]] = []
    for item in stamps:
        scaled.append(
            {
                "text": item["text"],
                "start_s": round(float(item["start_s"]) * scale, 3),
                "end_s": round(float(item["end_s"]) * scale, 3),
            }
        )
    pause = pause_s if pause_s > 0 else 0.0
    millis = int(round((spoken * scale + pause) * 1000))
    return scaled, millis / 1000


def render_png(seed: int | None, *, width: int = MOCK_WIDTH, height: int = MOCK_HEIGHT) -> bytes:
    rgb = color_rgb(seed)
    rows = bytearray()
    pixel = bytes(rgb)
    for _ in range(height):
        rows.append(0)
        rows.extend(pixel * width)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"".join(
        (
            PNG_SIGNATURE,
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", zlib.compress(bytes(rows), 9)),
            _chunk(b"IEND", b""),
        )
    )


def decode_png(data: bytes) -> tuple[int, int, tuple[int, int, int]]:
    """Inflate a flat-color PNG. Raises if the file is not a solid frame."""
    if not data.startswith(PNG_SIGNATURE):
        raise AdapterError("png signature mismatch")
    pos = len(PNG_SIGNATURE)
    width = height = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if len(chunk) != length:
            raise AdapterError("truncated png chunk")
        if tag == b"IHDR":
            width, height = struct.unpack(">II", chunk[:8])
        elif tag == b"IDAT":
            idat.extend(chunk)
        pos += 12 + length
    if width is None or height is None or not idat:
        raise AdapterError("png missing IHDR or IDAT")
    raw = zlib.decompress(bytes(idat))
    row_stride = width * 3 + 1
    if len(raw) != row_stride * height:
        raise AdapterError("png inflated size mismatch")
    first = raw[1:4]
    for y in range(height):
        row = raw[y * row_stride : (y + 1) * row_stride]
        if row[0] != 0 or row[1:] != first * width:
            raise AdapterError("png is not a flat color frame")
    return width, height, (first[0], first[1], first[2])


def render_wav(
    text: str,
    seed: int | None,
    *,
    sample_rate: int = 16000,
    speed: float = 1.0,
    pause_s: float = 0.0,
) -> tuple[bytes, list[dict[str, object]], float]:
    stamps, duration = prosody_timing(text, speed=speed, pause_s=pause_s)
    millis = int(round(duration * 1000))
    frames = sample_rate * millis // 1000
    spoken_frames = 0
    if stamps:
        spoken_frames = min(frames, int(round(float(stamps[-1]["end_s"]) * sample_rate)))
    freq = 220 + (0 if seed is None else int(seed) % 12) * 20
    pcm = bytearray()
    for index in range(frames):
        if index < spoken_frames:
            sample = int(6000 * math.sin(2 * math.pi * freq * index / sample_rate))
        else:
            sample = 0
        pcm.extend(struct.pack("<h", sample))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(pcm))
    return buf.getvalue(), stamps, duration


def decode_wav(data: bytes) -> float:
    try:
        with wave.open(io.BytesIO(data)) as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
            if rate <= 0 or frames <= 0 or handle.getnchannels() < 1:
                raise AdapterError("wav has no samples")
            return frames / rate
    except wave.Error as exc:
        raise AdapterError("wav could not be decoded") from exc


def render_mp4(seed: int | None, *, duration_s: float = 1.0) -> bytes:
    """One silent H.264 frame sequence. ffmpeg's color source draws no glyphs."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AdapterError("ffmpeg is required to build the mock mp4 sample")
    red, green, blue = color_rgb(seed)
    color = f"0x{red:02x}{green:02x}{blue:02x}"
    duration = f"{max(0.2, float(duration_s)):.3f}"
    with tempfile.TemporaryDirectory(prefix="hilatv-mp4-") as tmp:
        path = Path(tmp) / "sample.mp4"
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={MOCK_WIDTH}x{MOCK_HEIGHT}:d={duration}:r=25",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-an",
                str(path),
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not path.is_file() or path.stat().st_size == 0:
            detail = proc.stderr.decode("utf-8", errors="replace")[-400:]
            raise AdapterError(f"ffmpeg failed to encode mock mp4: {detail}")
        return path.read_bytes()


def ffmpeg_decode(data: bytes, suffix: str) -> None:
    """Decode a sample with ffmpeg. A non-zero exit means the file is not playable."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AdapterError("ffmpeg is required to decode the sample")
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(data)
        handle.flush()
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-i", handle.name, "-f", "null", "-"],
            capture_output=True,
            check=False,
        )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-400:]
        raise AdapterError(f"ffmpeg could not decode {suffix}: {detail}")


def sniff_mime(data: bytes, fallback: str) -> str:
    if data.startswith(PNG_SIGNATURE):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"ID3") or data[:2] in {b"\xff\xfb", b"\xff\xf3"}:
        return "audio/mpeg"
    return fallback


def extension_for(mime: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "video/mp4": "mp4",
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
    }.get(mime, "bin")


def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)
