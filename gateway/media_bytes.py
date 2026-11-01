"""Tiny decodable media samples. Frames are flat color; nothing draws text."""

from __future__ import annotations

import array
import io
import math
import re
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


# SPEC N4: about 4 Chinese characters per second, about 2.5 English words per second.
ZH_CHAR_MS = 250
EN_WORD_MS = 400
_EN_WORD = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


def speech_timestamps(
    text: str,
    *,
    language: str | None = None,
    seconds_per_unit: float | None = None,
) -> tuple[list[dict[str, object]], float]:
    """Word or character timings at the N4 speaking rate.

    ``seconds_per_unit`` forces one flat rate for every token. The default
    follows the language: 4 Han characters per second, 2.5 English words per second.
    """

    tokens = _timed_tokens(text, language=language, seconds_per_unit=seconds_per_unit)
    stamps: list[dict[str, object]] = []
    cursor = 0
    for token, millis in tokens:
        start = cursor
        cursor += millis
        stamps.append({"text": token, "start_s": start / 1000, "end_s": cursor / 1000})
    if cursor <= 0 and text.strip():
        cursor = ZH_CHAR_MS
        stamps.append({"text": text.strip()[:1] or " ", "start_s": 0.0, "end_s": cursor / 1000})
    return stamps, cursor / 1000


def prosody_timing(
    text: str,
    *,
    speed: float = 1.0,
    pause_s: float = 0.0,
    language: str | None = None,
    seconds_per_unit: float | None = None,
) -> tuple[list[dict[str, object]], float]:
    """Scale word timings by speech rate and append a trailing pause.

    Duration is an integer number of milliseconds so a 16 kHz WAV matches it.
    """

    tokens = _timed_tokens(text, language=language, seconds_per_unit=seconds_per_unit)
    rate = speed if speed > 0 else 1.0
    scale = 1.0 / rate
    stamps: list[dict[str, object]] = []
    cursor = 0
    for token, millis in tokens:
        scaled = int(round(millis * scale))
        start = cursor
        cursor += scaled
        stamps.append({"text": token, "start_s": start / 1000, "end_s": cursor / 1000})
    if cursor <= 0 and text.strip():
        cursor = int(round(ZH_CHAR_MS * scale))
        stamps.append({"text": text.strip()[:1] or " ", "start_s": 0.0, "end_s": cursor / 1000})
    pause = int(round(pause_s * 1000)) if pause_s > 0 else 0
    return stamps, (cursor + pause) / 1000


def _timed_tokens(
    text: str,
    *,
    language: str | None,
    seconds_per_unit: float | None,
) -> list[tuple[str, int]]:
    if seconds_per_unit is not None:
        millis = max(1, int(round(seconds_per_unit * 1000)))
        return [(unit, millis) for unit in speech_units(text) if unit.strip()]
    if _timing_mode(text, language) == "zh":
        return [
            (char, ZH_CHAR_MS)
            for char in text
            if 0x4E00 <= ord(char) <= 0x9FFF or (char.isascii() and char.isalnum())
        ]
    marks: list[tuple[int, str]] = []
    for match in _EN_WORD.finditer(text):
        marks.append((match.start(), match.group(0)))
    for index, char in enumerate(text):
        if 0x4E00 <= ord(char) <= 0x9FFF:
            marks.append((index, char))
    marks.sort(key=lambda item: item[0])
    return [(token, EN_WORD_MS) for _index, token in marks]


def _timing_mode(text: str, language: str | None) -> str:
    if language:
        primary = language.lower().split("-", 1)[0]
        return "zh" if primary == "zh" else "en"
    if any(0x4E00 <= ord(char) <= 0x9FFF for char in text):
        return "zh"
    return "en"


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
    language: str | None = None,
) -> tuple[bytes, list[dict[str, object]], float]:
    stamps, duration = prosody_timing(text, speed=speed, pause_s=pause_s, language=language)
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


MUSIC_RATE = 48000
CLICK_SAMPLES = 144
CLICK_PEAK = 30000


def beat_period_s(bpm: float) -> float:
    return 60.0 / bpm if bpm > 0 else 0.6


def beat_sample_index(index: int, bpm: float, sample_rate: int = MUSIC_RATE) -> int:
    """Sample where beat ``index`` falls. Index 0 is the first sample."""

    return int(round(index * beat_period_s(bpm) * sample_rate))


def render_beat_pcm(
    *,
    n_samples: int,
    bpm: float,
    pad_amp: int,
    seed: int | None = None,
    sample_rate: int = MUSIC_RATE,
) -> array.array:
    """Pad tone plus one click on each beat.

    The click jumps away from the pad so a later onset detector can find it
    without knowing the beat grid. This is synthesized here; it is not a
    commercial recording.
    """

    total = max(1, int(n_samples))
    amp = max(0, min(22000, int(pad_amp)))
    freq = 82.0 + (0 if seed is None else int(seed) % 5)
    samples = array.array("h", [0] * total)
    for index in range(total):
        samples[index] = int(amp * math.sin(2 * math.pi * freq * index / sample_rate))
    if bpm <= 0:
        return samples
    beat = 0
    while beat < 100000:
        start = beat_sample_index(beat, bpm, sample_rate)
        if start >= total:
            break
        previous = int(samples[start - 1]) if start else 0
        peak = -CLICK_PEAK if previous >= 0 else CLICK_PEAK
        for offset in range(CLICK_SAMPLES):
            pos = start + offset
            if pos >= total:
                break
            fade = 1.0 - (offset / CLICK_SAMPLES)
            samples[pos] = int(peak * fade)
        beat += 1
    return samples


def render_beat_wav(
    *,
    duration_s: float,
    bpm: float,
    pad_amp: int = 4000,
    seed: int | None = None,
    sample_rate: int = MUSIC_RATE,
) -> bytes:
    """Reference mock music file. The node rebuilds the same grid when mixing."""

    frames = max(1, int(round(max(0.2, float(duration_s)) * sample_rate)))
    pcm = render_beat_pcm(
        n_samples=frames,
        bpm=bpm,
        pad_amp=pad_amp,
        seed=seed,
        sample_rate=sample_rate,
    )
    return _wav_bytes(pcm, sample_rate)


def _wav_bytes(samples: array.array, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return buf.getvalue()


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


def render_mp4(
    seed: int | None, *, duration_s: float = 1.0, width: int = MOCK_WIDTH, height: int = MOCK_HEIGHT
) -> bytes:
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
                f"color=c={color}:s={width}x{height}:d={duration}:r=25",
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
