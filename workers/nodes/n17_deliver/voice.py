"""Dub one storyboard through the gateway and fit each take to the picture."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workers.media.ffmpeg import run_ffmpeg
from workers.nodes.n06_voiceover.audio import analyze_wav, character_error_rate
from workers.nodes.n06_voiceover.node import load_take
from workers.nodes.n06_voiceover.prosody import DEFAULT_SPEED, DEFAULT_VOICE, plan_prosody
from workers.nodes.n06_voiceover.schema import ShotVoiceover, WordStamp
from workers.nodes.n17_deliver.qa import QAError
from workers.schemas.brand import BrandKit
from workers.schemas.script import Script


def dub(
    script: Script,
    brand: BrandKit | None,
    work: Path,
    *,
    gateway: Any,
    project_id: str,
    attempt: int,
) -> list[ShotVoiceover]:
    base = brand.voice.speed if brand is not None else DEFAULT_SPEED
    voice = brand.voice.tts_voice if brand is not None else DEFAULT_VOICE
    plans = plan_prosody(script, base)
    takes: list[ShotVoiceover] = []
    audio_dir = work / "audio" / script.language
    audio_dir.mkdir(parents=True, exist_ok=True)
    for shot in script.shots:
        if not shot.voiceover.strip():
            continue
        plan = plans[shot.shot_id]
        spoken = gateway.tts(
            shot.voiceover,
            voice=voice,
            seed=0,
            language=script.language,
            project_id=project_id,
            node="n17_deliver",
            shot_id=shot.shot_id,
            attempt=attempt,
            params={"speed": plan.speed, "pause_s": plan.pause_s},
        )
        if not isinstance(spoken, dict):
            raise QAError(f"{shot.shot_id} tts returned a non-object")
        wav = load_take(
            str(spoken.get("uri") or ""),
            text=shot.voiceover,
            speed=plan.speed,
            pause_s=plan.pause_s,
            seed=0,
            language=script.language,
        )
        heard = gateway.asr(
            str(spoken.get("uri") or ""),
            language=script.language,
            project_id=project_id,
            node="n17_deliver",
            shot_id=shot.shot_id,
            attempt=attempt,
            params={"reference_text": shot.voiceover},
        )
        transcript = heard.get("text") if isinstance(heard, dict) else ""
        if not isinstance(transcript, str):
            transcript = ""
        cer = character_error_rate(shot.voiceover, transcript)
        if cer >= 0.02:
            raise QAError(f"{shot.shot_id} dub character error {cer:.3f}")
        level = analyze_wav(wav)
        if level.clipped:
            raise QAError(f"{shot.shot_id} dub is clipped")
        stamps = _stamps(spoken.get("timestamps"))
        dest = audio_dir / f"{shot.shot_id}.wav"
        audio_s = level.duration_s
        target = float(shot.duration_s)
        if audio_s > target + 0.03:
            _fit_wav(wav, dest, audio_s / target, target)
            scale = target / audio_s
            stamps = [
                WordStamp(text=item.text, start_s=item.start_s * scale, end_s=item.end_s * scale)
                for item in stamps
            ]
            audio_s = target
            hold = 0.0
        else:
            dest.write_bytes(wav)
            hold = max(0.0, target - audio_s)
        fitted = analyze_wav(dest.read_bytes())
        if fitted.clipped:
            raise QAError(f"{shot.shot_id} fitted dub is clipped")
        takes.append(
            ShotVoiceover(
                shot_id=shot.shot_id,
                uri=dest.resolve().as_uri(),
                voice=voice,
                speed=plan.speed,
                pause_s=plan.pause_s,
                audio_s=round(min(audio_s, target), 3),
                hold_s=round(hold, 3),
                duration_s=target,
                timestamps=stamps,
                transcript=transcript or shot.voiceover,
                cer=round(cer, 4),
                loudness_dbfs=level.loudness_dbfs,
                clipped=False,
                role=plan.role,
            )
        )
    return takes


def _fit_wav(wav: bytes, dest: Path, factor: float, target_s: float) -> None:
    source = dest.with_suffix(".src.wav")
    source.write_bytes(wav)
    filters: list[str] = []
    remaining = factor
    while remaining > 2:
        filters.append("atempo=2.0")
        remaining /= 2
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.5f}")
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-filter:a",
            ",".join(filters),
            "-t",
            f"{target_s:.3f}",
            str(dest),
        ]
    )


def _stamps(raw: object) -> list[WordStamp]:
    if not isinstance(raw, list):
        return []
    stamps: list[WordStamp] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        start = item.get("start_s")
        end = item.get("end_s")
        if not isinstance(text, str) or not isinstance(start, int | float):
            continue
        if not isinstance(end, int | float) or float(end) < float(start):
            continue
        stamps.append(WordStamp(text=text, start_s=float(start), end_s=float(end)))
    return stamps
