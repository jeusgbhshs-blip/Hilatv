"""Desk rules that do not need a rendered film."""

from __future__ import annotations

import pytest

from workers.expert.charge import generation_count, picture_regen_cost
from workers.expert.desk import add_edge, add_node, put_layout
from workers.expert.gates import GateError
from workers.expert.timeline_edit import save_structured_timeline
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.nodes.runtime import placeholder_qa
from workers.workflow.store import init_project, save_node


def test_one_shot_picture_cost_skips_the_downstream_span() -> None:
    shots = [
        {"shot_id": "S01", "generation_mode": "image_to_video", "voiceover": "甲"},
        {"shot_id": "S02", "generation_mode": "image_to_video", "voiceover": "乙"},
    ]
    assert picture_regen_cost(shots, "S01") == 2
    assert generation_count("n08_keyframe", shots, "S01") == 3


def test_layout_conflict_and_illegal_edges(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    enterprise = "00000000-0000-4000-8000-000000000001"
    init_project("desk", sentence="一句", status="completed", enterprise_id=enterprise)
    save_node("desk", "n05_storyboard", {"script": storyboard(shot())})
    first = put_layout(
        "desk",
        {
            "layout_version": 0,
            "positions": {"n01_brief": {"x": 12, "y": 34}},
            "viewport": {"x": 1, "y": 2, "zoom": 1.2},
        },
    )
    assert first["layout_version"] == 1
    assert first["positions"]["n01_brief"] == {"x": 12.0, "y": 34.0}
    with pytest.raises(GateError) as conflict:
        put_layout(
            "desk",
            {
                "layout_version": 0,
                "positions": {"n01_brief": {"x": 9, "y": 9}},
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            },
        )
    assert conflict.value.status == 409
    brief = add_node(
        "desk",
        {"kind": "brief", "position": {"x": 3, "y": 4}, "data": {"text": "冷色侧光"}},
        enterprise_id=enterprise,
    )
    with pytest.raises(GateError, match="类型不匹配") as mismatch:
        add_edge(
            "desk",
            {"source": brief["id"], "target": "final", "role": "reference"},
        )
    assert mismatch.value.status == 422
    with pytest.raises(GateError, match="成环") as cycle:
        add_edge("desk", {"source": "n15_compose", "target": "n01_brief", "role": "pipeline"})
    assert cycle.value.status == 422


def test_timeline_rejects_a_false_ai_label_and_a_trim_past_the_media(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    init_project("time", sentence="一句", status="completed")
    save_node("time", "n05_storyboard", {"script": storyboard(shot(duration_s=1.0))})
    qa = placeholder_qa(selected=False).model_dump(mode="json")
    save_node(
        "time",
        "n10_video",
        {
            "videos": [
                {
                    "candidate_id": "vid-1",
                    "shot_id": "S01",
                    "node": "N10",
                    "model": "mock-video",
                    "params": {"duration_s": 1.0, "prompt": "无文字"},
                    "uri": "mock://clip.mp4",
                    "qa": qa,
                    "selected": False,
                }
            ]
        },
    )
    with pytest.raises(GateError, match="标识") as locked:
        save_structured_timeline(
            "time",
            {
                "clips": [{"shot_id": "S01", "candidate_id": "vid-1", "in_s": 0, "out_s": 0.4}],
                "ai_label": False,
            },
        )
    assert locked.value.status == 422
    with pytest.raises(GateError, match="超出") as too_long:
        save_structured_timeline(
            "time",
            {"clips": [{"shot_id": "S01", "candidate_id": "vid-1", "in_s": 0, "out_s": 5}]},
        )
    assert too_long.value.status == 422
    saved = save_structured_timeline(
        "time",
        {"clips": [{"shot_id": "S01", "candidate_id": "vid-1", "in_s": 0.1, "out_s": 0.6}]},
    )
    assert saved["ai_label"] is True
    assert saved["canvas"]["timeline"]["edit"]["ai_label"] is True
    assert saved["canvas"]["nodes"][-1]["data"]["ai_label"] is True
    with pytest.raises(GateError, match="标识"):
        save_structured_timeline(
            "time",
            {
                "clips": [{"shot_id": "S01", "candidate_id": "vid-1", "in_s": 0, "out_s": 0.2}],
                "ai_label": True,
            },
        )
    assert saved["canvas"]["timeline"]["edit"]["clips"][0]["out_s"] == 0.6
