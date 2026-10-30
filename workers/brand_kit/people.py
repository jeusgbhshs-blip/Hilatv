"""Portrait and voice consent. A person with consent false cannot be used."""

from __future__ import annotations

from workers.schemas.brand import Person


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
