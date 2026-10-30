"""T18 benchmark: case set, scores, ledger, blind pack, and one real mock run."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from eval.cases import CASE_COUNT, INDUSTRY_ORDER, PER_INDUSTRY, load_cases
from eval.harness import build_report
from eval.qa_port import TEXT_ONLY_LABEL, JudgeInvalid, coerce_judge, review_shot
from eval.report import assert_benchmark, build_summary, write_report
from eval.run_eval import build_report as exported_report
from eval.runner import CaseOutcome, run_case
from eval.scoring import ShotScore, hard_injury_rate, score_state, within_hard_injury_limit
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


def test_coerce_schema_fill_is_not_a_score() -> None:
    with pytest.raises(JudgeInvalid):
        coerce_judge(
            {
                "scores": {name: 0 for name in QAScores.model_fields},
                "hard_fail": [],
                "total": 0,
                "evaluator": "mock",
                "notes": "mock",
            }
        )


def test_coerce_missing_dimension_is_invalid() -> None:
    with pytest.raises(JudgeInvalid, match="motion_quality"):
        coerce_judge(
            {
                "scores": {
                    "product_fidelity": 8,
                    "aesthetics": 8,
                    "prompt_match": 8,
                    "artifact_free": 8,
                },
                "hard_fail": [],
                "total": 8,
                "evaluator": "qwen-vl",
                "notes": "缺了一项",
            }
        )


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
    review = review_shot({"shot_id": "S01", "node": "n09_keyframe"}, gateway=object())
    assert review.status == "reviewed"
    assert review.source == "t12"
    assert review.report is not None
    assert review.report.evaluator == "t12-test"
    assert review.report.hard_fail == ["文字乱码"]


def test_ledger_and_blind_pack(tmp_path: Path) -> None:
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


def test_t12_missing_dimension_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(_payload: dict[str, object]) -> dict[str, object]:
        return {
            "scores": {"aesthetics": 8},
            "hard_fail": [],
            "total": 8,
            "evaluator": "t12",
            "notes": "缺项",
        }

    monkeypatch.setattr("eval.qa_port.t12_review_shot", lambda: fake)
    review = review_shot({"shot_id": "S01"}, gateway=object())
    assert review.status == "invalid"
    assert review.report is None


def test_storyboard_text_is_not_scored() -> None:
    class Boom:
        def judge(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("storyboard text must not be sent to the judge")

    review = review_shot(
        {
            "project_id": "e18-text",
            "shot_id": "S01",
            "shot_type": "slow_push_in",
            "purpose": "产品特写",
            "visual": "金属泵体，无文字无 Logo",
            "voiceover": "看这台泵",
            "node": "n09_keyframe",
        },
        gateway=Boom(),
    )
    assert review.status == "text_only"
    assert review.report is None
    assert review.note == TEXT_ONLY_LABEL


def test_media_reference_is_sent_and_mock_fill_stays_unreviewed(gateway) -> None:
    uri = "oss://hilatv/gateway/image/frame.png"
    review = review_shot(
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
            "candidate_uri": uri,
        },
        gateway=gateway,
    )
    assert review.status == "unreviewed"
    assert review.report is None
    assert review.media_uri == uri
    logs = gateway.store.list_logs(project_id="e18-judge")
    assert logs[-1]["task"] == "judge"
    assert logs[-1]["params"]["media_uri"] == uri
    assert uri in logs[-1]["params"]["prompt"]
    assert logs[-1]["cost_cny"] in {"0", "0.0", "0.00", "0.000000"} or str(
        logs[-1]["cost_cny"]
    ).startswith("0")


def test_real_judge_with_media_counts() -> None:
    class Live:
        def judge(self, prompt: str, **kwargs: object) -> dict[str, object]:
            assert kwargs["params"]["media_uri"] == "oss://hilatv/frame.png"  # type: ignore[index]
            assert "oss://hilatv/frame.png" in prompt
            return {
                "scores": {name: 9 for name in QAScores.model_fields},
                "hard_fail": [],
                "total": 9,
                "evaluator": "qwen-vl",
                "notes": "看过关键帧",
            }

    state = {
        "script": {
            "shots": [
                {
                    "shot_id": "S01",
                    "camera": "slow_push_in",
                    "purpose": "产品特写",
                    "visual": "金属泵体",
                    "voiceover": "看这台泵",
                }
            ]
        },
        "keyframes": [
            {
                "shot_id": "S01",
                "uri": "oss://hilatv/frame.png",
                "selected": True,
                "model": "mock-image",
            }
        ],
    }
    scored = score_state(state, project_id="e18-live", gateway=Live())
    assert scored.score == 9
    assert scored.reviewed_shots == 1
    assert scored.unreviewed_shots == 0
    assert scored.shots[0].review_source == "gateway-judge"
    assert scored.shots[0].media_uri == "oss://hilatv/frame.png"


def test_one_mock_case_is_unreviewed(gateway) -> None:
    case = load_cases()[0]
    outcome = run_case(case, mode="mock", gateway=gateway)
    assert outcome.status == "ok", outcome.error
    assert outcome.shot_count >= 1
    assert outcome.score is None
    assert outcome.reviewed_shots == 0
    assert outcome.unreviewed_shots == outcome.shot_count
    assert outcome.text_only_shots == outcome.shot_count
    assert outcome.hard_shots == 0
    assert outcome.cost_cny.startswith("0")
    assert outcome.elapsed_s >= 0
    assert all(shot.node == "n09_keyframe" for shot in outcome.shots)
    assert all(shot.model == "not-rendered" for shot in outcome.shots)
    assert all(shot.report is None for shot in outcome.shots)
    assert all(shot.note == TEXT_ONLY_LABEL for shot in outcome.shots)


def test_strict_rejects_a_partial_pack(tmp_path: Path) -> None:
    summary = build_summary([], mode="mock")
    write_report(tmp_path, [], summary)
    with pytest.raises(ValueError):
        assert_benchmark(summary, tmp_path)


def test_unreviewed_split_from_pipeline(tmp_path: Path) -> None:
    outcomes: list[CaseOutcome] = []
    for industry in INDUSTRY_ORDER:
        for index in range(PER_INDUSTRY):
            shot = ShotScore(
                f"S{index}",
                "slow_push_in",
                "n09_keyframe",
                "not-rendered",
                "产品",
                None,
                review_status="text_only",
                review_source="unreviewed",
                review_basis="text",
                note=TEXT_ONLY_LABEL,
            )
            outcomes.append(
                CaseOutcome(
                    case_id=f"{industry}-{index:02d}",
                    industry=industry,
                    status="ok",
                    score=None,
                    hard_shots=0,
                    shot_count=1,
                    elapsed_s=0.01,
                    cost_cny="0",
                    text_only_shots=1,
                    unreviewed_shots=1,
                    shots=[shot],
                )
            )
    summary = build_summary(outcomes, mode="mock")
    write_report(tmp_path, outcomes, summary)
    assert_benchmark(summary, tmp_path)
    assert summary["pipeline_complete"] is True
    assert summary["quality_met"] is False
    assert summary["conclusions"]["pipeline"]["label"] == "管线和报告结构完整"
    assert summary["conclusions"]["quality"]["label"] == "质量未达标"
    assert summary["unreviewed_shots"] == CASE_COUNT
    assert summary["text_only_shots"] == CASE_COUNT
    assert summary["mean_score"] is None
    assert summary["reviewer"] == "unreviewed"
    blob = (tmp_path / "summary.json").read_text(encoding="utf-8")
    assert "8.4" not in blob
    assert "mock-judge" not in blob
    assert TEXT_ONLY_LABEL in blob
    assert TEXT_ONLY_LABEL in (tmp_path / "scores.md").read_text(encoding="utf-8")


def test_strict_rejects_a_fake_quality_pass(tmp_path: Path) -> None:
    outcomes: list[CaseOutcome] = []
    for industry in INDUSTRY_ORDER:
        for index in range(PER_INDUSTRY):
            outcomes.append(
                CaseOutcome(
                    case_id=f"{industry}-{index:02d}",
                    industry=industry,
                    status="ok",
                    score=None,
                    hard_shots=0,
                    shot_count=1,
                    elapsed_s=0.01,
                    cost_cny="0",
                    unreviewed_shots=1,
                )
            )
    summary = build_summary(outcomes, mode="mock")
    summary["quality_met"] = True
    summary["conclusions"]["quality"]["met"] = True
    write_report(tmp_path, outcomes, summary)
    with pytest.raises(ValueError, match="未评审不能算通过"):
        assert_benchmark(summary, tmp_path)
