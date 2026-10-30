"""Brand Kit admin and N3 concept cards. Neither route starts a film."""

from __future__ import annotations

import base64
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

from workers.brand_kit.store import export_record, load_record, read_asset
from workers.nodes.n01_brief.node import run as run_brief
from workers.nodes.n02_brand_kit.node import run as run_brand
from workers.nodes.n02_brand_kit.qa import QAError as BrandQAError
from workers.nodes.n02_brand_kit.schema import PersonIntake, ProductIntake
from workers.nodes.n03_concept.node import run as run_concept
from workers.nodes.n03_concept.qa import QAError as ConceptQAError
from workers.schemas.brand import Industry

# TODO(auth): enterprise_id is client-supplied and unauthenticated.
# Global authentication is out of scope for T15. The auth task must bind
# enterprise_id to the signed-in member before these routes are exposed.

_MAX_B64_CHARS = 8_000_000

router = APIRouter()


def _cap_b64(value: str) -> str:
    if len(value) > _MAX_B64_CHARS:
        raise ValueError("图片过大")
    return value


class ProductBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    photo_b64: str = Field(min_length=1)
    selling_points: list[str] = Field(default_factory=list)
    source_text: str = ""
    forbidden_changes: list[str] = Field(default_factory=list)

    @field_validator("photo_b64")
    @classmethod
    def photo_is_bounded(cls, value: str) -> str:
        return _cap_b64(value)


class PersonBody(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    consent: bool = False
    voice_id: str | None = None


class BrandBody(BaseModel):
    enterprise_id: str
    company_name: str = Field(min_length=1, max_length=80)
    industry: str
    logo_b64: str = Field(min_length=1)
    products: list[ProductBody] = Field(default_factory=list)
    people: list[PersonBody] = Field(default_factory=list)
    tone: str = "专业、可靠、不夸张"
    phone: str = ""
    website: str = ""
    wechat_qr: str = ""
    title_font: str = "NotoSansSC-Bold"
    body_font: str = "NotoSansSC-Regular"
    extra_banned_words: list[str] = Field(default_factory=list)

    @field_validator("logo_b64")
    @classmethod
    def logo_is_bounded(cls, value: str) -> str:
        return _cap_b64(value)


class ReplacementBody(BaseModel):
    old: str = Field(min_length=1)
    new: str = Field(min_length=1)


class PreferenceBody(BaseModel):
    product_name: str | None = None
    replacements: list[ReplacementBody] = Field(default_factory=list)
    drop_lines: list[str] = Field(default_factory=list)


class ConceptBody(BaseModel):
    sentence: str = Field(min_length=1, max_length=4000)
    enterprise_id: str | None = None
    selection: str | None = Field(default=None, max_length=80)


def _enterprise(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="enterprise_id 需要是 UUID") from exc


def _public(payload: dict[str, Any], enterprise_id: str) -> dict[str, Any]:
    kit = payload.get("brand_kit") or {}
    logo = ((kit.get("logo") or {}).get("primary")) if isinstance(kit, dict) else None
    return {
        "enterprise_id": enterprise_id,
        "brand_kit": kit,
        "mono_black": payload.get("mono_black") or "",
        "anchors": payload.get("anchors") or [],
        "usable_people": payload.get("usable_people") or [],
        "preferences": payload.get("preferences") or [],
        "previews": {
            "logo": _data_url(logo, enterprise_id) if isinstance(logo, str) else "",
            "mono_white": _data_url((kit.get("logo") or {}).get("mono_white"), enterprise_id)
            if isinstance(kit, dict)
            else "",
            "mono_black": _data_url(payload.get("mono_black"), enterprise_id)
            if isinstance(payload.get("mono_black"), str)
            else "",
        },
    }


def _data_url(uri: str | None, enterprise_id: str) -> str:
    if not uri or not uri.startswith("brand://"):
        return ""
    data = read_asset(uri, enterprise_id=enterprise_id)
    if not data:
        return ""
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _intake(model: type[BaseModel], item: BaseModel) -> dict[str, Any]:
    return model.model_validate(item.model_dump()).model_dump()


def _run_brand(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = run_brand(
            {"project_id": "brand-admin", "payload": payload},
            timeout_s=60,
            max_attempts=1,
        )
    except (BrandQAError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.payload


@router.post("/v1/brands")
def save_brand(body: BrandBody) -> dict[str, Any]:
    enterprise_id = _enterprise(body.enterprise_id)
    try:
        Industry(body.industry)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="未知行业") from exc
    payload = _run_brand(
        {
            "mode": "build",
            "enterprise_id": enterprise_id,
            "company_name": body.company_name,
            "industry": body.industry,
            "logo_b64": body.logo_b64,
            "products": [_intake(ProductIntake, item) for item in body.products],
            "people": [_intake(PersonIntake, item) for item in body.people],
            "tone": body.tone,
            "phone": body.phone,
            "website": body.website,
            "wechat_qr": body.wechat_qr,
            "title_font": body.title_font,
            "body_font": body.body_font,
            "extra_banned_words": body.extra_banned_words,
        }
    )
    return _public(payload, enterprise_id)


@router.get("/v1/brands/{enterprise_id}")
def read_brand(enterprise_id: str) -> dict[str, Any]:
    enterprise_id = _enterprise(enterprise_id)
    record = load_record(enterprise_id)
    if record is None:
        raise HTTPException(status_code=404, detail="还没有品牌资料")
    exported = export_record(record)
    return _public(exported, enterprise_id)


@router.patch("/v1/brands/{enterprise_id}/preferences")
def write_preference(enterprise_id: str, body: PreferenceBody) -> dict[str, Any]:
    enterprise_id = _enterprise(enterprise_id)
    payload = _run_brand(
        {
            "mode": "preference",
            "enterprise_id": enterprise_id,
            "preference": body.model_dump(),
        }
    )
    return _public(payload, enterprise_id)


@router.post("/v1/concepts")
def create_concepts(body: ConceptBody) -> dict[str, Any]:
    enterprise_id = _enterprise(body.enterprise_id) if body.enterprise_id else None
    brand = None
    if enterprise_id:
        record = load_record(enterprise_id)
        brand = export_record(record)["brand_kit"] if record else None
    try:
        brief = run_brief(
            {
                "project_id": "concept-preview",
                "payload": {"raw_input": body.sentence, "brand_kit": brand},
            },
            timeout_s=30,
            max_attempts=1,
        )
        result = run_concept(
            {
                "project_id": "concept-preview",
                "payload": {
                    "brief": brief.payload["brief"],
                    "brand_kit": brand,
                    "selection": body.selection,
                },
            },
            timeout_s=60,
            max_attempts=1,
        )
    except (ConceptQAError, BrandQAError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    concept = result.payload["concept"]
    return {
        "concept": concept,
        "brand_applied": brand is not None,
        "enterprise_id": enterprise_id,
    }
