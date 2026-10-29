"""N6 voiceover. One storyboard in, the same shots with audio-driven durations.

TTS and ASR both go through the gateway. On-screen text stays on the shot for
the render nodes; this node only moves its in/out marks when the shot length
changes. The same input replays the same durations.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import ValidationError

from gateway.media_bytes import render_wav
from gateway.storage import StorageError, object_store_from_env
from workers.logging import log_event
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
from workers.schemas.asset import Asset, AssetKind
from workers.schemas.script import OnScreenText, Shot

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
    plans = plan_prosody(script, base)
    lexicon = load_lexicon()
    shots: list[Shot] = []
    takes: list[ShotVoiceover] = []
    assets: list[Asset] = []
    for shot in script.shots:
        deadline.check()
        plan = plans[shot.shot_id]
        if not shot.voiceover.strip():
            shots.append(shot)
            continue
        terms = matching_terms(shot.voiceover, lexicon)
        try:
            spoken = gateway.tts(
                shot.voiceover,
                voice=voice,
                seed=0,
                language=script.language,
                project_id=request.project_id,
                node=NODE,
                shot_id=shot.shot_id,
                attempt=attempt,
                params={
                    "speed": plan.speed,
                    "pause_s": plan.pause_s,
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
        duration = _engine_duration(spoken, plan.pause_s)
        wav = load_take(
            str(spoken.get("uri") or ""),
            text=shot.voiceover,
            speed=plan.speed,
            pause_s=plan.pause_s,
            seed=0,
        )
        level = analyze_wav(wav)
        if level.clipped:
            raise QAError(f"{shot.shot_id} voiceover is clipped")
        if abs(level.duration_s - duration) > FRAME_S:
            raise QAError(
                f"{shot.shot_id} wav {level.duration_s:.3f}s is not the take {duration:.3f}s"
            )
        try:
            heard = gateway.asr(
                str(spoken.get("uri") or ""),
                language=script.language,
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
        stamps = _stamps(spoken.get("timestamps"))
        updated = shot.model_copy(
            update={
                "duration_s": duration,
                "on_screen_text": _rescale(shot.on_screen_text, shot.duration_s, duration),
            }
        )
        uri = str(spoken.get("uri") or "")
        if not uri:
            raise QAError(f"{shot.shot_id} tts returned no uri")
        take = ShotVoiceover(
            shot_id=shot.shot_id,
            uri=uri,
            voice=voice,
            speed=plan.speed,
            pause_s=plan.pause_s,
            duration_s=duration,
            timestamps=stamps,
            transcript=transcript,
            cer=round(cer, 6),
            loudness_dbfs=level.loudness_dbfs,
            clipped=level.clipped,
            lexicon=[item["text"] for item in terms],
            role=plan.role,
        )
        asset = Asset(
            asset_id=str(
                uuid.uuid5(ASSET_NS, f"{request.project_id}:{shot.shot_id}:{shot.voiceover}")
            ),
            kind=AssetKind.voiceover,
            uri=uri,
            brand_id=brand.brand_id if brand is not None else None,
            shot_id=shot.shot_id,
            mime_type=str(spoken.get("mime_type") or "audio/wav"),
            license_source="mock" if spoken.get("mock") else "volcengine-doubao-tts",
        )
        shots.append(updated)
        takes.append(take)
        assets.append(asset)
        log_event(
            "voiceover_ready",
            project_id=request.project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=attempt,
            duration_s=duration,
            speed=plan.speed,
            pause_s=plan.pause_s,
            role=plan.role,
        )
    try:
        rewritten = script.model_copy(update={"shots": shots})
    except ValidationError as exc:
        raise QAError(f"storyboard failed: {exc}") from exc
    board_total = round(sum(item.duration_s for item in rewritten.shots), 3)
    audio_total = board_total
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        shots=len(rewritten.shots),
        audio_duration_s=audio_total,
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
        },
        attempt=attempt,
    )


def load_take(
    uri: str,
    *,
    text: str,
    speed: float,
    pause_s: float,
    seed: int | None,
) -> bytes:
    """Bytes for the loudness check. ``mock://`` is rebuilt with the same timing."""

    if uri.startswith(("oss://", "s3://")):
        store = object_store_from_env()
        if store is None:
            raise QAError(f"voiceover audio is not readable: {uri}")
        try:
            return store.get(uri)
        except StorageError as exc:
            raise QAError(f"voiceover audio is not readable: {uri}") from exc
    if uri.startswith("mock://"):
        data, _stamps, _duration = render_wav(text, seed, speed=speed, pause_s=pause_s)
        return data
    raise QAError(f"unsupported audio uri: {uri}")


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
        start = round(min(card.in_ * scale, new), 3)
        end = round(min(max(card.out * scale, start), new), 3)
        resized.append(card.model_copy(update={"in_": start, "out": end}))
    return resized


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
