"""Merge user text, attachments, the gateway extraction, and an industry template."""

from __future__ import annotations

import re
import uuid

from workers.nodes.n01_brief.attachments import ParsedAttachment
from workers.nodes.n01_brief.industries import (
    IndustryTemplate,
    detect_industry,
    industry_from_name,
    load_industries,
    match_video_type,
    video_from_name,
)
from workers.nodes.n01_brief.platforms import (
    aspects_for_platforms,
    canonical_platform,
    repair_aspects,
)
from workers.nodes.n01_brief.schema import ExtractedBrief
from workers.nodes.n01_brief.signals import (
    AttachmentFacts,
    ParsedText,
    clean_text,
    dedupe,
    goal_from_text,
    merge_facts,
    style_from_keywords,
)
from workers.schemas.base import ASPECT_RATIO_PATTERN, LANGUAGE_PATTERN
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief, ClarifyingQuestion

FACTORY_NOTE = "未提供工厂视频，使用 AI 生成工厂场景"
_LANG_LABELS = {
    "zh": "中文",
    "en": "英文",
    "ja": "日文",
    "ko": "韩文",
    "es": "西班牙文",
    "fr": "法文",
    "de": "德文",
    "ru": "俄文",
}

INDUSTRY_QUESTION = ClarifyingQuestion(
    question="这条视频主要服务哪个行业？",
    recommended="制造业",
    options=["制造业", "外贸出海", "电商零售", "本地生活", "教育培训", "政企公共"],
)
ASPECT_QUESTION = ClarifyingQuestion(
    question="画面比例和投放平台不一致。先按平台推荐的比例出片，还是改回你指定的比例？",
    recommended="按平台推荐比例",
    options=["按平台推荐比例", "按我指定的比例"],
)


def assemble(
    *,
    project_id: str,
    raw_input: str,
    parsed: ParsedText,
    attachments: list[ParsedAttachment],
    brand: BrandKit | None,
    extracted: ExtractedBrief,
) -> Brief:
    facts = merge_facts([item.facts() for item in attachments])
    attachment_text = "\n".join(item.text for item in attachments if item.text)
    evidence = f"{raw_input}\n{attachment_text}"
    assumptions: list[str] = []
    ask_industry = False
    ask_video = False
    ask_aspect = False

    industry = detect_industry(evidence)
    if industry is None and brand is not None:
        industry = brand.industry.value
        label = load_industries()[industry].label
        _add(assumptions, f"未在原话中说明行业，沿用品牌资料库：{label}。")
    if industry is None:
        industry = industry_from_name(extracted.industry)
    if industry is None:
        industry = "manufacturing"
        ask_industry = True
        _add(assumptions, "未能从原话判断行业，先按制造业继续。")

    template = load_industries()[industry]
    video_type = match_video_type(template, evidence)
    video_source = "user" if video_type else ""
    if video_type is None:
        video_type = video_from_name(template, extracted.video_type)
        video_source = "llm" if video_type else ""
    if video_type is None:
        video_type = template.default_video_type
        video_source = "default"
        _add(assumptions, f"未说明视频类型，先按默认「{template.default_video.label}」。")
        if len(template.video_types) > 1:
            ask_video = True

    goal = goal_from_text(raw_input)
    if goal is None and video_source == "user":
        goal = template.video(video_type).goal
    if goal is None:
        goal = clean_text(extracted.goal)
    if goal is None:
        goal = template.video(video_type).goal
        _add(assumptions, f"未说明投放目标，按{template.label}模板使用「{goal}」。")

    duration, duration_source = _duration(parsed, extracted)
    if duration_source == "default":
        duration = template.duration_s
        _add(assumptions, f"未说明时长，按{template.label}模板使用 {duration} 秒。")
    elif duration_source == "short":
        _add(assumptions, f"给出的时长 {parsed.duration_s} 秒短于 5 秒，已调整为 5 秒。")
        duration = 5
    elif duration_source == "long":
        _add(assumptions, f"给出的时长 {parsed.duration_s} 秒超过 180 秒，已调整为 180 秒。")
        duration = 180

    platforms, platform_source = _platforms(parsed, extracted, template.platforms)
    if platform_source == "default":
        shown = "、".join(platforms)
        _add(assumptions, f"未说明投放平台，按{template.label}模板使用{shown}。")

    aspects, aspect_note, ask_aspect = _aspects(
        parsed,
        extracted,
        platforms,
        platform_source,
        template.aspect_ratios,
        template.label,
    )
    if aspect_note:
        _add(assumptions, aspect_note)

    languages = parsed.languages or _clean_languages(extracted.languages)
    if not languages:
        languages = list(template.languages)
        shown = "、".join(f"{_LANG_LABELS.get(code, code)}（{code}）" for code in languages)
        _add(assumptions, f"未说明语种，按{template.label}模板使用{shown}。")

    audience = parsed.audience or clean_text(extracted.audience)
    if not audience:
        audience = template.audience
        _add(assumptions, f"未说明受众，按{template.label}模板使用「{audience}」。")

    style = parsed.style or style_from_keywords(raw_input, template.style_keywords)
    if not style:
        style = clean_text(extracted.style)
    if not style:
        style = template.style_default
        _add(assumptions, f"未说明风格，按{template.label}模板使用「{style}」。")

    must_include, must_notes = _must_include(
        parsed,
        facts,
        brand,
        extracted,
        evidence,
        template.must_include,
        template.label,
    )
    for note in must_notes:
        _add(assumptions, note)

    for item in attachments:
        if item.error:
            _add(assumptions, f"附件抓取失败，已忽略：{item.uri}。")
    if facts.products:
        _add(assumptions, f"从附件识别产品：{'、'.join(facts.products)}。")
    if industry in {"manufacturing", "foreign_trade"} and not _has_factory_video(attachments):
        _add(assumptions, FACTORY_NOTE)
    classes = _image_classes(attachments)
    if "logo" in classes:
        _add(assumptions, "检测到 Logo 素材，只在后期叠加，不交给图像或视频模型绘制。")
    if "person" in classes:
        _add(assumptions, "检测到人物素材，出镜前需已有肖像授权。")

    questions: list[ClarifyingQuestion] = []
    if ask_industry:
        questions.append(INDUSTRY_QUESTION)
    if ask_aspect:
        questions.append(ASPECT_QUESTION)
    if ask_video:
        questions.append(_video_question(template.clarify_question, template))
    questions = questions[:2]

    return Brief(
        brief_id=_brief_id(project_id, raw_input),
        raw_input=raw_input,
        goal=goal,
        platform=platforms,
        duration_s=duration,
        aspect_ratios=aspects,
        languages=languages,
        video_type=video_type,
        audience=audience,
        must_include=must_include,
        style=style,
        assumptions=assumptions,
        open_questions=questions,
    )


def _duration(parsed: ParsedText, extracted: ExtractedBrief) -> tuple[int, str]:
    if parsed.duration_s is None:
        if extracted.duration_s is not None and 1 <= extracted.duration_s <= 600:
            value = extracted.duration_s
            if value < 5:
                return 5, "llm-short"
            if value > 180:
                return 180, "llm-long"
            return value, "llm"
        return 0, "default"
    if parsed.duration_s < 5:
        return 5, "short"
    if parsed.duration_s > 180:
        return 180, "long"
    return parsed.duration_s, "user"


def _platforms(
    parsed: ParsedText,
    extracted: ExtractedBrief,
    defaults: list[str],
) -> tuple[list[str], str]:
    if parsed.platforms:
        return list(parsed.platforms), "user"
    from_model = dedupe(
        name for name in (canonical_platform(item) or "" for item in extracted.platform) if name
    )
    if from_model:
        return from_model, "llm"
    return list(defaults), "default"


def _aspects(
    parsed: ParsedText,
    extracted: ExtractedBrief,
    platforms: list[str],
    platform_source: str,
    template_aspects: list[str],
    industry_label: str,
) -> tuple[list[str], str, bool]:
    if parsed.aspects:
        repaired = repair_aspects(platforms, parsed.aspects)
        if repaired != parsed.aspects:
            return repaired, f"平台与画面比例不一致，已补齐为 {'、'.join(repaired)}。", True
        return repaired, "", False
    from_model = _clean_aspects(extracted.aspect_ratios)
    if from_model:
        repaired = repair_aspects(platforms, from_model)
        if repaired != from_model:
            return repaired, f"平台与画面比例不一致，已补齐为 {'、'.join(repaired)}。", False
        return repaired, "", False
    if platform_source == "default":
        repaired = repair_aspects(platforms, template_aspects)
        note = f"未说明画面比例，按{industry_label}模板使用 {'、'.join(repaired)}。"
        return repaired, note, False
    derived = aspects_for_platforms(platforms)
    return derived, f"未说明画面比例，按投放平台补齐 {'、'.join(derived)}。", False


def _must_include(
    parsed: ParsedText,
    facts: AttachmentFacts,
    brand: BrandKit | None,
    extracted: ExtractedBrief,
    evidence: str,
    defaults: list[str],
    industry_label: str,
) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    items = dedupe([*parsed.must_include, *facts.selling_points, *facts.specs])
    if facts.selling_points or facts.specs:
        shown = dedupe([*facts.selling_points, *facts.specs])
        notes.append(f"从附件提取卖点与参数：{'、'.join(shown)}。")
    if not parsed.must_include:
        points, names = _brand_points(brand, evidence)
        if points:
            items = dedupe([*items, *points])
            notes.append(f"必含卖点来自品牌资料库「{'、'.join(names)}」。")
    if not items:
        items = dedupe(clean_text(item) or "" for item in extracted.must_include)
        items = [item for item in items if item]
    if not items:
        items = list(defaults)
        notes.append(f"未说明必含信息，按{industry_label}模板放入：{'、'.join(items)}。")
    return items, notes


def _brand_points(brand: BrandKit | None, evidence: str) -> tuple[list[str], list[str]]:
    if brand is None or not brand.products:
        return [], []
    chosen = [item for item in brand.products if item.name and item.name in evidence]
    if not chosen and len(brand.products) == 1:
        chosen = list(brand.products)
    points: list[str] = []
    names: list[str] = []
    for product in chosen:
        names.append(product.name)
        points.extend(product.selling_points)
    return dedupe(points), dedupe(names)


def _video_question(question: str, template: IndustryTemplate) -> ClarifyingQuestion:
    labels = [item.label for item in template.video_types]
    recommended = template.default_video.label
    return ClarifyingQuestion(
        question=question,
        recommended=recommended,
        options=labels,
    )


def _clean_languages(values: list[str]) -> list[str]:
    kept: list[str] = []
    for value in values:
        text = value.strip()
        if re.fullmatch(LANGUAGE_PATTERN, text) and text not in kept:
            kept.append(text)
    return kept


def _clean_aspects(values: list[str]) -> list[str]:
    kept: list[str] = []
    for value in values:
        if re.fullmatch(ASPECT_RATIO_PATTERN, value) and value not in kept:
            kept.append(value)
    return kept


def _image_classes(attachments: list[ParsedAttachment]) -> set[str]:
    found: set[str] = set()
    for item in attachments:
        if item.image_class:
            found.add(item.image_class)
        for image in item.images:
            kind = image.get("image_class")
            if isinstance(kind, str):
                found.add(kind)
    return found


def _has_factory_video(attachments: list[ParsedAttachment]) -> bool:
    for item in attachments:
        blob = f"{item.kind} {item.uri} {item.filename}"
        if "工厂视频" in blob or "factory-video" in blob.lower():
            return True
    return False


def _brief_id(project_id: str, raw_input: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hilatv:{project_id}:{raw_input}"))


def _add(items: list[str], text: str) -> None:
    if text and text not in items:
        items.append(text)
