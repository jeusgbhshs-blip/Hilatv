import json
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from gateway.schema_util import fill_json_schema
from workers.nodes.n04_script import node as node_mod
from workers.nodes.n04_script.node import run
from workers.nodes.n04_script.prompts import NO_DRAWN_TEXT
from workers.nodes.n04_script.qa import QAError, check
from workers.nodes.n04_script.schema import NodeResult, ScriptDraft, ScriptReview
from workers.schemas.script import Script

FIXTURES = Path(__file__).resolve().parents[3] / "schemas" / "tests" / "fixtures"


def _request(languages: list[str] | None = None) -> dict[str, object]:
    brief = json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8"))
    brand = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))
    if languages is not None:
        brief["languages"] = languages
    return {"project_id": "proj-1", "payload": {"brief": brief, "brand_kit": brand}}


def test_mock_draft_schema_is_empty() -> None:
    draft = ScriptDraft.model_validate(fill_json_schema(ScriptDraft.model_json_schema()))
    review = ScriptReview.model_validate(fill_json_schema(ScriptReview.model_json_schema()))
    assert draft.hook == ""
    assert draft.selling_points == []
    assert draft.proof == ""
    assert draft.cta == ""
    assert review.passes is True
    assert review.numbers_sourced is True


def test_run_returns_script_and_chinese_master(gateway) -> None:
    result = run(_request(), gateway=gateway)
    script = check(result)
    assert isinstance(script, Script)
    assert script.language == "en"
    assert result.payload["master"]["language"] == "zh"
    assert NO_DRAWN_TEXT in result.payload["prompt"]
    assert "999" not in json.dumps(result.payload["script"], ensure_ascii=False)
    logs = gateway.store.list_logs(project_id="proj-1")
    assert logs
    assert {row["node"] for row in logs} == {"n04_script"}
    assert all(row["provider"] == "mock" for row in logs)


def test_rerun_is_stable(gateway) -> None:
    raw = _request()
    first = run(raw, gateway=gateway).payload["script"]
    second = run(raw, gateway=gateway).payload["script"]
    assert first == second


def test_bilingual_variants_follow_the_brief(gateway) -> None:
    result = run(_request(["zh", "en"]), gateway=gateway)
    script = check(result)
    assert script.language == "zh"
    assert [item["language"] for item in result.payload["variants"]] == ["zh", "en"]


def test_invalid_input_fails_fast(gateway) -> None:
    with pytest.raises(ValidationError):
        run({"project_id": ""}, gateway=gateway)
    with pytest.raises(ValidationError):
        run({"project_id": "proj-1", "payload": {}}, gateway=gateway)


def test_timeout(gateway) -> None:
    with pytest.raises(TimeoutError):
        run(_request(), gateway=gateway, timeout_s=0)


def test_timeout_after_slow_model(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*_args: object, **_kwargs: object) -> dict[str, object]:
        time.sleep(0.2)
        return {}

    monkeypatch.setattr(gateway, "generate_text", slow)
    with pytest.raises(TimeoutError):
        run(_request(), gateway=gateway, timeout_s=0.05)


def test_retries_then_passes(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky(result: NodeResult) -> Script:
        calls["n"] += 1
        if calls["n"] < 3:
            raise QAError("transient")
        return check(result)

    monkeypatch.setattr(node_mod, "check", flaky)
    result = run(_request(), gateway=gateway)
    assert result.attempt == 3


def test_qa_gives_up(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    def bad(_result: NodeResult) -> Script:
        raise QAError("nope")

    monkeypatch.setattr(node_mod, "check", bad)
    with pytest.raises(QAError):
        run(_request(), gateway=gateway, max_attempts=2)


def test_invented_draft_is_not_published(gateway) -> None:
    class Invented:
        def generate_text(self, _prompt: str, **kwargs: object) -> dict[str, object]:
            schema = kwargs.get("schema")
            name = getattr(schema, "__name__", "")
            if name == "ScriptDraft":
                return {
                    "hook": "效率提升999倍",
                    "selling_points": ["虚构888参数"],
                    "proof": "全国第一",
                    "cta": "马上购买",
                }
            return {}

    result = run(_request(), gateway=Invented())
    blob = json.dumps(result.payload["script"], ensure_ascii=False)
    master = json.dumps(result.payload["master"], ensure_ascii=False)
    assert "999" not in blob
    assert "888" not in blob
    assert "999" not in master
    assert "第一" not in blob
    check(result)
