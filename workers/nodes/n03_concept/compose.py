"""Three directions from the industry template's narrative structures.

The model draft is used only when it is already distinct and free of banned
words. Otherwise these rule lines are the card copy. They do not invent specs.
"""

from __future__ import annotations

from workers.nodes.n01_brief.industries import IndustryTemplate, NarrativeStructure
from workers.schemas.brand import find_banned_words

_ARCS = (
    ("钩子", "卖点", "证明", "行动"),
    ("钩子", "证明", "卖点", "行动"),
    ("证明", "卖点", "钩子", "行动"),
)
_VOICES = (
    (
        "{label}",
        "开场只谈{lead}。中段交给{mid}。收束在{tail}。",
        "冷静",
        ("近景", "冷色"),
        "适合把{lead}讲清楚",
    ),
    (
        "{lead}带路",
        "片子由{lead}进入，随后出现{mid}，停在{tail}。",
        "克制",
        ("中景", "稳定机位"),
        "适合把{label}讲完",
    ),
    (
        "回看{tail}",
        "观众先记住{lead}，中间用{mid}作证，结尾落到{tail}。",
        "扎实",
        ("侧光", "横移"),
        "适合强调{label}这条叙事",
    ),
)


def pick_structures(template: IndustryTemplate) -> list[NarrativeStructure]:
    """Read 3 of the template's 3–5 structures. The default narrative stays first."""

    default = next(
        item for item in template.narrative_structures if item.beats == template.narrative
    )
    rest = [item for item in template.narrative_structures if item.id != default.id]
    rest.sort(key=lambda item: (len(set(item.beats) & set(default.beats)), item.id))
    return [default, *rest[:2]]


def compose_directions(
    template: IndustryTemplate,
    structures: list[NarrativeStructure],
    *,
    banned: list[str],
) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    for index, structure in enumerate(structures):
        cards.append(_one(template, structure, index, banned))
    return cards


def card_text(card: dict[str, object]) -> str:
    structure = card.get("structure") or []
    beats = card.get("beats") or []
    keywords = card.get("style_keywords") or []
    parts = [
        str(card.get("title") or ""),
        str(card.get("idea") or ""),
        str(card.get("mood") or ""),
        " ".join(str(item) for item in structure),
        " ".join(str(item) for item in beats),
        " ".join(str(item) for item in keywords),
        str(card.get("estimated_effect") or ""),
    ]
    return "\n".join(parts)


def _one(
    template: IndustryTemplate,
    structure: NarrativeStructure,
    index: int,
    banned: list[str],
) -> dict[str, object]:
    lead = structure.beats[0]
    tail = structure.beats[-1]
    mid = structure.beats[min(1, len(structure.beats) - 1)]
    title_t, idea_t, mood, keywords, effect_t = _VOICES[index]
    values = {"label": structure.label, "lead": lead, "mid": mid, "tail": tail}
    style = list(keywords)
    if template.style_keywords:
        style.append(template.style_keywords[index % len(template.style_keywords)])
    card = {
        "direction_id": structure.id,
        "title": title_t.format(**values),
        "idea": idea_t.format(**values),
        "mood": mood,
        "structure": list(_ARCS[index]),
        "beats": list(structure.beats),
        "style_keywords": style,
        "estimated_effect": effect_t.format(**values),
        "structure_label": structure.label,
    }
    hit = find_banned_words(card_text(card), banned)
    if hit:
        raise ValueError(f"composed direction contains banned words: {hit}")
    return card
