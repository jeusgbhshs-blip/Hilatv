"""Gates expert mode is not allowed to skip.

QA passes only when ``visual_reviewed`` is True. Content-safety hard fails
stay out of the master. Cloned voices come from the enterprise archive.
The 「AI生成」 label and font license records are checked on the server.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError

from workers.brand_kit.people import people_for_use
from workers.brand_kit.store import load_record
from workers.expert.licenses import LicenseError, LicenseRecord, require_license
from workers.media.fonts import resolve_font
from workers.media.packaging import ai_label_text
from workers.nodes.n06_voiceover.prosody import DEFAULT_VOICE
from workers.qa.scores import content_blocked, is_quality_pass
from workers.schemas.asset import Candidate, QAReport
from workers.schemas.brand import BrandKit, Person


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
    """People the archive released for this enterprise. Inline kits are ignored."""

    if not enterprise_id:
        return []
    try:
        uuid.UUID(enterprise_id)
    except ValueError:
        return []
    record = load_record(enterprise_id)
    if record is None:
        return []
    try:
        kit = BrandKit.model_validate(record.brand_kit)
    except ValidationError:
        return []
    return people_for_use(kit, trust_consent=True)


def voice_allowlist(enterprise_id: str | None) -> set[str]:
    return {person.voice_id for person in server_people(enterprise_id) if person.voice_id}


def consent_gate(enterprise_id: str | None, voice_id: str | None) -> None:
    """A cloned voice must already be on the archive allowlist."""

    if voice_id is None or not str(voice_id).strip():
        return
    if voice_id not in voice_allowlist(enterprise_id):
        raise GateError("该克隆声音不在企业授权名单里")


def scrub_brand(raw: dict[str, Any] | None, enterprise_id: str | None) -> dict[str, Any] | None:
    """Drop caller-supplied people. Keep only archive people and a stock voice."""

    if raw is None:
        return None
    try:
        kit = BrandKit.model_validate(raw)
    except ValidationError as exc:
        raise GateError("品牌资料无效") from exc
    allowed = server_people(enterprise_id)
    allowed_voices = {person.voice_id for person in allowed if person.voice_id}
    clone_ids = {person.voice_id for person in kit.people if person.voice_id}
    voice = kit.voice
    if voice.tts_voice in clone_ids and voice.tts_voice not in allowed_voices:
        voice = voice.model_copy(update={"tts_voice": DEFAULT_VOICE})
    released = kit.model_copy(update={"people": allowed, "voice": voice})
    return released.model_dump(mode="json")


def assert_ai_label(items: list[dict[str, Any]]) -> None:
    label = ai_label_text()
    if any(item.get("kind") == "ai_label" and item.get("text") == label for item in items):
        return
    raise GateError("不能去掉「AI生成」标识")


def enforce_fonts() -> list[LicenseRecord]:
    """The fonts the render layer resolved, checked against LicenseRecord."""

    found: list[LicenseRecord] = []
    for weight in ("regular", "bold"):
        try:
            path = resolve_font(weight)
        except FileNotFoundError as exc:
            raise LicenseError("缺少可商用授权：font") from exc
        found.append(require_license(path.name, "font"))
    return found


def check_voices(
    voiceovers: list[dict[str, Any]],
    *,
    enterprise_id: str | None,
    brand: dict[str, Any] | None,
) -> None:
    allowed = voice_allowlist(enterprise_id)
    stock = DEFAULT_VOICE
    if isinstance(brand, dict):
        voice = brand.get("voice")
        if isinstance(voice, dict) and isinstance(voice.get("tts_voice"), str):
            stock = voice["tts_voice"]
    for item in voiceovers:
        used = str(item.get("voice") or "")
        if not used or used == stock or used in allowed:
            continue
        raise GateError("配音使用了未授权的克隆声音")
