import json
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from workers.nodes.n04_script.node import run as run_script
from workers.nodes.n05_storyboard import node as node_mod
from workers.nodes.n05_storyboard.node import run
from workers.nodes.n05_storyboard.prompts import NO_DRAWN_TEXT
from workers.nodes.n05_storyboard.qa import QAError, check
from workers.nodes.n05_storyboard.schema import NodeResult
from workers.schemas.script import Script

FIXTURES = Path(__file__).resolve().parents[3] / "schemas" / "tests" / "fixtures"


def _script_request() -> dict[str, object]:
    brief = json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8"))
    brand = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))
    return {"project_id": "proj-1", "payload": {"brief": brief, "brand_kit": brand}}


def test_run_fills_shots(gateway) -> None:
    scripted = run_script(_script_request(), gateway=gateway)
    raw = {
        "project_id": "proj-1",
        "payload": {
            "brief": scripted.payload["brief"],
            "script": scripted.payload["script"],
            "brand_kit": scripted.payload["brand_kit"],
        },
    }
    result = run(raw, gateway=gateway)
    script = check(result)
    assert isinstance(script, Script)
    assert script.shots
    assert NO_DRAWN_TEXT in result.payload["prompt"]
    assert result.payload["shots"][0]["shot_id"] == "S01"
    again = run(raw, gateway=gateway)
    assert again.payload["script"] == result.payload["script"]
    logs = [
        row
        for row in gateway.store.list_logs(project_id="proj-1")
        if row["node"] == "n05_storyboard"
    ]
    assert logs
    assert logs[0]["provider"] == "mock"


def test_invalid_input_fails_fast(gateway) -> None:
    with pytest.raises(ValidationError):
        run({"project_id": "proj-1", "payload": {}}, gateway=gateway)


def test_timeout(gateway) -> None:
    scripted = run_script(_script_request(), gateway=gateway)
    raw = {
        "project_id": "proj-1",
        "payload": {
            "brief": scripted.payload["brief"],
            "script": scripted.payload["script"],
            "brand_kit": scripted.payload["brand_kit"],
        },
    }
    with pytest.raises(TimeoutError):
        run(raw, gateway=gateway, timeout_s=0)


def test_timeout_after_slow_model(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    scripted = run_script(_script_request(), gateway=gateway)

    def slow(*_args: object, **_kwargs: object) -> dict[str, object]:
        time.sleep(0.2)
        return {}

    monkeypatch.setattr(gateway, "generate_text", slow)
    raw = {
        "project_id": "proj-1",
        "payload": {
            "brief": scripted.payload["brief"],
            "script": scripted.payload["script"],
            "brand_kit": scripted.payload["brand_kit"],
        },
    }
    with pytest.raises(TimeoutError):
        run(raw, gateway=gateway, timeout_s=0.05)


def test_retries_then_passes(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    scripted = run_script(_script_request(), gateway=gateway)
    calls = {"n": 0}

    def flaky(result: NodeResult) -> Script:
        calls["n"] += 1
        if calls["n"] < 2:
            raise QAError("transient")
        return check(result)

    monkeypatch.setattr(node_mod, "check", flaky)
    raw = {
        "project_id": "proj-1",
        "payload": {
            "brief": scripted.payload["brief"],
            "script": scripted.payload["script"],
            "brand_kit": scripted.payload["brand_kit"],
        },
    }
    result = run(raw, gateway=gateway)
    assert result.attempt == 2
