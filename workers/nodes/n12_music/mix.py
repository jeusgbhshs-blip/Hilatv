"""Narration, ducked music, and sound effects mixed to a measured loudness.

Narration is held near -16 LUFS. Music under narration is 11 dB below the
unducked bed. The master is pulled to about -14 LUFS by changing only the
music level, so the ducking ratio stays put.
"""

from __future__ import annotations

import array
from dataclasses import dataclass
from pathlib import Path

from gateway.media_bytes import CLICK_SAMPLES, MUSIC_RATE, beat_sample_index, render_beat_pcm
from workers.media.audio import AudioError
from workers.nodes.n12_music.library import render_sfx
from workers.nodes.n12_music.measure import integrated_lufs, speech_regions, write_wav

DUCK_DB = 11.0
DUCK_GAIN = 10 ** (-DUCK_DB / 20)
NARRATION_LUFS = -16.0
MASTER_LUFS = -14.0
RAMP_S = 0.01


@dataclass(frozen=True)
class MixFiles:
    narration: Path
    music_bed: Path
    music_ducked: Path
    sfx: Path
    mix: Path
    sample_rate: int
    duration_s: float
    narration_regions: tuple[Region, ...]


@dataclass(frozen=True)
class Region:
    start_s: float
    end_s: float


def build_mix(
    *,
    work: Path,
    n_samples: int,
    bpm: float,
    seed: int,
    effects: list[tuple[str, int]],
    narration: array.array,
    music: array.array | None = None,
    mock_music: bool = False,
    sample_rate: int = MUSIC_RATE,
) -> MixFiles:
    if len(narration) != n_samples:
        raise AudioError("narration must cover the aligned timeline")
    if music is None and not mock_music:
        raise AudioError("a real music asset or an explicit mock result is required")
    narration = _scale_to(narration, NARRATION_LUFS, work / "_narration_probe.wav", sample_rate)
    regions = [Region(start, end) for start, end in speech_regions(narration, sample_rate)]
    sfx = _sfx_bed(n_samples, effects, sample_rate)
    envelope = _envelope(n_samples, regions, sample_rate)
    pad_amp = _solve_pad(
        narration,
        sfx,
        envelope,
        n_samples=n_samples,
        bpm=bpm,
        seed=seed,
        sample_rate=sample_rate,
        probe=work / "_mix_probe.wav",
        music=music,
    )
    bed = _music_bed(music, n_samples, bpm, pad_amp, seed, sample_rate)
    ducked = _apply(bed, envelope)
    mixed = _add(narration, ducked, sfx)
    files = MixFiles(
        narration=work / "narration.wav",
        music_bed=work / "music_bed.wav",
        music_ducked=work / "music_ducked.wav",
        sfx=work / "sfx.wav",
        mix=work / "mix.wav",
        sample_rate=sample_rate,
        duration_s=n_samples / sample_rate,
        narration_regions=tuple(regions),
    )
    write_wav(files.narration, narration, sample_rate)
    write_wav(files.music_bed, bed, sample_rate)
    write_wav(files.music_ducked, ducked, sample_rate)
    write_wav(files.sfx, sfx, sample_rate)
    write_wav(files.mix, mixed, sample_rate)
    return files


def _music_bed(
    source: array.array | None, count: int, bpm: float, amp: int, seed: int, rate: int
) -> array.array:
    if source is None:
        return render_beat_pcm(n_samples=count, bpm=bpm, pad_amp=amp, seed=seed, sample_rate=rate)
    if len(source) < count:
        raise AudioError("music audio is shorter than the aligned timeline")
    return _gain(source[:count], amp / 8000)


def _sfx_bed(n_samples: int, effects: list[tuple[str, int]], sample_rate: int) -> array.array:
    samples = array.array("h", [0] * n_samples)
    for kind, start in effects:
        clip = render_sfx(kind, sample_rate)
        for offset, value in enumerate(clip):
            pos = start + offset
            if pos >= n_samples:
                break
            samples[pos] = _clamp(int(samples[pos]) + int(value))
    return samples


def _envelope(n_samples: int, regions: list[Region], sample_rate: int) -> list[float]:
    env = [1.0] * n_samples
    ramp = max(1, int(RAMP_S * sample_rate))
    for region in regions:
        start = max(0, int(round(region.start_s * sample_rate)))
        end = min(n_samples, int(round(region.end_s * sample_rate)))
        for index in range(start, end):
            env[index] = DUCK_GAIN
        for step in range(ramp):
            before = start - ramp + step
            if 0 <= before < n_samples and env[before] == 1.0:
                env[before] = 1.0 + (DUCK_GAIN - 1.0) * ((step + 1) / ramp)
            after = end + step
            if 0 <= after < n_samples:
                env[after] = DUCK_GAIN + (1.0 - DUCK_GAIN) * ((step + 1) / ramp)
    return env


def _solve_pad(
    narration: array.array,
    sfx: array.array,
    envelope: list[float],
    *,
    n_samples: int,
    bpm: float,
    seed: int,
    sample_rate: int,
    probe: Path,
    music: array.array | None = None,
) -> int:
    amp = 8000
    best_amp = amp
    best_error = 1_000.0
    for _ in range(6):
        bed = _music_bed(music, n_samples, bpm, amp, seed, sample_rate)
        mixed = _add(narration, _apply(bed, envelope), sfx)
        write_wav(probe, mixed, sample_rate)
        measured = integrated_lufs(probe)
        error = abs(measured - MASTER_LUFS)
        if error < best_error:
            best_error = error
            best_amp = amp
        if error <= 0.35:
            return amp
        scaled = amp * (10 ** ((MASTER_LUFS - measured) / 20))
        nxt = int(round(min(22000, max(400, scaled))))
        if nxt == amp:
            break
        amp = nxt
    return best_amp


def _scale_to(samples: array.array, target: float, probe: Path, sample_rate: int) -> array.array:
    current = samples
    if max(abs(int(sample)) for sample in current) == 0:
        return current
    for _ in range(3):
        write_wav(probe, current, sample_rate)
        measured = integrated_lufs(probe)
        if abs(measured - target) <= 0.35:
            return current
        gain = 10 ** ((target - measured) / 20)
        current = _gain(current, gain)
    return current


def _apply(samples: array.array, envelope: list[float]) -> array.array:
    out = array.array("h", samples)
    for index, gain in enumerate(envelope):
        if gain != 1.0:
            out[index] = _clamp(int(int(samples[index]) * gain))
    return out


def _add(left: array.array, middle: array.array, right: array.array) -> array.array:
    out = array.array("h", [0] * len(left))
    for index in range(len(left)):
        out[index] = _clamp(int(left[index]) + int(middle[index]) + int(right[index]))
    return out


def _gain(samples: array.array, gain: float) -> array.array:
    out = array.array("h", [0] * len(samples))
    for index, sample in enumerate(samples):
        out[index] = _clamp(int(int(sample) * gain))
    return out


def _clamp(value: int) -> int:
    if value > 32767:
        return 32767
    if value < -32768:
        return -32768
    return value


def effect_start(kind: str, start_sample: int, end_sample: int, sample_rate: int) -> int:
    if kind != "whoosh":
        return start_sample
    length = int(0.18 * sample_rate)
    return max(start_sample, end_sample - length)


def tail_samples(end_beat: int, bpm: float, sample_rate: int = MUSIC_RATE) -> int:
    """Frames that include the click on the final cut."""

    return beat_sample_index(end_beat, bpm, sample_rate) + CLICK_SAMPLES
