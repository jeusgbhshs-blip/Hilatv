"""One real mock regeneration. Downstream files stay put."""

from __future__ import annotations

import hashlib
import json

from workers.expert.invoke import invoke_node
from workers.expert.seed import build_film
from workers.expert.shot_action import regenerate_shot
from workers.identity.session import open_session
from workers.workflow.store import project_path, read_snapshot, save_node, update_snapshot


def test_real_regen_reads_upstream_and_leaves_downstream(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    built = build_film("film")
    ident = open_session()
    update_snapshot("film", enterprise_id=ident.enterprise_id)
    from workers.expert.desk import add_edge, add_node

    brief = add_node(
        "film",
        {"kind": "brief", "position": {"x": 1, "y": 2}, "data": {"text": "冷色侧光甲"}},
        enterprise_id=ident.enterprise_id,
    )
    add_edge("film", {"source": brief["id"], "target": "shot:S01", "role": "text"})
    folder = project_path("film") / "nodes"
    current = json.loads((folder / "n08_keyframe.json").read_text(encoding="utf-8"))
    marker = dict(current["keyframes"][0])
    marker["candidate_id"] = "keep-s02"
    marker["shot_id"] = "S02"
    current["keyframes"].append(marker)
    save_node("film", "n08_keyframe", current)
    compose = (folder / "n15_compose.json").read_bytes()
    master_path = read_snapshot("film")["deliverable"]
    master = hashlib.sha256(open(master_path, "rb").read()).hexdigest()
    calls: list[str] = []
    real = invoke_node

    def wrapped(name: str, **kwargs):
        calls.append(name)
        return real(name, **kwargs)

    monkeypatch.setattr("workers.expert.shot_action.invoke_node", wrapped)
    result = regenerate_shot(
        "film",
        "S01",
        {"prompt_suffix": "侧光", "qa_passed": True},
        gateway=built["gateway"],
    )
    assert calls == ["n08_keyframe", "n10_video"]
    assert result["charged"] == 2
    frames = result["canvas"]["shots"]
    s01 = next(item for item in frames if item["shot_id"] == "S01")
    s02 = next(item for item in frames if item["shot_id"] == "S02")
    assert any("冷色侧光甲" in item["prompt"] for item in s01["keyframes"])
    assert all("画面中不要出现任何文字" in item["prompt"] for item in s01["keyframes"])
    assert all(item["verdict"]["visual_reviewed"] is False for item in s01["keyframes"])
    assert all(item["verdict"]["qa_passed"] is False for item in s01["keyframes"])
    assert s02["keyframes"][0]["candidate_id"] == "keep-s02"
    assert (folder / "n15_compose.json").read_bytes() == compose
    again = hashlib.sha256(open(master_path, "rb").read()).hexdigest()
    assert again == master
