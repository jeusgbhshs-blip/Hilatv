"""Constants for the T10 film line. Import-safe inside the Temporal sandbox."""

from __future__ import annotations

# Implemented packages, not the SPEC planning names in ``pipeline.py``.
PIPELINE: tuple[str, ...] = (
    "n01_brief",
    "n02_brand_kit",
    "n03_concept",
    "n04_script",
    "n05_storyboard",
    "n06_voiceover",
    "n08_keyframe",
    "n10_video",
    "shot_director",
    "n12_music",
    "n13_subtitle",
    "n14_packaging",
    "n15_compose",
)

PEERS: tuple[str, ...] = ("n12_music", "n13_subtitle", "n14_packaging")
FINAL_NODE = "n15_compose"

# Activity start-to-close. The node itself is stopped a few seconds earlier.
TIMEOUT_S: dict[str, int] = {
    "n01_brief": 90,
    "n02_brand_kit": 30,
    "n03_concept": 30,
    "n04_script": 120,
    "n05_storyboard": 90,
    "n06_voiceover": 180,
    "n08_keyframe": 300,
    "n10_video": 600,
    "shot_director": 600,
    "n12_music": 180,
    "n13_subtitle": 120,
    "n14_packaging": 120,
    "n15_compose": 300,
}

# SPEC §2 user-facing states: 理解需求 → 选方案 → 看分镜 → 生成中 → 成片.
PHASE: dict[str, str] = {
    "n01_brief": "理解需求",
    "n02_brand_kit": "理解需求",
    "n03_concept": "选方案",
    "n04_script": "看分镜",
    "n05_storyboard": "看分镜",
    "n06_voiceover": "生成中",
    "n08_keyframe": "生成中",
    "n10_video": "生成中",
    "shot_director": "生成中",
    "n12_music": "生成中",
    "n13_subtitle": "生成中",
    "n14_packaging": "生成中",
    "n15_compose": "生成中",
}

NODE_MESSAGE: dict[str, str] = {
    "n01_brief": "正在理解需求",
    "n02_brand_kit": "正在读取品牌资料",
    "n03_concept": "正在选定创意方向",
    "n04_script": "正在撰写脚本",
    "n05_storyboard": "正在编排分镜",
    "n06_voiceover": "正在配音",
    "n08_keyframe": "正在生成画面",
    "n10_video": "正在生成视频",
    "shot_director": "正在检查镜头",
    "n12_music": "正在配乐",
    "n13_subtitle": "正在生成字幕",
    "n14_packaging": "正在叠加品牌包装",
    "n15_compose": "正在合成成片",
}

SHOT_ACTION: dict[str, str] = {
    "n06_voiceover": "正在配音",
    "n08_keyframe": "正在生成画面",
    "n10_video": "正在生成视频",
    "n13_subtitle": "正在生成字幕",
}
