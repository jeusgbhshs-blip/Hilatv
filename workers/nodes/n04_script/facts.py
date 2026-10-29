"""Pull only facts the script is allowed to say."""

from __future__ import annotations

from dataclasses import dataclass

from workers.nodes.n04_script.schema import N4Input
from workers.qa.copycheck import (
    allowed_numbers,
    banned_for,
    count_units,
    invented_numbers,
    normalize_phrase,
    source_corpus,
    strip_banned,
)
from workers.schemas.brand import BrandKit, Person, Product
from workers.schemas.brief import Brief

_PROOF_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("factory", ("工厂实拍", "工厂", "车间", "产线", "实拍")),
    ("cert", ("认证", "资质", "证书")),
    ("inspection", ("检测", "质检", "试验")),
    ("customer", ("客户", "案例", "出口")),
)


@dataclass(frozen=True)
class SourceFacts:
    company: str
    product_name: str
    product: Product | None
    points: list[str]
    proof: str
    proof_key: str
    phone: str
    website: str
    banned: list[str]
    allowed: set[str]
    people: list[Person]
    corpus: str
    point_sources: list[str]


def collect_facts(brief: Brief, brand: BrandKit | None) -> SourceFacts:
    banned = banned_for(brand)
    corpus = source_corpus(brief, brand)
    allowed = allowed_numbers(brief, brand)
    product = brand.products[0] if brand and brand.products else None
    company = _clean(brand.company_name, banned, allowed) if brand else ""
    product_name = _clean(product.name, banned, allowed) if product else ""
    points = _points(brief, brand, banned, allowed)
    proof, proof_key = _proof(corpus, banned, allowed)
    phone = ""
    website = ""
    if brand is not None:
        phone = _clean(brand.cta.phone, banned, allowed)
        website = _clean(brand.cta.website, banned, allowed)
    people = []
    if brand is not None:
        people = [person for person in brand.people if person.consent and person.photos]
    sources = _point_sources(brief, brand)
    return SourceFacts(
        company=company,
        product_name=product_name,
        product=product,
        points=points,
        proof=proof,
        proof_key=proof_key,
        phone=phone,
        website=website,
        banned=banned,
        allowed=allowed,
        people=people,
        corpus=corpus,
        point_sources=sources,
    )


def collect_input(payload: N4Input) -> SourceFacts:
    return collect_facts(payload.brief, payload.brand_kit)


def _points(
    brief: Brief,
    brand: BrandKit | None,
    banned: list[str],
    allowed: set[str],
) -> list[str]:
    raw: list[str] = []
    if brand is not None:
        for product in brand.products:
            raw.extend(product.selling_points)
    raw.extend(brief.must_include)
    points: list[str] = []
    seen: set[str] = set()
    for item in raw:
        cleaned = _clean(item, banned, allowed)
        if not cleaned or cleaned in seen or _already_covered(cleaned, seen):
            continue
        if _looks_like_proof_only(cleaned) and any(cue in cleaned for cue in ("工厂", "认证")):
            continue
        seen.add(cleaned)
        points.append(cleaned)
        if len(points) == 3:
            break
    if not points and product_name_from(brand):
        name = _clean(product_name_from(brand), banned, allowed)
        if name:
            points.append(name)
    return points


def product_name_from(brand: BrandKit | None) -> str:
    if brand is None or not brand.products:
        return ""
    return brand.products[0].name


def _proof(corpus: str, banned: list[str], allowed: set[str]) -> tuple[str, str]:
    for key, cues in _PROOF_CUES:
        for cue in cues:
            if cue in corpus:
                phrase = _clean(cue, banned, allowed)
                short = count_units(phrase, "zh") <= 12
                if phrase and short and not invented_numbers(phrase, allowed):
                    return phrase, key
    return "按资料说明", "none"


def _point_sources(brief: Brief, brand: BrandKit | None) -> list[str]:
    sources = [brief.raw_input, *brief.must_include]
    if brand is not None:
        sources.append(brand.company_name)
        for product in brand.products:
            sources.append(product.name)
            sources.extend(product.selling_points)
    return [item for item in sources if item]


def _already_covered(text: str, seen: set[str]) -> bool:
    needle = normalize_phrase(text)
    if len(needle) < 2:
        return False
    for item in seen:
        hay = normalize_phrase(item)
        if needle == hay or needle in hay or hay in needle:
            return True
    return False


def _looks_like_proof_only(text: str) -> bool:
    return "实拍" in text or text in {"工厂", "认证", "检测", "客户"}


def _clean(text: str, banned: list[str], allowed: set[str]) -> str:
    cleaned = strip_banned(text or "", banned)
    for token in invented_numbers(cleaned, allowed):
        cleaned = cleaned.replace(token, "")
    return " ".join(cleaned.split()).strip(" ，。,.;；")
