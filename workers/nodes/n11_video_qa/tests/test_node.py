"""N11 vetoes a short warp and can splice two complementary clips."""

from __future__ import annotations

from workers.nodes.n11_video_qa.node import run
from workers.nodes.n11_video_qa.qa import check
from workers.qa.frames import write_mp4
from workers.qa.samples import _plate
from workers.qa.scores import DIMS
from workers.qa.tests.conftest import MockGateway, candidate
from workers.schemas.director import DecisionAction


def _scores(evaluator: str) -> dict[str, object]:
    return {
        "scores": {name: 9 for name in DIMS},
        "hard_fail": [],
        "total": 9,
        "evaluator": evaluator,
        "notes": "ok",
    }


class _BothJudges:
    def judge(self, prompt: str, **kwargs: object) -> dict[str, object]:
        if kwargs.get("shot_type") == "cross_review":
            return _scores("gemini-test")
        return _scores("qwen-test")

    def generate_text(self, prompt: str, **kwargs: object) -> dict[str, object]:
        return {"text": prompt, "mock": True}


def test_half_second_warp_is_not_selected(tmp_path) -> None:
    frames = [_plate("rect") for _ in range(8)]
    frames[4] = _plate("shear")
    frames[5] = _plate("pinch")
    path = tmp_path / "warp.mp4"
    anchor = tmp_path / "anchor.png"
    write_mp4(frames, path, fps=4)
    _plate("rect").save(anchor)
    result = run(
        {
            "project_id": "p",
            "payload": {
                "candidates": [
                    candidate(str(path), node="N10", model="mock-video").model_dump(mode="json")
                ],
                "anchors": {"S01": str(anchor)},
            },
        },
        gateway=MockGateway(),
    )
    rows = check(result)
    assert rows[0].qa.hard_fail
    assert "product_deform" in rows[0].qa.hard_fail
    assert rows[0].selected is False
    assert result.payload["decisions"][0]["action"] == DecisionAction.switch_model.value
    assert result.payload["decisions"][0]["max_attempts_left"] == 2


def test_splice_keeps_the_clean_halves(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "1")
    clean = _plate("rect")
    bad = _plate("shear")
    left = tmp_path / "left.mp4"
    right = tmp_path / "right.mp4"
    anchor = tmp_path / "anchor.png"
    write_mp4([clean] * 4 + [bad] * 4, left, fps=4)
    write_mp4([bad] * 4 + [clean] * 4, right, fps=4)
    clean.save(anchor)
    result = run(
        {
            "project_id": "p",
            "payload": {
                "candidates": [
                    candidate(str(left), seed=1, node="N10", model="mock-video").model_dump(
                        mode="json"
                    ),
                    candidate(str(right), seed=2, node="N10", model="mock-video").model_dump(
                        mode="json"
                    ),
                ],
                "anchors": {"S01": str(anchor)},
            },
        },
        gateway=_BothJudges(),
    )
    rows = check(result)
    selected = [row for row in rows if row.selected]
    assert len(selected) == 1
    assert selected[0].params.get("spliced") is True
    assert selected[0].qa.hard_fail == []
    assert selected[0].qa.total >= 7.5
    decision = result.payload["decisions"][0]
    assert decision["action"] == DecisionAction.pass_.value
    assert decision["target"]["node"] == "N11"
    assert result.payload["splices"][0]["segments"][0]["candidate_id"]
