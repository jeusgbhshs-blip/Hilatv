"""People and cloned voices enter generation only through the brand archive.

Callers must use ``people_for_use`` / ``release_kit``. A kit pasted into a
project is not an archive, even when ``consent`` is true.
"""

from __future__ import annotations

from workers.brand_kit.people import ConsentError, people_for_use, release_kit
from workers.schemas.brand import BrandKit, Person
from workers.schemas.script import Shot


def archived_people(kit: BrandKit | None, *, archived: bool) -> list[Person]:
    """People a generator is allowed to see. An unarchived kit yields nobody."""

    if kit is None or not archived:
        return []
    return people_for_use(release_kit(kit, trust_consent=True))


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


def assert_generation_allowed(shot: Shot, kit: BrandKit | None, *, archived: bool) -> None:
    """Block a person shot that is not backed by an archived consent checkbox."""

    if not is_person_shot(shot):
        return
    allowed = archived_people(kit, archived=archived)
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


def assert_voice_allowed(voice_id: str | None, kit: BrandKit | None, *, archived: bool) -> None:
    """A stock TTS voice is not a clone. A person's ``voice_id`` needs the archive."""

    if not voice_id or kit is None:
        return
    clones = [person for person in kit.people if person.voice_id and person.voice_id == voice_id]
    if not clones:
        return
    allowed = {person.voice_id for person in archived_people(kit, archived=archived)}
    if voice_id not in allowed:
        role = clones[0].role
        raise ConsentError(f"未归档声音授权，不能使用「{role}」的声音")
