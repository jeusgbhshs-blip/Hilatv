"""Manual re-runs charge the shared ledger and cannot bypass QA."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from workers.expert.canvas import build_canvas
from workers.expert.charge import BudgetExhausted, generation_count, reserve
from workers.expert.gates import GateError
from workers.expert.rerun import rerun_span, save_timeline, select_candidate
from workers.expert.seed import build_film
from workers.qa.budget_store import open_project_budget
from workers.schemas.asset import Candidate
from workers.workflow.store import (
    init_project,
    project_path,
    read_snapshot,
    save_node,
    update_snapshot,
)


def test_reserve_matches_the_generative_span(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "3")
    assert generation_count("n14_packaging") == 0
    assert generation_count("n08_keyframe") == 2
    assert generation_count("n10_video") == 1
    shots = [
        {"shot_id": "S01", "generation_mode": "image_to_video", "voiceover": "甲"},
        {"shot_id": "S02", "generation_mode": "image_to_video", "voiceover": "乙"},
        {"shot_id": "S03", "generation_mode": "motion_graphics", "voiceover": ""},
    ]
    assert generation_count("n08_keyframe", shots) == 4
    assert generation_count("n10_video", shots) == 2
    assert generation_count("n08_keyframe", shots, "S01") == 3
    assert generation_count("n06_voiceover", shots) == 6
    assert reserve("p", "n14_packaging") == 0
    assert open_project_budget("p").used == 0
    assert reserve("p", "n08_keyframe") == 2
    assert reserve("p", "n10_video") == 1
    with pytest.raises(BudgetExhausted, match="已用完"):
        reserve("p", "n06_voiceover")
    assert open_project_budget("p").used == 3
    with pytest.raises(BudgetExhausted, match="已用完"):
        reserve("wide", "n08_keyframe", shots=shots)
    assert open_project_budget("wide").used == 0


def test_canvas_review_selection_and_rerun(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "6")
    built = build_film("film1")
    canvas = build_canvas("film1")
    assert [node["id"] for node in canvas["nodes"]][0] == "n01_brief"
    from workers.workflow.contract import PIPELINE

    prefix = [node["id"] for node in canvas["nodes"][: len(PIPELINE)]]
    assert prefix == list(PIPELINE)
    assert canvas["nodes"][-1]["kind"] == "final"
    assert canvas["nodes"][-1]["data"]["ai_label"] is True
    keyframes = canvas["shots"][0]["keyframes"]
    videos = canvas["shots"][0]["videos"]
    assert len(keyframes) == 3
    assert len(videos) == 3
    assert all(item["verdict"]["visual_reviewed"] is False for item in keyframes + videos)
    assert all(item["verdict"]["qa_passed"] is False for item in keyframes + videos)
    assert all("画面中不要出现任何文字" in item["prompt"] for item in keyframes)
    assert canvas["timeline"]["ai_label"] is True
    assert canvas["master"]["qa_passed"] is False
    assert canvas["budget"]["used"] == 0

    with pytest.raises(GateError, match="AI生成"):
        save_timeline("film1", {"overlays": [{"kind": "badge", "text": "30 MPa"}], "clips": []})
    with pytest.raises(GateError, match="AI生成"):
        rerun_span("film1", "n14_packaging", skip_ai_label=True)
    assert open_project_budget("film1").used == 0
    assert build_canvas("film1")["timeline"]["ai_label"] is True

    master = Path(str(read_snapshot("film1")["deliverable"]))
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    _mark_sensitive("film1")
    blocked = build_canvas("film1")
    assert blocked["master"]["blocked"] is True
    sensitive = next(item for item in blocked["shots"][0]["videos"] if item["verdict"]["blocked"])
    with pytest.raises(GateError, match="内容安全"):
        select_candidate(
            "film1",
            "n10_video",
            "S01",
            sensitive["candidate_id"],
            qa_passed=True,
            visual_reviewed=True,
        )
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before

    result = rerun_span(
        "film1",
        "n08_keyframe",
        prompt_suffix="cooler rim light",
        gateway=built["gateway"],
        qa_passed=True,
        visual_reviewed=True,
        consent=True,
        licensed=True,
    )
    assert result["charged"] == 2
    assert result["nodes"][0] == "n08_keyframe"
    assert result["nodes"][-1] == "n15_compose"
    assert "n01_brief" not in result["nodes"]
    # shot_director spends the same ledger when it actually regenerates a fallback.
    assert open_project_budget("film1").used >= 2
    if result.get("held"):
        assert result["deliverable"] is None
        held_snapshot = read_snapshot("film1") or {}
        assert held_snapshot["status"] == "needs_human_review"
        assert not held_snapshot.get("deliverable")
    again = result["canvas"]
    frames = again["shots"][0]["keyframes"]
    assert frames
    assert all("cooler rim light" in item["prompt"] for item in frames)
    assert all("画面中不要出现任何文字" in item["prompt"] for item in frames)
    assert all(item["verdict"]["qa_passed"] is False for item in frames)
    assert all(item["verdict"]["visual_reviewed"] is not True for item in frames)
    assert again["timeline"]["ai_label"] is True
    assert "regen" not in (read_snapshot("film1") or {})


def _mark_sensitive(project_id: str) -> None:
    import json

    path = project_path(project_id) / "nodes" / "n10_video.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = [Candidate.model_validate(item) for item in data["videos"]]
    target = rows[0].model_copy(
        update={
            "selected": True,
            "qa": rows[0].qa.model_copy(
                update={"hard_fail": ["sensitive"], "visual_reviewed": True, "total": 1.0}
            ),
        }
    )
    rows[0] = target
    data["videos"] = [item.model_dump(mode="json") for item in rows]
    save_node(project_id, "n10_video", data)


def test_http_rerun_charges_and_does_not_mark_unreviewed_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_GATEWAY_STORE", "sqlite")
    monkeypatch.setenv("HILATV_SQLITE_PATH", str(tmp_path / "gw.sqlite"))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from gateway.service import reset_gateway

    reset_gateway()
    build_film("httpfilm")
    from fastapi.testclient import TestClient

    from app.main import app
    from workers.identity.session import open_session

    ident = open_session()
    update_snapshot("httpfilm", enterprise_id=ident.enterprise_id)
    headers = {"Authorization": f"Bearer {ident.token}"}
    with TestClient(app, headers=headers) as client:
        response = client.post(
            "/v1/projects/httpfilm/expert/rerun",
            json={
                "node": "n08_keyframe",
                "qa_passed": True,
                "visual_reviewed": True,
                "consent": True,
                "licensed": True,
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["charged"] == 2
    frames = body["canvas"]["shots"][0]["keyframes"]
    assert frames
    assert all(item["verdict"]["qa_passed"] is False for item in frames)
    assert all(item["verdict"]["visual_reviewed"] is not True for item in frames)
    assert body["canvas"]["timeline"]["ai_label"] is True
    assert open_project_budget("httpfilm").used >= 2
    if body.get("held"):
        assert body["deliverable"] is None
        assert body["canvas"]["status"] == "needs_human_review"


def test_held_project_is_not_delivered(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "6")
    built = build_film("held")
    snapshot = read_snapshot("held") or {}
    master = Path(str(snapshot["deliverable"]))
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    update_snapshot("held", status="needs_human_review", deliverable=None)
    result = rerun_span(
        "held",
        "n15_compose",
        gateway=built["gateway"],
        human_release=True,
    )
    assert result["held"] is True
    assert result["deliverable"] is None
    again = read_snapshot("held") or {}
    assert again["status"] == "needs_human_review"
    assert not again.get("deliverable")
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before
    assert open_project_budget("held").used == 0


def test_api_refuses_a_rerun_when_the_ledger_is_full(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "1")
    monkeypatch.setenv("HILATV_LIVE", "0")
    from fastapi.testclient import TestClient

    from app.main import app
    from workers.identity.session import open_session

    ident = open_session()
    init_project("api1", sentence="预算", status="completed", enterprise_id=ident.enterprise_id)
    save_node(
        "api1",
        "n05_storyboard",
        {
            "script": {
                "shots": [
                    {"shot_id": "S01", "generation_mode": "image_to_video", "voiceover": "一句"}
                ]
            }
        },
    )
    budget = open_project_budget("api1")
    while budget.try_take():
        pass
    headers = {"Authorization": f"Bearer {ident.token}"}
    with TestClient(app, headers=headers) as client:
        missing = client.get("/v1/projects/missing/canvas")
        assert missing.status_code == 404
        canvas = client.get("/v1/projects/api1/canvas")
        assert canvas.status_code == 200
        assert any(item["id"] == "n08_keyframe" for item in canvas.json()["nodes"])
        refused = client.post(
            "/v1/projects/api1/expert/rerun",
            json={
                "node": "n08_keyframe",
                "qa_passed": True,
                "visual_reviewed": True,
                "consent": True,
                "licensed": True,
            },
        )
    assert refused.status_code == 409
    assert "已用完" in refused.json()["detail"]
    assert open_project_budget("api1").used == 1


def test_selecting_an_unreviewed_video_holds_without_a_deliverable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    monkeypatch.setenv("HILATV_LIVE", "0")
    build_film("pick")
    snapshot = read_snapshot("pick") or {}
    master = Path(str(snapshot["deliverable"]))
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    video = build_canvas("pick")["shots"][0]["videos"][0]
    assert video["verdict"]["qa_passed"] is False
    assert video["verdict"]["visual_reviewed"] is False
    result = select_candidate(
        "pick",
        "n10_video",
        "S01",
        video["candidate_id"],
        qa_passed=True,
        visual_reviewed=True,
    )
    assert result["held"] is True
    assert result["deliverable"] is None
    again = read_snapshot("pick") or {}
    assert again["status"] == "needs_human_review"
    assert not again.get("deliverable")
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before


def test_timeline_with_an_unreviewed_clip_holds(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    monkeypatch.setenv("HILATV_LIVE", "0")
    build_film("time")
    snapshot = read_snapshot("time") or {}
    master = Path(str(snapshot["deliverable"]))
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    from workers.expert.canvas import load_timeline_dict

    timeline = load_timeline_dict("time") or {}
    state = json.loads(
        (project_path("time") / "nodes" / "n10_video.json").read_text(encoding="utf-8")
    )
    uri = state["videos"][0]["uri"]
    result = save_timeline(
        "time",
        {
            "overlays": timeline["overlays"],
            "clips": [{"clip_id": "S01", "path": uri}],
        },
    )
    assert result["held"] is True
    assert result.get("deliverable") is None
    again = read_snapshot("time") or {}
    assert again["status"] == "needs_human_review"
    assert not again.get("deliverable")
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before


def test_concurrent_reruns_cannot_both_charge(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "1")
    monkeypatch.setenv("HILATV_LIVE", "0")
    init_project("race", sentence="并发", status="completed")
    save_node(
        "race",
        "n05_storyboard",
        {
            "script": {
                "shots": [
                    {"shot_id": "S01", "generation_mode": "image_to_video", "voiceover": "泵"}
                ]
            }
        },
    )
    save_node("race", "n08_keyframe", {"keyframes": [{"candidate_id": "k"}]})
    gate = threading.Event()
    entered = threading.Event()
    calls = {"n": 0}

    def fake_invoke(name: str, **kwargs: object) -> dict:
        del name, kwargs
        calls["n"] += 1
        if calls["n"] == 1:
            entered.set()
            assert gate.wait(3)
        return {}

    monkeypatch.setattr("workers.expert.rerun.invoke_node", fake_invoke)
    done: dict[str, object] = {}

    def run(label: str) -> None:
        try:
            done[label] = rerun_span("race", "n10_video")
        except Exception as exc:
            done[label] = exc

    first = threading.Thread(target=run, args=("a",))
    first.start()
    assert entered.wait(3)
    second = threading.Thread(target=run, args=("b",))
    second.start()
    second.join(0.4)
    assert second.is_alive()
    assert open_project_budget("race").used == 1
    gate.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive()
    assert not second.is_alive()
    assert open_project_budget("race").used == 1
    assert isinstance(done["b"], BudgetExhausted)


def test_selection_and_timeline_refuse_while_running(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    monkeypatch.setenv("HILATV_LIVE", "0")
    build_film("busy")
    node = project_path("busy") / "nodes" / "n10_video.json"
    before_node = node.read_bytes()
    before_snapshot = (project_path("busy") / "project.json").read_bytes()
    update_snapshot("busy", status="running")
    video = build_canvas("busy")["shots"][0]["videos"][0]
    with pytest.raises(GateError, match="仍在运行") as selected:
        select_candidate("busy", "n10_video", "S01", video["candidate_id"])
    assert selected.value.status == 409
    with pytest.raises(GateError, match="仍在运行") as saved:
        save_timeline("busy", {"overlays": [{"text": "AI生成"}], "clips": []})
    assert saved.value.status == 409
    update_snapshot("busy", status="completed")
    assert node.read_bytes() == before_node
    stored = json.loads((project_path("busy") / "project.json").read_text(encoding="utf-8"))
    assert stored["status"] == "completed"
    assert stored["deliverable"] == json.loads(before_snapshot)["deliverable"]


def test_mock_uri_is_not_a_project_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    from workers.expert.rerun import _review_of_path

    with pytest.raises(GateError, match="路径不在项目目录内") as caught:
        _review_of_path({}, "mock://not-a-project-file")
    assert caught.value.status == 422
