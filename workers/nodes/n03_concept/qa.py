"""N3 quality: three directions, cosine under 0.85, no banned words."""

from __future__ import annotations

from workers.nodes.n03_concept.compose import card_text
from workers.nodes.n03_concept.schema import NodeResult
from workers.nodes.n03_concept.similarity import cosine
from workers.schemas.brand import default_banned_words, find_banned_words
from workers.schemas.generation import generation_settings


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult, *, banned: list[str] | None = None) -> dict:
    """A pass needs model copy, distinct cards, and readable covers. mock:// does not pass."""

    if result.node != "n03_concept" or not result.ok:
        raise QAError("n03_concept result is not ok")
    concept = _concept(result)
    if concept.get("degraded") is True or concept.get("text_source") != "model":
        raise QAError("degraded concept cannot pass")
    texts = _texts(concept["directions"], banned, require_ready=True)
    _distinct(texts)
    _selection(concept)
    return concept


def require_degraded(result: NodeResult, *, banned: list[str] | None = None) -> dict:
    """A fallback is allowed only when it is explicitly marked and does not claim a ready cover."""

    if result.ok:
        raise QAError("degraded result is marked ok")
    concept = _concept(result)
    if concept.get("degraded") is not True:
        raise QAError("fallback is missing the degraded marker", retryable=False)
    directions = concept["directions"]
    if concept.get("text_source") == "template_fallback":
        if any(item.get("source") != "template_fallback" for item in directions):
            raise QAError("template fallback is not marked on every card", retryable=False)
    elif concept.get("text_source") != "model":
        raise QAError("concept source is missing", retryable=False)
    _texts(directions, banned, require_ready=False)
    _distinct([card_text(item) for item in directions])
    _selection(concept)
    return concept


def _concept(result: NodeResult) -> dict:
    if result.node != "n03_concept":
        raise QAError(f"unexpected node {result.node}")
    concept = result.payload.get("concept")
    if not isinstance(concept, dict):
        raise QAError("concept is missing")
    directions = concept.get("directions")
    if not isinstance(directions, list) or len(directions) != 3:
        raise QAError("concept needs exactly 3 directions")
    return concept


def _texts(directions: list, banned: list[str] | None, *, require_ready: bool) -> list[str]:
    words = banned if banned is not None else default_banned_words()
    texts: list[str] = []
    for item in directions:
        if not isinstance(item, dict):
            raise QAError("direction must be an object")
        for key in ("direction_id", "title", "idea", "mood", "estimated_effect", "source"):
            if not str(item.get(key) or "").strip():
                raise QAError(f"direction is missing {key}")
        if item.get("source") not in {"model", "template_fallback"}:
            raise QAError("direction source is unknown")
        if not item.get("structure"):
            raise QAError("direction is missing structure")
        status = item.get("cover_status")
        uri = str(item.get("cover_uri") or "")
        preview = str(item.get("cover_preview") or "")
        if status == "ready":
            readable = bool(uri) and not uri.startswith("mock:")
            readable = readable and preview.startswith("data:image/")
            if require_ready and not readable:
                raise QAError("cover is not a readable image")
            if uri.startswith("mock:") or not preview.startswith("data:image/"):
                raise QAError("mock cover cannot be ready", retryable=False)
        elif status != "not_ready" or uri or preview:
            raise QAError("unreadable cover must stay not ready", retryable=False)
        elif require_ready:
            raise QAError("cover is not ready")
        text = card_text(item)
        hit = find_banned_words(text, words)
        if hit:
            raise QAError(f"direction contains banned words: {hit}")
        texts.append(text)
    return texts


def _distinct(texts: list[str]) -> None:
    for index, left in enumerate(texts):
        for right in texts[index + 1 :]:
            score = cosine(left, right)
            if score >= 0.85:
                raise QAError(f"directions are too similar ({score:.3f})")


def _selection(concept: dict) -> None:
    directions = concept["directions"]
    try:
        settings = generation_settings(concept.get("generation_settings"))
    except ValueError as exc:
        raise QAError("invalid generation settings", retryable=False) from exc
    for item in [concept, *directions]:
        if settings.duration_s is not None and item.get("duration_s") != settings.duration_s:
            raise QAError("concept duration differs from the explicit setting", retryable=False)
        if settings.aspect_ratio is not None and item.get("aspect_ratio") != settings.aspect_ratio:
            raise QAError("concept format differs from the explicit setting", retryable=False)
    selection = str(concept.get("selection") or "")
    ids = [str(item["direction_id"]) for item in directions]
    if concept.get("auto") is True:
        if selection != "你帮我选":
            raise QAError("automatic selection must be 你帮我选")
    elif selection not in ids:
        raise QAError("selection does not match a direction")
    if concept.get("chosen_id") not in ids:
        raise QAError("chosen direction is missing")
