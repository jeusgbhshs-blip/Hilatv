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
from workers.logging import log_event
from workers.nodes.n01_brief.industries import detect_industry, load_industries
from workers.nodes.n03_concept.compose import card_text, compose_directions, pick_structures
from workers.nodes.n03_concept.qa import QAError, check
from workers.nodes.n03_concept.schema import DraftSet, N3Input, NodeRequest, NodeResult
from workers.nodes.n03_concept.similarity import too_similar
from workers.nodes.runtime import read_bytes
from workers.schemas.brand import BrandKit, default_banned_words, find_banned_words

NODE = "n03_concept"
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
            check(result, banned=_banned(payload.brand_kit))
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
    brand = payload.brand_kit
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
    drafted = _draft(
        gateway,
        prompt,
        project_id=request.project_id,
        attempt=attempt,
    )
    cards = _accept_draft(drafted, banned) or compose_directions(
        template, structures, banned=banned
    )
    if too_similar([card_text(card) for card in cards]) or _hits(cards, banned):
        cards = compose_directions(template, structures, banned=banned)
    deadline.check()
    rendered: list[dict[str, Any]] = []
    for index, card in enumerate(cards):
        deadline.check()
        cover_uri, preview = _cover(
            gateway,
            card,
            industry=template.label,
            project_id=request.project_id,
            attempt=attempt,
            index=index,
            phone=brand.cta.phone if brand is not None else "",
        )
        item = dict(card)
        item["cover_uri"] = cover_uri
        item["cover_preview"] = preview
        item["duration_s"] = brief.duration_s
        item["aspect_ratio"] = brief.aspect_ratios[0]
        rendered.append(item)
    concept = _select(rendered, payload.selection, brief)
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
        ok=True,
        payload={"concept": concept, "prompt": prompt},
        attempt=attempt,
    )


def _draft(gateway: Any, prompt: str, *, project_id: str, attempt: int) -> DraftSet:
    try:
        raw = gateway.generate_text(
            prompt,
            schema=DraftSet,
            system=_ENV.get_template("system.j2").render(),
            seed=0,
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


def _accept_draft(draft: DraftSet, banned: list[str]) -> list[dict[str, object]] | None:
    if len(draft.directions) != 3:
        return None
    cards: list[dict[str, object]] = []
    for index, item in enumerate(draft.directions):
        if not all((item.title, item.idea, item.mood, item.estimated_effect, item.structure)):
            return None
        card = {
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
            return None
        cards.append(card)
    if too_similar([card_text(card) for card in cards]):
        return None
    ids = [str(card["direction_id"]) for card in cards]
    if len(set(ids)) != 3:
        return None
    return cards


def _cover(
    gateway: Any,
    card: dict[str, object],
    *,
    industry: str,
    project_id: str,
    attempt: int,
    index: int,
    phone: str,
) -> tuple[str, str]:
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
    result = gateway.generate_image(
        prompt,
        seed=30 + index,
        shot_type="atmosphere",
        project_id=project_id,
        node=NODE,
        shot_id=str(card.get("direction_id") or index),
        attempt=attempt,
    )
    uri = str(result.get("uri") or "")
    if not uri:
        raise QAError("cover image is missing")
    return uri, _preview(gateway, uri, 30 + index)


def _preview(gateway: Any, uri: str, seed: int) -> str:
    loaded = read_bytes(gateway, uri)
    data = loaded[1] if loaded is not None else _flat(seed)
    try:
        image = Image.open(io.BytesIO(data))
        image.thumbnail((160, 160))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        encoded = base64.b64encode(_flat(seed)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _flat(seed: int) -> bytes:
    hue = ((seed * 47) % 360) / 360
    from colorsys import hsv_to_rgb

    red, green, blue = hsv_to_rgb(hue, 0.28, 0.86)
    image = Image.new("RGB", (64, 40), (int(red * 255), int(green * 255), int(blue * 255)))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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


def _hits(cards: list[dict[str, object]], banned: list[str]) -> bool:
    return any(find_banned_words(card_text(card), banned) for card in cards)


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
