"""创作者分镜模板库：把行业方法论固化成分镜骨架，一键套到项目里。"""

from __future__ import annotations

from typing import Any

from workers.expert.gates import GateError
from workers.expert.script_edit import _guard, _public, _read_ext, _save_script, _script, _write_ext
from workers.workflow.store import locked_project, read_snapshot, valid_project_id

_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "id": "hook_problem_turn_result",
        "title": "钩子 → 问题 → 转变 → 结果",
        "description": "广告/短视频最稳的四段式：先抓眼球，再讲痛点，给方案，落到结果。",
        "shots": [
            (
                "钩子",
                "先看这里",
                "开屏第一秒的强视觉：产品/结果/反差画面，直接怼到镜头前",
                "close_up",
                "snap_push",
            ),
            (
                "问题",
                "是不是也遇到过这种情况？",
                "用户真实的使用场景与痛点，画面要能识别出具体场景",
                "medium",
                "handheld_follow",
            ),
            (
                "转变",
                "现在这样做，三步搞定",
                "产品如何解决问题的关键动作，手部/操作特写",
                "detail",
                "slow_push_in",
            ),
            (
                "结果",
                "省下来的时间，才是真的",
                "使用后的结果画面，整洁/轻松/高效的生活或工作状态",
                "wide",
                "locked_off",
            ),
        ],
    },
    {
        "id": "product_hero",
        "title": "产品展示四段式",
        "description": "适合电商主图/详情页：建立镜头 → 动作镜头 → 细节镜头 → 英雄收尾。",
        "shots": [
            ("建立", "", "产品完整外观，干净背景，光从侧后方打亮轮廓", "wide", "locked_off"),
            ("动作", "", "手部拿起/使用产品，动作自然，产品形状稳定", "medium", "handheld_follow"),
            ("细节", "", "材质/工艺/关键结构的微距特写，缓慢横移", "macro", "detail_drift"),
            ("英雄", "", "产品英雄镜头，居中构图，缓慢环绕或推近", "close_up", "slow_push_in"),
        ],
    },
    {
        "id": "talking_head",
        "title": "口播讲解",
        "description": "真人口播/知识讲解：开场承诺、分点说明、例子、行动号召。",
        "shots": [
            ("开场", "", "人物中景正面口播，眼神看镜头，干净背景", "medium", "locked_off"),
            ("要点一", "", "人物+道具/展示物同框，手势自然", "medium", "locked_off"),
            ("要点二", "", "切到细节或演示画面，画面信息密度高", "close_up", "handheld_follow"),
            ("收尾", "", "人物略微推近，给出行动指令或总结", "close_up", "slow_push_in"),
        ],
    },
    {
        "id": "short_drama_hook",
        "title": "短剧黄金 3 秒",
        "description": "短剧/漫剧开场：冲突画面先行、人物关系、反转钩子、留白悬念。",
        "shots": [
            ("冲突", "", "第一秒直接进入冲突画面，人物表情/动作要强烈", "close_up", "snap_push"),
            ("关系", "", "交代人物关系与场景，环境要有信息量", "wide", "locked_off"),
            ("反转", "", "出现意外元素/台词，画面停住半拍", "medium", "locked_off"),
            ("悬念", "", "结尾留白：物件特写、背影、未说完的台词", "close_up", "slow_push_in"),
        ],
    },
)


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "description": item["description"],
            "shot_count": len(item["shots"]),
        }
        for item in _TEMPLATES
    ]


def apply_template(project_id: str, template_id: str) -> dict[str, Any]:
    template = next((item for item in _TEMPLATES if item["id"] == template_id), None)
    if template is None:
        raise GateError("没有这个分镜模板", status=404)
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    with locked_project(project_id):
        snapshot = read_snapshot(project_id) or {}
        _guard(snapshot)
        script = _script(project_id)
        rows = []
        for index, (purpose, voiceover, visual, shot_size, camera) in enumerate(
            template["shots"], 1
        ):
            rows.append(
                {
                    "shot_id": f"S{index:02d}",
                    "order": index,
                    "duration_s": 4.0,
                    "purpose": purpose,
                    "visual": visual,
                    "shot_size": shot_size,
                    "camera": camera,
                    "subject_refs": [],
                    "scene_ref": "",
                    "voiceover": voiceover,
                    "on_screen_text": [],
                    "transition_out": "cut",
                    "generation_mode": "image_to_video",
                    "status": "pending",
                }
            )
        script["shots"] = rows
        _save_script(project_id, script)
        ext = _read_ext(project_id)
        ext["shots"] = {}
        ext["revision"] = int(ext.get("revision") or 0) + 1
        _write_ext(project_id, ext)
    return _public(project_id)
