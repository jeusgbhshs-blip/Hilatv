"""Illegal documents from the SPEC samples are rejected."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from workers.schemas import (
    Asset,
    AssetKind,
    BrandKit,
    Brief,
    Candidate,
    ClarifyingQuestion,
    DecisionAction,
    DirectorDecision,
    GenerationMode,
    RevisionDirective,
    Script,
    Shot,
)
from workers.schemas.script import OnScreenText, ScriptSection, ScriptSectionKind
from workers.schemas.tests.conftest import load_fixture


def _brand() -> dict[str, Any]:
    return deepcopy(load_fixture("brand_kit.json"))


def _brief() -> dict[str, Any]:
    return deepcopy(load_fixture("brief.json"))


def _shot() -> dict[str, Any]:
    return deepcopy(load_fixture("shot.json"))


def test_unknown_generation_mode_is_rejected() -> None:
    payload = _shot()
    payload["generation_mode"] = "ken_burns"
    with pytest.raises(ValidationError):
        Shot.model_validate(payload)


def test_every_generation_mode_is_accepted() -> None:
    payload = _shot()
    for mode in GenerationMode:
        payload["generation_mode"] = mode.value
        assert Shot.model_validate(payload).generation_mode is mode


def test_missing_consent_is_rejected() -> None:
    payload = _brand()
    del payload["people"][0]["consent"]
    with pytest.raises(ValidationError):
        BrandKit.model_validate(payload)


def test_consent_must_be_a_boolean() -> None:
    payload = _brand()
    payload["people"][0]["consent"] = "true"
    with pytest.raises(ValidationError):
        BrandKit.model_validate(payload)
    payload["people"][0]["consent"] = False
    kit = BrandKit.model_validate(payload)
    assert kit.consented_people() == []
    payload["people"][0]["consent"] = True
    assert len(BrandKit.model_validate(payload).consented_people()) == 1


@pytest.mark.parametrize("bad", ["thirty", "30", "30s", True, None, 30.5])
def test_brief_duration_must_be_an_integer(bad: object) -> None:
    payload = _brief()
    payload["duration_s"] = bad
    with pytest.raises(ValidationError):
        Brief.model_validate(payload)


@pytest.mark.parametrize("bad", ["4.2", "four", True, None])
def test_shot_duration_must_be_numeric(bad: object) -> None:
    payload = _shot()
    payload["duration_s"] = bad
    with pytest.raises(ValidationError):
        Shot.model_validate(payload)


def test_shot_duration_accepts_whole_number() -> None:
    payload = _shot()
    payload["duration_s"] = 4
    assert Shot.model_validate(payload).duration_s == 4.0


@pytest.mark.parametrize("seconds", [4, 181, 0, -1])
def test_brief_duration_range(seconds: int) -> None:
    payload = _brief()
    payload["duration_s"] = seconds
    with pytest.raises(ValidationError):
        Brief.model_validate(payload)
    payload["duration_s"] = 5
    assert Brief.model_validate(payload).duration_s == 5
    payload["duration_s"] = 180
    assert Brief.model_validate(payload).duration_s == 180


@pytest.mark.parametrize(
    "color",
    ["blue", "0A3D91", "#GG0000", "#0A3D91 ", "#FFF", "#0A3D91FF", 123],
)
def test_non_hex_color_is_rejected(color: object) -> None:
    payload = _brand()
    payload["colors"]["primary"] = color
    with pytest.raises(ValidationError):
        BrandKit.model_validate(payload)


def test_lowercase_hex_is_kept() -> None:
    payload = _brand()
    payload["colors"]["accent"] = "#f5a623"
    assert BrandKit.model_validate(payload).colors.accent == "#f5a623"


def test_empty_text_item_is_rejected() -> None:
    payload = _brief()
    payload["platform"] = [""]
    with pytest.raises(ValidationError):
        Brief.model_validate(payload)
    payload = _brief()
    payload["must_include"] = ["30MPa", ""]
    with pytest.raises(ValidationError):
        Brief.model_validate(payload)


def test_unknown_field_is_rejected() -> None:
    payload = _brief()
    payload["surprise"] = 1
    with pytest.raises(ValidationError):
        Brief.model_validate(payload)


def test_unknown_industry_is_rejected() -> None:
    payload = _brand()
    payload["industry"] = "aerospace"
    with pytest.raises(ValidationError):
        BrandKit.model_validate(payload)


def test_bad_aspect_ratio_and_language() -> None:
    payload = _brief()
    payload["aspect_ratios"] = ["wide"]
    with pytest.raises(ValidationError):
        Brief.model_validate(payload)
    payload = _brief()
    payload["languages"] = ["EN"]
    with pytest.raises(ValidationError):
        Brief.model_validate(payload)
    payload = _brief()
    payload["languages"] = ["zh-CN"]
    payload["aspect_ratios"] = ["1:1"]
    brief = Brief.model_validate(payload)
    assert brief.languages == ["zh-CN"]
    assert brief.aspect_ratios == ["1:1"]


def test_at_most_two_open_questions() -> None:
    question = {
        "question": "做竖屏还是横屏？",
        "recommended": "两个都出",
        "options": ["9:16", "16:9", "两个都出"],
    }
    payload = _brief()
    payload["open_questions"] = [question, question, question]
    with pytest.raises(ValidationError):
        Brief.model_validate(payload)
    payload["open_questions"] = [question, question]
    brief = Brief.model_validate(payload)
    assert len(brief.open_questions) == 2
    assert isinstance(brief.open_questions[0], ClarifyingQuestion)


def test_clarifying_question_defaults_options() -> None:
    question = ClarifyingQuestion.model_validate(
        {"question": "做竖屏还是横屏？", "recommended": "两个都出"}
    )
    assert question.options == []


def test_on_screen_text_out_before_in() -> None:
    with pytest.raises(ValidationError):
        OnScreenText.model_validate({"text": "30 MPa", "style": "spec_badge", "in": 2, "out": 1})


def test_shot_needs_subject_or_scene() -> None:
    payload = _shot()
    payload["subject_refs"] = []
    payload["scene_ref"] = ""
    with pytest.raises(ValidationError):
        Shot.model_validate(payload)
    payload["subject_refs"] = ["product:HP-300"]
    assert Shot.model_validate(payload).scene_ref == ""


def test_empty_subject_ref_is_rejected() -> None:
    payload = _shot()
    payload["subject_refs"] = [""]
    with pytest.raises(ValidationError):
        Shot.model_validate(payload)


def test_decision_action_and_attempt_cap() -> None:
    payload = load_fixture("director_decision.json")
    payload["action"] = "improvise"
    with pytest.raises(ValidationError):
        DirectorDecision.model_validate(payload)
    for action in DecisionAction:
        payload["action"] = action.value
        payload["max_attempts_left"] = 3
        parsed = DirectorDecision.model_validate(payload)
        assert parsed.action is action
    payload["action"] = "pass"
    payload["max_attempts_left"] = 4
    with pytest.raises(ValidationError):
        DirectorDecision.model_validate(payload)
    payload["max_attempts_left"] = -1
    with pytest.raises(ValidationError):
        DirectorDecision.model_validate(payload)


def test_decision_node_pattern() -> None:
    payload = load_fixture("director_decision.json")
    payload["target"]["node"] = "N19"
    with pytest.raises(ValidationError):
        DirectorDecision.model_validate(payload)
    payload["target"]["node"] = "N1"
    payload["target"]["shot_id"] = None
    decision = DirectorDecision.model_validate(payload)
    assert decision.target.node == "N1"
    assert decision.target.shot_id is None


def test_candidate_node_pattern() -> None:
    payload = load_fixture("candidate.json")
    payload["node"] = "n10"
    with pytest.raises(ValidationError):
        Candidate.model_validate(payload)


def test_score_and_total_bounds() -> None:
    payload = load_fixture("candidate.json")
    payload["qa"]["scores"]["aesthetics"] = 11
    with pytest.raises(ValidationError):
        Candidate.model_validate(payload)
    payload = load_fixture("candidate.json")
    payload["qa"]["total"] = 10.1
    with pytest.raises(ValidationError):
        Candidate.model_validate(payload)
    payload = load_fixture("candidate.json")
    payload["qa"]["hard_fail"] = [""]
    with pytest.raises(ValidationError):
        Candidate.model_validate(payload)
    payload["qa"]["hard_fail"] = ["产品形变"]
    assert Candidate.model_validate(payload).qa.hard_fail == ["产品形变"]


def test_non_finite_float_is_rejected() -> None:
    payload = _shot()
    payload["duration_s"] = float("inf")
    with pytest.raises(ValidationError):
        Shot.model_validate(payload)


def test_logo_safe_area_and_voice_speed() -> None:
    payload = _brand()
    payload["logo"]["safe_area_ratio"] = 0
    with pytest.raises(ValidationError):
        BrandKit.model_validate(payload)
    payload = _brand()
    payload["voice"]["speed"] = 0
    with pytest.raises(ValidationError):
        BrandKit.model_validate(payload)


def test_script_selling_point_cap_and_asset_roundtrip() -> None:
    shot = Shot.model_validate(load_fixture("shot.json"))
    sections = [
        ScriptSection(kind=ScriptSectionKind.hook, text="30 MPa, on the first frame."),
        ScriptSection(kind=ScriptSectionKind.selling_point, text="压力 30MPa", shot_ids=["S03"]),
        ScriptSection(kind=ScriptSectionKind.selling_point, text="寿命 2 万小时"),
        ScriptSection(kind=ScriptSectionKind.selling_point, text="接口不改"),
        ScriptSection(kind=ScriptSectionKind.proof, text="工厂实拍感"),
        ScriptSection(kind=ScriptSectionKind.cta, text="0532-xxxx"),
    ]
    script = Script(
        script_id="script-1",
        brief_id="uuid",
        language="en",
        sections=sections,
        shots=[shot],
    )
    dumped = script.model_dump(mode="json")
    assert dumped["shots"][0]["generation_mode"] == "product_composite"
    assert Script.model_validate(dumped).script_id == "script-1"
    sections.append(ScriptSection(kind=ScriptSectionKind.selling_point, text="第四个卖点"))
    with pytest.raises(ValidationError):
        Script(script_id="script-1", brief_id="uuid", language="en", sections=sections, shots=[])

    asset = Asset(
        asset_id="asset-1",
        kind=AssetKind.cutout,
        uri="oss://...front_cutout.png",
        brand_id="uuid",
    )
    again = Asset.model_validate(asset.model_dump(mode="json"))
    assert again.kind is AssetKind.cutout
    assert again.shot_id is None
    assert again.license_source is None
    with pytest.raises(ValidationError):
        Asset.model_validate({"asset_id": "asset-1", "kind": "poster", "uri": "oss://x"})


def test_revision_directive_matches_n18_shape() -> None:
    directive = RevisionDirective.model_validate(
        {"targets": ["S02"], "change": {"lighting": "brighter"}, "keep": ["composition"]}
    )
    assert directive.model_dump(mode="json") == {
        "targets": ["S02"],
        "change": {"lighting": "brighter"},
        "keep": ["composition"],
    }
    with pytest.raises(ValidationError):
        RevisionDirective.model_validate({"targets": [], "change": {"lighting": "brighter"}})
    with pytest.raises(ValidationError):
        RevisionDirective.model_validate({"targets": ["S02"], "change": {}, "keep": [""]})
