"""N9 selects the clean keyframe and asks to regenerate a bad one."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from workers.nodes.n09_keyframe_qa.node import run
from workers.nodes.n09_keyframe_qa.qa import check
from workers.qa.samples import _plate
from workers.qa.tests.conftest import MockGateway, candidate
from workers.schemas.director import DecisionAction


def test_selects_the_higher_clean_frame(tmp_path) -> None:
    clean = tmp_path / "clean.png"
    dirty = tmp_path / "dirty.png"
    anchor = tmp_path / "anchor.png"
    _plate("rect").save(clean)
    _plate("rect", text="SALE HOT LINE").save(dirty)
    _plate("rect").save(anchor)
    result = run(
        {
            "project_id": "p",
            "attempt": 1,
            "payload": {
                "candidates": [
                    candidate(str(dirty), seed=1).model_dump(mode="json"),
                    candidate(str(clean), seed=2).model_dump(mode="json"),
                ],
                "anchors": {"S01": str(anchor)},
            },
        },
        gateway=MockGateway(),
    )
    rows = check(result)
    selected = [row for row in rows if row.selected]
    assert len(selected) == 1
    assert selected[0].uri == str(clean)
    assert selected[0].qa.total >= 7.5
    assert selected[0].qa.hard_fail == []
    decision = result.payload["decisions"][0]
    assert decision["action"] == DecisionAction.pass_.value
    assert decision["max_attempts_left"] == 2


def test_warped_product_switches_model(tmp_path) -> None:
    dirty = tmp_path / "dirty.png"
    anchor = tmp_path / "anchor.png"
    _plate("shear").save(dirty)
    _plate("rect").save(anchor)
    result = run(
        {
            "project_id": "p",
            "payload": {
                "candidates": [candidate(str(dirty)).model_dump(mode="json")],
                "anchors": {"S01": str(anchor)},
            },
        },
        gateway=MockGateway(),
    )
    check(result)
    assert result.payload["decisions"][0]["action"] == DecisionAction.switch_model.value
    assert all(not row.selected for row in check(result))


def test_rejects_an_empty_payload() -> None:
    with pytest.raises(ValidationError):
        run({"project_id": "p", "payload": {}}, gateway=MockGateway())


def test_timeout_is_reported() -> None:
    with pytest.raises(TimeoutError):
        run(
            {
                "project_id": "p",
                "payload": {"candidates": [candidate("mock://x").model_dump(mode="json")]},
            },
            timeout_s=0,
            gateway=MockGateway(),
        )
