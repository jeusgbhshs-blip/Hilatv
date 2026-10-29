"""Quality check for N6. A bad take is retried, not returned."""

from __future__ import annotations

from workers.nodes.n06_voiceover.audio import (
    CER_LIMIT,
    FRAME_S,
    LOUDNESS_MAX_DB,
    LOUDNESS_MIN_DB,
)
from workers.nodes.n06_voiceover.prosody import DEFAULT_SPEED, plan_prosody
from workers.nodes.n06_voiceover.schema import NodeResult, ShotVoiceover
from workers.schemas.asset import Asset, AssetKind
from workers.schemas.brand import BrandKit
from workers.schemas.script import Script, Shot


class QAError(Exception):
    """The node result failed this node's quality check."""


def check(result: NodeResult) -> Script:
    if result.node != "n06_voiceover":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n06_voiceover result is not ok")
    script = _script(result.payload.get("script"))
    if not script.shots:
        raise QAError("n06_voiceover script has no shots")
    brand = _brand(result.payload.get("brand_kit"))
    base = brand.voice.speed if brand is not None else DEFAULT_SPEED
    plans = plan_prosody(script, base)
    takes = _takes(result.payload.get("voiceovers"))
    assets = _assets(result.payload.get("assets"))
    by_shot = {item.shot_id: item for item in takes}
    asset_by_shot = {item.shot_id: item for item in assets}
    if len(by_shot) != len(takes):
        raise QAError("voiceover shot_id values must be unique")
    spoken = [shot for shot in script.shots if shot.voiceover.strip()]
    if not spoken:
        raise QAError("n06_voiceover script has no voiceover")
    if len(takes) != len(spoken):
        raise QAError("each spoken shot needs one voiceover")
    audio_total = 0.0
    board_total = 0.0
    for shot in script.shots:
        plan = plans[shot.shot_id]
        board_total += shot.duration_s
        if not shot.voiceover.strip():
            audio_total += shot.duration_s
            continue
        take = by_shot.get(shot.shot_id)
        if take is None:
            raise QAError(f"{shot.shot_id} is missing a voiceover")
        if take.role != plan.role:
            raise QAError(f"{shot.shot_id} role {take.role} != {plan.role}")
        if abs(take.speed - plan.speed) > 1e-4:
            raise QAError(f"{shot.shot_id} speed {take.speed} != {plan.speed}")
        if abs(take.pause_s - plan.pause_s) > 1e-4:
            raise QAError(f"{shot.shot_id} pause {take.pause_s} != {plan.pause_s}")
        if abs(shot.duration_s - take.duration_s) > 0.001:
            raise QAError(f"{shot.shot_id} duration {shot.duration_s} != audio {take.duration_s}")
        if take.cer >= CER_LIMIT:
            raise QAError(f"{shot.shot_id} character error rate {take.cer:.4f} is not under 2%")
        if take.clipped:
            raise QAError(f"{shot.shot_id} voiceover is clipped")
        if not LOUDNESS_MIN_DB <= take.loudness_dbfs <= LOUDNESS_MAX_DB:
            raise QAError(
                f"{shot.shot_id} loudness {take.loudness_dbfs} dBFS "
                f"is outside {LOUDNESS_MIN_DB} to {LOUDNESS_MAX_DB}"
            )
        _cards_inside(shot)
        _timestamps_cover(take)
        asset = asset_by_shot.get(shot.shot_id)
        if asset is None or asset.kind is not AssetKind.voiceover or asset.uri != take.uri:
            raise QAError(f"{shot.shot_id} is missing a voiceover asset")
        audio_total += take.duration_s
    if abs(audio_total - board_total) > FRAME_S:
        raise QAError(
            f"audio {audio_total:.3f}s and storyboard {board_total:.3f}s "
            "differ by more than one frame"
        )
    return script


def _script(raw: object) -> Script:
    if not isinstance(raw, dict):
        raise QAError("n06_voiceover payload is missing script")
    return Script.model_validate(raw)


def _brand(raw: object) -> BrandKit | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise QAError("brand_kit must be an object")
    return BrandKit.model_validate(raw)


def _takes(raw: object) -> list[ShotVoiceover]:
    if not isinstance(raw, list) or not raw:
        raise QAError("n06_voiceover payload is missing voiceovers")
    return [ShotVoiceover.model_validate(item) for item in raw]


def _assets(raw: object) -> list[Asset]:
    if not isinstance(raw, list):
        raise QAError("n06_voiceover payload is missing assets")
    return [Asset.model_validate(item) for item in raw]


def _cards_inside(shot: Shot) -> None:
    duration = shot.duration_s
    for card in shot.on_screen_text:
        if card.in_ < -1e-6 or card.out > duration + 1e-6:
            raise QAError(f"{shot.shot_id} on-screen text falls outside the shot")


def _timestamps_cover(take: ShotVoiceover) -> None:
    if not take.timestamps:
        raise QAError(f"{take.shot_id} is missing word timestamps")
    end = max(item.end_s for item in take.timestamps)
    if end - 1e-3 > take.duration_s:
        raise QAError(f"{take.shot_id} timestamps run past the audio")
    if abs(take.duration_s - (end + take.pause_s)) > FRAME_S + 0.001:
        raise QAError(f"{take.shot_id} duration does not cover the words plus the pause")
