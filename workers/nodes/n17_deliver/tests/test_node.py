"""Full export: three aspects, two languages, subject pixels inside the frame."""

from __future__ import annotations

from pathlib import Path

import pytest

from workers.nodes.n17_deliver.node import run
from workers.nodes.n17_deliver.qa import QAError
from workers.nodes.n17_deliver.sample import acceptance_request


def test_exports_keep_the_subject_and_the_language(tmp_path, gateway, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    result = run(acceptance_request(tmp_path), gateway=gateway)
    versions = result.payload["versions"]
    assert {item["aspect_ratio"] for item in versions} == {"16:9", "9:16", "1:1"}
    assert {item["language"] for item in versions} == {"zh", "en"}
    modes = {mode for item in versions for mode in item["modes"].values()}
    assert "crop" in modes
    assert "blur" in modes
    assert all(item["qa_status"] == "pass" for item in versions)
    assert all(item["subject_box_source"] == "provided" for item in versions)
    zh = next(item for item in versions if item["language"] == "zh")
    en = next(
        item
        for item in versions
        if item["language"] == "en" and item["aspect_ratio"] == zh["aspect_ratio"]
    )
    assert zh["spoken"][0]["voiceover"] != en["spoken"][0]["voiceover"]
    for item in (zh, en):
        line = item["spoken"][0]
        assert line["heard_check"] == "not_verified_in_mock"
        assert line["transcript"] == ""
        assert any(
            box["kind"] == "ai_label" and box["text"] == "AI生成" for box in item["overlays"]
        )
    assert _cjk(zh["spoken"][0]["subtitle"])
    assert _latin(en["spoken"][0]["subtitle"])
    assert "drawtext" not in zh["filters"]
    assert result.payload["rights"]["subtitles"]
    assert result.payload["verify_pixels"] is True
    note = Path(result.payload["rights"]["materials_note"])
    assert note.is_file()
    body = note.read_text(encoding="utf-8")
    assert "来源" in body and "许可" in body and "到期" in body and "使用范围" in body
    stages = {
        row["params"].get("stage")
        for row in gateway.store.list_logs()
        if row["task"] == "content_safety"
    }
    assert stages == {"input", "output"}


def test_missing_subject_box_is_blur_and_needs_review(tmp_path, gateway, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    result = run(
        acceptance_request(
            tmp_path,
            project_id="accept-default",
            languages=["zh"],
            aspect_ratios=["16:9", "9:16"],
            long_edge=160,
            with_tracks=False,
        ),
        gateway=gateway,
    )
    versions = result.payload["versions"]
    assert versions
    assert result.payload["verify_pixels"] is False
    for item in versions:
        assert item["subject_box_source"] == "default"
        assert item["qa_status"] == "needs_review"
        assert set(item["modes"].values()) == {"blur"}
        assert any(box["text"] == "AI生成" for box in item["overlays"])


def test_failing_review_blocks_delivery(tmp_path, gateway, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    raw = acceptance_request(
        tmp_path,
        project_id="blocked20",
        languages=["zh"],
        aspect_ratios=["16:9"],
        long_edge=160,
    )
    payload = raw["payload"]
    assert isinstance(payload, dict)
    brief = dict(payload["brief"])
    brief["raw_input"] = "HILATV_UNSAFE_SAMPLE 请做一条片子"
    payload["brief"] = brief
    with pytest.raises(QAError, match="content safety"):
        run(raw, gateway=gateway)
    stages = {
        row["params"].get("stage")
        for row in gateway.store.list_logs(project_id="blocked20")
        if row["task"] == "content_safety"
    }
    assert stages == {"input"}


def test_expired_licence_blocks_delivery(tmp_path, gateway, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    raw = acceptance_request(
        tmp_path,
        project_id="expired20",
        languages=["zh"],
        aspect_ratios=["16:9"],
        long_edge=160,
    )
    payload = raw["payload"]
    assert isinstance(payload, dict)
    payload["licensing"] = {
        "project_id": "expired20",
        "records": [
            {
                "record_id": "bed",
                "kind": "music",
                "source": "",
                "license": "",
                "evidence_ref": "missing",
                "usage_scope": "本片",
            }
        ],
    }
    with pytest.raises(QAError, match="missing a source or a license"):
        run(raw, gateway=gateway)


def _cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _latin(text: str) -> bool:
    return any("a" <= char.lower() <= "z" for char in text)
