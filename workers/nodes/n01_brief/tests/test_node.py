import time

import pytest
from pydantic import ValidationError

from gateway.schema_util import fill_json_schema
from workers.nodes.n01_brief import node as node_mod
from workers.nodes.n01_brief.node import run
from workers.nodes.n01_brief.prompts import NO_DRAWN_TEXT
from workers.nodes.n01_brief.qa import QAError, check
from workers.nodes.n01_brief.schema import ExtractedBrief, NodeResult
from workers.schemas.brief import Brief


def test_mock_extraction_schema_is_empty() -> None:
    raw = fill_json_schema(ExtractedBrief.model_json_schema())
    parsed = ExtractedBrief.model_validate(raw)
    assert parsed.industry == ""
    assert parsed.goal == ""
    assert parsed.duration_s is None
    assert parsed.platform == []
    assert parsed.aspect_ratios == []
    assert parsed.languages == []
    assert parsed.must_include == []


def test_run_returns_brief(gateway) -> None:
    result = run(
        {"project_id": "proj-1", "shot_id": "s1", "payload": {"raw_input": "做个视频"}},
        gateway=gateway,
    )
    brief = check(result)
    assert isinstance(brief, Brief)
    assert result.attempt == 1
    assert NO_DRAWN_TEXT in result.payload["prompt"]
    assert brief.raw_input == "做个视频"
    logs = gateway.store.list_logs(project_id="proj-1")
    assert logs
    assert logs[0]["node"] == "n01_brief"
    assert logs[0]["task"] == "llm"
    assert logs[0]["provider"] == "mock"


def test_rerun_is_stable(gateway) -> None:
    raw = {"project_id": "proj-1", "payload": {"raw_input": "给数控机床做一条产品宣传片"}}
    first = run(raw, gateway=gateway)
    second = run(raw, gateway=gateway)
    assert first.payload["brief"] == second.payload["brief"]


def test_invalid_input_fails_fast(gateway) -> None:
    with pytest.raises(ValidationError):
        run({"project_id": ""}, gateway=gateway)
    with pytest.raises(ValidationError):
        run({"project_id": "proj-1", "payload": {}}, gateway=gateway)


def test_timeout(gateway) -> None:
    with pytest.raises(TimeoutError):
        run(
            {"project_id": "proj-1", "payload": {"raw_input": "做个视频"}},
            gateway=gateway,
            timeout_s=0,
        )


def test_timeout_after_slow_model(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*_args: object, **_kwargs: object) -> dict[str, object]:
        time.sleep(0.2)
        return {}

    monkeypatch.setattr(gateway, "generate_text", slow)
    with pytest.raises(TimeoutError):
        run(
            {"project_id": "proj-1", "payload": {"raw_input": "做个视频"}},
            gateway=gateway,
            timeout_s=0.05,
        )


def test_retries_then_passes(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky(result: NodeResult) -> Brief:
        calls["n"] += 1
        if calls["n"] < 3:
            raise QAError("transient")
        return check(result)

    monkeypatch.setattr(node_mod, "check", flaky)
    result = run({"project_id": "proj-1", "payload": {"raw_input": "做个视频"}}, gateway=gateway)
    assert result.ok is True
    assert result.attempt == 3
    assert calls["n"] == 3


def test_qa_gives_up(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    def bad(_result: NodeResult) -> None:
        raise QAError("nope")

    monkeypatch.setattr(node_mod, "check", bad)
    with pytest.raises(QAError):
        run(
            {"project_id": "proj-1", "payload": {"raw_input": "做个视频"}},
            gateway=gateway,
            max_attempts=2,
        )


def test_llm_fills_gaps_without_overriding_user_facts(gateway) -> None:
    class Scripted:
        def generate_text(self, _prompt: str, **_kwargs: object) -> dict[str, object]:
            return {
                "industry": "education",
                "goal": "模型给的目标",
                "platform": ["mock"],
                "duration_s": 99,
                "aspect_ratios": ["mock"],
                "languages": ["mock"],
                "video_type": "explainer",
                "audience": "",
                "must_include": ["mock"],
                "style": "",
            }

    result = run(
        {
            "project_id": "proj-llm",
            "payload": {"raw_input": "30秒，英文，YouTube"},
        },
        gateway=Scripted(),
    )
    brief = check(result)
    assert brief.duration_s == 30
    assert brief.languages == ["en"]
    assert brief.platform == ["YouTube"]
    assert brief.video_type == "explainer"
    assert brief.goal == "模型给的目标"
    assert brief.open_questions == []


def test_qa_rejects_mismatched_platform() -> None:
    result = NodeResult(
        project_id="proj-1",
        node="n01_brief",
        ok=True,
        payload={
            "brief": {
                "brief_id": "b1",
                "raw_input": "做个视频",
                "goal": "产品宣传",
                "platform": ["抖音"],
                "duration_s": 30,
                "aspect_ratios": ["16:9"],
                "languages": ["zh"],
                "video_type": "product_showcase",
                "audience": "采购",
                "must_include": ["产品"],
                "style": "稳重",
                "assumptions": [],
                "open_questions": [],
            }
        },
        attempt=1,
    )
    with pytest.raises(QAError):
        check(result)
