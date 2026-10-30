"""Edits written without looking at the parser's keyword list.

Expected outcomes are what a finished editor should do. The mock model does
not read the sentence, so supported edits usually come back as a question.
"""

from __future__ import annotations

from typing import Any

from workers.nodes.n18_revision.corpus import sample_script
from workers.nodes.n18_revision.parse import parse_edit
from workers.schemas.script import Script

# status is apply, needs_clarification, or not_supported.
# apply cases also name the change the editor should make.
UNSEEN: list[dict[str, Any]] = [
    {"instruction": "去掉片尾的价格", "status": "apply", "change": {"price": "remove"}},
    {"instruction": "换成傍晚", "status": "not_supported"},
    {"instruction": "女声慢一点", "status": "needs_clarification"},
    {"instruction": "logo 小一点放右上角", "status": "not_supported"},
    {"instruction": "主持人别穿红衣服", "status": "not_supported"},
    {"instruction": "前两个镜头合成一个", "status": "not_supported"},
    {"instruction": "字幕改成英文", "status": "not_supported"},
    {"instruction": "节奏快一点", "status": "not_supported"},
    {
        "instruction": "把第二个镜头调亮",
        "status": "apply",
        "targets": ["S02"],
        "change": {"lighting": "brighter"},
    },
    {"instruction": "片尾电话去掉", "status": "apply", "change": {"phone": "remove"}},
    {"instruction": "旁白改成「欢迎咨询」", "status": "apply", "change": {"narration": "欢迎咨询"}},
    {"instruction": "整段再长一点", "status": "apply", "change": {"duration": "longer"}},
    {"instruction": "换成男声", "status": "apply", "change": {"voice": "male"}},
    {"instruction": "Logo 拿掉", "status": "apply", "change": {"logo": "remove"}},
    {
        "instruction": "第三镜太模糊，重做画面",
        "status": "apply",
        "targets": ["S03"],
        "change": {"visual": "regenerate"},
    },
    {"instruction": "价格数字别显示了", "status": "apply", "change": {"price": "remove"}},
    {
        "instruction": "第一个镜头的旁白缩短",
        "status": "apply",
        "targets": ["S01"],
        "change": {"narration": "shorter"},
    },
    {"instruction": "女声来念", "status": "apply", "change": {"voice": "female"}},
    {"instruction": "太亮了，压暗一点", "status": "apply", "change": {"lighting": "darker"}},
    {"instruction": "把两段镜头并成一个", "status": "not_supported"},
    {"instruction": "让主持人换一件蓝衣服", "status": "not_supported"},
    {"instruction": "字幕翻成英文", "status": "not_supported"},
    {"instruction": "节奏再慢一些", "status": "not_supported"},
    {"instruction": "改成夜景", "status": "not_supported"},
    {"instruction": "把 logo 放到左上角并放大", "status": "not_supported"},
    {"instruction": "嗯", "status": "needs_clarification"},
    {"instruction": "好看一点", "status": "needs_clarification"},
    {"instruction": "再调整一下", "status": "needs_clarification"},
    {"instruction": "这个感觉不对", "status": "needs_clarification"},
    {"instruction": "帮我改改", "status": "needs_clarification"},
    {"instruction": "随便优化", "status": "needs_clarification"},
    {"instruction": "有点奇怪", "status": "needs_clarification"},
]


def evaluate_unseen(script: Script | None = None, gateway: Any | None = None) -> dict[str, Any]:
    board = script or sample_script()
    passed = 0
    failures: list[dict[str, str]] = []
    unsafe = 0
    for case in UNSEEN:
        parsed = parse_edit(board, case["instruction"], gateway=gateway)
        if parsed.status == "apply" and parsed.directive is not None:
            everyone = {shot.shot_id for shot in board.shots}
            if (
                set(parsed.directive.targets) == everyone
                and parsed.directive.change.get("visual") == "regenerate"
            ):
                unsafe += 1
        reason = ""
        if parsed.status != case["status"]:
            reason = parsed.status
        elif case["status"] == "apply" and parsed.directive is not None:
            change = case.get("change") or {}
            if any(parsed.directive.change.get(key) != value for key, value in change.items()):
                reason = f"change {parsed.directive.change}"
            targets = case.get("targets")
            if targets and parsed.directive.targets != targets:
                reason = f"targets {parsed.directive.targets}"
        if reason:
            failures.append({"instruction": case["instruction"], "reason": reason})
        else:
            passed += 1
    total = len(UNSEEN)
    return {
        "total": total,
        "passed": passed,
        "rate": passed / total if total else 0.0,
        "failures": failures,
        "unsafe_blanket": unsafe,
        "self_made": False,
    }
