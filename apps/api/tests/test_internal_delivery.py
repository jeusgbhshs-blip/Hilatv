"""内部使用模式：跳过 N16 内容安全门，但判定本身与 AI 标识不受影响。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.delivery_gate import media_response
from workers.compliance.moderation import blocks_delivery, classify, internal_delivery
from workers.identity.session import open_session
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.workflow.readiness import readiness
from workers.workflow.store import (
    init_project,
    project_path,
    read_snapshot,
    save_node,
    update_snapshot,
)

FFMPEG = "/Users/ci/.local/bin/ffmpeg"


def _project(tmp_path, monkeypatch, name: str = "inner") -> Path:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ident = open_session()
    init_project(
        name,
        sentence="给一盆虎皮兰做一条片子",
        status="completed",
        enterprise_id=ident.enterprise_id,
    )
    save_node(name, "n05_storyboard", {"script": storyboard(shot(voiceover=""))})
    folder = project_path(name) / "render"
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / "master.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=1",
            "-r",
            "30",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    update_snapshot(name, deliverable=str(video))
    return video


def test_internal_mode_allows_download_of_unreviewed_media(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_INTERNAL_DELIVERY", "1")
    video = _project(tmp_path, monkeypatch)
    snapshot = read_snapshot("inner") or {}
    view = readiness(snapshot, {}, video)
    assert view["delivery_status"] == "internal"
    assert view["internal_only"] is True
    response = media_response(snapshot, media=video, preview=False)
    assert response.headers.get("x-hilatv-internal-only") == "1"


def test_without_internal_mode_download_stays_blocked(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_INTERNAL_DELIVERY", "0")
    video = _project(tmp_path, monkeypatch, "outer")
    snapshot = read_snapshot("outer") or {}
    view = readiness(snapshot, {}, video)
    assert view["delivery_status"] != "ready"
    with pytest.raises(HTTPException) as caught:
        media_response(snapshot, media=video, preview=False)
    assert caught.value.status_code == 409


def test_internal_mode_only_skips_content_review(monkeypatch) -> None:
    monkeypatch.setenv("HILATV_INTERNAL_DELIVERY", "1")
    assert internal_delivery() is True
    assert blocks_delivery("unreviewed") is True
    assert classify({"mock": False, "reviewed": False, "unreviewed": True}) == "unreviewed"


def test_internal_skip_visual_review_unholds_pipeline() -> None:
    from workers.workflow.film import needs_human_review

    notes = {"shot_quality": [{"shot_id": "S01", "needs_review": True}]}
    assert needs_human_review(notes, {}) is True
    assert needs_human_review(notes, {"internal_skip_review": True}) is False
