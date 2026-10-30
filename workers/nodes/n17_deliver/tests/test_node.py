"""Full export: three aspects, two languages, subject pixels inside the frame."""

from __future__ import annotations

from workers.nodes.n17_deliver.node import run
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
        assert _compact(line["subtitle"]) == _compact(line["transcript"])
        assert any(
            box["kind"] == "ai_label" and box["text"] == "AI生成" for box in item["overlays"]
        )
    assert _cjk(zh["spoken"][0]["transcript"]) and _cjk(zh["spoken"][0]["subtitle"])
    assert _latin(en["spoken"][0]["transcript"]) and _latin(en["spoken"][0]["subtitle"])
    assert "drawtext" not in zh["filters"]
    assert result.payload["rights"]["subtitles"]
    assert result.payload["verify_pixels"] is True


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


def _compact(text: str) -> str:
    return "".join(char for char in text if not char.isspace())


def _cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _latin(text: str) -> bool:
    return any("a" <= char.lower() <= "z" for char in text)
