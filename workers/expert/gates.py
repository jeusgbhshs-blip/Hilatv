"""Gates expert mode is not allowed to skip.

QA passes only when ``visual_reviewed`` is True. Content-safety hard fails
stay out of the master. Cloned voices come from the enterprise archive.
The 「AI生成」 label and font license records are checked on the server.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from workers.brand_kit.people import ConsentError
from workers.compliance.consent_gate import archive_people, assert_voice_allowed
from workers.compliance.licences import builtin_records, delivery_block_reason
from workers.media.packaging import ai_label_text
from workers.nodes.n06_voiceover.prosody import DEFAULT_VOICE
from workers.qa.scores import content_blocked, is_quality_pass
from workers.schemas.asset import Candidate, QAReport
from workers.schemas.brand import BrandKit, Person
from workers.schemas.label_lock import LabelLocked, walk_label_edits


class GateError(Exception):
    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def qa_passed_flag(report: QAReport) -> bool:
    """Unreviewed output is not a pass. The judge flag has to be True."""

    if report.visual_reviewed is not True:
        return False
    return is_quality_pass(report)


def verdict_of(report: QAReport) -> dict[str, Any]:
    reviewed = report.visual_reviewed is True
    return {
        "visual_reviewed": reviewed,
        "qa_passed": qa_passed_flag(report),
        "hard_fail": list(report.hard_fail),
        "total": report.total if reviewed else None,
        "notes": report.notes,
        "blocked": content_blocked(report),
    }


def enforce_review(candidate: Candidate, report: QAReport) -> Candidate:
    """Attach ``report`` as-is. This never sets ``visual_reviewed`` to True."""

    reviewed = report.visual_reviewed is True
    safe = report.model_copy(update={"visual_reviewed": reviewed})
    selected = bool(candidate.selected) and not content_blocked(safe)
    return candidate.model_copy(update={"qa": safe, "selected": selected})


def server_people(enterprise_id: str | None) -> list[Person]:
    """People ``archive_people`` released. An inline kit is not that archive."""

    return archive_people(enterprise_id)


def voice_allowlist(enterprise_id: str | None) -> set[str]:
    return {person.voice_id for person in server_people(enterprise_id) if person.voice_id}


def consent_gate(enterprise_id: str | None, voice_id: str | None) -> None:
    """Delegates to the archive voice allowlist. Caller consent is ignored."""

    try:
        assert_voice_allowed(voice_id, enterprise_id)
    except ConsentError as exc:
        raise GateError(str(exc)) from exc


def refuse_label_bypass(payload: object) -> None:
    """The visible 「AI生成」 mark cannot be switched off from a re-run body."""

    try:
        walk_label_edits(payload)
    except LabelLocked as exc:
        raise GateError(str(exc)) from exc


def scrub_brand(raw: dict[str, Any] | None, enterprise_id: str | None) -> dict[str, Any] | None:
    """Drop caller-supplied people. Keep only archive people and an allowed voice."""

    if raw is None:
        return None
    try:
        kit = BrandKit.model_validate(raw)
    except ValidationError as exc:
        raise GateError("品牌资料无效") from exc
    allowed = server_people(enterprise_id)
    voice = kit.voice
    try:
        assert_voice_allowed(voice.tts_voice, enterprise_id)
    except ConsentError:
        voice = voice.model_copy(update={"tts_voice": DEFAULT_VOICE})
    released = kit.model_copy(update={"people": allowed, "voice": voice})
    return released.model_dump(mode="json")


def assert_ai_label(items: list[dict[str, Any]]) -> None:
    label = ai_label_text()
    if any(item.get("kind") == "ai_label" and item.get("text") == label for item in items):
        return
    raise GateError("不能去掉「AI生成」标识")


def enforce_fonts() -> None:
    """Font rows are the N12 ``LicenseRecord`` list. A caller flag is not a record."""

    reason = delivery_block_reason(builtin_records())
    if reason:
        raise GateError(f"缺少可商用授权：{reason}")


def check_voices(
    voiceovers: list[dict[str, Any]],
    *,
    enterprise_id: str | None,
    brand: dict[str, Any] | None,
) -> None:
    del brand
    for item in voiceovers:
        used = str(item.get("voice") or "")
        if not used:
            continue
        consent_gate(enterprise_id, used)
