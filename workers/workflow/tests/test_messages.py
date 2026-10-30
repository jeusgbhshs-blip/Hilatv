from workers.workflow.contract import PEERS, PHASE, PIPELINE
from workers.workflow.messages import shot_message


def test_shot_line_matches_the_spec_example() -> None:
    assert shot_message(3, "正在生成画面") == "第 3 镜：正在生成画面"


def test_pipeline_covers_the_t10_chain() -> None:
    assert PIPELINE[0] == "n01_brief"
    assert PIPELINE[-1] == "n15_compose"
    assert "n03_concept" in PIPELINE
    assert (
        PIPELINE.index("n08_keyframe")
        < PIPELINE.index("n09_keyframe_qa")
        < PIPELINE.index("n10_video")
    )
    assert PIPELINE.index("shot_director") == PIPELINE.index("n10_video") + 1
    assert PIPELINE.index("n12_music") < PIPELINE.index("n13_subtitle")
    assert PEERS == ("n12_music", "n13_subtitle", "n14_packaging")
    assert PHASE["n08_keyframe"] == "生成中"
    assert PHASE["n09_keyframe_qa"] == "看分镜"
    assert PHASE["n03_concept"] == "选方案"
