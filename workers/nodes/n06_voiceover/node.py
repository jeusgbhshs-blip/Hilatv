"""N6 voiceover. One storyboard in, shots timed from the take and the Brief.

TTS and ASR both go through the gateway. A shot is never shorter than its
audio. Spare time against the Brief is picture hold after the line. On-screen
text stays on the shot; this node only moves its in/out marks.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, NoReturn

from pydantic import ValidationError

from gateway.media_bytes import render_wav
from workers.logging import log_event
from workers.media.audio import AudioError, audio_bytes, decode_audio, wav_bytes
from workers.media.packaging import FPS
from workers.media.timing import allocate_frames, duration_budget
from workers.nodes.n06_voiceover.audio import FRAME_S, analyze_wav, character_error_rate
from workers.nodes.n06_voiceover.lexicon import load_lexicon, matching_terms
from workers.nodes.n06_voiceover.prosody import DEFAULT_SPEED, DEFAULT_VOICE, plan_prosody
from workers.nodes.n06_voiceover.qa import QAError, check
from workers.nodes.n06_voiceover.schema import (
    N6Input,
    NodeRequest,
    NodeResult,
    ShotVoiceover,
    WordStamp,
)
from workers.nodes.n06_voiceover.timing import (
    DURATION_TOLERANCE,
    boost_factor,
    boosted_speed,
    fit_durations,
)
from workers.qa.settings import project_dir
from workers.schemas.asset import Asset, AssetKind
from workers.schemas.script import OnScreenText, Script, Shot

NODE = "n06_voiceover"
ASSET_NS = uuid.UUID("6f1c0a1e-7b2d-4e5a-9c31-0c0a6e6e0706")


class Deadline:
    def __init__(self, timeout_s: float) -> None:
        if timeout_s <= 0:
            raise TimeoutError("n06_voiceover exceeded timeout")
        self._end = time.monotonic() + timeout_s

    def check(self) -> None:
        if time.monotonic() >= self._end:
            raise TimeoutError("n06_voiceover exceeded timeout")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 180.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N6Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway or _default_gateway()
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = _execute(request, attempt=attempt, timeout_s=timeout_s, gateway=gateway)
            check(result)
        except QAError as exc:
            if not exc.retryable:
                raise
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=request.shot_id,
                attempt=attempt,
                error=str(exc),
            )
            continue
        return result
    raise QAError(
        f"n06_voiceover failed after {max_attempts} attempts: {last_error}"
    ) from last_error


def _execute(
    request: NodeRequest,
    *,
    attempt: int,
    timeout_s: float,
    gateway: Any,
) -> NodeResult:
    deadline = Deadline(timeout_s)
    payload = N6Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    script = payload.script
    brand = payload.brand_kit
    base = brand.voice.speed if brand is not None else DEFAULT_SPEED
    voice = brand.voice.tts_voice if brand is not None else DEFAULT_VOICE
    from workers.brand_kit.people import ConsentError
    from workers.compliance.consent_gate import assert_voice_allowed

    try:
        assert_voice_allowed(voice, payload.enterprise_id, brand)
    except ConsentError as exc:
        raise QAError(str(exc), retryable=False) from exc
    plans = plan_prosody(script, base)
    lexicon = load_lexicon()
    exact = (
        duration_budget(payload.target_duration_s, intro_s=payload.intro_s, outro_s=payload.outro_s)
        if payload.target_duration_s is not None
        else None
    )
    target = exact.body_s if exact else float(payload.brief.duration_s) if payload.brief else None
    speeds = {shot.shot_id: plans[shot.shot_id].speed for shot in script.shots}
    spoken = _speak_all(
        script,
        request=request,
        attempt=attempt,
        deadline=deadline,
        gateway=gateway,
        voice=voice,
        plans=plans,
        speeds=speeds,
        lexicon=lexicon,
        brand_id=brand.brand_id if brand is not None else None,
        enterprise_id=payload.enterprise_id,
    )
    reserved = sum(shot.duration_s for shot in script.shots if not shot.voiceover.strip())
    if exact:
        reserved = sum(1 / FPS for shot in script.shots if not shot.voiceover.strip())
    budget = None if target is None else max(0.0, target - reserved)
    # Explicit whole-film settings budget in frames; audio seconds are float
    # approximations of the same frame grid, so one frame of slack is rounding.
    slack = 1.0 / FPS if exact else DURATION_TOLERANCE
    factor = 1.0
    if budget is not None:
        factor = _maybe_speed_up(
            spoken,
            target=budget,
            brief_s=target if target is not None else budget,
            plans=plans,
            speeds=speeds,
            request=request,
            attempt=attempt,
            tolerance=slack,
        )
        if factor > 1:
            spoken = _speak_all(
                script,
                request=request,
                attempt=attempt,
                deadline=deadline,
                gateway=gateway,
                voice=voice,
                plans=plans,
                speeds=speeds,
                lexicon=lexicon,
                brand_id=brand.brand_id if brand is not None else None,
                enterprise_id=payload.enterprise_id,
            )
            _reject_if_still_long(
                spoken,
                target=budget,
                brief_s=target if target is not None else budget,
                request=request,
                attempt=attempt,
                tolerance=slack,
            )
    fitted = fit_durations(
        [item["audio_s"] for item in spoken],
        target_s=target,
        reserved_s=reserved,
    )
    exact_frames: dict[str, int] = {}
    if exact:
        by_id = {item["shot_id"]: item for item in spoken}
        try:
            frames = allocate_frames(
                [
                    by_id[shot.shot_id]["audio_s"] if shot.shot_id in by_id else 0
                    for shot in script.shots
                ],
                [float(shot.duration_s) for shot in script.shots],
                exact.body_frames,
            )
        except ValueError as exc:
            raise QAError(f"trim_copy: {exc}", retryable=False) from exc
        exact_frames = {
            shot.shot_id: count for shot, count in zip(script.shots, frames, strict=True)
        }
        fitted = [
            (
                item["audio_s"],
                max(0.0, exact_frames[item["shot_id"]] / FPS - item["audio_s"]),
                exact_frames[item["shot_id"]] / FPS,
            )
            for item in spoken
        ]
    shots: list[Shot] = []
    takes: list[ShotVoiceover] = []
    assets: list[Asset] = []
    spoken_index = 0
    for shot in script.shots:
        if not shot.voiceover.strip():
            duration = exact_frames[shot.shot_id] / FPS if exact else shot.duration_s
            shots.append(
                shot.model_copy(
                    update={
                        "duration_s": duration,
                        "on_screen_text": _rescale(shot.on_screen_text, shot.duration_s, duration),
                    }
                )
            )
            continue
        audio_s, hold_s, duration_s = fitted[spoken_index]
        item = spoken[spoken_index]
        spoken_index += 1
        updated = shot.model_copy(
            update={
                "duration_s": duration_s,
                "on_screen_text": _rescale(shot.on_screen_text, shot.duration_s, duration_s),
            }
        )
        take = ShotVoiceover(
            shot_id=shot.shot_id,
            uri=item["uri"],
            voice=voice,
            speed=speeds[shot.shot_id],
            pause_s=plans[shot.shot_id].pause_s,
            audio_s=audio_s,
            hold_s=hold_s,
            duration_s=duration_s,
            timestamps=item["timestamps"],
            transcript=item["transcript"],
            heard_check=item["heard_check"],
            cer=item["cer"],
            loudness_dbfs=item["loudness_dbfs"],
            clipped=item["clipped"],
            lexicon=item["lexicon"],
            role=plans[shot.shot_id].role,
            provenance=item["provenance"],
            seed=0,
        )
        shots.append(updated)
        takes.append(take)
        assets.append(item["asset"])
        log_event(
            "voiceover_ready",
            project_id=request.project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=attempt,
            duration_s=duration_s,
            audio_s=audio_s,
            hold_s=hold_s,
            speed=speeds[shot.shot_id],
            pause_s=plans[shot.shot_id].pause_s,
            role=plans[shot.shot_id].role,
        )
    try:
        rewritten = script.model_copy(update={"shots": shots})
    except ValidationError as exc:
        raise QAError(f"storyboard failed: {exc}") from exc
    board_total = round(sum(item.duration_s for item in rewritten.shots), 3)
    audio_total = round(sum(item.audio_s for item in takes), 3)
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        shots=len(rewritten.shots),
        audio_duration_s=audio_total,
        storyboard_duration_s=board_total,
        speed_factor=factor,
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload={
            "script": rewritten.model_dump(mode="json"),
            "shots": [shot.model_dump(mode="json") for shot in rewritten.shots],
            "assets": [asset.model_dump(mode="json") for asset in assets],
            "voiceovers": [take.model_dump(mode="json") for take in takes],
            "brief": payload.brief.model_dump(mode="json") if payload.brief else None,
            "brand_kit": brand.model_dump(mode="json") if brand else None,
            "audio_duration_s": audio_total,
            "storyboard_duration_s": board_total,
            "base_speed": base,
            "speed_factor": factor,
            "target_duration_s": payload.target_duration_s,
            "intro_s": payload.intro_s,
            "outro_s": payload.outro_s,
        },
        attempt=attempt,
    )


def _speak_all(
    script: Script,
    *,
    request: NodeRequest,
    attempt: int,
    deadline: Deadline,
    gateway: Any,
    voice: str,
    plans: dict[str, Any],
    speeds: dict[str, float],
    lexicon: tuple[Any, ...],
    brand_id: str | None,
    enterprise_id: str | None,
) -> list[dict[str, Any]]:
    spoken: list[dict[str, Any]] = []
    for shot in script.shots:
        if not shot.voiceover.strip():
            continue
        spoken.append(
            _speak_shot(
                shot,
                request=request,
                attempt=attempt,
                deadline=deadline,
                gateway=gateway,
                voice=voice,
                speed=speeds[shot.shot_id],
                pause_s=plans[shot.shot_id].pause_s,
                lexicon=lexicon,
                brand_id=brand_id,
                language=script.language,
                enterprise_id=enterprise_id,
            )
        )
    return spoken


def _speak_shot(
    shot: Shot,
    *,
    request: NodeRequest,
    attempt: int,
    deadline: Deadline,
    gateway: Any,
    voice: str,
    speed: float,
    pause_s: float,
    lexicon: tuple[Any, ...],
    brand_id: str | None,
    language: str,
    enterprise_id: str | None,
) -> dict[str, Any]:
    deadline.check()
    terms = matching_terms(shot.voiceover, lexicon)
    from workers.compliance.consent_gate import gated_tts

    try:
        spoken = gated_tts(
            gateway,
            shot.voiceover,
            voice=voice,
            enterprise_id=enterprise_id,
            seed=0,
            language=language,
            project_id=request.project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=attempt,
            params={
                "speed": speed,
                "pause_s": pause_s,
                "lexicon": terms,
            },
        )
    except TimeoutError:
        raise
    except Exception as exc:
        raise QAError(f"{shot.shot_id} tts failed: {exc}") from exc
    deadline.check()
    if not isinstance(spoken, dict):
        raise QAError(f"{shot.shot_id} tts returned a non-object")
    duration = _engine_duration(spoken, pause_s)
    wav = load_take(
        str(spoken.get("uri") or ""),
        text=shot.voiceover,
        speed=speed,
        pause_s=pause_s,
        seed=0,
        language=language,
        gateway=gateway,
        allow_mock=spoken.get("mock") is True,
    )
    level = analyze_wav(wav)
    if level.clipped:
        raise QAError(f"{shot.shot_id} voiceover is clipped")
    if abs(level.duration_s - duration) > FRAME_S:
        raise QAError(f"{shot.shot_id} wav {level.duration_s:.3f}s is not the take {duration:.3f}s")
    try:
        heard = gateway.asr(
            str(spoken.get("uri") or ""),
            language=language,
            project_id=request.project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=attempt,
            params={"reference_text": shot.voiceover},
        )
    except TimeoutError:
        raise
    except Exception as exc:
        raise QAError(f"{shot.shot_id} asr failed: {exc}") from exc
    deadline.check()
    transcript = ""
    if isinstance(heard, dict) and isinstance(heard.get("text"), str):
        transcript = heard["text"]
    cer = character_error_rate(shot.voiceover, transcript)
    if cer >= 0.02:
        raise QAError(f"{shot.shot_id} character error rate {cer:.4f} is not under 2%")
    uri = str(spoken.get("uri") or "")
    if not uri:
        raise QAError(f"{shot.shot_id} tts returned no uri")
    asset = Asset(
        asset_id=str(uuid.uuid5(ASSET_NS, f"{request.project_id}:{shot.shot_id}:{shot.voiceover}")),
        kind=AssetKind.voiceover,
        uri=uri,
        brand_id=brand_id,
        shot_id=shot.shot_id,
        mime_type=str(spoken.get("mime_type") or "audio/wav"),
        license_source="mock" if spoken.get("mock") else "volcengine-doubao-tts",
    )
    return {
        "shot_id": shot.shot_id,
        "audio_s": duration,
        "pause_s": pause_s,
        "uri": uri,
        "timestamps": _stamps(spoken.get("timestamps")),
        "transcript": transcript,
        "heard_check": (
            "verified"
            if heard.get("mock") is False
            else "not_verified_in_mock"
            if heard.get("mock") is True
            else "not_verified"
        ),
        "cer": round(cer, 6),
        "loudness_dbfs": level.loudness_dbfs,
        "clipped": level.clipped,
        "lexicon": [item["text"] for item in terms],
        "asset": asset,
        "provenance": (
            "mock"
            if spoken.get("mock") is True or uri.startswith("mock://")
            else "live"
            if spoken.get("mock") is False
            else "unknown"
        ),
    }


def _maybe_speed_up(
    spoken: list[dict[str, Any]],
    *,
    target: float,
    brief_s: float,
    plans: dict[str, Any],
    speeds: dict[str, float],
    request: NodeRequest,
    attempt: int,
    tolerance: float = DURATION_TOLERANCE,
) -> float:
    factor = boost_factor(
        [item["audio_s"] for item in spoken],
        [item["pause_s"] for item in spoken],
        target,
        tolerance=tolerance,
    )
    if factor is None:
        _flag_trim(spoken, target=brief_s, request=request, attempt=attempt)
    if factor <= 1:
        return 1.0
    for item in spoken:
        speeds[item["shot_id"]] = boosted_speed(plans[item["shot_id"]].speed, factor)
    log_event(
        "voiceover_speed_up",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        speed_factor=factor,
        target_s=target,
    )
    return factor


def _reject_if_still_long(
    spoken: list[dict[str, Any]],
    *,
    target: float,
    brief_s: float,
    request: NodeRequest,
    attempt: int,
    tolerance: float = DURATION_TOLERANCE,
) -> None:
    total = sum(item["audio_s"] for item in spoken)
    if total > target * (1 + tolerance):
        _flag_trim(spoken, target=brief_s, request=request, attempt=attempt)


def _flag_trim(
    spoken: list[dict[str, Any]],
    *,
    target: float,
    request: NodeRequest,
    attempt: int,
) -> NoReturn:
    total = round(sum(item["audio_s"] for item in spoken), 3)
    log_event(
        "copy_over_long",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        audio_s=total,
        brief_s=target,
        trim_copy=True,
    )
    raise QAError(
        f"trim_copy: voiceover {total:.3f}s exceeds the available story budget {target:.3f}s; "
        "N4 should shorten the script",
        retryable=False,
    )


def load_take(
    uri: str,
    *,
    text: str,
    speed: float,
    pause_s: float,
    seed: int | None,
    language: str | None = None,
    gateway: Any = None,
    allow_mock: bool | None = None,
) -> bytes:
    """Bytes for the loudness check. ``mock://`` is rebuilt with the same timing."""

    if uri.startswith("mock://"):
        permitted = (
            os.getenv("HILATV_LIVE", "0").strip() != "1" if allow_mock is None else allow_mock
        )
        if not permitted:
            raise QAError("mock voiceover requires an explicit mock result", retryable=False)
        data, _stamps, _duration = render_wav(
            text, seed, speed=speed, pause_s=pause_s, language=language
        )
        return data
    try:
        data = audio_bytes(uri, allowed_roots=[project_dir()], gateway=gateway)
        return wav_bytes(decode_audio(data))
    except AudioError as exc:
        raise QAError(f"voiceover audio is not readable: {exc}", retryable=False) from exc


def _engine_duration(spoken: dict[str, Any], pause_s: float) -> float:
    stamps = spoken.get("timestamps") if isinstance(spoken.get("timestamps"), list) else []
    end = 0.0
    for item in stamps:
        if isinstance(item, dict) and isinstance(item.get("end_s"), int | float):
            end = max(end, float(item["end_s"]))
    covered = round(end + max(0.0, pause_s), 3)
    raw = spoken.get("duration_s")
    if not isinstance(raw, int | float):
        return covered if covered > 0 else 0.001
    reported = round(float(raw), 3)
    if reported + FRAME_S < covered:
        return covered
    return reported


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
        if not isinstance(end, int | float):
            continue
        stamps.append(WordStamp(text=text, start_s=float(start), end_s=float(end)))
    return stamps


def _rescale(cards: list[OnScreenText], old: float, new: float) -> list[OnScreenText]:
    if old <= 0 or not cards:
        return list(cards)
    scale = new / old
    resized: list[OnScreenText] = []
    for card in cards:
        start = min(round(min(card.in_ * scale, new), 3), new)
        end = min(round(min(max(card.out * scale, start), new), 3), new)
        resized.append(card.model_copy(update={"in_": start, "out": end}))
    return resized


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
