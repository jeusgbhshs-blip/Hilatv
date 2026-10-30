"""Rule findings on the synthetic plates."""

from __future__ import annotations

from workers.qa.pixels import open_image
from workers.qa.rules import inspect_image
from workers.qa.samples import _bars, _face, _plate, _watermark


def test_clean_plate_has_no_finding() -> None:
    assert inspect_image(_plate("rect"), anchor=_plate("rect"), expected_faces=0) == []


def test_words_and_scribbles_are_different_codes() -> None:
    words = inspect_image(_plate("rect", text="SALE HOT LINE"), anchor=_plate("rect"))
    scribbles = inspect_image(_plate("rect", garbled=1), anchor=_plate("rect"))
    assert any(item.code == "extra_text" for item in words)
    assert any(item.code == "garbled_text" for item in scribbles)


def test_shear_is_product_deform_and_a_copy_is_not() -> None:
    anchor = _plate("rect")
    warped = inspect_image(_plate("shear"), anchor=anchor)
    same = inspect_image(_plate("rect"), anchor=anchor)
    assert any(item.code == "product_deform" for item in warped)
    assert same == []


def test_three_eyes_collapse_and_an_extra_face_is_counted() -> None:
    broken = inspect_image(_face(eyes=3), expected_faces=1)
    extra = inspect_image(_face(eyes=2), expected_faces=0)
    clean = inspect_image(_face(eyes=2), expected_faces=1)
    assert any(item.code == "face_collapse" for item in broken)
    assert any(item.code == "face_count" for item in extra)
    assert clean == []


def test_bars_watermark_resolution_and_crop() -> None:
    bars = inspect_image(_bars(_plate("rect"), "top"))
    marked = inspect_image(_watermark(_plate("rect"), phase=0))
    assert any(item.code == "black_bar" for item in bars)
    assert any(item.code == "watermark" for item in marked)
    assert any(
        item.code == "low_resolution" for item in inspect_image(_plate("rect").resize((96, 54)))
    )
    assert any(item.code == "bad_composition" for item in inspect_image(_plate("clip_left")))
    assert open_image("mock://image/x") is None
