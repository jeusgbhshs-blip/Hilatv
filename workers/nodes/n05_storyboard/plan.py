"""Split a script into shots. Durations sum to the brief, inside the N5 ranges."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from workers.nodes.n05_storyboard.modes import select_generation_mode
from workers.nodes.n05_storyboard.presets import ShotPreset, load_presets, match_preset
from workers.nodes.n05_storyboard.schema import StoryboardHint
from workers.qa.copycheck import count_units, language_family
from workers.schemas.brand import BrandKit, Product
from workers.schemas.brief import Brief
from workers.schemas.script import (
    OnScreenText,
    Script,
    ScriptSection,
    ScriptSectionKind,
    Shot,
    ShotStatus,
)

PROMO_TYPES = {"product_showcase", "factory_strength", "brand_film", "corporate"}
PROMO_RANGE = (4.0, 8.0)
SHORT_RANGE = (2.0, 6.0)

_ROLE_RANK = {
    "person": 6,
    "selling_point": 5,
    "spec": 4,
    "cta": 3,
    "proof": 2,
    "hook": 1,
}
_PURPOSE = {
    "hook": "钩子",
    "selling_point": "卖点",
    "spec": "参数",
    "proof": "信任证明",
    "cta": "行动号召",
    "person": "人物出镜",
}
_SCENE = {
    "hook": "scene:opening_01",
    "selling_point": "scene:product_01",
    "spec": "scene:graphic_01",
    "proof": "scene:workshop_01",
    "cta": "scene:endcard_01",
    "person": "scene:interview_01",
}
_VISUAL = {
    "hook": "开场环境，问题先出现，产品先不推到镜头正中。",
    "selling_point": "产品中近景，外形与资料照片一致，背景轻度虚化。",
    "spec": "干净的图形底，参数留给后期卡片。",
    "proof": "工厂或检测环境的空镜，光线平稳。",
    "cta": "留白底，联系方式由后期叠加。",
    "person": "已授权人物的中景，服装与资料一致。",
}
NO_DRAWN = "画面无任何文字、无 Logo、无价格、无电话号码。"
_FAMILY = {
    "hook": "atmos",
    "proof": "atmos",
    "selling_point": "product",
    "spec": "graphic",
    "cta": "graphic",
    "person": "person",
}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_MODEL_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]*\d")


class PlanError(ValueError):
    """The storyboard rules could not be satisfied."""


@dataclass
class Clip:
    role: str
    voiceover: str
    section_indexes: list[int]
    badge_texts: list[str] = field(default_factory=list)
    person_role: str = ""
    camera_id: str = ""


def is_promo(brief: Brief) -> bool:
    if brief.video_type in PROMO_TYPES:
        return True
    blob = f"{brief.raw_input}\n{brief.goal}\n{brief.video_type}"
    return "宣传片" in blob


def shot_bounds(duration_s: float, *, promo: bool) -> tuple[int, int, float, float]:
    lo, hi = PROMO_RANGE if promo else SHORT_RANGE
    total = int(round(duration_s * 1000))
    lo_ms = int(round(lo * 1000))
    hi_ms = int(round(hi * 1000))
    minimum = math.ceil(total / hi_ms)
    maximum = min(total // lo_ms, total // 2000)
    if minimum < 1 or minimum > maximum:
        raise PlanError(f"no shot count fits {duration_s}s")
    return minimum, maximum, lo, hi


def plan_shots(
    script: Script,
    brief: Brief,
    brand: BrandKit | None,
    *,
    hints: StoryboardHint | None = None,
    duration_s: float | None = None,
) -> Script:
    if not script.sections:
        raise PlanError("script has no sections")
    duration = brief.duration_s if duration_s is None else duration_s
    language = script.language
    clips = _clips_from_sections(script)
    minimum, maximum, lo, hi = shot_bounds(duration, promo=is_promo(brief))
    count = min(maximum, max(minimum, len(clips)))
    clips = _fit_count(clips, count, language)
    _apply_people(clips, brief, brand)
    sizes = _assign_sizes(clips)
    durations = _allocate(duration, len(clips), lo, hi)
    presets = load_presets()
    _assign_cameras(clips, sizes, presets, hints)
    shots = [
        _build_shot(index, clip, sizes[index], durations[index], brand, presets)
        for index, clip in enumerate(clips)
    ]
    sections = _bind_sections(script.sections, shots, clips)
    return script.model_copy(update={"sections": sections, "shots": shots})


def _clips_from_sections(script: Script) -> list[Clip]:
    clips: list[Clip] = []
    hero = False
    for index, section in enumerate(script.sections):
        role = _role_for(section.kind, section.text, hero_seen=hero)
        if role == "selling_point":
            hero = True
        badges = [section.text] if role in {"selling_point", "spec"} else []
        clips.append(
            Clip(
                role=role,
                voiceover=section.text,
                section_indexes=[index],
                badge_texts=badges,
            )
        )
    return clips


def _role_for(kind: ScriptSectionKind, text: str, *, hero_seen: bool) -> str:
    if kind is ScriptSectionKind.hook:
        return "hook"
    if kind is ScriptSectionKind.proof:
        return "proof"
    if kind is ScriptSectionKind.cta:
        return "cta"
    if hero_seen and _NUMBER.search(text):
        return "spec"
    return "selling_point"


def _fit_count(clips: list[Clip], count: int, language: str) -> list[Clip]:
    clips = list(clips)

    def weight(item: int) -> tuple[int, int]:
        return (count_units(clips[item].voiceover, language), item)

    while len(clips) > count:
        index = _merge_index(clips)
        merged = _merge(clips[index], clips[index + 1], language)
        clips = [*clips[:index], merged, *clips[index + 2 :]]
    while len(clips) < count:
        index = max(range(len(clips)), key=weight)
        left, right = _split(clips[index], language)
        clips = [*clips[:index], left, right, *clips[index + 1 :]]
    return clips


def _merge_index(clips: list[Clip]) -> int:
    best = 0
    best_key: tuple[int, int] | None = None
    for index in range(len(clips) - 1):
        same = 0 if _FAMILY[clips[index].role] == _FAMILY[clips[index + 1].role] else 1
        length = len(clips[index].voiceover) + len(clips[index + 1].voiceover)
        key = (same, length)
        if best_key is None or key < best_key:
            best_key = key
            best = index
    return best


def _merge(left: Clip, right: Clip, language: str) -> Clip:
    role = left.role if _ROLE_RANK[left.role] >= _ROLE_RANK[right.role] else right.role
    person = left.person_role or right.person_role
    return Clip(
        role=role,
        voiceover=_join_voice(left.voiceover, right.voiceover, language),
        section_indexes=[*left.section_indexes, *right.section_indexes],
        badge_texts=[*left.badge_texts, *right.badge_texts],
        person_role=person,
    )


def _split(clip: Clip, language: str) -> tuple[Clip, Clip]:
    left_text, right_text = _split_text(clip.voiceover, language)
    left = Clip(
        role=clip.role,
        voiceover=left_text,
        section_indexes=list(clip.section_indexes),
        badge_texts=list(clip.badge_texts),
        person_role=clip.person_role,
    )
    right = Clip(
        role=clip.role,
        voiceover=right_text,
        section_indexes=list(clip.section_indexes),
        badge_texts=[],
        person_role=clip.person_role,
    )
    return left, right


def _join_voice(left: str, right: str, language: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if language_family(language) == "zh":
        if left.endswith(("。", "！", "？")):
            return left + right
        return f"{left}。{right}"
    if left.endswith((".", "!", "?")):
        return f"{left} {right}"
    return f"{left}. {right}"


def _split_text(text: str, language: str) -> tuple[str, str]:
    parts = _atoms(text)
    if len(parts) < 2:
        return text, ""
    mid = max(1, len(parts) // 2)
    joiner = "" if language_family(language) == "zh" else " "
    return joiner.join(parts[:mid]).strip(), joiner.join(parts[mid:]).strip()


def _atoms(text: str) -> list[str]:
    parts: list[str] = []
    index = 0
    while index < len(text):
        ch = text[index]
        if ch.isspace():
            index += 1
            continue
        if ch.isdigit():
            end = index + 1
            while end < len(text) and text[end].isdigit():
                end += 1
            decimal = (
                end < len(text)
                and text[end] == "."
                and end + 1 < len(text)
                and text[end + 1].isdigit()
            )
            if decimal:
                end += 1
                while end < len(text) and text[end].isdigit():
                    end += 1
            parts.append(text[index:end])
            index = end
            continue
        if ch.isascii() and ch.isalpha():
            end = index + 1
            while end < len(text) and (text[end].isalnum() or text[end] in "-'"):
                end += 1
            parts.append(text[index:end])
            index = end
            continue
        if 0x4E00 <= ord(ch) <= 0x9FFF:
            parts.append(ch)
            index += 1
            continue
        if parts:
            parts[-1] = parts[-1] + ch
        index += 1
    return parts


def _apply_people(clips: list[Clip], brief: Brief, brand: BrandKit | None) -> None:
    people = []
    if brand is not None:
        people = [person for person in brand.people if person.consent and person.photos]
    if len(clips) < 2 or not people or not _wants_person(brief, people):
        return
    candidates = [index for index, clip in enumerate(clips) if clip.role in {"hook", "proof"}]
    if len(candidates) < 2:
        candidates = [index for index, clip in enumerate(clips) if clip.role != "selling_point"]
    if len(candidates) < 2:
        return
    role_name = people[0].role
    for index in candidates[:2]:
        clips[index].role = "person"
        clips[index].person_role = role_name
        clips[index].badge_texts = []


def _wants_person(brief: Brief, people: list[object]) -> bool:
    blob = "\n".join([brief.raw_input, brief.goal, brief.video_type, *brief.must_include])
    for person in people:
        role = getattr(person, "role", "")
        if role and role in blob:
            return True
    lowered = blob.lower()
    return any(token in lowered for token in ("口播", "出镜", "interview", "spokesperson"))


def _assign_sizes(clips: list[Clip]) -> list[str]:
    product_index = next(
        (index for index, clip in enumerate(clips) if clip.role == "selling_point"),
        None,
    )
    sizes: list[str] = []
    sell_n = 0
    for index, clip in enumerate(clips):
        first_product = index == product_index
        sizes.append(_preferred_size(clip.role, sell_n, first_product=first_product))
        if clip.role == "selling_point":
            sell_n += 1
    _repair_sizes(sizes, locked=product_index)
    return sizes


def _preferred_size(role: str, sell_n: int, *, first_product: bool) -> str:
    if first_product:
        return "close_up"
    if role == "selling_point":
        return "medium" if sell_n % 2 else "close_up"
    if role in {"person", "spec", "cta"}:
        return "medium"
    return "wide"


def _repair_sizes(sizes: list[str], *, locked: int | None) -> None:
    options = ("wide", "medium", "close_up")
    for _ in range(len(sizes) + 1):
        changed = False
        for index in range(2, len(sizes)):
            if not (sizes[index] == sizes[index - 1] == sizes[index - 2]):
                continue
            changed = True
            choices = [item for item in options if item != sizes[index]]
            if index == locked:
                choices = [item for item in choices if item != "wide"]
            if choices:
                sizes[index] = choices[0]
                continue
            if index - 1 != locked:
                sizes[index - 1] = "close_up" if sizes[index] != "close_up" else "medium"
        if not changed:
            return
    raise PlanError("shot sizes still repeat three times")


def _allocate(duration_s: float, count: int, lo: float, hi: float) -> list[float]:
    total = int(round(duration_s * 1000))
    lo_ms = int(round(lo * 1000))
    hi_ms = int(round(hi * 1000))
    base = total // count
    extra = total - base * count
    parts = [base + (1 if index < extra else 0) for index in range(count)]
    if any(part < lo_ms or part > hi_ms for part in parts):
        raise PlanError("allocated shot length is outside the allowed range")
    return [part / 1000 for part in parts]


def _assign_cameras(
    clips: list[Clip],
    sizes: list[str],
    presets: tuple[ShotPreset, ...],
    hints: StoryboardHint | None,
) -> None:
    by_id = {preset.id: preset for preset in presets}
    hinted: list[str] = []
    if hints is not None and len(hints.shots) == len(clips):
        hinted = [item.camera for item in hints.shots]
    for index, clip in enumerate(clips):
        choice = ""
        if index < len(hinted) and hinted[index] in by_id:
            preset = by_id[hinted[index]]
            if sizes[index] in preset.shot_sizes:
                choice = preset.id
        if not choice:
            choice = match_preset(presets, sizes[index], clip.role).id
        clip.camera_id = choice


def _build_shot(
    index: int,
    clip: Clip,
    size: str,
    duration_s: float,
    brand: BrandKit | None,
    presets: tuple[ShotPreset, ...],
) -> Shot:
    purpose = _PURPOSE[clip.role]
    preset = next(item for item in presets if item.id == clip.camera_id)
    product = brand.products[0] if brand and brand.products else None
    subjects: list[str] = []
    if clip.role == "selling_point" and product is not None:
        subjects.append(_product_ref(product))
    if clip.role == "person" and clip.person_role:
        subjects.append(f"person:{clip.person_role}")
    visual = f"{_VISUAL[clip.role]}{preset.prompt_fragment} {NO_DRAWN}"
    phone = ""
    if clip.role == "cta" and brand is not None:
        phone = brand.cta.phone.strip()
    return Shot(
        shot_id=f"S{index + 1:02d}",
        order=index + 1,
        duration_s=duration_s,
        purpose=purpose,
        visual=visual,
        shot_size=size,
        camera=clip.camera_id,
        subject_refs=subjects,
        scene_ref=_SCENE[clip.role],
        voiceover=clip.voiceover,
        on_screen_text=_badges(clip, duration_s, phone),
        transition_out="cut",
        generation_mode=select_generation_mode(purpose, brand),
        status=ShotStatus.pending,
    )


def _product_ref(product: Product) -> str:
    match = _MODEL_TOKEN.search(product.name)
    token = match.group(0) if match else product.name
    return f"product:{token}"


def _badges(clip: Clip, duration_s: float, phone: str) -> list[OnScreenText]:
    labels: list[tuple[str, str]] = []
    if clip.role in {"selling_point", "spec"}:
        for text in clip.badge_texts:
            label = _badge_label(text)
            if label:
                labels.append((label, "spec_badge"))
    if clip.role == "cta" and phone:
        labels.append((phone, "cta_line"))
    if not labels:
        return []
    margin = min(0.2, duration_s / 10)
    usable = max(duration_s - (2 * margin), 0.0)
    span = usable / len(labels) if labels else duration_s
    badges: list[OnScreenText] = []
    for index, (label, style) in enumerate(labels):
        start = round(margin + index * span, 3)
        end = round(margin + (index + 1) * span, 3)
        if end < start:
            end = start
        if start > duration_s:
            start = duration_s
        if end > duration_s:
            end = duration_s
        if end < start:
            end = start
        badges.append(OnScreenText(text=label, style=style, in_=start, out=end))
    return badges


def _badge_label(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return ""
    if count_units(compact, "zh") <= 16:
        return compact
    match = _NUMBER.search(compact)
    if match is None:
        return ""
    prefix = _tail_units(compact[: match.start()], 4)
    suffix = _head_units(compact[match.end() :], 6)
    return f"{prefix}{match.group(0)}{suffix}".strip()


def _tail_units(text: str, limit: int) -> str:
    kept: list[str] = []
    got = 0
    for ch in reversed(text):
        if count_units(ch, "zh") == 0:
            if kept:
                kept.append(ch)
            continue
        if got >= limit:
            break
        kept.append(ch)
        got += 1
    return "".join(reversed(kept)).strip()


def _head_units(text: str, limit: int) -> str:
    out: list[str] = []
    got = 0
    index = 0
    while index < len(text) and got < limit:
        ch = text[index]
        if ch.isdigit():
            end = index + 1
            while end < len(text) and text[end].isdigit():
                end += 1
            if got + (end - index) > limit:
                break
            out.append(text[index:end])
            got += end - index
            index = end
            continue
        out.append(ch)
        got += count_units(ch, "zh")
        index += 1
    return "".join(out).strip()


def _bind_sections(
    sections: list[ScriptSection],
    shots: list[Shot],
    clips: list[Clip],
) -> list[ScriptSection]:
    bound: list[ScriptSection] = []
    for index, section in enumerate(sections):
        shot_ids = [
            shot.shot_id
            for shot, clip in zip(shots, clips, strict=True)
            if index in clip.section_indexes
        ]
        bound.append(section.model_copy(update={"shot_ids": shot_ids}))
    return bound
