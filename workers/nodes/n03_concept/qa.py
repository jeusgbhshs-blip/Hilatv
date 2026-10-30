"""N3 quality: three directions, cosine under 0.85, no banned words."""

from __future__ import annotations

from workers.nodes.n03_concept.compose import card_text
from workers.nodes.n03_concept.schema import NodeResult
from workers.nodes.n03_concept.similarity import cosine
from workers.schemas.brand import default_banned_words, find_banned_words


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult, *, banned: list[str] | None = None) -> dict:
    if result.node != "n03_concept" or not result.ok:
        raise QAError("n03_concept result is not ok")
    concept = result.payload.get("concept")
    if not isinstance(concept, dict):
        raise QAError("concept is missing")
    directions = concept.get("directions")
    if not isinstance(directions, list) or len(directions) != 3:
        raise QAError("concept needs exactly 3 directions")
    words = banned if banned is not None else default_banned_words()
    texts: list[str] = []
    for item in directions:
        if not isinstance(item, dict):
            raise QAError("direction must be an object")
        for key in ("direction_id", "title", "idea", "mood", "estimated_effect", "cover_uri"):
            if not str(item.get(key) or "").strip():
                raise QAError(f"direction is missing {key}")
        if not item.get("structure"):
            raise QAError("direction is missing structure")
        text = card_text(item)
        hit = find_banned_words(text, words)
        if hit:
            raise QAError(f"direction contains banned words: {hit}")
        texts.append(text)
    for index, left in enumerate(texts):
        for right in texts[index + 1 :]:
            score = cosine(left, right)
            if score >= 0.85:
                raise QAError(f"directions are too similar ({score:.3f})")
    selection = str(concept.get("selection") or "")
    ids = [str(item["direction_id"]) for item in directions]
    if concept.get("auto") is True:
        if selection != "你帮我选":
            raise QAError("automatic selection must be 你帮我选")
    elif selection not in ids:
        raise QAError("selection does not match a direction")
    if concept.get("chosen_id") not in ids:
        raise QAError("chosen direction is missing")
    return concept
