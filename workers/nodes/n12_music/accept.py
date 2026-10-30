"""T21 acceptance.

Picture cuts are read from the N15 mp4. Beats are onsets in that same file.
N12's planned cut list is not compared with itself. Ducking is the music
level under narration versus the gaps, recovered from the rendered mix.
Master loudness is ffmpeg ebur128 on the N15 mp4.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from gateway.media_bytes import speech_timestamps
from workers.nodes.n12_music.measure import ducking_db_on_mix, integrated_lufs
from workers.nodes.n12_music.node import run
from workers.nodes.n12_music.picture import measure_picture_cuts
from workers.nodes.n12_music.qa import BEAT_LIMIT_MS, QAError
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
        "picture_cut_ms={picture_cut_ms:.2f} "
        "picture_cuts={picture_cuts} "
        "picture_beats={picture_beats} "
        "ducking_db={ducking_db:.2f} "
        "narration_lufs={narration_lufs:.2f} "
        "mix_lufs={mix_lufs:.2f} "
        "mp4_lufs={mp4_lufs:.2f} "
        "hard_picture_cut_ms={hard_picture_cut_ms:.2f} "
        "hard_picture_cuts={hard_picture_cuts} "
        "hard_joins={hard_joins} "
        "hard_step_peak={hard_step_peak:.1f} "
        "hard_fades={hard_fades}".format(**metrics)
    )
    print(
        "T21 accept: picture cuts on the N15 mp4 are within 80ms of the beats "
        "in that file, including the 8-cut low-contrast fade sample. "
        "ducking 10–12 dB measured on the mix. N15 mp4 -14 LUFS ± 1"
    )
    return 0


def evaluate(work: Path, gateway: Any) -> dict[str, Any]:
    root = work.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["HILATV_PROJECT_DIR"] = str(root)
    os.environ["HILATV_LIVE"] = "0"
    n12 = root / "n12"
    body = fixture()
    result = run(
        {"project_id": "accept-t21", "payload": {**body, "work_dir": str(n12)}},
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
    metrics = _measure(payload, body, root)
    hard = _hard_measure(root, gateway)
    metrics.update(hard)
    if not 10.0 <= metrics["ducking_db"] <= 12.0:
        raise AssertionError(f"ducking {metrics['ducking_db']:.2f} dB")
    if abs(metrics["narration_lufs"] + 16) > 1:
        raise AssertionError(f"narration {metrics['narration_lufs']:.2f} LUFS")
    if abs(metrics["mix_lufs"] + 14) > 1:
        raise AssertionError(f"mix {metrics['mix_lufs']:.2f} LUFS")
    if abs(metrics["mp4_lufs"] + 14) > 1:
        raise AssertionError(f"mp4 {metrics['mp4_lufs']:.2f} LUFS")
    if metrics["picture_cuts"] != metrics["expected_cuts"]:
        raise AssertionError(
            f"decoded {metrics['picture_cuts']} picture changes, "
            f"the film has {metrics['expected_cuts']} joins "
            f"peak={metrics['step_peak']:.1f} median={metrics['step_median']:.1f} "
            f"cuts={metrics['decoded_cuts']}"
        )
    if metrics["picture_cut_ms"] > BEAT_LIMIT_MS:
        raise AssertionError(
            f"picture cuts {metrics['picture_cut_ms']:.2f}ms "
            f"cuts={metrics['decoded_cuts']} beats={metrics['decoded_beats']}"
        )
    if metrics["hard_joins"] < 8:
        raise AssertionError(f"hard sample has {metrics['hard_joins']} joins, need 8+")
    if metrics["hard_fades"] < 1:
        raise AssertionError("hard sample has no fade")
    if not metrics["hard_unequal"]:
        raise AssertionError("hard sample shot lengths are all equal")
    if metrics["hard_picture_cuts"] < 8:
        raise AssertionError(
            f"hard sample decoded {metrics['hard_picture_cuts']} cuts "
            f"peak={metrics['hard_step_peak']:.1f} cuts={metrics['hard_decoded_cuts']}"
        )
    if metrics["hard_picture_cut_ms"] > BEAT_LIMIT_MS:
        raise AssertionError(
            f"hard picture cuts {metrics['hard_picture_cut_ms']:.2f}ms "
            f"cuts={metrics['hard_decoded_cuts']} beats={metrics['hard_decoded_beats']}"
        )
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


def _measure(payload: dict[str, Any], body: dict[str, Any], root: Path) -> dict[str, Any]:
    narration = Path(payload["narration_path"])
    mix = Path(payload["mix_path"])
    script = payload["script"]
    aligned = payload["aligned_script"]
    brief = body["brief"]
    cues = _subtitles(root, script, body["voiceovers"], brief)
    elements, intro_s, outro_s = _packaging(root, script, brief)
    composed = _compose_mp4(
        root,
        script,
        aligned,
        payload["audio_track"],
        cues,
        elements,
        intro_s,
        outro_s,
    )
    timeline = composed["timeline"]
    _assert_synced(script, aligned, cues, timeline, intro_s)
    mp4 = Path(composed["exports"]["master"])
    film = measure_picture_cuts(mp4, root / "picture")
    return {
        "picture_cut_ms": film.error_ms,
        "picture_cuts": len(film.cuts_s),
        "picture_beats": len(film.beats_s),
        "expected_cuts": max(0, len(timeline["clips"]) - 1),
        "decoded_cuts": [round(item, 4) for item in film.cuts_s],
        "decoded_beats": [round(item, 4) for item in film.beats_s],
        "step_peak": film.step_peak,
        "step_median": film.step_median,
        "ducking_db": ducking_db_on_mix(mix, narration, mix.parent),
        "narration_lufs": integrated_lufs(narration),
        "mix_lufs": integrated_lufs(mix),
        "mp4_lufs": integrated_lufs(mp4),
    }


def _hard_measure(root: Path, gateway: Any) -> dict[str, Any]:
    """Eight unequal shots, one fade, and low-contrast frames. Numbers are measured."""

    body = hard_fixture()
    result = run(
        {
            "project_id": "accept-t21-hard",
            "payload": {**body, "work_dir": str(root / "n12-hard")},
        },
        gateway=gateway,
    )
    payload = result.payload
    script = payload["script"]
    aligned = payload["aligned_script"]
    lengths = [float(shot["duration_s"]) for shot in aligned["shots"]]
    elements, intro_s, outro_s = _packaging(root / "hard", script, body["brief"])
    composed = _compose_mp4(
        root / "hard",
        script,
        aligned,
        payload["audio_track"],
        [],
        elements,
        intro_s,
        outro_s,
        project_id="accept-t21-hard",
        low_contrast=True,
        keep_transitions=True,
    )
    timeline = composed["timeline"]
    joins = max(0, len(timeline["clips"]) - 1)
    fades = str(composed["filters"]["master"]).count("xfade=")
    film = measure_picture_cuts(Path(composed["exports"]["master"]), root / "hard-picture")
    return {
        "hard_picture_cut_ms": film.error_ms,
        "hard_picture_cuts": len(film.cuts_s),
        "hard_joins": joins,
        "hard_fades": fades,
        "hard_unequal": len(set(round(item, 3) for item in lengths)) > 1,
        "hard_step_peak": film.step_peak,
        "hard_decoded_cuts": [round(item, 4) for item in film.cuts_s],
        "hard_decoded_beats": [round(item, 4) for item in film.beats_s],
    }


def _assert_synced(
    script: dict[str, Any],
    aligned: dict[str, Any],
    cues: list[dict[str, Any]],
    timeline: dict[str, Any],
    intro_s: float,
) -> None:
    old = _shot_starts(script["shots"])
    new = _shot_starts(aligned["shots"])
    clips = {item["clip_id"]: item for item in timeline["clips"]}
    moved = False
    for shot in aligned["shots"]:
        original = next(item for item in script["shots"] if item["shot_id"] == shot["shot_id"])
        if abs(float(shot["duration_s"]) - float(original["duration_s"])) > 0.02:
            moved = True
        duration = float(clips[shot["shot_id"]]["duration_s"])
        if abs(duration - float(shot["duration_s"])) > (1 / 30) + 1e-3:
            raise AssertionError(
                f"{shot['shot_id']} timeline {duration} != aligned {shot['duration_s']}"
            )
    if not moved:
        raise AssertionError("aligned durations did not move a shot")
    overlays = timeline["overlays"]
    for cue in cues:
        offset = float(cue["start_s"]) - old[cue["shot_id"]]
        expect = intro_s + new[cue["shot_id"]] + offset
        match = next(
            item for item in overlays if item["kind"] == "subtitle" and item["text"] == cue["text"]
        )
        if abs(float(match["start_s"]) - expect) > 0.04:
            raise AssertionError(
                f"subtitle {cue['text']} at {match['start_s']} wanted {expect:.3f}"
            )
    board = sum(float(shot["duration_s"]) for shot in aligned["shots"])
    old_board = sum(float(shot["duration_s"]) for shot in script["shots"])
    outro = next(item for item in overlays if item["kind"] == "outro_logo")
    if abs(float(outro["start_s"]) - (intro_s + board)) > 0.04:
        raise AssertionError(f"outro at {outro['start_s']} wanted {intro_s + board:.3f}")
    if abs(board - old_board) < 0.05:
        raise AssertionError("packaging did not move with the aligned picture")
    labels = [item for item in overlays if item["kind"] == "ai_label" and item["text"] == "AI生成"]
    if len(labels) != 1 or float(labels[0]["start_s"]) != 0.0:
        raise AssertionError("AI生成 label is missing from the timeline")
    if float(labels[0]["end_s"]) + 0.05 < float(timeline["duration_s"]):
        raise AssertionError("AI生成 label does not cover the film")


def _shot_starts(shots: list[dict[str, Any]]) -> dict[str, float]:
    cursor = 0.0
    found: dict[str, float] = {}
    for shot in shots:
        found[str(shot["shot_id"])] = cursor
        cursor += float(shot["duration_s"])
    return found


def _subtitles(
    root: Path,
    script: dict[str, Any],
    voiceovers: list[dict[str, Any]],
    brief: dict[str, Any],
) -> list[dict[str, Any]]:
    from workers.nodes.n13_subtitle.node import run as run_subs

    result = run_subs(
        {
            "project_id": "accept-t21",
            "payload": {
                "script": script,
                "voiceovers": voiceovers,
                "brief": brief,
                "width": 320,
                "height": 180,
                "work_dir": str(root / "n13"),
            },
        },
        timeout_s=60,
        max_attempts=1,
    )
    cues = result.payload["cues"]
    if not cues:
        raise AssertionError("spoken shots produced no subtitles")
    return cues


def _packaging(
    root: Path, script: dict[str, Any], brief: dict[str, Any]
) -> tuple[list[dict[str, Any]], float, float]:
    from workers.nodes.n14_packaging.node import run as run_pack

    result = run_pack(
        {
            "project_id": "accept-t21",
            "payload": {
                "script": script,
                "brief": brief,
                "width": 320,
                "height": 180,
                "work_dir": str(root / "n14"),
            },
        },
        timeout_s=60,
        max_attempts=1,
    )
    return (
        result.payload["elements"],
        float(result.payload.get("intro_s") or 0),
        float(result.payload.get("outro_s") or 0),
    )


def _compose_mp4(
    root: Path,
    script: dict[str, Any],
    aligned: dict[str, Any],
    track: dict[str, Any],
    cues: list[dict[str, Any]],
    elements: list[dict[str, Any]],
    intro_s: float,
    outro_s: float,
    *,
    project_id: str = "accept-t21",
    low_contrast: bool = False,
    keep_transitions: bool = False,
) -> dict[str, Any]:
    from workers.nodes.n15_compose.node import run as run_edit

    picture = script if keep_transitions else _hard_cuts(script)
    aligned_picture = aligned if keep_transitions else _hard_cuts(aligned)
    clips = []
    for index, shot in enumerate(picture["shots"]):
        path = _pattern(
            root / "patterns" / f"{shot['shot_id']}.mp4",
            index,
            low_contrast=low_contrast,
        )
        clips.append({"shot_id": shot["shot_id"], "path": str(path), "cards": []})
    edited = run_edit(
        {
            "project_id": project_id,
            "payload": {
                "script": picture,
                "aligned_script": aligned_picture,
                "cues": cues,
                "elements": elements,
                "work_dir": str(root / "n15"),
                "intro_s": intro_s,
                "outro_s": outro_s,
                "width": 320,
                "height": 180,
                "audio_track": track,
                "shot_clips": clips,
            },
        },
        timeout_s=120,
        max_attempts=1,
    )
    return edited.payload


def _hard_cuts(script: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(script)
    for shot in body["shots"]:
        shot["transition_out"] = "cut"
    return body


def _pattern(path: Path, index: int, *, low_contrast: bool = False) -> Path:
    """A bar pattern with no glyphs, so a graded frame still changes at the cut."""

    from workers.media.ffmpeg import run_ffmpeg

    hi, lo = (72, 48) if low_contrast else (255, 0)
    exprs = (
        rf"if(lt(mod(X\,48)\,24)\,{hi}\,{lo})",
        rf"if(lt(mod(Y\,48)\,24)\,{hi}\,{lo})",
        rf"if(lt(mod(X+Y\,64)\,32)\,{hi}\,{lo})",
    )
    expr = exprs[index % len(exprs)]
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=320x180:r=30:d=0.4,geq=r='{expr}':g='{expr}':b='{expr}'",
            "-frames:v",
            "8",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-preset",
            "ultrafast",
            str(path),
        ]
    )
    return path


def hard_fixture() -> dict[str, Any]:
    """Eight shots, unequal lengths, one dissolve. No customer pictures."""

    lengths = (0.4, 0.9, 1.3, 0.5, 1.7, 0.8, 1.1, 0.6, 1.4)
    purposes = (
        "产品落地",
        "机械运转",
        "转场",
        "空镜",
        "产品落地",
        "机械运转",
        "转场",
        "空镜",
        "产品落地",
    )
    shots = []
    for index, duration in enumerate(lengths, start=1):
        transition = "dissolve" if index == 3 else "cut"
        shots.append(
            _shot(
                f"S{index:02d}",
                index,
                duration,
                purposes[index - 1],
                f"{purposes[index - 1]}，画面里没有文字",
                "wide",
                "",
                transition,
            )
        )
    spoken = "泵在运转。"
    shots[4]["voiceover"] = spoken
    body = fixture()
    body["script"] = {
        "script_id": "script-t21-hard",
        "brief_id": "brief-t21",
        "language": "zh",
        "sections": [],
        "shots": shots,
    }
    body["voiceovers"] = [_take("S05", spoken, lengths[4])]
    return body


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
