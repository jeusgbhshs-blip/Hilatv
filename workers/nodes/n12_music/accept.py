"""T21 acceptance.

Picture-cut alignment is not met: T10 still cuts on N6 durations, so this
command does not treat a plan-versus-grid check as the SPEC beat limit.
Ducking is the music level under narration versus the gaps, recovered from
the rendered mix. Master loudness is ffmpeg ebur128 on the N15 mp4.
"""

from __future__ import annotations

import array
import os
from pathlib import Path
from typing import Any

from gateway.media_bytes import speech_timestamps
from workers.nodes.n12_music.measure import ducking_db_on_mix, integrated_lufs, read_wav
from workers.nodes.n12_music.node import run
from workers.nodes.n12_music.qa import QAError
from workers.nodes.n12_music.schema import LicenseRecord


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
        "picture_cut_alignment={picture_cut_alignment} "
        "internal_grid_check_ms={internal_grid_ms:.2f} "
        "ducking_db={ducking_db:.2f} "
        "narration_lufs={narration_lufs:.2f} "
        "mix_lufs={mix_lufs:.2f} "
        "mp4_lufs={mp4_lufs:.2f}".format(**metrics)
    )
    print(
        "T21 accept: picture cuts 未达标 / 遗留 (not aligned on the film). "
        "ducking 10–12 dB measured on the mix. N15 mp4 -14 LUFS ± 1"
    )
    return 0


def evaluate(work: Path, gateway: Any) -> dict[str, Any]:
    root = work.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["HILATV_PROJECT_DIR"] = str(root)
    os.environ["HILATV_LIVE"] = "0"
    n12 = root / "n12"
    result = run(
        {"project_id": "accept-t21", "payload": {**fixture(), "work_dir": str(n12)}},
        gateway=gateway,
    )
    payload = result.payload
    prompt = str(payload.get("prompt") or "")
    if "无歌词" not in prompt or "无文字" not in prompt:
        raise AssertionError("music prompt is missing the no-lyrics constraint")
    records = [LicenseRecord.model_validate(item) for item in payload["segments"]]
    if not records or any(_bare_record(item) for item in records):
        raise AssertionError("a music or sound-effect segment is missing a rights field")
    kinds = {item.kind for item in records}
    if kinds != {"music", "sfx"}:
        raise AssertionError(f"expected music and sfx segments, got {kinds}")
    metrics = _measure(payload, root)
    if not 10.0 <= metrics["ducking_db"] <= 12.0:
        raise AssertionError(f"ducking {metrics['ducking_db']:.2f} dB")
    if abs(metrics["narration_lufs"] + 16) > 1:
        raise AssertionError(f"narration {metrics['narration_lufs']:.2f} LUFS")
    if abs(metrics["mix_lufs"] + 14) > 1:
        raise AssertionError(f"mix {metrics['mix_lufs']:.2f} LUFS")
    if abs(metrics["mp4_lufs"] + 14) > 1:
        raise AssertionError(f"mp4 {metrics['mp4_lufs']:.2f} LUFS")
    if metrics["picture_cut_alignment"] != "未达标":
        raise AssertionError("picture-cut alignment must stay marked as not met")
    return metrics


def _bare_record(record: LicenseRecord) -> bool:
    return not all(
        (
            record.source.strip(),
            record.license.strip(),
            record.evidence_ref.strip(),
            record.expires_on.strip(),
            record.usage_scope.strip(),
        )
    )


def _measure(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    bed = Path(payload["music_bed_path"])
    narration = Path(payload["narration_path"])
    mix = Path(payload["mix_path"])
    bed_pcm, rate = read_wav(bed)
    beats = smoothed_onsets(bed_pcm, rate)
    cuts = [float(item) for item in payload["cut_times_s"]]
    if beats and cuts:
        internal_ms = max(min(abs(cut - beat) for beat in beats) for cut in cuts) * 1000
    else:
        internal_ms = 1_000_000.0
    track = payload["audio_track"]
    script = payload["script"]
    for shot in script.get("shots") or []:
        shot["transition_out"] = "cut"
    mp4 = _compose_mp4(root, script, track)
    return {
        "picture_cut_alignment": "未达标",
        "internal_grid_ms": internal_ms,
        "ducking_db": ducking_db_on_mix(mix, narration, mix.parent),
        "narration_lufs": integrated_lufs(narration),
        "mix_lufs": integrated_lufs(mix),
        "mp4_lufs": integrated_lufs(mp4),
    }


def _compose_mp4(root: Path, script: dict[str, Any], track: dict[str, Any]) -> Path:
    from PIL import Image

    from workers.nodes.n15_compose.node import run as run_edit

    logo = root / "logo.png"
    Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(logo)
    edited = run_edit(
        {
            "project_id": "accept-t21",
            "payload": {
                "script": script,
                "work_dir": str(root / "n15"),
                "intro_s": 0,
                "outro_s": 0.4,
                "width": 320,
                "height": 180,
                "audio_track": track,
                "elements": [
                    _element("outro-logo", "outro_logo", "", 0.4, logo),
                    _element("outro-cta", "outro_cta", "联系我们", 0.6, logo),
                ],
            },
        },
        timeout_s=120,
        max_attempts=1,
    )
    return Path(edited.payload["exports"]["master"])


def _element(element_id: str, kind: str, text: str, y_ratio: float, logo: Path) -> dict[str, Any]:
    return {
        "element_id": element_id,
        "kind": kind,
        "text": text,
        "start_s": 0.2,
        "end_s": 1.2,
        "anchor": "center",
        "y_ratio": y_ratio,
        "png_path": str(logo),
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
