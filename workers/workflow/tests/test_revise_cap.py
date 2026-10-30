"""A capped project does not spend another video call. Logo URLs go through the SSRF guard."""

import json

from workers.workflow.revise import _maybe_fetch_logo, revise_project
from workers.workflow.store import init_project, project_path, update_snapshot
from workers.workflow.versions import hashes


def _script() -> dict:
    def shot(shot_id: str, order: int) -> dict:
        return {
            "shot_id": shot_id,
            "order": order,
            "duration_s": 2.0,
            "purpose": "展示产品",
            "visual": "车间里的泵。画面无任何文字、无 Logo、无价格、无电话号码。",
            "shot_size": "medium",
            "camera": "locked_off",
            "subject_refs": ["product:HP-300"],
            "scene_ref": "scene:workshop",
            "voiceover": "泵已经就位。",
            "on_screen_text": [],
            "transition_out": "cut",
            "generation_mode": "image_to_video",
            "status": "pending",
        }

    return {
        "script_id": "script-cap",
        "brief_id": "brief-cap",
        "language": "zh",
        "sections": [],
        "shots": [shot("S01", 1), shot("S02", 2)],
    }


def test_project_regen_cap_blocks_another_video_call(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "1")
    monkeypatch.setenv("HILATV_LIVE", "0")
    project_id = "revcap01"
    init_project(project_id, sentence="一句", status="completed")
    directory = project_path(project_id)
    nodes = directory / "nodes"
    nodes.mkdir()
    (nodes / "n05_storyboard.json").write_text(
        json.dumps({"script": _script()}, ensure_ascii=False),
        encoding="utf-8",
    )
    media = directory / "media"
    media.mkdir()
    (media / "S01.bin").write_bytes(b"a")
    (media / "S02.bin").write_bytes(b"b")
    update_snapshot(project_id, status="completed", regen_used=1, deliverable=None)
    before = hashes(directory)
    result = revise_project(project_id, "第二个镜头太暗")
    assert result["quality_pass"] is False
    assert result["video_shots"] == []
    assert hashes(directory) == before
    from workers.workflow.revise import revision_gateway

    gateway = revision_gateway(directory)
    assert not any(
        row.get("task") == "video" for row in gateway.store.list_logs(project_id=project_id)
    )


def test_logo_replacement_url_is_refused_by_the_ssrf_guard(tmp_path) -> None:
    _maybe_fetch_logo(
        tmp_path,
        "把 Logo 换成 https://127.0.0.1/logo.png",
        {"change": {"logo": "replace"}},
    )
    assert not (tmp_path / "render" / "fetched-logo.png").exists()
