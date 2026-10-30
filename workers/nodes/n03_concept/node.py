"""N3 concept cards. Three directions, each with one cover still.

The film path leaves ``selection`` empty and records 「你帮我选」. A caller
that already picked a card passes that direction id. Covers go through the
image gateway and must not ask the model to draw text.
"""

from __future__ import annotations

import base64
import io
import time
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from gateway.constants import NO_RENDERED_TEXT
from workers.brand_kit.media_ready import ready_image_bytes
from workers.brand_kit.people import people_for_use, release_kit, require_consent
from workers.logging import log_event
from workers.nodes.n01_brief.industries import detect_industry, load_industries
from workers.nodes.n03_concept.compose import card_text, compose_directions, pick_structures
from workers.nodes.n03_concept.qa import QAError, check, require_degraded
from workers.nodes.n03_concept.schema import DraftSet, N3Input, NodeRequest, NodeResult
from workers.nodes.n03_concept.similarity import too_similar
from workers.schemas.brand import BrandKit, default_banned_words, find_banned_words

NODE = "n03_concept"
_TEXT_ATTEMPTS = 3
_IMAGE_ATTEMPTS = 2
PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(PROMPTS),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


class Deadline:
    def __init__(self, timeout_s: float) -> None:
        if timeout_s <= 0:
            raise TimeoutError("n03_concept exceeded timeout")
        self._end = time.monotonic() + timeout_s

    def check(self) -> None:
        if time.monotonic() >= self._end:
            raise TimeoutError("n03_concept exceeded timeout")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 60.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    payload = N3Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway or _default_gateway()
    feedback = ""
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = _execute(
                request,
                payload,
                attempt=attempt,
                timeout_s=timeout_s,
                gateway=gateway,
                feedback=feedback,
            )
            if result.ok:
                check(result, banned=_banned(payload.brand_kit))
            else:
                require_degraded(result, banned=_banned(payload.brand_kit))
        except QAError as exc:
            last_error = exc
            feedback = str(exc)
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
    raise QAError(f"n03_concept failed after {max_attempts} attempts") from last_error


def _execute(
    request: NodeRequest,
    payload: N3Input,
    *,
    attempt: int,
    timeout_s: float,
    gateway: Any,
    feedback: str,
) -> NodeResult:
    deadline = Deadline(timeout_s)
    brief = payload.brief
    brand = _trusted_brand(payload.brand_kit)
    banned = _banned(brand)
    industry_id = brand.industry.value if brand is not None else _industry(brief.raw_input)
    template = load_industries()[industry_id]
    structures = pick_structures(template)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        industry=industry_id,
    )
    prompt = _ENV.get_template("directions.j2").render(
        structures="\n".join(
            f"- {item.id} {item.label}: {' / '.join(item.beats)}" for item in structures
        ),
        brief=brief.raw_input,
        tone=brand.tone if brand is not None else brief.style,
        banned="、".join(banned),
        feedback=feedback,
    )
    deadline.check()
    cards, text_source = _draft_until_distinct(
        gateway,
        prompt,
        template=template,
        structures=structures,
        banned=banned,
        project_id=request.project_id,
        attempt=attempt,
        deadline=deadline,
        feedback=feedback,
    )
    deadline.check()
    rendered: list[dict[str, Any]] = []
    covers_ready = True
    for index, card in enumerate(cards):
        deadline.check()
        cover = _cover(
            gateway,
            card,
            industry=template.label,
            project_id=request.project_id,
            attempt=attempt,
            index=index,
            phone=brand.cta.phone if brand is not None else "",
        )
        item = dict(card)
        item.update(cover)
        item["duration_s"] = brief.duration_s
        item["aspect_ratio"] = brief.aspect_ratios[0]
        if item["cover_status"] != "ready":
            covers_ready = False
        rendered.append(item)
    degraded = text_source != "model" or not covers_ready
    concept = _select(rendered, payload.selection, brief)
    concept["degraded"] = degraded
    concept["text_source"] = text_source
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        selection=concept["selection"],
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=not degraded,
        payload={"concept": concept, "prompt": prompt},
        attempt=attempt,
    )


def _trusted_brand(brand: BrandKit | None) -> BrandKit | None:
    if brand is None:
        return None
    released = release_kit(brand, trust_consent=True)
    for person in people_for_use(released):
        require_consent(person)
    return released


def _draft_until_distinct(
    gateway: Any,
    prompt: str,
    *,
    template: Any,
    structures: list[Any],
    banned: list[str],
    project_id: str,
    attempt: int,
    deadline: Deadline,
    feedback: str,
) -> tuple[list[dict[str, object]], str]:
    """Ask again while the draft is similar or unusable. Then mark a template fallback."""

    note = feedback
    for index in range(_TEXT_ATTEMPTS):
        deadline.check()
        drafted = _draft(
            gateway,
            prompt,
            project_id=project_id,
            attempt=attempt,
            seed=index,
            feedback=note,
        )
        cards, reason = _cards_from_draft(drafted, banned)
        if reason == "ok" and cards is not None:
            for card in cards:
                card["source"] = "model"
            return cards, "model"
        note = {
            "similar": "三个方向过于相似，余弦必须低于 0.85，请重写。",
            "banned": "草稿含有禁用词，请重写。",
        }.get(reason, "草稿不可用，请给出三个不同的方向。")
    fallback = compose_directions(template, structures, banned=banned)
    for card in fallback:
        card["source"] = "template_fallback"
    return fallback, "template_fallback"


def _draft(
    gateway: Any,
    prompt: str,
    *,
    project_id: str,
    attempt: int,
    seed: int = 0,
    feedback: str = "",
) -> DraftSet:
    if feedback:
        prompt = f"{prompt}\n上次的问题：{feedback}"
    try:
        raw = gateway.generate_text(
            prompt,
            schema=DraftSet,
            system=_ENV.get_template("system.j2").render(),
            seed=seed,
            project_id=project_id,
            node=NODE,
            shot_id=None,
            attempt=attempt,
        )
        return DraftSet.model_validate(raw)
    except Exception as exc:
        log_event(
            "node_llm_failed",
            project_id=project_id,
            node=NODE,
            shot_id=None,
            attempt=attempt,
            error=str(exc)[:300],
        )
        return DraftSet()


def _cards_from_draft(
    draft: DraftSet,
    banned: list[str],
) -> tuple[list[dict[str, object]] | None, str]:
    if len(draft.directions) != 3:
        return None, "invalid"
    cards: list[dict[str, object]] = []
    for index, item in enumerate(draft.directions):
        if not all((item.title, item.idea, item.mood, item.estimated_effect, item.structure)):
            return None, "invalid"
        card: dict[str, object] = {
            "direction_id": item.direction_id or f"d{index + 1}",
            "title": item.title,
            "idea": item.idea,
            "mood": item.mood,
            "structure": list(item.structure),
            "beats": list(item.structure),
            "style_keywords": list(item.style_keywords),
            "estimated_effect": item.estimated_effect,
            "structure_label": item.title,
        }
        if find_banned_words(card_text(card), banned):
            return None, "banned"
        cards.append(card)
    ids = [str(card["direction_id"]) for card in cards]
    if len(set(ids)) != 3:
        return None, "invalid"
    if too_similar([card_text(card) for card in cards]):
        return cards, "similar"
    return cards, "ok"


def _cover(
    gateway: Any,
    card: dict[str, object],
    *,
    industry: str,
    project_id: str,
    attempt: int,
    index: int,
    phone: str,
) -> dict[str, str]:
    beats = card.get("beats") or []
    lead = str(beats[0]) if beats else str(card.get("title") or "")
    prompt = _ENV.get_template("cover.j2").render(
        industry=industry,
        mood=str(card.get("mood") or ""),
        scene=f"a quiet scene about {lead}, no written characters",
        negative=NO_RENDERED_TEXT,
    )
    if phone and phone in prompt:
        raise QAError("cover prompt contains a phone number", retryable=False)
    if NO_RENDERED_TEXT not in prompt:
        raise QAError("cover prompt is missing the no-text constraint", retryable=False)
    for try_index in range(_IMAGE_ATTEMPTS):
        result = gateway.generate_image(
            prompt,
            seed=30 + index * 10 + try_index,
            shot_type="atmosphere",
            project_id=project_id,
            node=NODE,
            shot_id=str(card.get("direction_id") or index),
            attempt=attempt,
        )
        uri = str(result.get("uri") or "")
        data = ready_image_bytes(gateway, uri)
        if data is None:
            continue
        return {
            "cover_uri": uri,
            "cover_preview": _preview(data),
            "cover_status": "ready",
        }
    return {"cover_uri": "", "cover_preview": "", "cover_status": "not_ready"}


def _preview(data: bytes) -> str:
    image = Image.open(io.BytesIO(data))
    image.load()
    image.thumbnail((160, 160))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _select(cards: list[dict[str, Any]], selection: str | None, brief: Any) -> dict[str, Any]:
    ids = [str(card["direction_id"]) for card in cards]
    if selection and selection != "你帮我选" and selection not in ids:
        raise QAError(f"未知方案 {selection}", retryable=False)
    auto = not selection or selection == "你帮我选"
    chosen_id = ids[0] if auto else selection
    chosen = next(card for card in cards if card["direction_id"] == chosen_id)
    return {
        "selection": "你帮我选" if auto else chosen_id,
        "auto": auto,
        "direction": brief.video_type,
        "title": chosen["title"],
        "duration_s": brief.duration_s,
        "aspect_ratio": brief.aspect_ratios[0],
        "chosen_id": chosen_id,
        "directions": cards,
        "note": "系统自动选定" if auto else "用户选定方案卡",
    }


def _banned(brand: BrandKit | None) -> list[str]:
    if brand is not None and brand.banned_words:
        return list(brand.banned_words)
    return default_banned_words()


def _industry(text: str) -> str:
    return detect_industry(text) or "manufacturing"


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
