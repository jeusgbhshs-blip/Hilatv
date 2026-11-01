"""Quality check for N6. A bad take is retried, not returned."""

from __future__ import annotations

from workers.media.timing import duration_budget
from workers.nodes.n06_voiceover.audio import (
    CER_LIMIT,
    FRAME_S,
    LOUDNESS_MAX_DB,
    LOUDNESS_MIN_DB,
)
from workers.nodes.n06_voiceover.prosody import DEFAULT_SPEED, plan_prosody
from workers.nodes.n06_voiceover.schema import NodeResult, ShotVoiceover
from workers.nodes.n06_voiceover.timing import DURATION_TOLERANCE, MAX_SPEED_BOOST, boosted_speed
from workers.schemas.asset import Asset, AssetKind
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import Script, Shot


class QAError(Exception):
    """The node result failed this node's quality check."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


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
    factor = _speed_factor(result.payload.get("speed_factor"))
    board_total = 0.0
    for shot in script.shots:
        plan = plans[shot.shot_id]
        board_total += shot.duration_s
        if not shot.voiceover.strip():
            continue
        take = by_shot.get(shot.shot_id)
        if take is None:
            raise QAError(f"{shot.shot_id} is missing a voiceover")
        if take.role != plan.role:
            raise QAError(f"{shot.shot_id} role {take.role} != {plan.role}")
        expected_speed = boosted_speed(plan.speed, factor)
        if abs(take.speed - expected_speed) > 1e-3:
            raise QAError(f"{shot.shot_id} speed {take.speed} != {expected_speed}")
        if abs(take.pause_s - plan.pause_s) > 1e-4:
            raise QAError(f"{shot.shot_id} pause {take.pause_s} != {plan.pause_s}")
        if shot.duration_s + 0.001 < take.audio_s:
            raise QAError(f"{shot.shot_id} duration {shot.duration_s} is shorter than its audio")
        if abs(shot.duration_s - take.duration_s) > 0.001:
            raise QAError(
                f"{shot.shot_id} duration {shot.duration_s} != timeline {take.duration_s}"
            )
        if abs((take.audio_s + take.hold_s) - take.duration_s) > 0.001:
            raise QAError(f"{shot.shot_id} hold does not add up to the shot")
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
    brief = _brief(result.payload.get("brief"))
    if result.payload.get("target_duration_s") is not None:
        exact = duration_budget(
            result.payload["target_duration_s"],
            intro_s=result.payload.get("intro_s", 0),
            outro_s=result.payload.get("outro_s"),
        )
        if abs(board_total - exact.body_s) > 0.001:
            raise QAError(
                "storyboard does not match the explicit whole-film frame budget", retryable=False
            )
    elif brief is not None and brief.duration_s > 0:
        error = abs(board_total - brief.duration_s) / brief.duration_s
        if error > DURATION_TOLERANCE + 1e-9:
            raise QAError(
                f"storyboard {board_total:.3f}s is {error:.2%} off brief {brief.duration_s}s"
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
    if end - 1e-3 > take.audio_s:
        raise QAError(f"{take.shot_id} timestamps run past the audio")
    if abs(take.audio_s - (end + take.pause_s)) > FRAME_S + 0.001:
        raise QAError(f"{take.shot_id} audio does not cover the words plus the pause")


def _speed_factor(raw: object) -> float:
    if raw is None:
        return 1.0
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        raise QAError("speed_factor must be a number")
    factor = float(raw)
    if factor < 1 or factor > MAX_SPEED_BOOST + 1e-9:
        raise QAError(f"speed_factor {factor} is outside 1–{MAX_SPEED_BOOST}")
    return factor


def _brief(raw: object) -> Brief | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise QAError("brief must be an object")
    return Brief.model_validate(raw)
