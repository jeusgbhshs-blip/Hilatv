"""N2 brand library. One enterprise kit, reused by later projects.

Run again with the same JSON. Model calls go through the gateway. With no key
the mock image adapter still returns a legal anchor URI and costs nothing.
"""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any

from workers.brand_kit.assemble import BuildInput, PersonIn, ProductIn, build_brand_kit
from workers.brand_kit.matting import ReplaceImageError
from workers.brand_kit.people import ConsentError, people_for_use, persist_people, release_kit
from workers.brand_kit.points import PreferenceError, apply_preference
from workers.brand_kit.store import (
    BrandReadError,
    BrandRecord,
    export_record,
    load_by_brand_id,
    load_record,
    resolve_kit,
    save_record,
)
from workers.logging import log_event
from workers.nodes.n02_brand_kit.qa import QAError, check
from workers.nodes.n02_brand_kit.schema import N2Input, NodeRequest, NodeResult
from workers.schemas.brand import BrandKit, Industry

NODE = "n02_brand_kit"


class Deadline:
    def __init__(self, timeout_s: float) -> None:
        if timeout_s <= 0:
            raise TimeoutError("n02_brand_kit exceeded timeout")
        self._end = time.monotonic() + timeout_s

    def check(self) -> None:
        if time.monotonic() >= self._end:
            raise TimeoutError("n02_brand_kit exceeded timeout")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 60.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N2Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway or _default_gateway()
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = _execute(request, attempt=attempt, timeout_s=timeout_s, gateway=gateway)
            check(result)
        except QAError as exc:
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=request.shot_id,
                attempt=attempt,
                error=str(exc),
            )
            if not exc.retryable:
                raise
            continue
        return result
    raise QAError(f"n02_brand_kit failed after {max_attempts} attempts") from last_error


def _execute(
    request: NodeRequest,
    *,
    attempt: int,
    timeout_s: float,
    gateway: Any,
) -> NodeResult:
    deadline = Deadline(timeout_s)
    payload = N2Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        mode=payload.mode,
    )
    deadline.check()
    try:
        if payload.mode == "build":
            body = _build(payload, gateway, request.project_id, attempt, deadline)
        elif payload.mode == "preference":
            body = _prefer(payload)
        else:
            body = _resolve(payload, request.project_id, attempt)
    except (ReplaceImageError, ConsentError, PreferenceError, BrandReadError) as exc:
        raise QAError(str(exc), retryable=False) from exc
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        mode=payload.mode,
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload=body,
        attempt=attempt,
    )


def _resolve(payload: N2Input, project_id: str, attempt: int) -> dict[str, Any]:
    enterprise_id = _enterprise(payload.enterprise_id) if payload.enterprise_id else None
    if payload.inline is not None or not enterprise_id:
        kit = resolve_kit(
            inline=payload.inline,
            brand_id=payload.brand_id,
            enterprise_id=enterprise_id,
            project_id=project_id,
            attempt=attempt,
        )
        people = (kit or {}).get("people") or []
        return {
            "brand_kit": kit,
            "mono_black": "",
            "anchors": [],
            "usable_people": [item["person_id"] for item in people if isinstance(item, dict)],
        }
    record = load_record(enterprise_id)
    if payload.brand_id:
        record = load_by_brand_id(payload.brand_id, enterprise_id)
    if record is None:
        return {"brand_kit": None, "mono_black": "", "anchors": [], "usable_people": []}
    return export_record(record)


def _build(
    payload: N2Input,
    gateway: Any,
    project_id: str,
    attempt: int,
    deadline: Deadline,
) -> dict[str, Any]:
    if not payload.enterprise_id or not payload.company_name or not payload.industry:
        raise QAError("录入品牌资料需要企业、名称和行业", retryable=False)
    if not payload.logo_b64:
        raise QAError("录入品牌资料需要 Logo", retryable=False)
    deadline.check()
    spec = BuildInput(
        enterprise_id=_enterprise(payload.enterprise_id),
        company_name=payload.company_name,
        industry=Industry(payload.industry),
        logo=_decode(payload.logo_b64, target="logo"),
        products=[
            ProductIn(
                name=item.name,
                photo=_decode(item.photo_b64, target=item.name),
                selling_points=list(item.selling_points),
                source_text=item.source_text,
                forbidden_changes=list(item.forbidden_changes),
            )
            for item in payload.products
        ],
        people=[
            PersonIn(role=item.role, consent=item.consent, voice_id=item.voice_id)
            for item in payload.people
        ],
        tone=payload.tone,
        phone=payload.phone,
        website=payload.website,
        wechat_qr=payload.wechat_qr,
        title_font=payload.title_font,
        body_font=payload.body_font,
        extra_banned_words=list(payload.extra_banned_words),
        project_id=project_id,
        attempt=attempt,
    )
    deadline.check()
    built = build_brand_kit(spec, gateway)
    deadline.check()
    return {
        "brand_kit": built.kit.model_dump(mode="json"),
        "mono_black": built.mono_black,
        "anchors": [item.model_dump(mode="json") for item in built.anchors],
        "usable_people": built.usable_people,
        "anchor_status": built.anchor_status,
    }


def _prefer(payload: N2Input) -> dict[str, Any]:
    if not payload.enterprise_id or payload.preference is None:
        raise QAError("回写偏好需要企业和修改内容", retryable=False)
    enterprise_id = _enterprise(payload.enterprise_id)
    record = load_record(enterprise_id)
    if record is None:
        raise QAError("还没有品牌资料，无法回写偏好", retryable=False)
    kit = BrandKit.model_validate(record.brand_kit)
    updated, change = apply_preference(kit, payload.preference)
    stored = persist_people(updated)
    released = release_kit(stored, trust_consent=True)
    preferences = [*record.preferences, change]
    usable = [person.person_id for person in people_for_use(released)]
    save_record(
        BrandRecord(
            enterprise_id=enterprise_id,
            brand_kit=stored.model_dump(mode="json"),
            mono_black=record.mono_black,
            anchors=record.anchors,
            preferences=preferences,
            usable_people=usable,
        )
    )
    return {
        "brand_kit": released.model_dump(mode="json"),
        "mono_black": record.mono_black,
        "anchors": record.anchors,
        "usable_people": usable,
        "preferences": preferences,
    }


def _enterprise(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise QAError("enterprise_id 需要是 UUID", retryable=False) from exc


def _decode(value: str, *, target: str) -> bytes:
    if len(value) > 8_000_000:
        raise QAError(f"{target} 图片过大。请更换图片", retryable=False)
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise QAError(f"{target} 图片不是合法的 base64。请更换图片", retryable=False) from exc
    if not raw:
        raise QAError(f"{target} 图片是空的。请更换图片", retryable=False)
    return raw


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
