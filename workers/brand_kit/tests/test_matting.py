import base64

import pytest

from workers.brand_kit.colors import extract_colors
from workers.brand_kit.matting import matte, mono_plate, with_safe_margin
from workers.brand_kit.people import ConsentError, require_consent, usable_people
from workers.brand_kit.tests.images import logo_png, noise_png
from workers.schemas.brand import Person


def test_flat_logo_mattes_and_keeps_a_safe_margin() -> None:
    cut = matte(logo_png())
    assert cut.edge.ok
    assert cut.edge.message == ""
    padded, ratio = with_safe_margin(cut.png)
    assert 0.2 <= ratio <= 1
    white = mono_plate(padded, rgb=(255, 255, 255))
    black = mono_plate(padded, rgb=(0, 0, 0))
    assert white != black
    colors = extract_colors(padded)
    primary = colors.primary.lstrip("#")
    red, green, blue = int(primary[0:2], 16), int(primary[2:4], 16), int(primary[4:6], 16)
    assert blue > red and blue > green


def test_speckled_edge_asks_for_a_new_picture() -> None:
    cut = matte(noise_png())
    assert cut.edge.ok is False
    assert "请更换图片" in cut.edge.message


def test_unconsented_person_cannot_be_used() -> None:
    blocked = Person(
        person_id="p-no",
        role="老板",
        photos=[],
        consent=False,
        voice_id=None,
    )
    allowed = Person(
        person_id="p-yes",
        role="工程师",
        photos=["brand://p.png"],
        consent=True,
        voice_id=None,
    )
    assert [person.person_id for person in usable_people([blocked, allowed])] == ["p-yes"]
    with pytest.raises(ConsentError, match="肖像授权"):
        require_consent(blocked)
    require_consent(allowed)


def test_logo_bytes_are_self_drawn() -> None:
    raw = base64.b64encode(logo_png()).decode("ascii")
    assert raw.startswith("iVBORw0KGgo")
