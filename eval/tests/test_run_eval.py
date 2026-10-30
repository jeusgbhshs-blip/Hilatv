"""T18 benchmark: case set, scores, ledger, blind pack, and one real mock run."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from eval.cases import CASE_COUNT, INDUSTRY_ORDER, PER_INDUSTRY, load_cases
from eval.harness import build_report
from eval.qa_port import coerce_judge, review_shot
from eval.report import assert_benchmark, build_summary, write_report
from eval.run_eval import build_report as exported_report
from eval.runner import run_case
from eval.scoring import hard_injury_rate, within_hard_injury_limit
from gateway.service import get_gateway, reset_gateway
from workers.schemas.asset import QAReport, QAScores


def test_build_report_idle() -> None:
    report = build_report()
    assert report["task"] == "T18"
    assert report["status"] == "ready"
    assert report["cases"] == 0
    assert exported_report()["task"] == "T18"


def test_benchmark_has_sixty_briefs() -> None:
    cases = load_cases()
    assert len(cases) == CASE_COUNT
    counts = {industry: 0 for industry in INDUSTRY_ORDER}
    for case in cases:
        counts[case.industry] += 1
        assert case.sentence
    assert set(counts.values()) == {PER_INDUSTRY}


def test_coerce_schema_fill_uses_mock_judge_profile() -> None:
    report = coerce_judge(
        {
            "scores": {name: 0 for name in QAScores.model_fields},
            "hard_fail": [],
            "total": 0,
            "evaluator": "mock",
            "notes": "mock",
        }
    )
    assert report.evaluator == "mock-judge"
    assert report.hard_fail == []
    assert report.total == pytest.approx(8.4)
    assert report.scores.artifact_free == 10


def test_coerce_keeps_a_real_hard_fail() -> None:
    report = coerce_judge(
        {
            "scores": {
                "product_fidelity": 3,
                "motion_quality": 4,
                "aesthetics": 6,
                "prompt_match": 5,
                "artifact_free": 2,
            },
            "hard_fail": ["product_deform"],
            "total": 4,
            "evaluator": "qwen-vl",
            "notes": "瓶身变形",
        }
    )
    assert report.hard_fail == ["产品变形"]
    assert report.evaluator == "qwen-vl"
    assert report.total == 4


def test_hard_injury_rate_is_per_shot() -> None:
    from decimal import Decimal

    assert hard_injury_rate(1, 20) == Decimal("0.0500")
    assert within_hard_injury_limit(1, 20)
    assert not within_hard_injury_limit(2, 20)
    assert within_hard_injury_limit(0, 0)


def test_review_shot_delegates_to_t12(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(payload: dict[str, object]) -> dict[str, object]:
        assert payload["shot_id"] == "S01"
        return {
            "scores": {
                "product_fidelity": 9,
                "motion_quality": 9,
                "aesthetics": 9,
                "prompt_match": 9,
                "artifact_free": 9,
            },
            "hard_fail": ["文字乱码"],
            "total": 9,
            "evaluator": "t12-test",
            "notes": "planted",
        }

    monkeypatch.setattr("eval.qa_port.t12_review_shot", lambda: fake)
    report = review_shot({"shot_id": "S01", "node": "n09_keyframe"}, gateway=object())
    assert report.evaluator == "t12-test"
    assert report.hard_fail == ["文字乱码"]


def test_ledger_and_blind_pack(tmp_path: Path) -> None:
    from eval.runner import CaseOutcome
    from eval.scoring import ShotScore

    bad = QAReport(
        scores=QAScores(
            product_fidelity=2,
            motion_quality=2,
            aesthetics=2,
            prompt_match=2,
            artifact_free=2,
        ),
        hard_fail=["产品变形", "穿帮"],
        total=2,
        evaluator="t12-test",
        notes="planted",
    )
    good = QAReport(
        scores=QAScores(
            product_fidelity=8,
            motion_quality=8,
            aesthetics=8,
            prompt_match=8,
            artifact_free=8,
        ),
        hard_fail=[],
        total=8,
        evaluator="t12-test",
        notes="ok",
    )
    outcome = CaseOutcome(
        case_id="manufacturing-01",
        industry="manufacturing",
        status="ok",
        score=5,
        hard_shots=1,
        shot_count=2,
        elapsed_s=1.25,
        cost_cny="0",
        shots=[
            ShotScore("S01", "slow_push_in", "n09_keyframe", "not-rendered", "产品特写", bad),
            ShotScore("S02", "gentle_arc", "n09_keyframe", "not-rendered", "工厂", good),
        ],
    )
    summary = build_summary([outcome], mode="mock")
    write_report(tmp_path, [outcome], summary)
    with (tmp_path / "ledger.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["defect"] for row in rows] == ["产品变形", "穿帮"]
    assert rows[0]["node"] == "n09_keyframe"
    assert rows[0]["model"] == "not-rendered"
    assert rows[0]["shot_type"] == "slow_push_in"
    reviewer = (tmp_path / "blind" / "pairs.json").read_text(encoding="utf-8")
    assert "manufacturing-01" not in reviewer
    assert "hilatv" not in reviewer.casefold()
    assert "slow_push_in" not in reviewer
    key = json.loads((tmp_path / "blind" / "key.json").read_text(encoding="utf-8"))
    assert key["pairs"][0]["case_id"] == "manufacturing-01"
    assert key["pairs"][0]["control_status"] == "withheld"
    header = (tmp_path / "scores.csv").read_text(encoding="utf-8").splitlines()[0]
    for column in ("score", "hard_shots", "elapsed_s", "cost_cny"):
        assert column in header


def test_live_mode_calls_the_film_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def fake_run_and_wait(**kwargs: object) -> dict[str, object]:
        called.update(kwargs)
        return {"deliverable": None, "completed": []}

    monkeypatch.setattr("workers.workflow.service.run_and_wait", fake_run_and_wait)
    monkeypatch.setattr("workers.workflow.store.load_checkpoint", lambda _project_id: {})
    case = load_cases()[0]
    outcome = run_case(case, mode="live", gateway=object())
    assert called["sentence"] == case.sentence
    assert outcome.status == "error"
    assert "shots" in outcome.error


@pytest.fixture
def gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_GATEWAY_STORE", "sqlite")
    monkeypatch.setenv("HILATV_SQLITE_PATH", str(tmp_path / "gw.sqlite"))
    monkeypatch.setenv("HILATV_PROGRESS_PATH", str(tmp_path / "progress.md"))
    monkeypatch.setenv("REDIS_URL", "")
    for key in (
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_BUCKET",
        "MINIO_ENDPOINT",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_BUCKET",
    ):
        monkeypatch.setenv(key, "")
    reset_gateway()
    yield get_gateway()
    reset_gateway()


def test_gateway_judge_is_logged(gateway, tmp_path: Path) -> None:
    report = review_shot(
        {
            "project_id": "e18-judge",
            "shot_id": "S01",
            "shot_type": "slow_push_in",
            "purpose": "产品特写",
            "visual": "金属泵体，无文字无 Logo",
            "voiceover": "看这台泵",
            "shot_size": "close_up",
            "generation_mode": "image_to_video",
            "node": "n09_keyframe",
            "model": "not-rendered",
        },
        gateway=gateway,
    )
    assert report.evaluator == "mock-judge"
    assert report.hard_fail == []
    logs = gateway.store.list_logs(project_id="e18-judge")
    assert logs[-1]["task"] == "judge"
    assert logs[-1]["cost_cny"] in {"0", "0.0", "0.00", "0.000000"} or str(
        logs[-1]["cost_cny"]
    ).startswith("0")


def test_one_mock_case_scores(gateway) -> None:
    case = load_cases()[0]
    outcome = run_case(case, mode="mock", gateway=gateway)
    assert outcome.status == "ok", outcome.error
    assert outcome.shot_count >= 1
    assert outcome.score is not None
    assert 0 <= outcome.score <= 10
    assert outcome.hard_shots == 0
    assert outcome.cost_cny.startswith("0")
    assert outcome.elapsed_s >= 0
    assert all(shot.node == "n09_keyframe" for shot in outcome.shots)
    assert all(shot.model == "not-rendered" for shot in outcome.shots)


def test_strict_rejects_a_partial_pack(tmp_path: Path) -> None:
    summary = build_summary([], mode="mock")
    write_report(tmp_path, [], summary)
    with pytest.raises(ValueError):
        assert_benchmark(summary, tmp_path)
