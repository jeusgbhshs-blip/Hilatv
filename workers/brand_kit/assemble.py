"""Build one chapter 5 Brand Kit from logo, products, and people.

Image and text models are reached only through the gateway object the caller
passes in. Anchor frames stay out of ``photos`` and ``cutouts``.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from workers.brand_kit.angles import AnchorRef, complete_angles
from workers.brand_kit.colors import extract_colors
from workers.brand_kit.matting import (
    ReplaceImageError,
    matte,
    mono_plate,
    reencode_image,
    with_safe_margin,
)
from workers.brand_kit.people import (
    ConsentError,
    check_voice,
    people_for_use,
    persist_people,
    release_kit,
)
from workers.brand_kit.points import extract_selling_points
from workers.brand_kit.store import BrandRecord, save_record, write_asset
from workers.schemas.brand import (
    BrandFonts,
    BrandKit,
    BrandVoice,
    CallToAction,
    Industry,
    LogoAsset,
    Person,
    Product,
    default_banned_words,
)


class ProductIn(BaseModel):
    name: str = Field(min_length=1)
    photo: bytes
    selling_points: list[str] = Field(default_factory=list)
    source_text: str = ""
    forbidden_changes: list[str] = Field(default_factory=list)


class PersonIn(BaseModel):
    role: str = Field(min_length=1)
    consent: bool
    voice_id: str | None = None
    photos: list[str] = Field(default_factory=list)


class BuildInput(BaseModel):
    enterprise_id: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    industry: Industry
    logo: bytes
    products: list[ProductIn] = Field(default_factory=list)
    people: list[PersonIn] = Field(default_factory=list)
    tone: str = "专业、可靠、不夸张"
    phone: str = ""
    website: str = ""
    wechat_qr: str = ""
    title_font: str = "NotoSansSC-Bold"
    body_font: str = "NotoSansSC-Regular"
    extra_banned_words: list[str] = Field(default_factory=list)
    project_id: str = "brand"
    attempt: int = 1

    model_config = {"arbitrary_types_allowed": True}


class BuildOutput(BaseModel):
    kit: BrandKit
    mono_black: str
    anchors: list[AnchorRef]
    usable_people: list[str]
    anchor_status: str = "not_ready"
    model_config = {"arbitrary_types_allowed": True}


def build_brand_kit(spec: BuildInput, gateway: Any) -> BuildOutput:
    """Matte, color, consent-check, and persist. Raises when a picture should be replaced."""

    names = [item.name for item in spec.products]
    if len(names) != len(set(names)):
        raise ReplaceImageError("产品名称重复", target="product")
    brand_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"hilatv:brand:{spec.enterprise_id}"))
    logo = _cut(spec.logo, target="logo")
    logo_png, ratio = with_safe_margin(logo.png)
    white = mono_plate(logo_png, rgb=(255, 255, 255))
    black = mono_plate(logo_png, rgb=(0, 0, 0))
    logo_uri = write_asset(spec.enterprise_id, "logo.png", logo_png)
    white_uri = write_asset(spec.enterprise_id, "logo-white.png", white)
    black_uri = write_asset(spec.enterprise_id, "logo-black.png", black)
    colors = extract_colors(logo_png)
    banned = default_banned_words()
    for word in spec.extra_banned_words:
        if word and word not in banned:
            banned.append(word)
    products: list[Product] = []
    anchors: list[AnchorRef] = []
    for item in spec.products:
        product_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"hilatv:product:{brand_id}:{item.name}"))
        cut = _cut(item.photo, target=item.name)
        photo_uri = write_asset(
            spec.enterprise_id,
            f"{product_id}-photo.png",
            reencode_image(item.photo),
        )
        cut_uri = write_asset(spec.enterprise_id, f"{product_id}-cutout.png", cut.png)
        points = extract_selling_points(
            manual=item.selling_points,
            source_text=item.source_text,
            banned=banned,
            gateway=gateway,
            project_id=spec.project_id,
            attempt=spec.attempt,
        )
        products.append(
            Product(
                product_id=product_id,
                name=item.name,
                photos=[photo_uri],
                cutouts=[cut_uri],
                selling_points=points,
                forbidden_changes=list(item.forbidden_changes),
            )
        )
        anchors.extend(
            complete_angles(
                gateway,
                product_name=item.name,
                project_id=spec.project_id,
                attempt=spec.attempt,
                product_id=product_id,
            )
        )
    people = [_person(brand_id, item) for item in spec.people]
    kit = BrandKit(
        brand_id=brand_id,
        company_name=spec.company_name,
        industry=spec.industry,
        logo=LogoAsset(primary=logo_uri, mono_white=white_uri, safe_area_ratio=ratio),
        colors=colors,
        fonts=BrandFonts(title=spec.title_font, body=spec.body_font),
        products=products,
        people=people,
        voice=BrandVoice(tts_voice="zh_male_steady", speed=1.0),
        tone=spec.tone,
        banned_words=banned,
        cta=CallToAction(phone=spec.phone, website=spec.website, wechat_qr=spec.wechat_qr),
    )
    stored = persist_people(kit)
    released = release_kit(stored, trust_consent=True)
    allowed = [person.person_id for person in people_for_use(released)]
    on_screen = {uri for product in kit.products for uri in [*product.photos, *product.cutouts]}
    ready = [item for item in anchors if not item.on_screen and item.uri not in on_screen]
    if len(ready) != len(anchors):
        raise RuntimeError("anchor frame leaked onto a screen asset")
    save_record(
        BrandRecord(
            enterprise_id=spec.enterprise_id,
            brand_kit=stored.model_dump(mode="json"),
            mono_black=black_uri,
            anchors=[item.model_dump(mode="json") for item in ready],
            preferences=[],
            usable_people=allowed,
        )
    )
    status = "ready" if not spec.products or ready else "not_ready"
    return BuildOutput(
        kit=released,
        mono_black=black_uri,
        anchors=ready,
        usable_people=allowed,
        anchor_status=status,
    )


def _cut(image: bytes, *, target: str):
    try:
        cut = matte(image)
    except ReplaceImageError as exc:
        raise ReplaceImageError(str(exc), target=target) from exc
    if not cut.edge.ok:
        raise ReplaceImageError(cut.edge.message, target=target)
    return cut


def _person(brand_id: str, item: PersonIn) -> Person:
    person = Person(
        person_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"hilatv:person:{brand_id}:{item.role}")),
        role=item.role,
        photos=list(item.photos),
        consent=item.consent,
        voice_id=item.voice_id,
    )
    try:
        check_voice(person)
    except ConsentError:
        raise
    return person
