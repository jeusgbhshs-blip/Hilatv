import pytest
from pydantic import ValidationError

from workers.nodes.n01_brief import node as node_mod
from workers.nodes.n01_brief.node import run
from workers.nodes.n01_brief.qa import QAError, check
from workers.nodes.n01_brief.schema import NodeResult


def test_run_returns_stub() -> None:
    result = run({"project_id": "proj-1", "shot_id": "s1"})
    assert result.ok is True
    assert result.node == "n01_brief"
    assert result.payload["task"] == "T05"
    assert "on-screen text" in result.payload["prompt"]
    assert "proj-1" in result.payload["prompt"]


def test_rerun_is_stable() -> None:
    first = run({"project_id": "proj-1"})
    second = run({"project_id": "proj-1"})
    assert first.model_dump() == second.model_dump()


def test_invalid_input_fails_fast() -> None:
    with pytest.raises(ValidationError):
        run({"project_id": ""})


def test_timeout() -> None:
    with pytest.raises(TimeoutError):
        run({"project_id": "proj-1"}, timeout_s=0)


def test_retries_then_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky(result: NodeResult) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise QAError("transient")
        check(result)

    monkeypatch.setattr(node_mod, "check", flaky)
    result = run({"project_id": "proj-1"})
    assert result.ok is True
    assert result.attempt == 3
    assert calls["n"] == 3


def test_qa_rejects_missing_constraint() -> None:
    result = NodeResult(
        project_id="proj-1",
        node="n01_brief",
        ok=True,
        payload={"status": "stub", "prompt": "draw a logo"},
        attempt=1,
    )
    with pytest.raises(QAError):
        check(result)
