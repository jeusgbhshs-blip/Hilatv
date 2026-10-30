"""Apply a change set onto the script and brand voice. Pictures are not drawn here.

On-screen words stay on the cards the render layer paints. A lighting note is
appended to the visual description together with the no-text constraint.
"""

from __future__ import annotations

import os
import re

from workers.nodes.n06_voiceover.prosody import DEFAULT_VOICE
from workers.schemas.brand import BrandKit
from workers.schemas.director import RevisionDirective
from workers.schemas.script import OnScreenText, Script, Shot

NO_TEXT = "画面无任何文字、无 Logo、无价格、无电话号码。"
_PRICE = re.compile(r"(价格|价钱|售价|标价|¥|￥|\$|\d+(?:\.\d+)?\s*元)")
_PHONE = re.compile(r"(电话|手机|1[3-9]\d{9}|0\d{2,3}-?\d{7,8})")


def female_voice() -> str:
    raw = os.getenv("HILATV_REVISION_FEMALE_VOICE", "").strip()
    return raw or "zh_female_steady"


def apply_script(script: Script, directive: RevisionDirective) -> Script:
    targets = set(directive.targets)
    shots = [_shot(shot, directive) if shot.shot_id in targets else shot for shot in script.shots]
    return script.model_copy(update={"shots": shots})


def apply_brand(kit: BrandKit | None, directive: RevisionDirective) -> BrandKit | None:
    if kit is None:
        return None
    voice = kit.voice
    if directive.change.get("voice") == "male":
        voice = voice.model_copy(update={"tts_voice": DEFAULT_VOICE})
    elif directive.change.get("voice") == "female":
        voice = voice.model_copy(update={"tts_voice": female_voice()})
    cta = kit.cta
    if directive.change.get("phone") == "remove":
        cta = cta.model_copy(update={"phone": ""})
    return kit.model_copy(update={"voice": voice, "cta": cta})


def brand_logo_enabled(directive: RevisionDirective) -> bool:
    return directive.change.get("logo") != "remove"


def _shot(shot: Shot, directive: RevisionDirective) -> Shot:
    change = directive.change
    updates: dict[str, object] = {}
    visual = shot.visual
    if change.get("lighting") == "brighter":
        visual = _visual(visual, "光线更亮。")
    elif change.get("lighting") == "darker":
        visual = _visual(visual, "光线更暗。")
    if change.get("visual") == "regenerate":
        visual = _visual(visual, "按原构图重新取景。")
    if visual != shot.visual:
        updates["visual"] = visual
    if "narration" in change:
        spoken = shot.voiceover
        if change["narration"] == "shorter":
            spoken = _shorter(spoken)
        elif isinstance(change["narration"], str) and change["narration"].strip():
            spoken = change["narration"].strip()
        updates["voiceover"] = spoken
    cards = list(shot.on_screen_text)
    if change.get("price") == "remove":
        cards = [card for card in cards if not _PRICE.search(card.text)]
    if change.get("phone") == "remove":
        cards = [card for card in cards if not _PHONE.search(card.text)]
    duration = float(shot.duration_s)
    if change.get("duration") == "shorter":
        duration = max(1.0, round(duration * 0.8, 3))
    elif change.get("duration") == "longer":
        duration = min(180.0, round(duration * 1.2, 3))
    if abs(duration - float(shot.duration_s)) > 1e-6:
        cards = _scale(cards, float(shot.duration_s), duration)
        updates["duration_s"] = duration
    if cards != list(shot.on_screen_text):
        updates["on_screen_text"] = cards
    if not updates:
        return shot
    return shot.model_copy(update=updates)


def _visual(text: str, extra: str) -> str:
    body = text.strip()
    if extra not in body:
        body = f"{body} {extra}".strip()
    if not _has_no_text(body):
        body = f"{body} {NO_TEXT}"
    return body


def _has_no_text(text: str) -> bool:
    return "无文字" in text or "无任何文字" in text or "不要出现任何文字" in text


def _shorter(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= 2:
        return stripped
    keep = max(2, int(len(stripped) * 0.6))
    return stripped[:keep]


def _scale(cards: list[OnScreenText], old: float, new: float) -> list[OnScreenText]:
    if old <= 0:
        return cards
    ratio = new / old
    scaled: list[OnScreenText] = []
    for card in cards:
        start = round(float(card.in_) * ratio, 3)
        end = round(float(card.out) * ratio, 3)
        end = min(new, max(end, start))
        scaled.append(card.model_copy(update={"in_": start, "out": end}))
    return scaled
