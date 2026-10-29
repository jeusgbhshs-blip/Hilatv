"""Rule-written scripts stay inside the N4 length and provenance rules."""

from __future__ import annotations

import json
from pathlib import Path

from workers.nodes.n04_script.compose import compose_script
from workers.nodes.n04_script.facts import collect_facts
from workers.nodes.n04_script.qa import audit_script
from workers.qa.copycheck import count_units, spoken_seconds, target_units, within_target
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief

FIXTURES = Path(__file__).resolve().parents[3] / "schemas" / "tests" / "fixtures"


def _brief() -> Brief:
    return Brief.model_validate(json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8")))


def _brand() -> BrandKit:
    raw = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))
    return BrandKit.model_validate(raw)


def test_chinese_and_english_hit_the_length_window() -> None:
    brief = _brief()
    brand = _brand()
    facts = collect_facts(brief, brand)
    zh = compose_script(project_id="p", brief=brief, facts=facts, language="zh")
    en = compose_script(project_id="p", brief=brief, facts=facts, language="en")
    for script in (zh, en):
        audit_script(script, brief, brand)
        total = sum(count_units(section.text, script.language) for section in script.sections)
        assert within_target(total, target_units(brief.duration_s, script.language))
        assert spoken_seconds(script.sections[0].text, script.language) <= 3
    assert [section.text for section in zh.sections] != [section.text for section in en.sections]
    assert facts.points == ["压力 30MPa", "寿命 2 万小时"]


def test_short_chinese_spot_keeps_one_sourced_point() -> None:
    brief = _brief().model_copy(update={"duration_s": 5, "languages": ["zh"]})
    facts = collect_facts(brief, _brand())
    script = compose_script(project_id="p", brief=brief, facts=facts, language="zh")
    audit_script(script, brief, _brand())
    points = [section.text for section in script.sections if section.kind.value == "selling_point"]
    assert points == ["压力 30MPa"]
    assert "999" not in "".join(section.text for section in script.sections)
