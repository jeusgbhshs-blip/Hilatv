"""Director decisions stay inside DirectorDecision and the 3-review cap."""

from __future__ import annotations

from workers.qa.director import decide
from workers.qa.loop import run_shot_loop
from workers.qa.tests.conftest import MockGateway, candidate
from workers.schemas.asset import QAReport, QAScores
from workers.schemas.director import DecisionAction, DirectorDecision


def _report(*, total: float, hard: list[str] | None = None) -> QAReport:
    score = int(min(10, max(0, round(total))))
    return QAReport(
        scores=QAScores(
            product_fidelity=score,
            motion_quality=score,
            aesthetics=score,
            prompt_match=score,
            artifact_free=score,
        ),
        hard_fail=hard or [],
        total=total,
        evaluator="rule+vlm-v1",
        notes="fixture",
    )


def test_low_score_regenerates_and_validates() -> None:
    decision = decide(
        _report(total=7.4),
        node="N8",
        shot_id="S04",
        attempt=1,
        model="mock-image",
        gateway=MockGateway(),
    )
    assert isinstance(decision, DirectorDecision)
    assert decision.action is DecisionAction.regenerate
    assert decision.max_attempts_left == 2
    assert decision.target.node == "N8"
    assert decision.target.shot_id == "S04"
    assert "no text" in decision.changes["prompt_suffix"]


def test_product_warp_switches_model() -> None:
    decision = decide(
        _report(total=4, hard=["product_deform"]),
        node="N10",
        shot_id="S04",
        attempt=1,
        model="kling-o3",
    )
    assert decision.action is DecisionAction.switch_model
    assert decision.changes["model"] != "kling-o3"
    assert decision.changes["motion_strength"] == "low"


def test_sensitive_asks_the_user_and_the_third_failure_falls_back() -> None:
    ask = decide(
        _report(total=2, hard=["sensitive"]),
        node="N8",
        shot_id="S01",
        attempt=1,
    )
    assert ask.action is DecisionAction.ask_user
    fallback = decide(
        _report(total=5),
        node="N8",
        shot_id="S01",
        attempt=3,
    )
    assert fallback.action is DecisionAction.fallback
    assert fallback.max_attempts_left == 0


def test_loop_stops_at_three_reviews() -> None:
    calls = {"review": 0, "apply": 0}

    def review(rows: list) -> list[QAReport]:
        calls["review"] += 1
        return [_report(total=6.0) for _ in rows]

    def apply(decision: DirectorDecision) -> list:
        calls["apply"] += 1
        assert decision.action is DecisionAction.regenerate
        return [candidate("mock://next", seed=calls["apply"])]

    result = run_shot_loop(
        [candidate("mock://first")],
        shot_id="S01",
        generator_node="N8",
        review=review,
        apply=apply,
        gateway=MockGateway(),
    )
    assert calls["review"] == 3
    assert calls["apply"] == 2
    assert result.attempts == 3
    assert [item.action for item in result.decisions] == [
        DecisionAction.regenerate,
        DecisionAction.regenerate,
        DecisionAction.fallback,
    ]
    assert all(isinstance(item, DirectorDecision) for item in result.decisions)


def test_loop_passes_on_the_second_review() -> None:
    totals = [6.0, 8.8]

    def review(rows: list) -> list[QAReport]:
        total = totals.pop(0)
        return [_report(total=total) for _ in rows]

    result = run_shot_loop(
        [candidate("mock://first")],
        shot_id="S02",
        generator_node="N10",
        review=review,
        apply=lambda decision: [candidate("mock://second", seed=2)],
    )
    assert result.attempts == 2
    assert result.decisions[0].action is DecisionAction.regenerate
    assert result.decisions[1].action is DecisionAction.pass_
    assert result.decisions[1].max_attempts_left == 1
    assert sum(row.selected for row in result.candidates) == 1
