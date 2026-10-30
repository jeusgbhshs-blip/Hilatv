"""review_shot is the function eval calls with one payload dict."""

from __future__ import annotations

from workers.qa.samples import _plate
from workers.qa.scores import DIMS, ParsedOpinion, combine_judges, parse_opinion
from workers.qa.service import review_not_ready, review_shot
from workers.qa.tests.conftest import MockGateway
from workers.schemas.asset import QAReport, QAScores


def test_stub_marker_stays() -> None:
    assert review_not_ready()["task"] == "T12"


def test_missing_uri_is_not_reviewed(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_GATEWAY_STORE", "sqlite")
    monkeypatch.setenv("HILATV_SQLITE_PATH", str(tmp_path / "qa.sqlite"))
    monkeypatch.setenv("HILATV_PROGRESS_PATH", str(tmp_path / "progress.md"))
    monkeypatch.delenv("REDIS_URL", raising=False)
    from gateway.service import reset_gateway

    reset_gateway()
    report = review_shot(
        {
            "project_id": "eval-1",
            "shot_id": "S01",
            "shot_type": "slow_push_in",
            "purpose": "展示核心卖点",
            "visual": "车间里的金属泵",
            "voiceover": "每天三十兆帕",
            "shot_size": "close_up",
            "generation_mode": "image_to_video",
            "node": "n09_keyframe",
            "model": "not-rendered",
            "candidate_uri": "",
        }
    )
    reset_gateway()
    assert isinstance(report, QAReport)
    assert report.hard_fail == ["not_reviewed"]
    assert report.total == 0
    assert "media=missing" in report.notes


def test_painted_text_is_intercepted(tmp_path) -> None:
    path = tmp_path / "words.png"
    _plate("rect", text="热线 400-800-1234").save(path)
    anchor = tmp_path / "anchor.png"
    _plate("rect").save(anchor)
    report = review_shot(
        {
            "project_id": "p",
            "shot_id": "S01",
            "node": "n09_keyframe",
            "candidate_uri": str(path),
            "anchor_uri": str(anchor),
            "expected_faces": 0,
        },
        gateway=MockGateway(),
    )
    assert report.hard_fail
    assert report.total < 7.5


def test_disagreement_keeps_the_stricter_judge(monkeypatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "1")

    class Split:
        def judge(self, prompt: str, **kwargs: object) -> dict[str, object]:
            low = kwargs.get("shot_type") == "cross_review"
            score = 3 if low else 9
            return {
                "scores": {name: score for name in DIMS},
                "hard_fail": ["sensitive"] if low else [],
                "total": float(score),
                "evaluator": "gemini-test" if low else "qwen-test",
                "notes": "split",
            }

        def generate_text(self, prompt: str, **kwargs: object) -> dict[str, object]:
            return {"text": prompt, "mock": True}

    report = review_shot(
        {"project_id": "p", "shot_id": "S02", "node": "n09_keyframe", "purpose": "产品"},
        gateway=Split(),
        image=_plate("rect"),
    )
    assert report.visual_reviewed is True
    assert report.judges_used == 2
    assert report.degraded is False
    assert "sensitive" in report.hard_fail
    assert report.total <= 6
    assert report.scores.product_fidelity <= 3


def test_blank_mock_is_not_an_opinion() -> None:
    blank = {
        "scores": {name: 0 for name in DIMS},
        "hard_fail": [],
        "total": 0,
        "evaluator": "mock",
        "notes": "mock",
    }
    parsed = parse_opinion(blank)
    assert parsed.report is None
    assert parsed.error == "mock"
    high = QAReport(
        scores=QAScores(
            product_fidelity=9,
            motion_quality=9,
            aesthetics=9,
            prompt_match=9,
            artifact_free=9,
        ),
        hard_fail=[],
        total=9,
        evaluator="qwen-vl-max",
        notes="clean",
    )
    partial = {
        "scores": {"product_fidelity": 9, "aesthetics": 9},
        "hard_fail": [],
        "total": 9,
        "evaluator": "qwen-vl-max",
        "notes": "short",
    }
    assert parse_opinion(partial).error == "missing_dimensions"
    review = combine_judges(
        ParsedOpinion(high, None),
        ParsedOpinion(None, "timeout"),
        live=True,
    )
    assert review.judges_used == 1
    assert review.degraded is True
    assert "degraded=true" in review.detail
    assert "cross=timeout" in review.detail
