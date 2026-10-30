"""Unreviewable media and judge failures must not become a pass."""

from __future__ import annotations

from workers.qa.director import decide
from workers.qa.pixels import load_image
from workers.qa.rules import inspect_image
from workers.qa.samples import _plate
from workers.qa.scores import DIMS
from workers.qa.service import review_shot
from workers.qa.settings import RetryBudget
from workers.qa.tests.conftest import MockGateway
from workers.schemas.director import DecisionAction


def _payload(uri: str, **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "project_id": "p",
        "shot_id": "S01",
        "node": "n09_keyframe",
        "candidate_uri": uri,
        "expected_faces": 0,
    }
    body.update(extra)
    return body


def _full(evaluator: str, score: int = 9) -> dict[str, object]:
    return {
        "scores": {name: score for name in DIMS},
        "hard_fail": [],
        "total": float(score),
        "evaluator": evaluator,
        "notes": "ok",
    }


class _Both:
    def judge(self, prompt: str, **kwargs: object) -> dict[str, object]:
        name = "gemini-test" if kwargs.get("shot_type") == "cross_review" else "qwen-test"
        return _full(name)

    def generate_text(self, prompt: str, **kwargs: object) -> dict[str, object]:
        return {
            "action": "pass",
            "target": {"node": "N8", "shot_id": "S01"},
            "reason": "模型想通过",
            "changes": {},
            "max_attempts_left": 2,
        }


def _refuses_pass(report) -> None:
    decision = decide(report, node="N8", shot_id="S01", attempt=1, gateway=_Both())
    assert decision.action is not DecisionAction.pass_


def test_missing_broken_and_unreadable_are_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "0")
    missing = review_shot(_payload(str(tmp_path / "gone.png")), gateway=MockGateway())
    assert missing.visual_reviewed is False
    assert missing.hard_fail == ["not_reviewed"]
    assert missing.total == 0
    assert "media=missing" in missing.notes
    assert "file not found" in missing.notes
    _refuses_pass(missing)

    broken = review_shot(_payload("mock://image/shot"), gateway=MockGateway())
    assert broken.visual_reviewed is False
    assert broken.hard_fail == ["not_reviewed"]
    assert broken.total == 0
    assert "media=broken" in broken.notes
    assert "mock uri" in broken.notes
    _refuses_pass(broken)

    remote = review_shot(_payload("https://example.com/frame.png"), gateway=MockGateway())
    assert "media=broken" in remote.notes
    assert remote.total == 0
    _refuses_pass(remote)

    garbage = tmp_path / "frame.png"
    garbage.write_bytes(b"this is not an image")
    unreadable = review_shot(_payload(str(garbage)), gateway=MockGateway())
    assert unreadable.visual_reviewed is False
    assert unreadable.hard_fail == ["not_reviewed"]
    assert unreadable.total == 0
    assert "media=unreadable" in unreadable.notes
    _refuses_pass(unreadable)

    assert load_image("mock://x").status == "broken"
    assert load_image(str(tmp_path / "gone.png")).status == "missing"
    assert load_image(str(garbage)).status == "unreadable"


def test_text_only_is_not_a_media_error_and_does_not_pass() -> None:
    explicit = review_shot(
        {
            "project_id": "p",
            "shot_id": "S02",
            "node": "n09_keyframe",
            "text_only": True,
            "generation_mode": "motion_graphics",
        },
        gateway=MockGateway(),
    )
    implied = review_shot(
        {
            "project_id": "p",
            "shot_id": "S03",
            "node": "n09_keyframe",
            "generation_mode": "motion_graphics",
        },
        gateway=MockGateway(),
    )
    for report in (explicit, implied):
        assert report.visual_reviewed is False
        assert report.hard_fail == ["not_reviewed"]
        assert report.total == 0
        assert "media=text_only" in report.notes
        assert "intentionally text-only" in report.notes
        assert "file not found" not in report.notes
        decision = decide(report, node="N8", shot_id=str(report.notes), attempt=1)
        assert decision.action is DecisionAction.fallback
        assert decision.action is not DecisionAction.pass_
        assert decision.changes.get("text_only") is True


def test_live_judge_failures_do_not_pass(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "1")
    path = tmp_path / "clean.png"
    _plate("rect").save(path)
    body = _payload(str(path))

    class _Timeout:
        def judge(self, prompt: str, **kwargs: object) -> dict[str, object]:
            raise TimeoutError("slow")

    class _Boom:
        def judge(self, prompt: str, **kwargs: object) -> dict[str, object]:
            raise RuntimeError("down")

    class _Garbage:
        def judge(self, prompt: str, **kwargs: object) -> str:
            return "not-json"

    class _Short:
        def judge(self, prompt: str, **kwargs: object) -> dict[str, object]:
            return {
                "scores": {"product_fidelity": 9},
                "hard_fail": [],
                "total": 9,
                "evaluator": "qwen-test",
                "notes": "short",
            }

    for gateway, marker in (
        (_Timeout(), "timeout"),
        (_Boom(), "judge_error"),
        (_Garbage(), "parse_failure"),
        (_Short(), "missing_dimensions"),
        (MockGateway(), "mock"),
    ):
        report = review_shot(body, gateway=gateway)
        assert report.visual_reviewed is False
        assert report.hard_fail[0] == "judge_unavailable"
        assert report.total == 0
        assert marker in report.notes
        assert "quality_pass=false" in report.notes
        _refuses_pass(report)


def test_one_live_judge_is_marked_degraded(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "1")
    path = tmp_path / "clean.png"
    _plate("rect").save(path)

    class _Half:
        def judge(self, prompt: str, **kwargs: object) -> dict[str, object]:
            if kwargs.get("shot_type") == "cross_review":
                raise TimeoutError("slow")
            return _full("qwen-test")

        def generate_text(self, prompt: str, **kwargs: object) -> dict[str, object]:
            return {"text": prompt, "mock": True}

    report = review_shot(_payload(str(path)), gateway=_Half())
    assert report.visual_reviewed is True
    assert "judges_used=1" in report.notes
    assert "degraded=true" in report.notes
    assert "cross=timeout" in report.notes
    assert "judge_unavailable" not in report.hard_fail
    assert report.hard_fail == []
    assert "quality_pass=true" in report.notes
    decision = decide(report, node="N8", shot_id="S01", attempt=1, gateway=_Half())
    assert decision.action is DecisionAction.pass_


def test_image_without_a_judge_opinion_is_not_a_rule_only_pass(tmp_path, monkeypatch) -> None:
    """A real frame plus a mock judge must not become the old 8.6 rule score."""

    monkeypatch.setenv("HILATV_LIVE", "0")
    path = tmp_path / "clean.png"
    _plate("rect").save(path)
    report = review_shot(_payload(str(path)), gateway=MockGateway())
    assert report.visual_reviewed is False
    assert "judge_unavailable" in report.hard_fail
    assert report.total == 0
    assert report.total != 8.6
    assert "quality_pass=false" in report.notes
    _refuses_pass(report)


def test_project_retry_cap_stops_a_later_shot() -> None:
    from workers.qa.tests.test_director import _report

    budget = RetryBudget(limit=1)
    first = decide(
        _report(total=6.0),
        node="N8",
        shot_id="S01",
        attempt=1,
        budget=budget,
    )
    second = decide(
        _report(total=6.0),
        node="N8",
        shot_id="S02",
        attempt=1,
        budget=budget,
    )
    assert first.action is DecisionAction.regenerate
    assert second.action is DecisionAction.fallback
    assert "项目重生次数已到上限" in second.reason
    assert budget.used == 1


def test_deform_threshold_comes_from_the_environment(monkeypatch) -> None:
    anchor = _plate("rect")
    warped = _plate("shear")
    monkeypatch.setenv("HILATV_QA_DEFORM_MIN_SIMILARITY", "0.50")
    assert inspect_image(warped, anchor=anchor) == []
    monkeypatch.setenv("HILATV_QA_DEFORM_MIN_SIMILARITY", "0.90")
    assert any(item.code == "product_deform" for item in inspect_image(warped, anchor=anchor))
