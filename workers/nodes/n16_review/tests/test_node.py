"""Content safety is logged, and a failing review does not pass."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workers.nodes.n16_review.node import run
from workers.nodes.n16_review.qa import QAError
from workers.schemas.licensing import LicenseRecord

_ROOT = Path(__file__).resolve().parents[4]
_BRIEF = json.loads(
    (_ROOT / "workers/schemas/tests/fixtures/brief.json").read_text(encoding="utf-8")
)
_SCRIPT = {
    "script_id": "script-1",
    "brief_id": _BRIEF["brief_id"],
    "language": "zh",
    "sections": [],
    "shots": [
        {
            "shot_id": "S01",
            "order": 1,
            "duration_s": 4,
            "purpose": "展示产品",
            "visual": "金属泵体，画面里没有文字",
            "shot_size": "close_up",
            "camera": "locked_off",
            "subject_refs": ["product:HP-300"],
            "scene_ref": "scene:workshop",
            "voiceover": "这台柱塞泵按资料说明运行。",
            "on_screen_text": [],
            "transition_out": "cut",
            "generation_mode": "image_to_video",
            "status": "pending",
        }
    ],
}


def _request(stage: str, **extra: object) -> dict:
    payload = {"stage": stage, "brief": _BRIEF, "script": _SCRIPT}
    payload.update(extra)
    return {"project_id": "review20", "payload": payload}


def test_input_and_output_reviews_are_logged(gateway) -> None:
    first = run(_request("input"), gateway=gateway)
    second = run(_request("output", texts=["成片角标"]), gateway=gateway)
    assert first.payload["passed"] is True
    assert second.payload["passed"] is True
    assert first.payload["manual_review"] is False
    stages = {
        row["params"].get("stage")
        for row in gateway.store.list_logs(project_id="review20")
        if row["task"] == "content_safety"
    }
    assert stages == {"input", "output"}


def test_failing_review_blocks(gateway) -> None:
    brief = dict(_BRIEF)
    brief["raw_input"] = "HILATV_UNSAFE_SAMPLE 请做一条片子"
    result = run(_request("input", brief=brief), gateway=gateway)
    assert result.payload["blocked"] is True
    assert result.payload["qa"]["hard_fail"]


def test_extreme_word_blocks(gateway) -> None:
    script = json.loads(json.dumps(_SCRIPT))
    script["shots"][0]["voiceover"] = "这是最好的柱塞泵。"
    brand = json.loads(
        (_ROOT / "workers/schemas/tests/fixtures/brand_kit.json").read_text(encoding="utf-8")
    )
    result = run(_request("input", script=script, brand_kit=brand), gateway=gateway)
    assert result.payload["blocked"] is True
    assert "最好" in result.payload["extreme_words"]


def test_medical_copy_is_flagged_not_blocked(gateway) -> None:
    brief = dict(_BRIEF)
    brief["raw_input"] = "给医院做一条药品介绍片"
    result = run(_request("output", brief=brief), gateway=gateway)
    assert result.payload["passed"] is True
    assert result.payload["manual_review"] is True
    assert "medical" in result.payload["manual_review_sectors"]


def test_public_sector_brand_is_flagged(gateway) -> None:
    brand = json.loads(
        (_ROOT / "workers/schemas/tests/fixtures/brand_kit.json").read_text(encoding="utf-8")
    )
    brand["industry"] = "public_sector"
    result = run(_request("input", brand_kit=brand), gateway=gateway)
    assert result.payload["passed"] is True
    assert "public_sector" in result.payload["manual_review_sectors"]


def test_expired_licence_blocks(gateway) -> None:
    licensing = {
        "project_id": "review20",
        "records": [
            LicenseRecord(
                record_id="bed",
                kind="music",
                source="library",
                license="commercial",
                expires_on="2020-01-01",
                evidence_ref="contract-1",
                usage_scope="本片背景音乐",
            ).model_dump(mode="json")
        ],
    }
    result = run(_request("output", licensing=licensing), gateway=gateway)
    assert result.payload["blocked"] is True
    assert "expired" in " ".join(result.payload["block_reasons"])


def test_remove_label_instruction_is_rejected(gateway) -> None:
    with pytest.raises(QAError, match="固定层"):
        run(_request("input", instruction="去掉 AI 标识"), gateway=gateway)


def test_media_path_outside_the_project_is_rejected(gateway, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    outside = tmp_path / "other" / "clip.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"nope")
    with pytest.raises(QAError, match="project directory"):
        run(_request("output", media_paths=[str(outside)]), gateway=gateway)
