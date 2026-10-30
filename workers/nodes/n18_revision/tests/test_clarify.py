"""Unclear edits ask a question and do not spend a generation or a version."""

import json

from workers.nodes.n18_revision.corpus import sample_script
from workers.nodes.n18_revision.parse import parse_edit
from workers.nodes.n18_revision.unseen import UNSEEN, evaluate_unseen
from workers.workflow.revise import revise_project
from workers.workflow.store import init_project, project_path, update_snapshot


def test_unparseable_instruction_asks_and_does_not_regenerate(tmp_path, monkeypatch) -> None:
    from gateway import reset_gateway

    reset_gateway()
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    project_id = "clarify01"
    init_project(project_id, sentence="一句", status="completed")
    directory = project_path(project_id)
    nodes = directory / "nodes"
    nodes.mkdir()
    script = sample_script().model_dump(mode="json")
    (nodes / "n05_storyboard.json").write_text(json.dumps({"script": script}), encoding="utf-8")
    update_snapshot(project_id, status="completed")
    result = revise_project(project_id, "嗯")
    assert result["status"] == "needs_clarification"
    assert result["question"]
    assert result["version_id"] is None
    assert result["video_shots"] == []
    assert not (directory / "versions" / "index.json").exists()


def test_merging_shots_is_not_supported_and_not_a_full_regen() -> None:
    parsed = parse_edit(sample_script(), "前两个镜头合成一个", gateway=None)
    assert parsed.status == "not_supported"
    assert parsed.directive is None


def test_unseen_set_includes_the_required_sentences() -> None:
    instructions = {case["instruction"] for case in UNSEEN}
    required = {
        "去掉片尾的价格",
        "换成傍晚",
        "女声慢一点",
        "logo 小一点放右上角",
        "主持人别穿红衣服",
        "前两个镜头合成一个",
        "字幕改成英文",
        "节奏快一点",
    }
    assert required <= instructions
    assert len(UNSEEN) >= 30
    report = evaluate_unseen()
    assert report["unsafe_blanket"] == 0
    unsupported = [case for case in UNSEEN if case["status"] == "not_supported"]
    assert unsupported
    for case in unsupported:
        parsed = parse_edit(sample_script(), case["instruction"], gateway=None)
        assert parsed.status == "not_supported"


def test_a_real_model_decision_is_kept_when_it_is_safe() -> None:
    class _Gateway:
        def generate_text(self, prompt: str, **kwargs: object) -> dict[str, object]:
            return {
                "targets": ["S02"],
                "change": {"lighting": "brighter"},
                "keep": ["composition", "narration"],
            }

    parsed = parse_edit(sample_script(), "第二个镜头太暗", gateway=_Gateway())
    assert parsed.status == "apply"
    assert parsed.directive is not None
    assert parsed.directive.targets == ["S02"]
    assert parsed.directive.change == {"lighting": "brighter"}
