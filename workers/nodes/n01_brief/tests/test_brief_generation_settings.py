"""User controls outrank text, platform, model and template without QA loops."""

import copy

import pytest

from workers.nodes.n01_brief.node import run
from workers.nodes.n01_brief.qa import QAError, check
from workers.nodes.n01_brief.schema import NodeResult
from workers.schemas.tests.test_generation import RATIOS


@pytest.mark.parametrize("ratio", RATIOS)
def test_explicit_primary_format_survives_platform_conflict(gateway, ratio):
    result = run(
        {
            "project_id": "explicit-format",
            "payload": {
                "raw_input": "给机床做抖音9:16竖屏15秒宣传视频",
                "generation_settings": {"aspect_ratio": ratio, "duration_s": 30},
            },
        },
        gateway=gateway,
    )
    brief = check(result)
    assert brief.aspect_ratios == [ratio]
    assert brief.duration_s == 30
    assert brief.generation_settings.duration_s == 30
    assert result.attempt == 1
    assert not any("补齐" in note or "调整为" in note for note in brief.assumptions)
    assert not any("画面比例和投放平台" in item.question for item in brief.open_questions)
    if ratio not in {"9:16", "1:1"}:
        assert any("主画幅不会自动修改" in note for note in brief.assumptions)


def test_null_settings_preserve_legacy_inference_and_id(gateway):
    body = {"project_id": "legacy-format", "payload": {"raw_input": "机床抖音15秒竖屏宣传"}}
    legacy = run(body, gateway=gateway)
    explicit_auto = copy.deepcopy(body)
    explicit_auto["payload"]["generation_settings"] = {"aspect_ratio": None, "duration_s": None}
    assert run(explicit_auto, gateway=gateway).payload["brief"] == legacy.payload["brief"]
    settings = copy.deepcopy(body)
    settings["payload"]["generation_settings"] = {"aspect_ratio": "21:9", "duration_s": 5}
    changed = run(settings, gateway=gateway)
    assert changed.payload["brief"]["brief_id"] != legacy.payload["brief"]["brief_id"]


def test_explicit_settings_outrank_a_conflicting_model(gateway, monkeypatch):
    monkeypatch.setattr(
        gateway,
        "generate_text",
        lambda *_args, **_kwargs: {"duration_s": 180, "aspect_ratios": ["9:16"]},
    )
    result = run(
        {
            "project_id": "conflicting-model",
            "payload": {
                "raw_input": "机床宣传",
                "generation_settings": {"aspect_ratio": "4:3", "duration_s": 5},
            },
        },
        gateway=gateway,
    )
    assert check(result).duration_s == 5
    assert check(result).aspect_ratios == ["4:3"]
    tampered = result.model_dump()
    tampered["payload"]["brief"]["aspect_ratios"].append("9:16")
    with pytest.raises(QAError, match="explicit primary"):
        check(NodeResult.model_validate(tampered))
