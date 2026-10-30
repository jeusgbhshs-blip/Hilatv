from workers.workflow.store import init_project, load_checkpoint, publish, read_events, save_node


def test_checkpoint_keeps_only_saved_nodes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    init_project("p1", sentence="一句话")
    save_node("p1", "n01_brief", {"brief": {"goal": "宣传"}})
    save_node("p1", "n04_script", {"script": {"language": "zh"}})
    publish(
        "p1",
        {
            "node": "n08_keyframe",
            "phase": "生成中",
            "message": "第 3 镜：正在生成画面",
            "status": "running",
            "shot_index": 3,
            "shot_id": "S03",
            "attempt": 1,
        },
    )
    checkpoint = load_checkpoint("p1")
    assert checkpoint["completed"] == ["n01_brief", "n04_script"]
    assert checkpoint["brief"]["goal"] == "宣传"
    assert "n08_keyframe" not in checkpoint["completed"]
    events = read_events("p1")
    assert events[0]["message"] == "第 3 镜：正在生成画面"
