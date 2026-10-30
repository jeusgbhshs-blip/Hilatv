"""Hand-written edit set. Expected fields are not produced by the parser.

Success means the change set matches this intent, the dependency list matches
the literals below, and shots that are not targets keep every field.
"""

from __future__ import annotations

from typing import Any

from workers.nodes.n18_revision.apply import apply_script
from workers.nodes.n18_revision.deps import plan_for
from workers.nodes.n18_revision.parse import parse_edit
from workers.schemas.script import Script

_LIGHT = ["n08_keyframe", "n09_keyframe_qa", "n10_video", "n11_video_qa", "n15_compose"]
_LENGTH = ["n06_voiceover", "n10_video", "n11_video_qa", "n13_subtitle", "n15_compose"]
_VOICE = ["n06_voiceover", "n15_compose"]
_OVERLAY = ["n14_packaging", "n15_compose"]
_ALL = ["S01", "S02", "S03"]


def sample_script() -> Script:
    def card(text: str) -> dict[str, Any]:
        return {"text": text, "style": "spec_badge", "in": 0.2, "out": 1.6}

    def shot(shot_id: str, order: int, spoken: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "shot_id": shot_id,
            "order": order,
            "duration_s": 4.0,
            "purpose": "展示产品",
            "visual": "柱塞泵在车间里运转，金属冷光。画面无任何文字、无 Logo、无价格、无电话号码。",
            "shot_size": "medium",
            "camera": "locked_off",
            "subject_refs": ["product:HP-300"],
            "scene_ref": "scene:workshop",
            "voiceover": spoken,
            "on_screen_text": cards,
            "transition_out": "cut",
            "generation_mode": "image_to_video",
            "status": "pending",
        }

    return Script.model_validate(
        {
            "script_id": "script-edit",
            "brief_id": "brief-edit",
            "language": "zh",
            "sections": [],
            "shots": [
                shot("S01", 1, "车间里的泵已经就位。", []),
                shot("S02", 2, "压力稳定，适合连续作业。", [card("¥199")]),
                shot("S03", 3, "欢迎来电了解交期。", [card("电话 0532-88881234")]),
            ],
        }
    )


# Literals below are the intent. Do not build them by calling the parser.
CASES: list[dict[str, Any]] = [
    {
        "instruction": "第二个镜头太暗",
        "targets": ["S02"],
        "change": {"lighting": "brighter"},
        "keep": ["composition", "narration", "logo", "other_shots"],
        "nodes": _LIGHT,
        "video": ["S02"],
    },
    {
        "instruction": "把价格去掉",
        "targets": _ALL,
        "change": {"price": "remove"},
        "keep": ["narration", "composition", "logo"],
        "nodes": _OVERLAY,
        "video": [],
    },
    {
        "instruction": "换个男声",
        "targets": _ALL,
        "change": {"voice": "male"},
        "keep": ["narration", "visual", "logo"],
        "nodes": _VOICE,
        "video": [],
    },
    {
        "instruction": "再短一点",
        "targets": _ALL,
        "change": {"duration": "shorter"},
        "keep": ["logo", "composition"],
        "nodes": _LENGTH,
        "video": _ALL,
    },
    {
        "instruction": "第二个镜头的旁白改成「压力稳定」",
        "targets": ["S02"],
        "change": {"narration": "压力稳定"},
        "keep": ["composition", "logo", "other_shots"],
        "nodes": _LENGTH,
        "video": ["S02"],
    },
    {
        "instruction": "去掉 Logo",
        "targets": _ALL,
        "change": {"logo": "remove"},
        "keep": ["narration", "composition"],
        "nodes": _OVERLAY,
        "video": [],
    },
    {
        "instruction": "第一个镜头再亮一点",
        "targets": ["S01"],
        "change": {"lighting": "brighter"},
        "keep": ["composition", "other_shots"],
        "nodes": _LIGHT,
        "video": ["S01"],
    },
    {
        "instruction": "第三镜暗一点",
        "targets": ["S03"],
        "change": {"lighting": "darker"},
        "keep": ["composition", "narration", "other_shots"],
        "nodes": _LIGHT,
        "video": ["S03"],
    },
    {
        "instruction": "镜头2保持构图，打亮一点",
        "targets": ["S02"],
        "change": {"lighting": "brighter"},
        "keep": ["composition", "narration"],
        "nodes": _LIGHT,
        "video": ["S02"],
    },
    {
        "instruction": "不要改旁白，第二个镜头亮一些",
        "targets": ["S02"],
        "change": {"lighting": "brighter"},
        "keep": ["narration", "composition"],
        "nodes": _LIGHT,
        "video": ["S02"],
    },
    {
        "instruction": "把第二个镜头的价格卡片去掉",
        "targets": ["S02"],
        "change": {"price": "remove"},
        "keep": ["narration", "logo", "other_shots"],
        "nodes": _OVERLAY,
        "video": [],
    },
    {
        "instruction": "换成女声",
        "targets": _ALL,
        "change": {"voice": "female"},
        "keep": ["narration", "visual", "logo"],
        "nodes": _VOICE,
        "video": [],
    },
    {
        "instruction": "整片再短两秒",
        "targets": _ALL,
        "change": {"duration": "shorter"},
        "keep": ["logo", "narration"],
        "nodes": _LENGTH,
        "video": _ALL,
    },
    {
        "instruction": "只改第二个镜头的旁白，其他镜头别动。旁白改成「出水稳定」",
        "targets": ["S02"],
        "change": {"narration": "出水稳定"},
        "keep": ["other_shots", "composition", "logo"],
        "nodes": _LENGTH,
        "video": ["S02"],
    },
    {
        "instruction": "片头 Logo 换成新的，画面不要重做",
        "targets": _ALL,
        "change": {"logo": "replace"},
        "keep": ["visual", "narration"],
        "nodes": _OVERLAY,
        "video": [],
    },
    {
        "instruction": "第二个镜头太模糊",
        "targets": ["S02"],
        "change": {"visual": "regenerate"},
        "keep": ["composition", "narration", "logo", "other_shots"],
        "nodes": _LIGHT,
        "video": ["S02"],
    },
    {
        "instruction": "把电话从画面上拿掉",
        "targets": _ALL,
        "change": {"phone": "remove"},
        "keep": ["narration", "logo", "composition"],
        "nodes": _OVERLAY,
        "video": [],
    },
    {
        "instruction": "第三个镜头的运镜别动，只把旁白缩短",
        "targets": ["S03"],
        "change": {"narration": "shorter"},
        "keep": ["composition", "logo", "other_shots"],
        "nodes": _LENGTH,
        "video": ["S03"],
    },
    {
        "instruction": "所有镜头都亮一点",
        "targets": _ALL,
        "change": {"lighting": "brighter"},
        "keep": ["composition", "narration", "logo"],
        "nodes": _LIGHT,
        "video": _ALL,
    },
    {
        "instruction": "第二个镜头保持现有旁白，把灯光调亮",
        "targets": ["S02"],
        "change": {"lighting": "brighter"},
        "keep": ["narration", "composition"],
        "nodes": _LIGHT,
        "video": ["S02"],
    },
    {
        "instruction": "去掉右下角价格",
        "targets": _ALL,
        "change": {"price": "remove"},
        "keep": ["narration", "logo"],
        "nodes": _OVERLAY,
        "video": [],
    },
    {
        "instruction": "男声配音，画面保持不变",
        "targets": _ALL,
        "change": {"voice": "male"},
        "keep": ["visual", "narration", "logo"],
        "nodes": _VOICE,
        "video": [],
    },
    {
        "instruction": "把第一镜的字幕价格 99 元删掉",
        "targets": ["S01"],
        "change": {"price": "remove"},
        "keep": ["narration", "logo", "other_shots"],
        "nodes": _OVERLAY,
        "video": [],
    },
    {
        "instruction": "仅重做第二个镜头的画面，旁白和 logo 不动",
        "targets": ["S02"],
        "change": {"visual": "regenerate"},
        "keep": ["narration", "logo", "composition", "other_shots"],
        "nodes": _LIGHT,
        "video": ["S02"],
    },
    {
        "instruction": "太暗",
        "focused_shot_id": "S03",
        "targets": ["S03"],
        "change": {"lighting": "brighter"},
        "keep": ["composition", "narration", "other_shots"],
        "nodes": _LIGHT,
        "video": ["S03"],
    },
]


def evaluate(script: Script | None = None) -> dict[str, Any]:
    """Score the set. A miss records the first mismatched field."""

    board = script or sample_script()
    passed = 0
    failures: list[dict[str, str]] = []
    for case in CASES:
        reason = _judge(board, case)
        if reason:
            failures.append({"instruction": case["instruction"], "reason": reason})
        else:
            passed += 1
    total = len(CASES)
    return {
        "total": total,
        "passed": passed,
        "rate": passed / total if total else 0.0,
        "failures": failures,
        "self_made": True,
    }


def _judge(script: Script, case: dict[str, Any]) -> str:
    directive = parse_edit(
        script,
        case["instruction"],
        focused_shot_id=case.get("focused_shot_id"),
        gateway=None,
    )
    if directive.targets != case["targets"]:
        return f"targets {directive.targets}"
    if directive.change != case["change"]:
        return f"change {directive.change}"
    for item in case["keep"]:
        if item not in directive.keep:
            return f"missing keep {item}"
    for key in directive.change:
        if key in directive.keep:
            return f"{key} is both changed and kept"
    plan = plan_for(script, directive)
    if plan.nodes != case["nodes"]:
        return f"nodes {plan.nodes}"
    if plan.video_shots != case["video"]:
        return f"video {plan.video_shots}"
    updated = apply_script(script, directive)
    targets = set(directive.targets)
    for before, after in zip(script.shots, updated.shots, strict=True):
        if before.shot_id in targets:
            continue
        if before.model_dump(mode="json") != after.model_dump(mode="json"):
            return f"{before.shot_id} changed"
    return ""
