"""Quality check for N13. A line that splits a word or drifts from the audio fails."""

from __future__ import annotations

from workers.media.packaging import ALIGNMENT_MS, EN_MAX_CHARS, ZH_MAX_CHARS, lexicon_words
from workers.nodes.n06_voiceover.schema import ShotVoiceover
from workers.nodes.n13_subtitle.schema import NodeResult, SubtitleCue
from workers.nodes.n13_subtitle.segment import is_chinese, stamp_bounds, within_alignment
from workers.schemas.asset import Asset, AssetKind
from workers.schemas.script import Script


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> list[SubtitleCue]:
    if result.node != "n13_subtitle":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n13_subtitle result is not ok")
    script = Script.model_validate(result.payload.get("script"))
    cues = [SubtitleCue.model_validate(item) for item in result.payload.get("cues") or []]
    takes = [ShotVoiceover.model_validate(item) for item in result.payload.get("voiceovers") or []]
    by_shot = {item.shot_id: item for item in takes}
    assets = [Asset.model_validate(item) for item in result.payload.get("assets") or []]
    if not any(item.kind is AssetKind.subtitle for item in assets):
        raise QAError("n13_subtitle did not write a subtitle asset")
    protected = set(lexicon_words())
    protected.update(str(item) for item in result.payload.get("protected_words") or [])
    spoken = [shot for shot in script.shots if shot.voiceover.strip()]
    if spoken and not cues:
        raise QAError("spoken shots produced no subtitles")
    grouped: dict[str, list[SubtitleCue]] = {}
    for cue in cues:
        _audit_cue(cue, by_shot.get(cue.shot_id))
        grouped.setdefault(cue.shot_id, []).append(cue)
    for shot_id, rows in grouped.items():
        take = by_shot.get(shot_id)
        source = take.transcript if take and take.transcript else ""
        if take is None:
            continue
        shot = next((item for item in script.shots if item.shot_id == shot_id), None)
        voice = shot.voiceover if shot is not None else source
        zh = is_chinese(rows[0].language, voice)
        _assert_not_split([row.text for row in rows], protected, voice, zh=zh)
        if _compact("".join(row.text for row in rows)) != _compact(voice):
            raise QAError(f"{shot_id} subtitles do not match the voiceover")
    return cues


def _audit_cue(cue: SubtitleCue, take: ShotVoiceover | None) -> None:
    if take is None:
        raise QAError(f"{cue.shot_id} subtitle has no voiceover")
    if cue.lines != [cue.text] and "\n".join(cue.lines) != cue.text:
        raise QAError(f"{cue.cue_id} lines do not match the cue text")
    zh = is_chinese(cue.language, cue.text)
    limit = ZH_MAX_CHARS if zh else EN_MAX_CHARS
    for line in cue.lines:
        count = _count(line, zh=zh)
        if count > limit:
            raise QAError(f"{cue.cue_id} line is {count} characters, limit {limit}")
    if not within_alignment(cue.alignment_error_ms):
        raise QAError(
            f"{cue.cue_id} alignment {cue.alignment_error_ms:.1f}ms exceeds {ALIGNMENT_MS}ms"
        )
    bounds = stamp_bounds(cue.text, take.timestamps)
    if bounds is None:
        raise QAError(f"{cue.cue_id} does not match the voiceover timestamps")
    drift = max(abs(cue.audio_start_s - bounds[0]), abs(cue.audio_end_s - bounds[1])) * 1000
    if drift > ALIGNMENT_MS:
        raise QAError(f"{cue.cue_id} is {drift:.1f}ms away from the audio")
    if cue.end_s + 1e-3 < cue.start_s:
        raise QAError(f"{cue.cue_id} ends before it starts")


def _count(line: str, *, zh: bool) -> int:
    if zh:
        return sum(1 for char in line if not char.isspace())
    return len(line)


def _assert_not_split(lines: list[str], protected: set[str], voiceover: str, *, zh: bool) -> None:
    limit = ZH_MAX_CHARS if zh else EN_MAX_CHARS
    flat = "".join(lines)
    for word in protected:
        if len(word) < 2 or word not in voiceover or _count(word, zh=zh) > limit:
            continue
        if not any(word in line for line in lines):
            if word in flat or _compact(word) in _compact(flat):
                raise QAError(f"protected word {word} was split across subtitle lines")


def _compact(text: str) -> str:
    return "".join(char for char in text if not char.isspace())
