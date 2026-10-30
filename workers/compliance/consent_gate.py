"""People and cloned voices enter generation only from the brand archive.

The archive is the T15 brand record for ``enterprise_id``. Consent on a kit
in the request is ignored. ``people_for_use`` / ``release_kit`` are the only
way a person or a cloned voice is released.

A narration ``voice_id`` is allowed only when it is on the gateway's built-in
list, or it is a clone on a person that archive already released. The request
kit is never consulted for that decision.
"""

from __future__ import annotations

from typing import Any

from gateway.constants import BUILTIN_TTS_VOICES
from workers.brand_kit.people import ConsentError, people_for_use
from workers.brand_kit.store import export_record, load_record
from workers.compliance.voice_token import issue_voice_token
from workers.schemas.brand import BrandKit, Person
from workers.schemas.script import Shot


def archive_people(enterprise_id: str | None) -> list[Person]:
    """People the brand store has already released for this enterprise."""

    if not enterprise_id:
        return []
    record = load_record(enterprise_id)
    if record is None:
        return []
    exported = export_record(record)
    kit = BrandKit.model_validate(exported["brand_kit"])
    return people_for_use(kit)


def person_refs(shot: Shot) -> list[str]:
    found: list[str] = []
    for ref in shot.subject_refs:
        if not ref.startswith("person:"):
            continue
        name = ref.split(":", 1)[1].strip()
        if name:
            found.append(name)
    return found


def is_person_shot(shot: Shot) -> bool:
    return bool(person_refs(shot)) or "人物" in shot.purpose


def assert_generation_allowed(shot: Shot, enterprise_id: str | None) -> None:
    """Block a person shot that is not in the archived release."""

    if not is_person_shot(shot):
        return
    allowed = archive_people(enterprise_id)
    roles = {person.role for person in allowed}
    ids = {person.person_id for person in allowed}
    refs = person_refs(shot)
    if not refs:
        if not allowed:
            raise ConsentError("未归档肖像授权，人物不能进入生成")
        return
    for ref in refs:
        if ref not in roles and ref not in ids:
            raise ConsentError(f"未归档肖像授权，不能使用「{ref}」")


def assert_voice_allowed(
    voice_id: str | None,
    enterprise_id: str | None,
    request_kit: BrandKit | None = None,
) -> None:
    """Allow a built-in gateway voice, or a clone the brand archive released.

    ``request_kit`` is ignored. Leaving the person off the request does not
    turn a cloned ``voice_id`` into stock TTS, and putting them on the request
    does not authorize the clone.
    """

    del request_kit
    if not voice_id:
        return
    if voice_id in BUILTIN_TTS_VOICES:
        return
    archived = {person.voice_id for person in archive_people(enterprise_id) if person.voice_id}
    if voice_id in archived:
        return
    raise ConsentError("未归档声音授权，不能使用该声音")


def issue_tts_consent(voice_id: str | None, enterprise_id: str | None) -> str:
    """Allow the voice, then hand back the only token ``Gateway.tts`` accepts."""

    assert_voice_allowed(voice_id, enterprise_id)
    return issue_voice_token(voice_id or "", enterprise_id or "")


def gated_tts(
    gateway: Any,
    text: str,
    *,
    voice: str | None,
    enterprise_id: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """The only supported way for a node to synthesize speech."""

    token = issue_tts_consent(voice, enterprise_id)
    return gateway.tts(
        text,
        voice=voice,
        consent_token=token,
        enterprise_id=enterprise_id or "",
        **kwargs,
    )
