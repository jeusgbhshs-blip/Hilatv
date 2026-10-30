"""Chinese master first, then a localized read. Mock drafts fall back to the rules.

The rewrite is not a sentence-by-sentence translation. Digits stay only when the
source file already contains them. On-screen cards are still render-layer text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict, Field

from workers.nodes.n04_script.compose import compose_script, script_id_for
from workers.nodes.n04_script.facts import collect_facts
from workers.nodes.n04_script.prompts import system_prompt
from workers.qa.copycheck import language_family
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import OnScreenText, Script, Shot

PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(PROMPTS),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


class ShotLine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: str = ""
    voiceover: str = ""
    card: str = ""


class LocalDraft(BaseModel):
    """Empty defaults so a mock LLM cannot invent a line."""

    model_config = ConfigDict(extra="ignore")

    shots: list[ShotLine] = Field(default_factory=list)


def localize(
    master: Script,
    brief: Brief,
    brand: BrandKit | None,
    language: str,
    *,
    gateway: Any,
    project_id: str,
    attempt: int,
    ready: Script | None = None,
) -> tuple[Script, str]:
    if ready is not None and _same_board(master, ready):
        return ready, ""
    if language_family(language) == "zh":
        script = master.model_copy(
            update={
                "language": language,
                "script_id": script_id_for(project_id, brief.brief_id, language),
            }
        )
        return script, ""
    facts = collect_facts(brief, brand)
    prompt = (
        _ENV.get_template("localize_shots.j2")
        .render(
            language=language,
            shots=[{"shot_id": shot.shot_id, "voiceover": shot.voiceover} for shot in master.shots],
            points="\n".join(facts.points) or "无",
            proof=facts.proof or "无",
            banned="、".join(facts.banned) or "无",
        )
        .strip()
    )
    if "Do not render any on-screen text" not in prompt:
        raise ValueError("localization prompt is missing the no-text constraint")
    draft = _complete(
        gateway,
        prompt,
        project_id=project_id,
        attempt=attempt,
        language=language,
    )
    voices, cards = _from_draft(master, draft)
    if voices is None:
        spoken = compose_script(
            project_id=project_id,
            brief=brief,
            facts=facts,
            language=language,
        )
        voices = split_copy(
            [section.text for section in spoken.sections],
            master.shots,
            language,
        )
        cards = [
            _card(shot, language, voice) for shot, voice in zip(master.shots, voices, strict=True)
        ]
    script = _apply(master, brief, project_id, language, voices, cards)
    return script, prompt


def split_copy(sections: list[str], shots: list[Shot], language: str) -> list[str]:
    zh = language_family(language) == "zh"
    if zh:
        tokens = [char for char in "".join(sections) if not char.isspace()]
        joiner = ""
    else:
        tokens = " ".join(sections).split()
        joiner = " "
    if not tokens:
        tokens = ["看"] if zh else ["Look"]
    counts = _allocate(len(tokens), [float(shot.duration_s) for shot in shots])
    parts: list[str] = []
    cursor = 0
    for count in counts:
        piece = tokens[cursor : cursor + count]
        cursor += count
        if not piece:
            piece = [tokens[-1]]
        parts.append(joiner.join(piece))
    return parts


def _from_draft(master: Script, draft: LocalDraft) -> tuple[list[str] | None, list[str]]:
    by_id = {item.shot_id: item for item in draft.shots if item.shot_id}
    ordered = by_id or None
    lines: list[ShotLine] = []
    if ordered is not None and all(shot.shot_id in ordered for shot in master.shots):
        lines = [ordered[shot.shot_id] for shot in master.shots]
    elif len(draft.shots) == len(master.shots):
        lines = list(draft.shots)
    else:
        return None, []
    voices: list[str] = []
    cards: list[str] = []
    for shot, line in zip(master.shots, lines, strict=True):
        voice = line.voiceover.strip()
        if not voice or voice == "mock":
            return None, []
        card = line.card.strip()
        if not card or card == "mock":
            card = _card(shot, "en", voice)
        voices.append(voice)
        cards.append(card)
    return voices, cards


def _card(shot: Shot, language: str, voice: str) -> str:
    original = shot.on_screen_text[0].text if shot.on_screen_text else ""
    if language_family(language) == "zh":
        return original or voice[:16]
    if original and not _cjk(original):
        return original
    pieces = original.replace("，", " ").split()
    digits = [token for token in pieces if any(char.isdigit() for char in token)]
    if not digits:
        digits = [token for token in voice.split() if any(ch.isdigit() for ch in token)]
    if digits:
        return ("On file " + " ".join(digits))[:42]
    words = [word for word in voice.split() if word.isascii()][:6]
    return (" ".join(words) or "On file")[:42]


def _apply(
    master: Script,
    brief: Brief,
    project_id: str,
    language: str,
    voices: list[str],
    cards: list[str],
) -> Script:
    shots: list[Shot] = []
    for shot, voice, card in zip(master.shots, voices, cards, strict=True):
        cards_out: list[OnScreenText] = []
        if shot.on_screen_text and card:
            cards_out.append(shot.on_screen_text[0].model_copy(update={"text": card}))
            cards_out.extend(shot.on_screen_text[1:])
        elif shot.on_screen_text:
            cards_out = list(shot.on_screen_text)
        shots.append(shot.model_copy(update={"voiceover": voice, "on_screen_text": cards_out}))
    return master.model_copy(
        update={
            "script_id": script_id_for(project_id, brief.brief_id, language),
            "language": language,
            "shots": shots,
        }
    )


def _same_board(master: Script, ready: Script) -> bool:
    if len(ready.shots) != len(master.shots):
        return False
    for left, right in zip(master.shots, ready.shots, strict=True):
        if left.shot_id != right.shot_id or not right.voiceover.strip():
            return False
    return True


def _complete(
    gateway: Any,
    prompt: str,
    *,
    project_id: str,
    attempt: int,
    language: str,
) -> LocalDraft:
    try:
        raw = gateway.generate_text(
            prompt,
            schema=LocalDraft,
            system=system_prompt(),
            seed=0,
            language=language,
            project_id=project_id,
            node="n17_deliver",
            shot_id=None,
            attempt=attempt,
        )
        return LocalDraft.model_validate(raw)
    except Exception:
        return LocalDraft()


def _allocate(total: int, weights: list[float]) -> list[int]:
    if not weights:
        return []
    if total <= 0:
        return [0 for _ in weights]
    safe = [weight if weight > 0 else 1.0 for weight in weights]
    budget = sum(safe)
    counts = [max(1, int(round(total * weight / budget))) for weight in safe]
    while sum(counts) > total:
        index = max(range(len(counts)), key=lambda item: counts[item])
        if counts[index] <= 1:
            break
        counts[index] -= 1
    while sum(counts) < total:
        counts[-1] += 1
    return counts


def _cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)
