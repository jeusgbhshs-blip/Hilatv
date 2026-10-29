"""Build a timed script from sourced facts. The LLM draft is optional."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from workers.nodes.n04_script.facts import SourceFacts
from workers.nodes.n04_script.schema import ScriptDraft
from workers.qa.copycheck import (
    banned_hits,
    count_units,
    hook_unit_limit,
    invented_numbers,
    language_family,
    phrase_is_sourced,
    spoken_seconds,
    target_units,
    unit_window,
)
from workers.schemas.brief import Brief
from workers.schemas.script import Script, ScriptSection, ScriptSectionKind

_NS = uuid.UUID("6c8c5b1e-1e4a-4c1d-9c1a-3d0a0c6e0a11")

_ZH_FILLER = (
    "画面顺着产品慢慢展开细节留在镜头里面节奏一直保持平稳方便对方自己判断"
    "需要沟通时再联系过程看得清楚光色保持稳定主体停留在画面中部"
)
_EN_FILLER = (
    "the camera stays with the product details remain easy to see the pace stays calm "
    "buyers can judge for themselves talk more when needed the light stays even "
    "the form stays readable the motion stays gentle the frame stays clear"
)

_EN_PROOF = {
    "factory": "The workshop context stays in the file.",
    "cert": "Listed certifications stay as written.",
    "inspection": "Inspection is mentioned in the file.",
    "customer": "Customer context stays as written.",
    "none": "The file sets the limit of the claim.",
}


class ComposeError(ValueError):
    """The rule writer could not hit the length window."""


@dataclass
class SpokenDraft:
    hook: str
    points: list[str] = field(default_factory=list)
    proof: str = ""
    cta: str = ""

    def parts(self) -> list[tuple[ScriptSectionKind, str]]:
        rows: list[tuple[ScriptSectionKind, str]] = [(ScriptSectionKind.hook, self.hook)]
        for point in self.points:
            rows.append((ScriptSectionKind.selling_point, point))
        rows.append((ScriptSectionKind.proof, self.proof))
        rows.append((ScriptSectionKind.cta, self.cta))
        return rows


def script_id_for(project_id: str, brief_id: str, language: str) -> str:
    return str(uuid.uuid5(_NS, f"hilatv:{project_id}:{brief_id}:{language}"))


def compose_script(
    *,
    project_id: str,
    brief: Brief,
    facts: SourceFacts,
    language: str,
    draft: ScriptDraft | None = None,
) -> Script:
    spoken = _spoken(facts, language, brief.duration_s, draft)
    _assert_spoken(spoken, facts, language, brief.duration_s)
    sections = [
        ScriptSection(kind=kind, text=text, shot_ids=[])
        for kind, text in spoken.parts()
        if text.strip()
    ]
    return Script(
        script_id=script_id_for(project_id, brief.brief_id, language),
        brief_id=brief.brief_id,
        language=language,
        sections=sections,
        shots=[],
    )


def _spoken(
    facts: SourceFacts,
    language: str,
    duration_s: int,
    draft: ScriptDraft | None,
) -> SpokenDraft:
    target = target_units(duration_s, language)
    low, high = unit_window(target)
    limit = hook_unit_limit(language)
    spoken = _from_model(draft, facts, language, limit) if draft else None
    if spoken is None:
        spoken = _from_facts(facts, language, limit)
    _shrink(spoken, language, high, limit)
    _pad(spoken, language, low, high)
    return spoken


def _from_model(
    draft: ScriptDraft | None,
    facts: SourceFacts,
    language: str,
    limit: int,
) -> SpokenDraft | None:
    if draft is None:
        return None
    hook = _accept_line(draft.hook, facts)
    proof = _accept_line(draft.proof, facts)
    cta = _accept_line(draft.cta, facts)
    if not hook or not proof or not cta:
        return None
    if count_units(hook, language) > limit or spoken_seconds(hook, language) > 3:
        return None
    points: list[str] = []
    for item in draft.selling_points:
        line = _accept_line(item, facts)
        if not line or not phrase_is_sourced(line, facts.point_sources):
            return None
        points.append(line)
        if len(points) == 3:
            break
    return SpokenDraft(hook=hook, points=points, proof=proof, cta=cta)


def _accept_line(text: str, facts: SourceFacts) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return ""
    if banned_hits(cleaned, facts.banned) or invented_numbers(cleaned, facts.allowed):
        return ""
    return cleaned


def _from_facts(facts: SourceFacts, language: str, limit: int) -> SpokenDraft:
    if language_family(language) == "zh":
        return SpokenDraft(
            hook=_hook_zh(facts, limit),
            points=list(facts.points),
            proof=facts.proof or "按资料说明",
            cta=_cta_zh(facts),
        )
    return SpokenDraft(
        hook=_hook_en(facts, limit),
        points=[_en_point(item) for item in facts.points],
        proof=_EN_PROOF.get(facts.proof_key, _EN_PROOF["none"]),
        cta=_cta_en(facts),
    )


def _hook_zh(facts: SourceFacts, limit: int) -> str:
    options: list[str] = []
    for point in facts.points:
        if any(ch.isdigit() for ch in point):
            options.append(point)
    if facts.product_name:
        options.append(facts.product_name)
    options.extend(["先看这里", "看这里", "看"])
    return _first_fit(options, "zh", limit)


def _hook_en(facts: SourceFacts, limit: int) -> str:
    options: list[str] = []
    for point in facts.points:
        if any(ch.isdigit() for ch in point):
            options.append(f"See {point}")
    if facts.product_name:
        options.append(f"See {facts.product_name}")
    options.extend(["See this", "Look"])
    return _first_fit(options, "en", limit)


def _first_fit(options: list[str], language: str, limit: int) -> str:
    for option in options:
        text = option.strip()
        if text and count_units(text, language) <= limit:
            return text
    return "看" if language == "zh" else "Look"


def _cta_zh(facts: SourceFacts) -> str:
    if facts.phone:
        return f"联系{facts.phone}"
    if facts.website:
        return f"查看{facts.website}"
    return "欢迎沟通"


def _cta_en(facts: SourceFacts) -> str:
    if facts.phone:
        return f"Call {facts.phone}"
    if facts.website:
        return f"Visit {facts.website}"
    return "Talk when ready"


def _en_point(point: str) -> str:
    """English frame around a sourced fact. Not a sentence-by-sentence translation."""

    lowered = point.lower()
    if "moq" in lowered or "起订" in point:
        return f"Buyers ask about MOQ {point}"
    if "交期" in point or "lead time" in lowered:
        return f"Lead time on file {point}"
    if "认证" in point:
        return f"Certification on file {point}"
    return f"On file {point}"


def _shrink(spoken: SpokenDraft, language: str, high: int, limit: int) -> None:
    """Drop extra claims before the last sourced selling point, then shorten the rest."""

    zh = language_family(language) == "zh"
    while _total(spoken, language) > high and len(spoken.points) > 1:
        spoken.points.pop()
    if _total(spoken, language) > high:
        spoken.proof = "资料" if zh else "Noted"
    if _total(spoken, language) > high:
        spoken.cta = "再" if zh else "Hello"
    while _total(spoken, language) > high and spoken.points:
        spoken.points.pop()
    if count_units(spoken.hook, language) > limit or _total(spoken, language) > high:
        spoken.hook = "看" if zh else "Look"
    if _total(spoken, language) > high:
        raise ComposeError("script is still over the length window")


def _pad(spoken: SpokenDraft, language: str, low: int, high: int) -> None:
    current = _total(spoken, language)
    if current > high:
        raise ComposeError("script is over the length window")
    if current >= low:
        return
    extra = _filler(language, low - current)
    if not extra:
        raise ComposeError("could not pad the script")
    spoken.cta = f"{spoken.cta} {extra}".strip()
    done = _total(spoken, language)
    if done < low or done > high:
        raise ComposeError(f"padded script landed on {done}, window {low}-{high}")


def _filler(language: str, units: int) -> str:
    if units <= 0:
        return ""
    if language_family(language) == "zh":
        base = _ZH_FILLER
        block = count_units(base, "zh")
        copies = (units // block) + 1 if block else 1
        return _take_zh(base * copies, units)
    words = _EN_FILLER.split()
    if not words:
        raise ComposeError("missing english filler")
    picked: list[str] = []
    while len(picked) < units:
        picked.extend(words)
    return " ".join(picked[:units])


def _take_zh(text: str, units: int) -> str:
    out: list[str] = []
    got = 0
    for ch in text:
        if count_units(ch, "zh") == 0:
            continue
        if got >= units:
            break
        out.append(ch)
        got += 1
    return "".join(out)


def _total(spoken: SpokenDraft, language: str) -> int:
    return sum(count_units(text, language) for _, text in spoken.parts())


def _assert_spoken(spoken: SpokenDraft, facts: SourceFacts, language: str, duration_s: int) -> None:
    blob = "".join(text for _, text in spoken.parts())
    if banned_hits(blob, facts.banned):
        raise ComposeError("banned words remain in the script")
    if invented_numbers(blob, facts.allowed):
        raise ComposeError("invented numbers remain in the script")
    if spoken_seconds(spoken.hook, language) > 3:
        raise ComposeError("hook runs past the first 3 seconds")
    target = target_units(duration_s, language)
    if not _in_window(_total(spoken, language), target):
        raise ComposeError("script missed the length window")


def _in_window(actual: int, target: float) -> bool:
    low, high = unit_window(target)
    return low <= actual <= high
