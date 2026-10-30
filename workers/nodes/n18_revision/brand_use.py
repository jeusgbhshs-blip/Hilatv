"""Brand kits seen by a revision. People come only from the consent helpers.

An inline kit pasted onto a project is not the brand archive, so
``trust_consent`` stays false and no portrait is released. T15 owns
``people_for_use`` / ``release_kit``. Until that module is importable, every
person is dropped and none of their fields are read.
"""

from __future__ import annotations

from workers.schemas.brand import BrandKit


def gate_brand(kit: BrandKit | None, *, from_archive: bool = False) -> BrandKit | None:
    """Return the kit a revision node is allowed to pass downstream."""

    if kit is None:
        return None
    try:
        from workers.brand_kit.people import people_for_use, release_kit
    except ImportError:
        return kit.model_copy(update={"people": []})
    released = release_kit(kit, trust_consent=from_archive)
    allowed = people_for_use(released, trust_consent=from_archive)
    if not from_archive and allowed:
        raise RuntimeError("an inline brand kit must not yield people")
    return released
