"""Parse one edit sentence. The gateway model is the parser.

Rules only check that a model decision is safe: known shots, allowed change
keys, and no silent regeneration of every shot. They do not invent a change
from sentence-specific phrases. A mock model fills the schema with placeholders,
so CI usually gets a clarification instead of a finished change set.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
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

ALLOWED_CHANGE = frozenset(
    {"lighting", "narration", "voice", "logo", "price", "phone", "duration", "visual"}
)
_GLOBAL = ("所有", "每个", "全部", "整片", "全片")
# Operations this node cannot apply. These are categories, not the scored sentences.
_UNSUPPORTED = (
    (re.compile(r"合成|合并|并成"), "不能把镜头合成或拆开。"),
    (re.compile(r"衣服|穿着|别穿|服装"), "不能改服装。"),
    (re.compile(r"字幕"), "不能在这里改字幕语种。"),
    (re.compile(r"节奏"), "不能单独改整片节奏。"),
    (re.compile(r"傍晚|黄昏|清晨|深夜|夜景"), "不能把时间改成某个时段。"),
    (
        re.compile(
            r"logo.{0,8}(小|大|左|右|角)|(小|大|左|右).{0,6}logo",
            re.IGNORECASE,
        ),
        "不能改 Logo 的大小或位置。",
    ),
)


@dataclass(frozen=True)
class EditParse:
    status: str
    directive: RevisionDirective | None = None
    question: str = ""
    notice: str = ""


def parse_edit(
    script: Script,
    instruction: str,
    *,
    focused_shot_id: str | None = None,
    gateway: Any | None = None,
    project_id: str | None = None,
    attempt: int = 1,
) -> EditParse:
    text = instruction.strip()
    proposed = _from_model(
        gateway,
        script=script,
        instruction=text,
        project_id=project_id,
        attempt=attempt,
    )
    blocked = _unsupported(text)
    if blocked:
        return EditParse(status="not_supported", notice=blocked)
    if proposed is None:
        return _clarify(script, text, focused_shot_id)
    reason = _reject(proposed, script, text)
    if reason:
        return _clarify(script, text, focused_shot_id, why=reason)
    return EditParse(status="apply", directive=proposed)


def _unsupported(text: str) -> str:
    for pattern, notice in _UNSUPPORTED:
        if pattern.search(text):
            return notice
    return ""


def _clarify(
    script: Script,
    text: str,
    focused_shot_id: str | None,
    *,
    why: str = "",
) -> EditParse:
    known = {shot.shot_id for shot in script.shots}
    named = _mentions_shot(text) or (focused_shot_id in known if focused_shot_id else False)
    if not named and not any(word in text for word in _GLOBAL):
        question = "要改哪一个镜头？也可以说全部镜头。"
    else:
        question = "请说明要改灯光、旁白、声音、Logo、价格、电话，还是时长。"
    notice = why or "这句话还不能对应到一个具体改动。"
    return EditParse(status="needs_clarification", question=question, notice=notice)


def _mentions_shot(text: str) -> bool:
    return bool(
        re.search(r"第\s*[0-9一二三四五六七八九十两]", text)
        or re.search(r"镜头\s*[0-9一二三四五六七八九]", text)
        or re.search(r"\bS\d{1,2}\b", text, re.IGNORECASE)
    )


def _reject(directive: RevisionDirective, script: Script, text: str) -> str:
    known = [shot.shot_id for shot in script.shots]
    if any(shot_id not in known for shot_id in directive.targets):
        return "镜头编号不在这条片子里。"
    if not set(directive.change).issubset(ALLOWED_CHANGE):
        return "改动类型不能执行。"
    values = directive.change.values()
    if any(not isinstance(value, str) or not value.strip() or value == "mock" for value in values):
        return "改动内容是空的。"
    everyone = set(directive.targets) == set(known)
    blanket = everyone and directive.change.get("visual") == "regenerate"
    if blanket and not any(word in text for word in _GLOBAL):
        return "不能在没说清范围时重做全部镜头。"
    return ""


def _from_model(
    gateway: Any | None,
    *,
    script: Script,
    instruction: str,
    project_id: str | None,
    attempt: int,
) -> RevisionDirective | None:
    if gateway is None or not callable(getattr(gateway, "generate_text", None)):
        return None
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
        return None
    return _coerce(raw, known=[shot.shot_id for shot in script.shots])


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
    if not set(directive.change).issubset(ALLOWED_CHANGE):
        return None
    if any(
        not isinstance(value, str) or not value.strip() or value == "mock"
        for value in directive.change.values()
    ):
        return None
    return directive
