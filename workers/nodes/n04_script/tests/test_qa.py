"""Planted numbers and banned words are rejected."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workers.nodes.n04_script.compose import compose_script
from workers.nodes.n04_script.facts import collect_facts
from workers.nodes.n04_script.qa import QAError, audit_script
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import ScriptSectionKind

FIXTURES = Path(__file__).resolve().parents[3] / "schemas" / "tests" / "fixtures"


def _pair() -> tuple[Brief, BrandKit]:
    brief = Brief.model_validate(json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8")))
    raw_brand = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))
    brand = BrandKit.model_validate(raw_brand)
    return brief, brand


def test_planted_number_is_blocked() -> None:
    brief, brand = _pair()
    facts = collect_facts(brief, brand)
    script = compose_script(project_id="p", brief=brief, facts=facts, language="zh")
    sections = list(script.sections)
    sections[1] = sections[1].model_copy(update={"text": "寿命 99999 万小时"})
    planted = script.model_copy(update={"sections": sections})
    with pytest.raises(QAError, match="99999"):
        audit_script(planted, brief, brand)


def test_banned_word_is_blocked() -> None:
    brief, brand = _pair()
    facts = collect_facts(brief, brand)
    script = compose_script(project_id="p", brief=brief, facts=facts, language="zh")
    sections = list(script.sections)
    hook = sections[0].model_copy(update={"text": "这是最好的泵"})
    planted = script.model_copy(update={"sections": [hook, *sections[1:]]})
    with pytest.raises(QAError, match="最好"):
        audit_script(planted, brief, brand)
    assert planted.sections[0].kind is ScriptSectionKind.hook
