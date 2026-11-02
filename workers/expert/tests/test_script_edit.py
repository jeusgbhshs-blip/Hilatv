"""分镜表编辑：单镜修改、增删排序、提示词编译（mock，免费）。"""

from __future__ import annotations

import pytest

from workers.expert.gates import GateError
from workers.expert.script_edit import (
    add_shot,
    delete_shot,
    load_script,
    patch_shot,
    reorder_shots,
    update_meta,
)
from workers.identity.session import open_session
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.workflow.store import init_project, save_node


@pytest.fixture()
def project(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    ident = open_session()
    name = "script-desk"
    init_project(
        name, sentence="给泵做一条片子", status="completed", enterprise_id=ident.enterprise_id
    )
    save_node(
        name,
        "n05_storyboard",
        {
            "script": storyboard(
                shot(voiceover="第一句台词。"),
                shot(shot_id="S02", order=2, visual="第二镜画面", voiceover="第二句台词。"),
            )
        },
    )
    return name


def test_load_compiles_seedance_prompt(project: str) -> None:
    payload = load_script(project)
    assert [row["shot_id"] for row in payload["shots"]] == ["S01", "S02"]
    first = payload["shots"][0]
    assert first["prompt"]["params"]["duration_s"] == 5
    assert "第 1/2 镜" in first["prompt"]["prompt"]
    assert first["prompt"]["parts"]
    assert "文字" in first["prompt"]["negative_prompt"]


def test_patch_add_reorder_delete(project: str) -> None:
    patched = patch_shot(
        project,
        "S01",
        {
            "duration_s": 8,
            "visual": "改后的第一镜画面",
            "voiceover": "改后的台词。",
            "ext": {
                "lighting": "冷光",
                "mood": "压抑",
                "continuity_notes": "保持同一张桌子",
                "characters": [{"name": "老板", "desc": "40岁男性，深灰衬衫"}],
                "action": "敲下回车",
                "emotion": "焦虑",
                "sfx": ["键盘声"],
                "bgm": "低沉氛围",
            },
        },
    )
    row = patched["shots"][0]
    assert row["visual"] == "改后的第一镜画面"
    assert row["ext"]["lighting"] == "冷光"
    assert row["ext"]["characters"][0]["name"] == "老板"
    assert "老板" in row["prompt"]["prompt"]
    assert "焦虑" in row["prompt"]["prompt"]
    assert "键盘声" in row["prompt"]["prompt"]
    # 8 秒按 Seedance 2.x 规则编译成 10 秒
    assert row["prompt"]["params"]["duration_s"] == 10

    added = add_shot(project, {"after_shot_id": "S01"})
    assert len(added["shots"]) == 3
    assert added["shots"][1]["order"] == 2

    ids = [row["shot_id"] for row in added["shots"]]
    reordered = reorder_shots(project, list(reversed(ids)))
    assert [row["order"] for row in reordered["shots"]] == [1, 2, 3]
    assert reordered["shots"][0]["shot_id"] == ids[-1]

    deleted = delete_shot(project, ids[1])
    assert len(deleted["shots"]) == 2
    assert deleted["shots"][0]["order"] == 1


def test_meta_and_guards(project: str) -> None:
    updated = update_meta(
        project, {"title": "老板的深夜一问", "genre": "企业故事", "style_bible": "写实电影感"}
    )
    assert updated["meta"]["title"] == "老板的深夜一问"
    assert updated["style_bible"] == "写实电影感"

    with pytest.raises(GateError):
        patch_shot(project, "S01", {"duration_s": 0.5})
    with pytest.raises(GateError):
        patch_shot(project, "S01", {"visual": ""})
    with pytest.raises(GateError):
        patch_shot(project, "NOPE", {"visual": "x"})
    with pytest.raises(GateError):
        reorder_shots(project, ["S01"])
    with pytest.raises(GateError):
        patch_shot(project, "S01", {"revision": 999, "visual": "x"})
