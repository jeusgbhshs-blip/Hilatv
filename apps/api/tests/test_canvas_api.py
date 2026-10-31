"""HTTP coverage for the expert desk: layout, wires, one shot, timeline."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.main import app
from workers.expert.canvas import build_canvas
from workers.identity.session import open_session
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.nodes.runtime import placeholder_qa
from workers.qa.budget_store import open_project_budget
from workers.schemas.asset import Candidate
from workers.workflow.contract import PIPELINE
from workers.workflow.store import init_project, project_path, save_node, update_snapshot

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _project(tmp_path, monkeypatch, name: str = "desk") -> tuple[TestClient, str]:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    ident = open_session()
    init_project(
        name,
        sentence="给我们的泵做一条片子",
        status="completed",
        enterprise_id=ident.enterprise_id,
    )
    save_node(name, "n05_storyboard", {"script": storyboard(shot(duration_s=1.0))})
    client = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    return client, ident.enterprise_id


def _candidate(shot_id: str, candidate_id: str, *, reviewed: bool = False) -> dict:
    qa = placeholder_qa(selected=False).model_copy(update={"visual_reviewed": reviewed})
    return Candidate(
        candidate_id=candidate_id,
        shot_id=shot_id,
        node="N10",
        model="mock-video",
        params={"seed": 1, "duration_s": 1.0, "prompt": "画面中不要出现任何文字"},
        uri="mock://clip.mp4",
        qa=qa,
        selected=True,
    ).model_dump(mode="json")


def test_canvas_routes_cover_layout_wires_shot_and_timeline(tmp_path, monkeypatch) -> None:
    client, _enterprise = _project(tmp_path, monkeypatch)
    bare = TestClient(app)
    assert bare.get("/v1/projects/desk/canvas").status_code == 401
    other = open_session()
    foreign = TestClient(app, headers={"Authorization": f"Bearer {other.token}"})
    assert (
        foreign.put(
            "/v1/projects/desk/canvas/layout",
            json={"layout_version": 0, "positions": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
        ).status_code
        == 404
    )

    first = client.get("/v1/projects/desk/canvas")
    assert first.status_code == 200
    body = first.json()
    assert [node["id"] for node in body["nodes"][: len(PIPELINE)]] == list(PIPELINE)
    assert body["nodes"][-1]["kind"] == "final"
    assert body["nodes"][-1]["data"]["ai_label"] is True
    assert body["layout_version"] == 0
    assert body["viewport"]["zoom"] == 1
    assert any(
        edge["role"] == "pipeline" and edge["user_created"] is False for edge in body["edges"]
    )

    saved = client.put(
        "/v1/projects/desk/canvas/layout",
        json={
            "layout_version": 0,
            "positions": {"n01_brief": {"x": 20, "y": 40}, "shot:S01": {"x": 480, "y": 16}},
            "viewport": {"x": 3, "y": 4, "zoom": 1.25},
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["layout_version"] == 1
    again = client.get("/v1/projects/desk/canvas")
    assert again.json()["viewport"] == {"x": 3.0, "y": 4.0, "zoom": 1.25}
    placed = next(node for node in again.json()["nodes"] if node["id"] == "n01_brief")
    assert placed["position"] == {"x": 20.0, "y": 40.0}
    conflict = client.put(
        "/v1/projects/desk/canvas/layout",
        json={
            "layout_version": 0,
            "positions": {"n01_brief": {"x": 1, "y": 1}},
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["layout_version"] == 1
    stayed = client.get("/v1/projects/desk/canvas").json()["nodes"]
    brief_node = next(node for node in stayed if node["id"] == "n01_brief")
    assert brief_node["position"] == {"x": 20.0, "y": 40.0}

    brief = client.post(
        "/v1/projects/desk/canvas/nodes",
        json={"kind": "brief", "position": {"x": 8, "y": 9}, "data": {"text": "冷色侧光甲"}},
    )
    assert brief.status_code == 200, brief.text
    upload = client.post("/v1/uploads", files={"file": ("pixel.png", PNG, "image/png")})
    assert upload.status_code == 200, upload.text
    upload_id = upload.json()["upload_id"]
    ref = client.post(
        "/v1/projects/desk/canvas/nodes",
        json={
            "kind": "ref_image",
            "position": {"x": 10, "y": 12},
            "data": {"upload_id": upload_id},
        },
    )
    assert ref.status_code == 200, ref.text
    text_edge = client.post(
        "/v1/projects/desk/canvas/edges",
        json={"source": brief.json()["id"], "target": "shot:S01", "role": "text"},
    )
    assert text_edge.status_code == 200, text_edge.text
    ref_edge = client.post(
        "/v1/projects/desk/canvas/edges",
        json={"source": ref.json()["id"], "target": "shot:S01", "role": "reference"},
    )
    assert ref_edge.status_code == 200, ref_edge.text
    final_edge = client.post(
        "/v1/projects/desk/canvas/edges",
        json={"source": "shot:S01", "target": "final", "role": "feeds_final"},
    )
    assert final_edge.status_code == 200, final_edge.text
    mismatch = client.post(
        "/v1/projects/desk/canvas/edges",
        json={"source": ref.json()["id"], "target": "final", "role": "reference"},
    )
    assert mismatch.status_code == 422
    assert "类型不匹配" in mismatch.json()["detail"]
    cycle = client.post(
        "/v1/projects/desk/canvas/edges",
        json={"source": "n15_compose", "target": "n01_brief", "role": "pipeline"},
    )
    assert cycle.status_code == 422
    assert "成环" in cycle.json()["detail"]
    pipe_id = "pipe:n01_brief:n02_brand_kit"
    pipe = next(edge for edge in again.json()["edges"] if edge["id"] == pipe_id)
    removed = client.delete(f"/v1/projects/desk/canvas/edges/{pipe['id']}")
    assert removed.status_code == 200, removed.text
    refreshed = client.get("/v1/projects/desk/canvas").json()
    assert all(edge["id"] != pipe["id"] for edge in refreshed["edges"])
    restored = client.post(
        "/v1/projects/desk/canvas/edges",
        json={"source": "n01_brief", "target": "n02_brand_kit", "role": "pipeline"},
    )
    assert restored.status_code == 200, restored.text
    assert client.delete("/v1/projects/desk/canvas/nodes/n08_keyframe").status_code == 422

    edited = client.patch(
        f"/v1/projects/desk/canvas/nodes/{brief.json()['id']}",
        json={"data": {"text": "暖色逆光乙"}},
    )
    assert edited.status_code == 200, edited.text
    calls: list[str] = []
    seen: list[str] = []

    def fake_invoke(name: str, **kwargs):
        calls.append(name)
        seen.append(str(kwargs.get("prompt_suffix") or ""))
        assert kwargs.get("shot_id") == "S01"
        assert name in {"n08_keyframe", "n10_video"}
        node = "N8" if name == "n08_keyframe" else "N10"
        qa = placeholder_qa(selected=True).model_copy(update={"visual_reviewed": True})
        row = Candidate(
            candidate_id=f"{name}-new",
            shot_id="S01",
            node=node,
            model="mock",
            params={"seed": 2, "prompt": str(kwargs.get("prompt_suffix") or ""), "duration_s": 1.0},
            uri="mock://new.mp4",
            qa=qa,
            selected=True,
        ).model_dump(mode="json")
        key = "keyframes" if name == "n08_keyframe" else "videos"
        return {key: [row]}

    monkeypatch.setattr("workers.expert.shot_action.invoke_node", fake_invoke)
    before = open_project_budget("desk").used
    regen = client.post(
        "/v1/projects/desk/shots/S01/regenerate",
        json={
            "narration": "稳定输出。",
            "prompt_suffix": "侧光",
            "qa_passed": True,
            "visual_reviewed": True,
        },
    )
    assert regen.status_code == 200, regen.text
    payload = regen.json()
    assert payload["nodes"] == ["n08_keyframe", "n10_video"]
    assert calls == ["n08_keyframe", "n10_video"]
    assert payload["charged"] == 2
    assert open_project_budget("desk").used == before + 2
    assert all("暖色逆光乙" in item for item in seen)
    assert all(upload_id in item for item in seen)
    shot_card = next(node for node in payload["canvas"]["nodes"] if node["id"] == "shot:S01")
    assert shot_card["data"]["verdict"] == "unreviewed"
    assert shot_card["data"]["narration"] == "稳定输出。"
    assert all(item["verdict"] == "unreviewed" for item in shot_card["data"]["candidates"])
    videos = payload["canvas"]["shots"][0]["videos"]
    assert videos
    assert all(item["verdict"]["qa_passed"] is False for item in videos)
    assert all(item["verdict"]["visual_reviewed"] is False for item in videos)

    chosen = client.post(
        "/v1/projects/desk/expert/select",
        json={
            "node": "n10_video",
            "shot_id": "S01",
            "candidate_id": "n10_video-new",
            "qa_passed": True,
            "visual_reviewed": True,
        },
    )
    assert chosen.status_code == 200, chosen.text
    selected = chosen.json()
    assert selected.get("held") is True
    assert selected["canvas"]["master"]["qa_passed"] is False
    held_videos = selected["canvas"]["shots"][0]["videos"]
    assert all(item["verdict"]["qa_passed"] is False for item in held_videos)

    reference = client.post(
        "/v1/projects/desk/shots/S01/reference",
        json={"upload_id": upload_id},
    )
    assert reference.status_code == 200, reference.text
    linked = client.get(f"/v1/projects/desk/expert/uploads/{upload_id}")
    assert linked.status_code == 200
    assert linked.content == PNG

    clip = {
        "shot_id": "S01",
        "candidate_id": "n10_video-new",
        "in_s": 0,
        "out_s": 0.4,
    }
    hidden = client.put(
        "/v1/projects/desk/timeline",
        json={"clips": [clip], "ai_label": False},
    )
    assert hidden.status_code == 422
    assert "标识" in hidden.json()["detail"]
    turned_on = client.put(
        "/v1/projects/desk/timeline",
        json={"clips": [clip], "ai_label": True},
    )
    assert turned_on.status_code == 422
    too_far = client.put(
        "/v1/projects/desk/timeline",
        json={"clips": [{**clip, "out_s": 8}]},
    )
    assert too_far.status_code == 422
    assert "超出" in too_far.json()["detail"]
    ordered = client.put("/v1/projects/desk/timeline", json={"clips": [clip, clip]})
    assert ordered.status_code == 422
    kept = client.put("/v1/projects/desk/timeline", json={"clips": [clip]})
    assert kept.status_code == 200, kept.text
    assert kept.json()["ai_label"] is True
    final = client.get("/v1/projects/desk/canvas").json()
    assert final["timeline"]["edit"]["ai_label"] is True
    assert final["timeline"]["edit"]["clips"] == [clip]
    assert final["nodes"][-1]["data"]["ai_label"] is True
    spec = app.openapi()["paths"]
    for path in (
        "/v1/projects/{project_id}/canvas",
        "/v1/projects/{project_id}/canvas/layout",
        "/v1/projects/{project_id}/canvas/nodes",
        "/v1/projects/{project_id}/canvas/nodes/{node_id}",
        "/v1/projects/{project_id}/canvas/edges",
        "/v1/projects/{project_id}/canvas/edges/{edge_id}",
        "/v1/projects/{project_id}/shots/{shot_id}/regenerate",
        "/v1/projects/{project_id}/shots/{shot_id}/reference",
        "/v1/projects/{project_id}/timeline",
        "/v1/projects/{project_id}/expert/rerun",
        "/v1/projects/{project_id}/expert/select",
        "/v1/projects/{project_id}/expert/timeline",
    ):
        assert path in spec


def test_regenerate_does_not_touch_another_shot(tmp_path, monkeypatch) -> None:
    client, _enterprise = _project(tmp_path, monkeypatch, "solo")
    qa = placeholder_qa(selected=False).model_dump(mode="json")
    marker = {
        "candidate_id": "keep-s02",
        "shot_id": "S02",
        "node": "N8",
        "model": "mock",
        "params": {"seed": 9, "prompt": "leave-me"},
        "uri": "mock://s02.png",
        "qa": qa,
        "selected": False,
    }
    save_node("solo", "n08_keyframe", {"keyframes": [marker]})

    def fake_invoke(name: str, **kwargs):
        del kwargs
        node = "N8" if name == "n08_keyframe" else "N10"
        row = _candidate("S01", f"{name}-new")
        row["node"] = node
        mutated = {
            **marker,
            "params": {**marker["params"], "prompt": "mutated"},
        }
        key = "keyframes" if name == "n08_keyframe" else "videos"
        return {key: [row, mutated]}

    monkeypatch.setattr("workers.expert.shot_action.invoke_node", fake_invoke)
    response = client.post("/v1/projects/solo/shots/S01/regenerate", json={})
    assert response.status_code == 200, response.text
    canvas = build_canvas("solo")
    kept = next(
        item
        for shot_row in canvas["shots"]
        if shot_row["shot_id"] == "S02"
        for item in shot_row["keyframes"]
    )
    assert kept["candidate_id"] == "keep-s02"
    assert kept["prompt"] == "leave-me"
    stored = (project_path("solo") / "nodes" / "n12_music.json").exists()
    assert stored is False
    assert not (project_path("solo") / "nodes" / "n15_compose.json").exists()
    update_snapshot("solo", status="running")
    busy = client.post("/v1/projects/solo/shots/S01/regenerate", json={})
    assert busy.status_code == 409


def test_blank_project_opens_an_empty_canvas(tmp_path, monkeypatch) -> None:
    """LibTV 式入口：先要一块空白画布，再在画布上生成。"""

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ident = open_session()
    client = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    created = client.post("/v1/projects/blank", json={"sentence": "先搭画布"})
    assert created.status_code == 201, created.text
    project_id = created.json()["project_id"]
    snapshot = client.get(f"/v1/projects/{project_id}").json()
    assert snapshot["status"] == "draft"
    canvas = client.get(f"/v1/projects/{project_id}/canvas").json()
    assert canvas["shots"] == []
    assert canvas["nodes"][-1]["kind"] == "final"
    assert canvas["timeline"]["present"] is False


def test_project_list_is_per_enterprise_and_each_has_a_canvas(tmp_path, monkeypatch) -> None:
    """项目列表跟着登录企业走；每个项目各自一块画布。"""

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    mine = open_session()
    other = open_session()
    client = TestClient(app, headers={"Authorization": f"Bearer {mine.token}"})
    first = client.post("/v1/projects/blank", json={"sentence": "第一个画布"}).json()["project_id"]
    second = client.post("/v1/projects/blank", json={"sentence": "第二个画布"}).json()["project_id"]
    stranger = TestClient(app, headers={"Authorization": f"Bearer {other.token}"})
    assert stranger.post("/v1/projects/blank", json={"sentence": "别人的画布"}).status_code == 201
    listed = client.get("/v1/projects")
    assert listed.status_code == 200, listed.text
    ids = [row["project_id"] for row in listed.json()["projects"]]
    assert set(ids) == {first, second}
    sentences = {row["sentence"] for row in listed.json()["projects"]}
    assert sentences == {"第一个画布", "第二个画布"}
    # 两个项目的画布是分开的
    assert client.get(f"/v1/projects/{first}/canvas").status_code == 200
    assert client.get(f"/v1/projects/{second}/canvas").status_code == 200


def test_blank_canvas_grows_a_storyboard_from_one_sentence(tmp_path, monkeypatch) -> None:
    """画布里的一句话：脚本入口跑 N1/N4/N5，长出分镜镜头，不跑视频。"""

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    ident = open_session()
    client = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    project_id = client.post("/v1/projects/blank", json={"sentence": ""}).json()["project_id"]
    made = client.post(
        f"/v1/projects/{project_id}/canvas/script",
        json={"sentence": "给高压球阀做一条 15 秒产品宣传片，面向采购，风格稳重"},
    )
    assert made.status_code == 200, made.text
    canvas = made.json()
    shots = [node for node in canvas["nodes"] if node["kind"] == "shot"]
    assert len(shots) >= 1
    assert all(shot["data"]["candidates"] == [] for shot in shots)
    assert canvas["timeline"]["present"] is False
    snapshot = client.get(f"/v1/projects/{project_id}").json()
    assert snapshot["status"] == "draft"


def test_image_and_video_nodes_generate_on_the_canvas(tmp_path, monkeypatch) -> None:
    """图片节点自己出图、视频节点自己出视频，都是 mock、都记 unreviewed。"""

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    ident = open_session()
    client = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    project_id = client.post("/v1/projects/blank", json={"sentence": ""}).json()["project_id"]
    image = client.post(
        f"/v1/projects/{project_id}/canvas/nodes",
        json={"kind": "image", "position": {"x": 10, "y": 10}, "data": {"prompt": "香水瓶广告"}},
    )
    assert image.status_code == 200, image.text
    image_id = image.json()["id"]
    made = client.post(
        f"/v1/projects/{project_id}/canvas/nodes/{image_id}/generate",
        json={"count": 2},
    )
    assert made.status_code == 200, made.text
    node = next(item for item in made.json()["canvas"]["nodes"] if item["id"] == image_id)
    assert len(node["data"]["candidates"]) == 2
    assert all(row["verdict"] == "unreviewed" for row in node["data"]["candidates"])
    video = client.post(
        f"/v1/projects/{project_id}/canvas/nodes",
        json={"kind": "video", "position": {"x": 400, "y": 10}, "data": {"prompt": "镜头缓慢推进"}},
    )
    video_id = video.json()["id"]
    made_video = client.post(f"/v1/projects/{project_id}/canvas/nodes/{video_id}/generate", json={})
    assert made_video.status_code == 200, made_video.text
    video_node = next(
        item for item in made_video.json()["canvas"]["nodes"] if item["id"] == video_id
    )
    assert len(video_node["data"]["candidates"]) == 1
    assert (
        video_node["data"]["selected_candidate_id"]
        == video_node["data"]["candidates"][0]["candidate_id"]
    )
