"""Pull facts the user actually wrote. Missing fields stay empty for the template."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from workers.nodes.n01_brief.platforms import find_aspects, find_platforms

_SENTINELS = {"", "mock", "string", "none", "null", "n/a", "xxx"}
_SPEC_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:万小时|MPa|kPa|GPa|kW|mm|cm|kg|g|小时|吨|转|rpm)",
    re.IGNORECASE,
)
_INCLUDE_RE = re.compile(r"(?:一定要带上|一定要|必须包含|必须带上|带上|突出)\s*([^，。；\n]+)")
_ADDRESS_RE = re.compile(r"地址(?:在|是|为|：|:)\s*([^，。；\n]{2,40})")
_TAIL_RE = re.compile(r"([^，。；\n]{2,30}放片尾)")
_STYLE_RE = re.compile(r"风格(?:是|为|：|:)?\s*([^，。；\n]{2,40})")
_AUDIENCE_RE = re.compile(r"面向([^，。；\n]{2,30})")
_MINUTE_RE = re.compile(r"(\d+)\s*分钟")
_SECOND_RE = re.compile(r"(\d+)\s*(?:秒|seconds?\b|secs?\b|s\b)", re.IGNORECASE)
_PRODUCT_RE = re.compile(
    r"(?:产品名称|产品名|品名|Product)\s*[：:]\s*([^\n，。；]+)",
    re.IGNORECASE,
)
_POINT_RE = re.compile(
    r"(?:卖点|优势|Selling point)\s*[：:]\s*([^\n，。；]+)",
    re.IGNORECASE,
)

_LANG_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("zh", ("中文", "汉语", "国语", "普通话", "chinese")),
    ("en", ("英文", "英语", "english")),
    ("ja", ("日文", "日语", "japanese")),
    ("ko", ("韩文", "韩语", "korean")),
    (
        "es",
        (
            "西班牙文",
            "西班牙语",
        ),
    ),
    (
        "fr",
        (
            "法文",
            "法语",
        ),
    ),
    (
        "de",
        (
            "德文",
            "德语",
        ),
    ),
    (
        "ru",
        (
            "俄文",
            "俄语",
        ),
    ),
    ("ar", ("阿拉伯语",)),
    ("pt", ("葡萄牙语",)),
    ("th", ("泰语",)),
    ("vi", ("越南语",)),
)


@dataclass
class ParsedText:
    platforms: list[str] = field(default_factory=list)
    duration_s: int | None = None
    aspects: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    audience: str | None = None
    style: str | None = None
    must_include: list[str] = field(default_factory=list)


@dataclass
class AttachmentFacts:
    products: list[str] = field(default_factory=list)
    selling_points: list[str] = field(default_factory=list)
    specs: list[str] = field(default_factory=list)
    text: str = ""


def parse_text(text: str) -> ParsedText:
    return ParsedText(
        platforms=find_platforms(text),
        duration_s=duration_from_text(text),
        aspects=find_aspects(text),
        languages=languages_from_text(text),
        audience=_first_group(_AUDIENCE_RE, text),
        style=_first_group(_STYLE_RE, text),
        must_include=includes_from_text(text),
    )


def extract_facts(text: str) -> AttachmentFacts:
    products = [_clean_fact(item) for item in _PRODUCT_RE.findall(text)]
    points = [_clean_fact(item) for item in _POINT_RE.findall(text)]
    specs = [_clean_fact(item) for item in _SPEC_RE.findall(text)]
    return AttachmentFacts(
        products=dedupe([item for item in products if item]),
        selling_points=dedupe([item for item in points if item]),
        specs=dedupe([item for item in specs if item]),
        text=text.strip(),
    )


def merge_facts(items: list[AttachmentFacts]) -> AttachmentFacts:
    merged = AttachmentFacts()
    for item in items:
        merged.products.extend(item.products)
        merged.selling_points.extend(item.selling_points)
        merged.specs.extend(item.specs)
        if item.text:
            merged.text = f"{merged.text}\n{item.text}".strip()
    merged.products = dedupe(merged.products)
    merged.selling_points = dedupe(merged.selling_points)
    merged.specs = dedupe(merged.specs)
    return merged


def duration_from_text(text: str) -> int | None:
    if "半分钟" in text:
        return 30
    minute = _MINUTE_RE.search(text)
    if minute:
        return int(minute.group(1)) * 60
    second = _SECOND_RE.search(text)
    if second:
        return int(second.group(1))
    return None


def languages_from_text(text: str) -> list[str]:
    if "中英" in text or "双语" in text:
        return ["zh", "en"]
    lowered = text.lower()
    hits: list[tuple[int, str]] = []
    for code, aliases in _LANG_ALIASES:
        positions = [lowered.find(alias.lower()) for alias in aliases]
        positions = [pos for pos in positions if pos >= 0]
        if positions:
            hits.append((min(positions), code))
    hits.sort()
    return dedupe(code for _, code in hits)


def goal_from_text(text: str) -> str | None:
    if "政策解读" in text or "政策" in text:
        return "政策解读"
    if "招商" in text:
        return "招商宣传"
    if any(token in text for token in ("带货", "下单", "促销")):
        return "带货转化"
    if any(token in text for token in ("探店", "到店")):
        return "到店引流"
    if any(token in text for token in ("招生", "报名")):
        return "课程获客"
    if "知识讲解" in text:
        return "知识讲解"
    if any(token in text for token in ("外贸", "出海", "出口")):
        return "外贸获客"
    return None


def style_from_keywords(text: str, keywords: list[str]) -> str | None:
    found = [keyword for keyword in keywords if keyword and keyword in text]
    if not found:
        return None
    return "、".join(found)


def includes_from_text(text: str) -> list[str]:
    items: list[str] = []
    for phrase in _INCLUDE_RE.findall(text):
        for part in re.split(r"和|与|、|以及", phrase):
            cleaned = part.strip()
            if cleaned:
                items.append(cleaned)
    for place in _ADDRESS_RE.findall(text):
        items.append(f"地址：{place.strip()}")
    for tail in _TAIL_RE.findall(text):
        items.append(tail.strip())
    items.extend(match.group(0).strip() for match in _SPEC_RE.finditer(text))
    return dedupe(items)


def clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower() in _SENTINELS:
        return None
    return text


def dedupe(items: object) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:  # type: ignore[union-attr]
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None


def _clean_fact(value: str) -> str:
    return value.strip(" ：:;；，,。")
