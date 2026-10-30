"""Review port for T12.

T12 is expected to expose ``workers.qa.service.review_shot(payload) -> QAReport``.
Until that function exists, a shot is reviewed only when a keyframe or video
reference is passed through ``gateway.judge`` and the gateway returns a real
score. A mock schema fill (all zeros, ``evaluator=mock``) is not a review.
Storyboard text alone is not a score.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import ValidationError

from workers.schemas.asset import QAReport

_DIMS = (
    "product_fidelity",
    "motion_quality",
    "aesthetics",
    "prompt_match",
    "artifact_free",
)

_ALIASES = {
    "产品变形": "产品变形",
    "文字乱码": "文字乱码",
    "人物崩坏": "人物崩坏",
    "穿帮": "穿帮",
    "product_deform": "产品变形",
    "garbled_text": "文字乱码",
    "extra_text": "文字乱码",
    "face_collapse": "人物崩坏",
    "continuity": "穿帮",
}

TEXT_ONLY_LABEL = "只评了文字，不计入质量结论"
UNREVIEWED_LABEL = "未评审"

_PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(_PROMPTS),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


class JudgeInvalid(ValueError):
    """The judge payload is missing a dimension or is not a real score."""


@dataclass(frozen=True)
class ShotReview:
    status: str
    source: str
    basis: str
    report: QAReport | None
    media_uri: str
    note: str


def t12_review_shot() -> Any | None:
    try:
        module = importlib.import_module("workers.qa.service")
    except ImportError:
        return None
    fn = getattr(module, "review_shot", None)
    if callable(fn):
        return fn
    return None


def review_port() -> str:
    return "t12" if t12_review_shot() is not None else "gateway-judge"


def review_shot(payload: dict[str, Any], *, gateway: Any) -> ShotReview:
    """Score one shot. ``payload`` is the T12 request, not free text."""

    media_uri = str(payload.get("candidate_uri") or "").strip()
    fn = t12_review_shot()
    if fn is not None:
        raw = fn(dict(payload))
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(mode="json")
        if not isinstance(raw, dict):
            return _invalid("t12", media_uri, "review_shot did not return an object")
        try:
            report = coerce_judge(raw)
        except JudgeInvalid as exc:
            return _invalid("t12", media_uri, str(exc))
        return ShotReview(
            status="reviewed",
            source="t12",
            basis="t12",
            report=report,
            media_uri=media_uri,
            note=report.notes,
        )
    if not media_uri:
        return ShotReview(
            status="text_only",
            source="unreviewed",
            basis="text",
            report=None,
            media_uri="",
            note=TEXT_ONLY_LABEL,
        )
    kind = "video" if str(payload.get("node") or "") == "n11_video" else "keyframe"
    prompt = _ENV.get_template("judge.j2").render(
        shot_id=payload.get("shot_id") or "",
        purpose=payload.get("purpose") or "",
        shot_size=payload.get("shot_size") or "",
        camera=payload.get("shot_type") or "",
        generation_mode=payload.get("generation_mode") or "",
        visual=payload.get("visual") or "",
        voiceover=payload.get("voiceover") or "",
        media_kind=kind,
        media_uri=media_uri,
    )
    raw = gateway.judge(
        prompt,
        schema=QAReport,
        project_id=payload.get("project_id"),
        node=str(payload.get("node") or "n09_keyframe"),
        shot_id=payload.get("shot_id"),
        shot_type=payload.get("shot_type") or None,
        attempt=1,
        params={"media_uri": media_uri, "media_kind": kind},
    )
    if not isinstance(raw, dict) or _is_schema_fill(raw):
        return ShotReview(
            status="unreviewed",
            source="unreviewed",
            basis="media",
            report=None,
            media_uri=media_uri,
            note=f"{UNREVIEWED_LABEL}：网关返回的是 mock 填表，没有真实视觉评审",
        )
    try:
        report = coerce_judge(raw)
    except JudgeInvalid as exc:
        return _invalid("gateway-judge", media_uri, str(exc))
    return ShotReview(
        status="reviewed",
        source="gateway-judge",
        basis="media",
        report=report,
        media_uri=media_uri,
        note=report.notes,
    )


def coerce_judge(raw: dict[str, Any]) -> QAReport:
    """Validate a judge payload. Missing dimensions are an error, not an 8."""

    if not isinstance(raw, dict) or not raw:
        raise JudgeInvalid("judge payload is empty")
    if _is_schema_fill(raw):
        raise JudgeInvalid("gateway mock schema fill is not a review")
    scores_raw = raw.get("scores")
    if not isinstance(scores_raw, dict):
        raise JudgeInvalid("judge payload is missing scores")
    missing = [name for name in _DIMS if name not in scores_raw]
    if missing:
        raise JudgeInvalid("judge payload is missing " + ", ".join(missing))
    scores = {name: _require_score(scores_raw[name], name) for name in _DIMS}
    hard_raw = raw.get("hard_fail")
    if hard_raw is None:
        hard_raw = []
    if not isinstance(hard_raw, list):
        raise JudgeInvalid("hard_fail must be a list")
    hard = [_ALIASES.get(str(item), str(item)) for item in hard_raw]
    total = raw.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        total = round(sum(scores.values()) / len(scores), 1)
    evaluator = raw.get("evaluator")
    if not isinstance(evaluator, str) or not evaluator.strip() or evaluator.strip() == "mock":
        raise JudgeInvalid("judge payload is missing a real evaluator")
    notes = raw.get("notes")
    if not isinstance(notes, str):
        raise JudgeInvalid("judge payload is missing notes")
    try:
        return QAReport.model_validate(
            {
                "scores": scores,
                "hard_fail": hard,
                "total": total,
                "evaluator": evaluator.strip(),
                "notes": notes,
            }
        )
    except ValidationError as exc:
        raise JudgeInvalid("judge payload is invalid") from exc


def _invalid(source: str, media_uri: str, note: str) -> ShotReview:
    return ShotReview(
        status="invalid",
        source=source,
        basis="media" if media_uri else "none",
        report=None,
        media_uri=media_uri,
        note=note,
    )


def _is_schema_fill(raw: dict[str, Any]) -> bool:
    scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    if not scores:
        return False
    zeros = all(_is_zero(scores.get(name)) for name in _DIMS)
    try:
        total = float(raw.get("total") or 0)
    except (TypeError, ValueError):
        total = 0.0
    return (
        raw.get("evaluator") == "mock"
        and raw.get("notes") == "mock"
        and not raw.get("hard_fail")
        and zeros
        and total == 0.0
    )


def _is_zero(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return float(value) == 0.0


def _require_score(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise JudgeInvalid(f"{name} is missing or not an integer")
    if value < 0 or value > 10:
        raise JudgeInvalid(f"{name} is outside 0-10")
    return value
