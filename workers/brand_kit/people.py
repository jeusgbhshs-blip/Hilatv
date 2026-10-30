"""Portrait and voice consent. A person with consent false cannot be used.

T13 and every other node must take people from ``people_for_use`` / ``release_kit``.
Consent on a kit pasted into a project is not trusted; only the brand-flow archive is.
"""

from __future__ import annotations

from workers.schemas.brand import BrandKit, Person


class ConsentError(ValueError):
    """The enterprise did not check portrait (or voice) consent."""

    retryable = False


def usable_people(people: list[Person]) -> list[Person]:
    """People N2 is allowed to put on screen."""

    return [person for person in people if person.consent is True]


def require_consent(person: Person) -> Person:
    if person.consent is not True:
        raise ConsentError(f"未勾选肖像授权，不能使用「{person.role}」")
    return person


def check_voice(person: Person) -> None:
    """Voice cloning needs the same consent checkbox as the portrait."""

    if person.voice_id and person.consent is not True:
        raise ConsentError(f"未勾选肖像授权，不能使用「{person.role}」的声音")


def people_for_use(kit: BrandKit, *, trust_consent: bool = True) -> list[Person]:
    """People a downstream node (T13 included) is allowed to see.

    ``trust_consent`` is true only for a kit saved by the brand-flow archive.
    An inline kit is not that archive, so it yields nobody, even if the client
    set ``consent`` to true.
    """

    if not trust_consent:
        return []
    allowed: list[Person] = []
    for person in kit.people:
        if person.consent is not True:
            continue
        require_consent(person)
        allowed.append(person)
    return allowed


def release_kit(kit: BrandKit, *, trust_consent: bool) -> BrandKit:
    """Drop non-consented people, and therefore their photos, from a shared kit."""

    return kit.model_copy(update={"people": people_for_use(kit, trust_consent=trust_consent)})


def persist_people(kit: BrandKit) -> BrandKit:
    """Keep a withheld person on file, but never keep their photos or voice id."""

    stored: list[Person] = []
    for person in kit.people:
        if person.consent is not True:
            stored.append(
                person.model_copy(update={"photos": [], "voice_id": None, "consent": False})
            )
            continue
        stored.append(person)
    return kit.model_copy(update={"people": stored})
