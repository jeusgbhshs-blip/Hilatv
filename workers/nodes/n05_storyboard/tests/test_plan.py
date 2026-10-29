"""Duration, rhythm, and mode rules hold across the brief's duration range."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workers.nodes.n04_script.compose import compose_script
from workers.nodes.n04_script.facts import collect_facts
from workers.nodes.n05_storyboard.plan import plan_shots
from workers.nodes.n05_storyboard.qa import QAError, audit_storyboard
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import GenerationMode

FIXTURES = Path(__file__).resolve().parents[3] / "schemas" / "tests" / "fixtures"


def _base() -> tuple[Brief, BrandKit]:
    brief = Brief.model_validate(json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8")))
    raw_brand = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))
    brand = BrandKit.model_validate(raw_brand)
    return brief, brand


def _board(
    duration: int,
    video_type: str,
    raw: str,
    *,
    brand: BrandKit | None,
) -> tuple[Brief, object]:
    brief, _kit = _base()
    brief = brief.model_copy(
        update={
            "duration_s": duration,
            "video_type": video_type,
            "raw_input": raw,
            "languages": ["zh"],
        }
    )
    facts = collect_facts(brief, brand)
    script = compose_script(project_id="p", brief=brief, facts=facts, language="zh")
    return brief, plan_shots(script, brief, brand)


@pytest.mark.parametrize("duration", [5, 9, 15, 30, 45, 180])
@pytest.mark.parametrize(
    ("video_type", "raw"),
    [("product_showcase", "做宣传片"), ("sku_clip", "做带货短视频")],
)
def test_duration_grid(duration: int, video_type: str, raw: str) -> None:
    _, brand = _base()
    brief, script = _board(duration, video_type, f"{raw}{duration}秒", brand=brand)
    audit_storyboard(script, brief, brand)
    total = sum(shot.duration_s for shot in script.shots)
    assert abs(total - duration) / duration <= 0.05
    assert len(script.shots) <= duration / 2
    assert all(shot.generation_mode is not GenerationMode.first_last_frame for shot in script.shots)


def test_product_without_cutout_uses_reference() -> None:
    _, brand = _base()
    brand.products[0].cutouts = []
    brief, script = _board(30, "product_showcase", "做30秒宣传片", brand=brand)
    audit_storyboard(script, brief, brand)
    selling = [shot for shot in script.shots if shot.purpose == "卖点"]
    assert selling
    assert all(shot.generation_mode is GenerationMode.reference_to_video for shot in selling)


def test_continuous_person_uses_reference() -> None:
    _, brand = _base()
    brand.people[0].photos = ["oss://boss.jpg"]
    brief, script = _board(30, "product_showcase", "老板出镜讲这台泵", brand=brand)
    audit_storyboard(script, brief, brand)
    people = [shot for shot in script.shots if shot.purpose == "人物出镜"]
    assert len(people) >= 2
    assert all(shot.generation_mode is GenerationMode.reference_to_video for shot in people)
    assert all(any(ref.startswith("person:") for ref in shot.subject_refs) for shot in people)


def test_no_product_photo_uses_image_to_video() -> None:
    brief, script = _board(15, "sku_clip", "给杯子做15秒短视频", brand=None)
    audit_storyboard(script, brief, None)
    selling = [shot for shot in script.shots if "卖点" in shot.purpose]
    assert selling
    assert all(shot.generation_mode is GenerationMode.image_to_video for shot in selling)


def test_planted_onscreen_number_is_blocked() -> None:
    brief, script = _board(30, "product_showcase", "做30秒宣传片", brand=_base()[1])
    shot = script.shots[1].model_copy(deep=True)
    card = shot.on_screen_text[0].model_copy(update={"text": "99999 MPa"})
    shot = shot.model_copy(update={"on_screen_text": [card]})
    shots = list(script.shots)
    shots[1] = shot
    planted = script.model_copy(update={"shots": shots})
    with pytest.raises(QAError, match="99999"):
        audit_storyboard(planted, brief, _base()[1])
