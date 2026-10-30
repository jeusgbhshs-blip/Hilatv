"""Turn one sentence into a RevisionDirective.

The gateway is asked first. A mock fill (``targets: ["mock"]``) does not name a
real shot, so the hand-written rules decide. Rules are the acceptance path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from workers.schemas.director import RevisionDirective
from workers.schemas.script import Script, Shot

_PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(_PROMPTS),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ORDINAL = re.compile(r"第\s*([0-9一二三四五六七八九十两]+)\s*(?:个)?\s*(?:镜头|镜)")
_SHOT_DIGIT = re.compile(r"(?:镜头|镜)\s*([0-9]{1,2})")
_SHOT_CN = re.compile(r"镜头\s*([一二三四五六七八九两])")
_SHOT_CODE = re.compile(r"\bS(\d{1,2})\b", re.IGNORECASE)
_GLOBAL = ("所有", "每个", "全部", "整片", "全片")
_QUOTED = (
    re.compile(r"「([^」]+)」"),
    re.compile(r"『([^』]+)』"),
    re.compile(r"“([^”]+)”"),
    re.compile(r'"([^"]+)"'),
)


def parse_edit(
    script: Script,
    instruction: str,
    *,
    focused_shot_id: str | None = None,
    gateway: Any | None = None,
    project_id: str | None = None,
    attempt: int = 1,
) -> RevisionDirective:
    rules = _rules(script, instruction, focused_shot_id)
    return _from_model(
        gateway,
        rules,
        script=script,
        instruction=instruction,
        project_id=project_id,
        attempt=attempt,
    )


def _rules(script: Script, instruction: str, focused_shot_id: str | None) -> RevisionDirective:
    text = instruction.strip()
    orders = _orders(text)
    by_order = {shot.order: shot.shot_id for shot in script.shots}
    known = [shot.shot_id for shot in script.shots]
    if any(word in text for word in _GLOBAL) and not orders:
        targets = list(known)
    elif orders:
        targets = [by_order[order] for order in orders if order in by_order]
    elif focused_shot_id and focused_shot_id in known:
        targets = [focused_shot_id]
    else:
        targets = list(known)
    if not targets:
        targets = list(known)
    change = _change(text)
    if not change:
        change = {"visual": "regenerate"}
    keep = _keep(text, change, targets, known)
    return RevisionDirective(targets=targets, change=change, keep=keep)


def _orders(text: str) -> list[int]:
    found: list[int] = []
    for token in _ORDINAL.findall(text):
        _push(found, _number(token))
    for token in _SHOT_DIGIT.findall(text):
        _push(found, _number(token))
    for token in _SHOT_CN.findall(text):
        _push(found, _number(token))
    for token in _SHOT_CODE.findall(text):
        _push(found, _number(token))
    return found


def _push(found: list[int], value: int | None) -> None:
    if value is None or value in found:
        return
    found.append(value)


def _number(token: str) -> int | None:
    if token.isdigit():
        value = int(token)
        return value if 1 <= value <= 30 else None
    if token in _CN:
        return _CN[token]
    if token == "十":
        return 10
    if len(token) == 2 and token[0] == "十" and token[1] in _CN:
        return 10 + _CN[token[1]]
    return None


def _change(text: str) -> dict[str, str]:
    change: dict[str, str] = {}
    quoted = _quote(text)
    keep_narration = _keeps_narration(text)
    keep_picture = _keeps_picture(text)
    if re.search(r"太暗|不够亮|亮一点|亮一些|再亮|打亮|调亮|更亮|太黑", text):
        change["lighting"] = "brighter"
    elif re.search(r"太亮|暗一点|暗一些|再暗|压暗|更暗|调暗", text):
        change["lighting"] = "darker"
    if not keep_picture and (
        "太模糊" in text
        or ("重做" in text and "画面" in text and not re.search(r"不要重做|别重做|不用重做", text))
    ):
        change["visual"] = "regenerate"
    if re.search(r"旁白|文案|台词", text) and not keep_narration:
        if quoted:
            change["narration"] = quoted
        elif re.search(r"缩短|短一点|再短|精简", text):
            change["narration"] = "shorter"
    if re.search(r"男声|男生|男配音", text):
        change["voice"] = "male"
    elif re.search(r"女声|女生|女配音", text):
        change["voice"] = "female"
    if re.search(r"logo|标志|角标", text, re.IGNORECASE) and not _keeps_logo(text):
        if re.search(
            r"(去掉|删除|拿掉|隐藏|取消|不要).{0,8}(logo|标志|角标)"
            r"|(logo|标志|角标).{0,8}(去掉|删除|拿掉|隐藏|取消)",
            text,
            re.IGNORECASE,
        ):
            change["logo"] = "remove"
        elif re.search(r"换|替换|更新", text):
            change["logo"] = "replace"
    if re.search(r"去掉|删除|拿掉|删掉|不要", text) and (
        re.search(r"价格|价钱|售价|标价", text) or re.search(r"\d+\s*元", text)
    ):
        change["price"] = "remove"
    if re.search(r"电话|手机号|联系电话", text) and re.search(r"去掉|删除|拿掉|不要", text):
        change["phone"] = "remove"
    if "narration" not in change and not re.search(r"旁白|文案|台词", text):
        if re.search(r"短一点|再短|缩短|太长|短两秒|短一些", text):
            change["duration"] = "shorter"
        elif re.search(r"长一点|再长|加长|太短", text):
            change["duration"] = "longer"
    return change


def _quote(text: str) -> str:
    for pattern in _QUOTED:
        found = pattern.search(text)
        if found:
            return found.group(1).strip()
    return ""


def _keeps_narration(text: str) -> bool:
    if re.search(r"不要改旁白|别改旁白|旁白不动|旁白保持|保持现有旁白", text):
        return True
    return bool(re.search(r"旁白和.{0,16}不动", text))


def _keeps_picture(text: str) -> bool:
    return bool(re.search(r"画面不要|画面保持不变|画面别动|不要重做|别重做", text))


def _keeps_logo(text: str) -> bool:
    return bool(re.search(r"logo\s*不动|标志不动", text, re.IGNORECASE)) or (
        "logo" in text.lower() and re.search(r"不动|别动", text) is not None and "旁白和" in text
    )


def _keep(text: str, change: dict[str, str], targets: list[str], known: list[str]) -> list[str]:
    keep: list[str] = []

    def add(item: str) -> None:
        if item not in keep and item not in change:
            keep.append(item)

    if re.search(r"保持构图|别动构图|构图不变|构图不动|运镜别动|运镜不动", text):
        add("composition")
    if _keeps_narration(text):
        add("narration")
    if _keeps_picture(text):
        add("visual")
    if _keeps_logo(text):
        add("logo")
    if re.search(r"其他镜头", text) and re.search(r"别动|不动|不要", text):
        add("other_shots")
    if "lighting" in change or "visual" in change:
        add("composition")
    if set(targets) != set(known):
        add("other_shots")
    for aspect in (
        "composition",
        "narration",
        "lighting",
        "logo",
        "price",
        "phone",
        "voice",
        "visual",
        "duration",
    ):
        if aspect == "visual" and ("lighting" in change or "visual" in change):
            continue
        add(aspect)
    return keep


def _from_model(
    gateway: Any | None,
    rules: RevisionDirective,
    *,
    script: Script,
    instruction: str,
    project_id: str | None,
    attempt: int,
) -> RevisionDirective:
    if gateway is None or not hasattr(gateway, "generate_text"):
        return rules
    prompt = _ENV.get_template("parse.j2").render(
        instruction=instruction,
        shots=_shot_lines(script.shots),
    )
    try:
        raw = gateway.generate_text(
            prompt,
            schema=RevisionDirective,
            seed=attempt,
            project_id=project_id,
            node="n18_revision",
            attempt=attempt,
        )
    except Exception:
        return rules
    parsed = _coerce(raw, known=[shot.shot_id for shot in script.shots])
    if parsed is None:
        return rules
    if parsed.targets == rules.targets and parsed.change == rules.change:
        return parsed
    return rules


def _shot_lines(shots: list[Shot]) -> str:
    lines = []
    for shot in shots:
        cards = "、".join(card.text for card in shot.on_screen_text) or "无"
        lines.append(f"{shot.shot_id} 第{shot.order}镜 旁白={shot.voiceover} 画面字={cards}")
    return "\n".join(lines)


def _coerce(raw: object, *, known: list[str]) -> RevisionDirective | None:
    body: object = raw
    if isinstance(raw, dict) and "targets" not in raw and isinstance(raw.get("text"), str):
        try:
            body = json.loads(raw["text"])
        except json.JSONDecodeError:
            return None
    if not isinstance(body, dict):
        return None
    try:
        directive = RevisionDirective.model_validate(body)
    except Exception:
        return None
    if any(shot_id not in known for shot_id in directive.targets):
        return None
    allowed = {
        "lighting",
        "narration",
        "voice",
        "logo",
        "price",
        "phone",
        "duration",
        "visual",
    }
    if not set(directive.change).issubset(allowed):
        return None
    if any(
        not isinstance(value, str) or not value.strip() or value == "mock"
        for value in directive.change.values()
    ):
        return None
    return directive
