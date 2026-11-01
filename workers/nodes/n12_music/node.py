"""N12 music and sound effects.

Music comes from the gateway ``music`` call. With no key that call is the mock
adapter, which names a track from the in-repo test library. Beat clicks are
synthesized, detected on the wav, and the shot cuts are moved onto them.
Sound effects are picked from the same test library by shot wording.
"""

from __future__ import annotations

import array
import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

from gateway.media_bytes import MUSIC_RATE, beat_sample_index
from workers.logging import log_event
from workers.media.audio import (
    AudioError,
    AudioProvenance,
    audio_bytes,
    combine_provenance,
    decode_audio,
)
from workers.media.ffmpeg import RenderError
from workers.nodes.n06_voiceover.node import load_take
from workers.nodes.n06_voiceover.qa import QAError as VoiceError
from workers.nodes.n12_music.align import boundaries_for
from workers.nodes.n12_music.library import (
    EVIDENCE_REF,
    EXPIRES_ON,
    LICENSE_NOTE,
    SFX_CATALOG,
    USAGE_SCOPE,
    Track,
    match_sfx,
    select_track,
)
from workers.nodes.n12_music.mix import Region, build_mix, effect_start, tail_samples
from workers.nodes.n12_music.prompts import render_music_prompt
from workers.nodes.n12_music.qa import QAError, check
from workers.nodes.n12_music.schema import (
    AudioTrack,
    CutPoint,
    LicenseRecord,
    LicensingSummary,
    N12Input,
    NodeRequest,
    NodeResult,
    incomplete_reason,
)
from workers.nodes.runtime import Deadline
from workers.qa.settings import project_dir
from workers.schemas.asset import Asset, AssetKind
from workers.schemas.script import OnScreenText, Script, Shot

NODE = "n12_music"
ASSET_NS = uuid.UUID("6f1c0a1e-7b2d-4e5a-9c31-0c0a6e6e0712")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 120.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N12Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway or _default_gateway()
    deadline = Deadline(timeout_s, node=NODE)
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            deadline.check()
            result = _execute(request, attempt=attempt, deadline=deadline, gateway=gateway)
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
        except RenderError as exc:
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
    message = f"n12_music failed after {max_attempts} attempts: {last_error}"
    raise QAError(message, retryable=False) from last_error


def _execute(
    request: NodeRequest,
    *,
    attempt: int,
    deadline: Deadline,
    gateway: Any,
) -> NodeResult:
    payload = N12Input.model_validate(request.payload)
    if not payload.script.shots:
        raise QAError("n12_music needs at least one shot", retryable=False)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    deadline.check()
    mood = _mood(payload)
    track = select_track(mood)
    durations = [float(shot.duration_s) for shot in payload.script.shots]
    voice_pcm, voice_sources = _load_voices(payload, gateway)
    minimums = [
        len(voice_pcm[shot.shot_id]) / MUSIC_RATE if shot.shot_id in voice_pcm else 0.0
        for shot in payload.script.shots
    ]
    marks = boundaries_for(durations, minimums, track)
    end_beat = marks[-1]
    n_samples = tail_samples(end_beat, track.bpm)
    duration_s = n_samples / MUSIC_RATE
    prompt = render_music_prompt(mood=mood, duration_s=duration_s, bpm=track.bpm)
    seed = _seed(request.project_id)
    spoken = _call_music(
        gateway,
        prompt,
        duration_s=duration_s,
        seed=seed,
        track=track,
        request=request,
        attempt=attempt,
    )
    deadline.check()
    source = str(spoken.get("source") or "").strip()
    license_name = str(spoken.get("license") or "").strip()
    if not source or not license_name:
        raise QAError("music response has no source or license", retryable=False)
    _reject_test_library_when_live(spoken, source, license_name)
    work = _work_dir(payload.work_dir, request.project_id)
    cuts, _regions, placed = _layout(payload.script.shots, marks, minimums, track.bpm)
    mock_music = spoken.get("mock") is True
    if placed and os.getenv("HILATV_LIVE", "0").strip() == "1" and not mock_music:
        raise QAError("live sound effects require a licensed audio source", retryable=False)
    try:
        music = (
            None
            if mock_music
            else decode_audio(
                audio_bytes(
                    str(spoken.get("uri") or ""), allowed_roots=[project_dir()], gateway=gateway
                )
            )
        )
        narration = _place_voices(voice_pcm, cuts, n_samples)
        files = build_mix(
            work=work,
            n_samples=n_samples,
            bpm=track.bpm,
            seed=seed,
            effects=[(kind, start) for kind, start, _shot_id in placed],
            narration=narration,
            music=music,
            mock_music=mock_music,
        )
    except AudioError as exc:
        raise QAError(str(exc), retryable=False) from exc
    provenance = combine_provenance(
        [
            *voice_sources,
            "mock" if mock_music else "live" if spoken.get("mock") is False else "unknown",
            # These procedural effects are the explicitly internal-only test library.
            *(["mock"] if placed else []),
        ]
    )
    records = _records(
        cuts,
        placed,
        track=track,
        source=source,
        license_name=license_name,
        bed_uri=files.music_bed.resolve().as_uri(),
        work=work,
    )
    reason = incomplete_reason(records)
    if reason:
        raise QAError(reason, retryable=False)
    summary = LicensingSummary(project_id=request.project_id, records=records, blocked=False)
    assets = _assets(request.project_id, payload, records)
    audio = AudioTrack(
        path=str(files.mix),
        start_s=None,
        duration_s=round(files.duration_s, 6),
        source=source,
        license=license_name,
        provenance=provenance,
        narration_path=str(files.narration),
        music_path=str(files.music_ducked),
        sfx_path=str(files.sfx),
        music_source_uri=str(spoken.get("uri") or "") or None,
    )
    aligned = _aligned_script(payload.script, cuts)
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        duration_s=round(files.duration_s, 3),
        library_id=track.library_id,
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        attempt=attempt,
        payload={
            "script": payload.script.model_dump(mode="json"),
            "aligned_script": aligned.model_dump(mode="json"),
            "cuts": [item.model_dump(mode="json") for item in cuts],
            "cut_times_s": _cut_times(cuts),
            "narration_regions": [
                {"start_s": region.start_s, "end_s": region.end_s}
                for region in files.narration_regions
            ],
            "segments": [item.model_dump(mode="json") for item in records],
            "licensing_summary": summary.model_dump(mode="json"),
            "audio_track": audio.model_dump(mode="json"),
            "assets": [item.model_dump(mode="json") for item in assets],
            "music_bed_path": str(files.music_bed),
            "music_ducked_path": str(files.music_ducked),
            "narration_path": str(files.narration),
            "sfx_path": str(files.sfx),
            "mix_path": str(files.mix),
            "mood": mood,
            "bpm": track.bpm,
            "prompt": prompt,
            "audio_provenance": provenance,
            "has_narration": bool(voice_pcm),
        },
    )


def _call_music(
    gateway: Any,
    prompt: str,
    *,
    duration_s: float,
    seed: int,
    track: Track,
    request: NodeRequest,
    attempt: int,
) -> dict[str, Any]:
    try:
        spoken = gateway.music(
            prompt,
            duration_s=duration_s,
            seed=seed,
            project_id=request.project_id,
            node=NODE,
            shot_id=request.shot_id,
            attempt=attempt,
            params={
                "bpm": track.bpm,
                "library_id": track.library_id,
                "source": track.source,
                "license": "CC0-1.0",
                "instrumental": True,
            },
        )
    except TimeoutError:
        raise
    except Exception as exc:
        raise QAError(f"music call failed: {exc}") from exc
    if not isinstance(spoken, dict):
        raise QAError("music call returned a non-object")
    return spoken


def _layout(
    shots: list[Shot],
    marks: list[int],
    voice_s: list[float],
    bpm: float,
) -> tuple[list[CutPoint], list[Region], list[tuple[str, int, str]]]:
    cuts: list[CutPoint] = []
    regions: list[Region] = []
    placed: list[tuple[str, int, str]] = []
    pairs = zip(shots, marks[:-1], marks[1:], voice_s, strict=True)
    for shot, start_beat, end_beat, spoken in pairs:
        start = beat_sample_index(start_beat, bpm) / MUSIC_RATE
        end = beat_sample_index(end_beat, bpm) / MUSIC_RATE
        cuts.append(CutPoint(shot_id=shot.shot_id, start_s=start, end_s=end))
        if spoken > 0 and shot.voiceover.strip():
            voice_end = min(end, start + spoken)
            if voice_end - start >= 0.05:
                regions.append(Region(start, voice_end))
        kind = match_sfx(shot)
        if kind is not None:
            start_sample = beat_sample_index(start_beat, bpm)
            end_sample = beat_sample_index(end_beat, bpm)
            placed.append(
                (kind, effect_start(kind, start_sample, end_sample, MUSIC_RATE), shot.shot_id)
            )
    return cuts, regions, placed


def _records(
    cuts: list[CutPoint],
    effects: list[tuple[str, int, str]],
    *,
    track: Track,
    source: str,
    license_name: str,
    bed_uri: str,
    work: Path,
) -> list[LicenseRecord]:
    span = cuts[-1].end_s - cuts[0].start_s if cuts else 0.0
    records = [
        LicenseRecord(
            record_id="music-bed",
            kind="music",
            source=source,
            license=license_name,
            title=track.title,
            uri=bed_uri,
            start_s=cuts[0].start_s if cuts else 0.0,
            duration_s=round(span, 6),
            note=LICENSE_NOTE,
            **_rights(),
        )
    ]
    for index, (kind, start, shot_id) in enumerate(effects):
        title, sfx_source = SFX_CATALOG[kind]
        records.append(
            LicenseRecord(
                record_id=f"sfx-{index + 1}",
                kind="sfx",
                source=sfx_source,
                license=license_name,
                title=title,
                uri=(work / "sfx.wav").resolve().as_uri(),
                start_s=round(start / MUSIC_RATE, 6),
                duration_s=0.45 if kind == "machine" else 0.18 if kind == "whoosh" else 0.09,
                shot_id=shot_id,
                note=LICENSE_NOTE,
                **_rights(),
            )
        )
    return records


def _assets(project_id: str, payload: N12Input, records: list[LicenseRecord]) -> list[Asset]:
    del payload
    assets: list[Asset] = []
    for record in records:
        kind = AssetKind.music if record.kind == "music" else AssetKind.sound_effect
        assets.append(
            Asset(
                asset_id=str(uuid.uuid5(ASSET_NS, f"{project_id}:{record.record_id}")),
                kind=kind,
                uri=record.uri,
                shot_id=record.shot_id,
                mime_type="audio/wav",
                license_source=f"{record.source}|{record.license}",
            )
        )
    return assets


def _aligned_script(script: Script, cuts: list[CutPoint]) -> Script:
    by_id = {item.shot_id: item for item in cuts}
    shots: list[Shot] = []
    for shot in script.shots:
        cut = by_id[shot.shot_id]
        duration = round(cut.end_s - cut.start_s, 6)
        cards = _rescale(shot.on_screen_text, float(shot.duration_s), duration)
        shots.append(shot.model_copy(update={"duration_s": duration, "on_screen_text": cards}))
    return script.model_copy(update={"shots": shots})


def _rescale(cards: list[OnScreenText], old: float, new: float) -> list[OnScreenText]:
    if old <= 0 or not cards or abs(new - old) < 1e-6:
        return list(cards)
    scale = new / old
    resized: list[OnScreenText] = []
    for card in cards:
        start = round(min(card.in_ * scale, new), 3)
        end = round(min(max(card.out * scale, start), new), 3)
        resized.append(card.model_copy(update={"in_": start, "out": end}))
    return resized


def _cut_times(cuts: list[CutPoint]) -> list[float]:
    if not cuts:
        return []
    times = [cuts[0].start_s]
    times.extend(item.end_s for item in cuts)
    return times


def _load_voices(
    payload: N12Input, gateway: Any
) -> tuple[dict[str, array.array], list[AudioProvenance]]:
    takes = {item.shot_id: item for item in payload.voiceovers}
    if len(takes) != len(payload.voiceovers):
        raise QAError("voiceover shot ids must be unique", retryable=False)
    found = {}
    sources = []
    for shot in payload.script.shots:
        if not shot.voiceover.strip():
            continue
        take = takes.get(shot.shot_id)
        if take is None:
            raise QAError(f"{shot.shot_id} is missing a voiceover asset", retryable=False)
        try:
            data = load_take(
                take.uri,
                text=shot.voiceover,
                speed=take.speed,
                pause_s=take.pause_s,
                seed=take.seed,
                language=payload.script.language,
                gateway=gateway,
                allow_mock=True if take.provenance == "mock" else None,
            )
            samples = decode_audio(data)
        except (AudioError, VoiceError) as exc:
            raise QAError(
                f"{shot.shot_id} voiceover is unreadable: {exc}", retryable=False
            ) from exc
        if abs(len(samples) / MUSIC_RATE - take.audio_s) > 1 / 30 + 0.001:
            raise QAError(f"{shot.shot_id} audio duration does not match its take", retryable=False)
        if not any(samples):
            raise QAError(f"{shot.shot_id} voiceover is silent", retryable=False)
        found[shot.shot_id] = samples
        sources.append("mock" if take.uri.startswith("mock://") else take.provenance)
    return found, sources


def _place_voices(voices: dict[str, array.array], cuts: list[CutPoint], count: int) -> array.array:
    narration = array.array("h", [0] * count)
    for cut in cuts:
        samples = voices.get(cut.shot_id)
        if samples is None:
            continue
        start = round(cut.start_s * MUSIC_RATE)
        end = start + len(samples)
        if end > round(cut.end_s * MUSIC_RATE) + 1 or end > count:
            raise AudioError(f"{cut.shot_id} narration exceeds the aligned shot")
        narration[start:end] = samples
    return narration


def _rights() -> dict[str, str]:
    return {
        "evidence_ref": EVIDENCE_REF,
        "expires_on": EXPIRES_ON,
        "usage_scope": USAGE_SCOPE,
    }


def _reject_test_library_when_live(spoken: dict[str, Any], source: str, license_name: str) -> None:
    """Explicit mock fallback may finish a preview, never masquerade as live."""

    if os.getenv("HILATV_LIVE", "0").strip() != "1":
        return
    if spoken.get("mock") is True:
        return
    test_source = source.startswith("hilatv-test-")
    if test_source:
        raise QAError(
            "live mode cannot deliver the mock test-library licence",
            retryable=False,
        )


def _work_dir(raw: str | None, project_id: str) -> Path:
    root = project_dir()
    default = root / project_id / "n12"
    if not raw:
        default.mkdir(parents=True, exist_ok=True)
        return default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise QAError(
            "n12 work directory must stay inside the project directory",
            retryable=False,
        )
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _mood(payload: N12Input) -> str:
    if payload.mood.strip():
        return payload.mood.strip()
    if payload.brief is not None and payload.brief.style.strip():
        return payload.brief.style.strip()
    return "稳定"


def _seed(project_id: str) -> int:
    return int(hashlib.sha256(project_id.encode()).hexdigest()[:8], 16) % 100_000


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
