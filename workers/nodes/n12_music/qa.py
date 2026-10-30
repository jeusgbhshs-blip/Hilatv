"""Quality check for N12.

Beat error, ducking, and loudness are measured again from the wav files.
A music or sound-effect row with no source or license blocks delivery.
"""

from __future__ import annotations

from pathlib import Path

from workers.media.ffmpeg import RenderError
from workers.nodes.n12_music.beats import detect_onsets, max_error_ms
from workers.nodes.n12_music.measure import ducking_db_on_mix, integrated_lufs, read_wav
from workers.nodes.n12_music.schema import (
    AudioTrack,
    LicenseRecord,
    LicensingSummary,
    NodeResult,
    incomplete_reason,
)
from workers.schemas.asset import Asset, AssetKind

BEAT_LIMIT_MS = 80.0
DUCK_MIN_DB = 10.0
DUCK_MAX_DB = 12.0
# 「约 -16」and the master window are assumptions. SPEC states the targets, not the ±.
NARRATION_TARGET = -16.0
MASTER_TARGET = -14.0
LOUDNESS_TOLERANCE = 1.0


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> LicensingSummary:
    if result.node != "n12_music":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n12_music result is not ok")
    summary = LicensingSummary.model_validate(result.payload.get("licensing_summary"))
    reason = incomplete_reason(summary.records)
    if reason or summary.blocked:
        raise QAError(reason or summary.block_reason or "license record is incomplete")
    _assets(result)
    AudioTrack.model_validate(result.payload.get("audio_track"))
    cuts = [float(item) for item in result.payload.get("cut_times_s") or []]
    bed = Path(str(result.payload.get("music_bed_path") or ""))
    ducked = Path(str(result.payload.get("music_ducked_path") or ""))
    narration = Path(str(result.payload.get("narration_path") or ""))
    mix = Path(str(result.payload.get("mix_path") or ""))
    for path, label in (
        (bed, "music bed"),
        (ducked, "ducked music"),
        (narration, "narration"),
        (mix, "mix"),
    ):
        if not path.is_file():
            raise QAError(f"missing {label}")
    samples, rate = read_wav(bed)
    onsets = detect_onsets(samples, rate)
    error_ms = max_error_ms(cuts, onsets)
    if error_ms > BEAT_LIMIT_MS:
        raise QAError(f"internal beat grid is {error_ms:.1f}ms off the planned cuts")
    narration_lufs = integrated_lufs(narration)
    master_lufs = integrated_lufs(mix)
    if abs(narration_lufs - NARRATION_TARGET) > LOUDNESS_TOLERANCE:
        raise QAError(f"narration {narration_lufs:.2f} LUFS is outside the window around -16")
    if abs(master_lufs - MASTER_TARGET) > LOUDNESS_TOLERANCE:
        raise QAError(f"master {master_lufs:.2f} LUFS is outside -14 ± {LOUDNESS_TOLERANCE:.0f}")
    try:
        ducking = ducking_db_on_mix(mix, narration, mix.parent)
    except RenderError as exc:
        raise QAError(str(exc)) from exc
    if not DUCK_MIN_DB <= ducking <= DUCK_MAX_DB:
        raise QAError(f"ducking {ducking:.2f} dB is outside 10–12")
    return summary


def _assets(result: NodeResult) -> None:
    assets = [Asset.model_validate(item) for item in result.payload.get("assets") or []]
    wanted = {AssetKind.music, AssetKind.sound_effect}
    seen = {item.kind for item in assets}
    if AssetKind.music not in seen:
        raise QAError("music asset is missing")
    for asset in assets:
        if asset.kind in wanted and not (asset.license_source or "").strip():
            raise QAError(f"{asset.kind} asset has no license_source")
    records = [LicenseRecord.model_validate(item) for item in result.payload.get("segments") or []]
    if incomplete_reason(records):
        raise QAError(incomplete_reason(records))
    if any(item.kind == "sfx" for item in records) and AssetKind.sound_effect not in seen:
        raise QAError("sound-effect asset is missing")
