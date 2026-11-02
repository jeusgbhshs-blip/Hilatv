"""画布配音与多镜头合成的 HTTP 覆盖（mock，免费）。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from workers.identity.session import open_session
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.workflow.store import init_project, save_node

BRIEF = {
    "brief_id": "brief-1",
    "raw_input": "给一盆虎皮兰做一条片子",
    "goal": "展示产品",
    "platform": ["douyin"],
    "duration_s": 6,
    "aspect_ratios": ["9:16"],
    "languages": ["zh"],
    "video_type": "product_showcase",
    "audience": "室内绿植爱好者",
    "must_include": ["虎皮兰"],
    "style": "自然",
    "assumptions": [],
}


def _project(tmp_path, monkeypatch, name: str = "dub") -> TestClient:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    ident = open_session()
    init_project(
        name,
        sentence="给一盆虎皮兰做一条片子",
        status="completed",
        enterprise_id=ident.enterprise_id,
    )
    save_node(
        name,
        "n05_storyboard",
        {"script": storyboard(shot(voiceover="Built for pressure.")), "brief": BRIEF},
    )
    save_node(name, "n01_brief", {"brief": BRIEF})
    return TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})


def test_canvas_voiceover_generates_and_plays_mock_audio(tmp_path, monkeypatch) -> None:
    client = _project(tmp_path, monkeypatch, "dub")

    made = client.post(
        "/v1/projects/dub/canvas/shots/S01/voiceover",
        json={"text": "先看这里，这是这一镜的配音。"},
    )
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["shot_id"] == "S01"
    shot_node = next(node for node in body["canvas"]["nodes"] if node["kind"] == "shot")
    url = shot_node["data"]["voiceover_url"]
    assert url == "/v1/projects/dub/canvas/shots/S01/voiceover"
    assert (
        shot_node["data"]["voiceover_duration_s"] and shot_node["data"]["voiceover_duration_s"] > 0
    )

    audio = client.get(url)
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")
    assert len(audio.content) > 44
    assert audio.content[:4] == b"RIFF"

    foreign = TestClient(app, headers={"Authorization": f"Bearer {open_session().token}"})
    assert foreign.post("/v1/projects/dub/canvas/shots/S01/voiceover", json={}).status_code == 404
    assert foreign.get(url).status_code == 404


def test_canvas_compose_renders_a_master_and_marks_the_project_completed(
    tmp_path, monkeypatch
) -> None:
    client = _project(tmp_path, monkeypatch, "compose")
    dubbed = client.post(
        "/v1/projects/compose/canvas/shots/S01/voiceover",
        json={"text": "先看这里，这是这一镜的配音。"},
    )
    assert dubbed.status_code == 200, dubbed.text

    blocked = client.post("/v1/projects/compose/canvas/compose", json={})
    # 本项目没有未经评审的镜头，正常放行
    assert blocked.status_code == 200, blocked.text
    body = blocked.json()
    assert body["deliverable"] and Path(body["deliverable"]).is_file()
    assert Path(body["deliverable"]).stat().st_size > 1000

    # 合成后成片页能播放（私有预览），导出后能下载完整 MP4
    snapshot = client.get("/v1/projects/compose").json()
    assert snapshot["status"] == "completed"
    assert snapshot["preview_path"] == "/v1/projects/compose/preview"
    preview = client.get("/v1/projects/compose/preview")
    assert preview.status_code == 200 and len(preview.content) > 1000
    assert preview.content[4:8] == b"ftyp"

    exported = client.post("/v1/projects/compose/deliveries", json={})
    assert exported.status_code == 200, exported.text
    versions = exported.json()["versions"]
    assert versions
    download = client.get(f"/v1/projects/compose/versions/{versions[0]['version_id']}/download")
    # mock 素材只能在登录后预览；正式下载要等真实素材与终审证据，交付门必须拦住
    assert download.status_code == 409
    assert download.json()["detail"]["code"] == "delivery_not_ready"

    # 同一操作编号重放返回同一结果，不重复渲染
    replay = client.post(
        "/v1/projects/compose/canvas/compose", json={"operation_id": "compose-replay-1"}
    )
    assert replay.status_code == 200
    again = client.post(
        "/v1/projects/compose/canvas/compose", json={"operation_id": "compose-replay-1"}
    )
    assert again.status_code == 200 and again.json().get("replayed") is True


def test_canvas_compose_refuses_while_review_is_held(tmp_path, monkeypatch) -> None:
    client = _project(tmp_path, monkeypatch, "held")
    save_node(
        "held",
        "n09_keyframe_qa",
        {"shot_quality": [{"shot_id": "S01", "needs_review": True}]},
    )
    held = client.post("/v1/projects/held/canvas/compose", json={})
    assert held.status_code == 409
    assert "放行" in held.json()["detail"]
