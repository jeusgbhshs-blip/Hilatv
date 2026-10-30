"""T21 acceptance. Loudness, ducking, and beat error are read back from the wavs.

The beat detector here is not the one inside the node. It smooths the sample
difference and picks peaks. Cut times are the node's edit. The comparison is
those cuts against this detector, on the rendered bed.
"""

from __future__ import annotations

import array
import math
from pathlib import Path
from typing import Any

from gateway.media_bytes import speech_timestamps
from workers.nodes.n12_music.measure import integrated_lufs, mean_volume_db, read_wav
from workers.nodes.n12_music.node import run
from workers.nodes.n12_music.qa import QAError
from workers.nodes.n12_music.schema import LicenseRecord

BEAT_LIMIT_MS = 80.0


def main() -> int:
    from gateway import get_gateway, reset_gateway

    reset_gateway()
    work = Path("/tmp/hilatv-t21-accept")
    try:
        metrics = evaluate(work, get_gateway())
        _expect_block()
    except (QAError, AssertionError, OSError, RuntimeError) as exc:
        print(f"T21 accept: FAIL {exc}")
        return 1
    print(
        "beat_error_ms={beat_error_ms:.2f} ducking_db={ducking_db:.2f} "
        "narration_lufs={narration_lufs:.2f} master_lufs={master_lufs:.2f}".format(**metrics)
    )
    print("T21 accept: cuts within 80ms of measured beats, ducking 10–12 dB, master -14 LUFS ± 1")
    return 0


def evaluate(work: Path, gateway: Any) -> dict[str, float]:
    work.mkdir(parents=True, exist_ok=True)
    result = run(
        {"project_id": "accept-t21", "payload": {**fixture(), "work_dir": str(work)}},
        gateway=gateway,
    )
    payload = result.payload
    prompt = str(payload.get("prompt") or "")
    if "无歌词" not in prompt or "无文字" not in prompt:
        raise AssertionError("music prompt is missing the no-lyrics constraint")
    records = [LicenseRecord.model_validate(item) for item in payload["segments"]]
    if not records or any(not item.source.strip() or not item.license.strip() for item in records):
        raise AssertionError("a music or sound-effect segment has no source or license")
    kinds = {item.kind for item in records}
    if kinds != {"music", "sfx"}:
        raise AssertionError(f"expected music and sfx segments, got {kinds}")
    metrics = measure_files(
        cuts_s=[float(item) for item in payload["cut_times_s"]],
        bed=Path(payload["music_bed_path"]),
        ducked=Path(payload["music_ducked_path"]),
        narration=Path(payload["narration_path"]),
        mix=Path(payload["mix_path"]),
    )
    if metrics["beat_error_ms"] > BEAT_LIMIT_MS:
        raise AssertionError(f"beat error {metrics['beat_error_ms']:.1f}ms")
    if not 10.0 <= metrics["ducking_db"] <= 12.0:
        raise AssertionError(f"ducking {metrics['ducking_db']:.2f} dB")
    if abs(metrics["narration_lufs"] + 16) > 1:
        raise AssertionError(f"narration {metrics['narration_lufs']:.2f} LUFS")
    if abs(metrics["master_lufs"] + 14) > 1:
        raise AssertionError(f"master {metrics['master_lufs']:.2f} LUFS")
    return metrics


def measure_files(
    *,
    cuts_s: list[float],
    bed: Path,
    ducked: Path,
    narration: Path,
    mix: Path,
) -> dict[str, float]:
    bed_pcm, rate = read_wav(bed)
    beats = smoothed_onsets(bed_pcm, rate)
    if not beats:
        raise AssertionError("no beats found in the rendered bed")
    worst = max(min(abs(cut - beat) for beat in beats) for cut in cuts_s)
    speech_pcm, speech_rate = read_wav(narration)
    regions = speech_regions(speech_pcm, speech_rate)
    spans = pad_spans(regions, beats)
    if not spans:
        raise AssertionError("no narration span clear of the clicks")
    deltas = [
        mean_volume_db(bed, start, end) - mean_volume_db(ducked, start, end) for start, end in spans
    ]
    return {
        "beat_error_ms": worst * 1000,
        "ducking_db": sum(deltas) / len(deltas),
        "narration_lufs": integrated_lufs(narration),
        "master_lufs": integrated_lufs(mix),
    }


def smoothed_onsets(samples: array.array, sample_rate: int) -> list[float]:
    """Peaks of a short moving sum of the absolute sample difference."""

    if not samples:
        return []
    diffs = [0] * len(samples)
    previous = 0
    for index, sample in enumerate(samples):
        diffs[index] = abs(int(sample) - previous)
        previous = int(sample)
    window = max(1, sample_rate // 400)
    smooth = [0] * len(diffs)
    total = 0
    for index, value in enumerate(diffs):
        total += value
        if index >= window:
            total -= diffs[index - window]
        smooth[index] = total
    peak = max(smooth)
    if peak <= 0:
        return []
    threshold = peak * 0.45
    found: list[float] = []
    refractory = int(0.1 * sample_rate)
    last = -refractory
    for index in range(1, len(smooth) - 1):
        if smooth[index] < threshold or index - last < refractory:
            continue
        if smooth[index] >= smooth[index - 1] and smooth[index] >= smooth[index + 1]:
            found.append(index / sample_rate)
            last = index
    return found


def speech_regions(
    samples: array.array,
    sample_rate: int,
    *,
    threshold: int = 400,
) -> list[tuple[float, float]]:
    """Windows of energy, so a sine's zero crossings do not split the phrase."""

    hop = max(1, sample_rate // 100)
    window = max(hop, sample_rate // 50)
    hot_hops: list[bool] = []
    for start in range(0, max(0, len(samples) - window), hop):
        total = 0
        for sample in samples[start : start + window]:
            value = int(sample)
            total += value * value
        rms = math.sqrt(total / window)
        hot_hops.append(rms >= threshold)
    regions: list[tuple[float, float]] = []
    begin: int | None = None
    for index, hot in enumerate(hot_hops):
        if hot and begin is None:
            begin = index
        elif not hot and begin is not None:
            regions.append((begin * hop / sample_rate, index * hop / sample_rate))
            begin = None
    if begin is not None:
        regions.append((begin * hop / sample_rate, len(hot_hops) * hop / sample_rate))
    return [(start, end) for start, end in regions if end - start >= 0.08]


def pad_spans(
    regions: list[tuple[float, float]],
    clicks: list[float],
    *,
    inset: float = 0.02,
    guard: float = 0.008,
) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    for start, end in regions:
        inner_s = start + inset
        inner_e = end - inset
        if inner_e - inner_s < 0.04:
            continue
        cursor = inner_s
        for click in sorted(item for item in clicks if inner_s < item < inner_e):
            left = click - guard
            if left - cursor >= 0.04:
                spans.append((cursor, left))
            cursor = max(cursor, click + guard)
        if inner_e - cursor >= 0.04:
            spans.append((cursor, inner_e))
    return spans


def fixture() -> dict[str, Any]:
    first = "泵在运转。"
    third = "适合连续作业。"
    first_s = speech_timestamps(first, language="zh")[1]
    third_s = speech_timestamps(third, language="zh")[1]
    shots = [
        _shot(
            "S01",
            1,
            max(1.6, first_s + 0.05),
            "产品落地",
            "产品落地特写，金属表面，画面里没有文字",
            "close_up",
            first,
            "cut",
        ),
        _shot(
            "S02",
            2,
            1.5,
            "机械运转",
            "车间里的机械运转，没有文字",
            "wide",
            "",
            "cut",
        ),
        _shot(
            "S03",
            3,
            max(1.6, third_s + 0.05),
            "转场",
            "叠化转场到车间全景，没有文字",
            "wide",
            third,
            "dissolve",
        ),
    ]
    return {
        "mood": "稳重、低沉",
        "script": {
            "script_id": "script-t21",
            "brief_id": "brief-t21",
            "language": "zh",
            "sections": [],
            "shots": shots,
        },
        "voiceovers": [
            _take("S01", first, shots[0]["duration_s"]),
            _take("S03", third, shots[2]["duration_s"]),
        ],
        "brief": {
            "brief_id": "brief-t21",
            "raw_input": "给我们的柱塞泵做条片子",
            "goal": "获客",
            "platform": ["视频号"],
            "duration_s": 15,
            "aspect_ratios": ["16:9"],
            "languages": ["zh"],
            "video_type": "product_showcase",
            "audience": "采购",
            "must_include": [],
            "style": "稳重",
            "assumptions": [],
            "open_questions": [],
        },
    }


def _expect_block() -> None:
    class _Blank:
        def music(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            del prompt, kwargs
            return {"mock": True, "source": "", "license": "", "bpm": 90, "duration_s": 1}

    try:
        run(
            {"project_id": "accept-t21-block", "payload": fixture()},
            gateway=_Blank(),
            max_attempts=1,
        )
    except QAError as exc:
        if "license" not in str(exc):
            raise AssertionError(f"block reason did not mention the license: {exc}") from exc
        return
    raise AssertionError("missing license did not block delivery")


def _shot(
    shot_id: str,
    order: int,
    duration: float,
    purpose: str,
    visual: str,
    size: str,
    voice: str,
    transition: str,
) -> dict[str, Any]:
    return {
        "shot_id": shot_id,
        "order": order,
        "duration_s": round(duration, 3),
        "purpose": purpose,
        "visual": visual,
        "shot_size": size,
        "camera": "locked_off",
        "subject_refs": ["product:HP-300"],
        "scene_ref": "scene:workshop",
        "voiceover": voice,
        "on_screen_text": [],
        "transition_out": transition,
        "generation_mode": "image_to_video",
        "status": "pending",
    }


def _take(shot_id: str, text: str, duration: float) -> dict[str, Any]:
    stamps, audio = speech_timestamps(text, language="zh")
    return {
        "shot_id": shot_id,
        "uri": f"mock://{shot_id}",
        "voice": "zh_male_steady",
        "speed": 1.0,
        "pause_s": 0.0,
        "audio_s": audio,
        "hold_s": max(0.0, duration - audio),
        "duration_s": duration,
        "timestamps": stamps,
        "transcript": text,
        "cer": 0.0,
        "loudness_dbfs": -16.0,
        "clipped": False,
        "role": "body",
    }


if __name__ == "__main__":
    raise SystemExit(main())
