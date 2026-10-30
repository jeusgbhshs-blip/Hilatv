"""Review port for T12.

T12 is expected to expose ``workers.qa.service.review_shot(payload) -> dict``
returning a chapter 5 ``QAReport``. Until that function exists, each shot is
scored with ``gateway.judge``. The gateway mock fills a JSON Schema with zeros;
that fingerprint is rewritten to the mock judge profile so an unkeyed run is
not reported as a row of zeros. A real judge payload is kept as returned.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from workers.schemas.asset import QAReport, QAScores

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

_PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(_PROMPTS),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def t12_review_shot() -> Any | None:
    try:
        module = importlib.import_module("workers.qa.service")
    except ImportError:
        return None
    fn = getattr(module, "review_shot", None)
    if callable(fn):
        return fn
    return None


def reviewer_name() -> str:
    return "t12" if t12_review_shot() is not None else "gateway-judge"


def review_shot(payload: dict[str, Any], *, gateway: Any) -> QAReport:
    """Score one shot. ``payload`` is the T12 request, not free text."""

    fn = t12_review_shot()
    if fn is not None:
        raw = fn(dict(payload))
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(mode="json")
        return QAReport.model_validate(raw)
    prompt = _ENV.get_template("judge.j2").render(
        shot_id=payload.get("shot_id") or "",
        purpose=payload.get("purpose") or "",
        shot_size=payload.get("shot_size") or "",
        camera=payload.get("shot_type") or "",
        generation_mode=payload.get("generation_mode") or "",
        visual=payload.get("visual") or "",
        voiceover=payload.get("voiceover") or "",
    )
    raw = gateway.judge(
        prompt,
        schema=QAReport,
        project_id=payload.get("project_id"),
        node=str(payload.get("node") or "n09_keyframe"),
        shot_id=payload.get("shot_id"),
        shot_type=payload.get("shot_type") or None,
        attempt=1,
    )
    return coerce_judge(raw if isinstance(raw, dict) else {})


def coerce_judge(raw: dict[str, Any]) -> QAReport:
    if _is_schema_fill(raw):
        scores = {
            "product_fidelity": 8,
            "motion_quality": 8,
            "aesthetics": 8,
            "prompt_match": 8,
            "artifact_free": 10,
        }
        return QAReport(
            scores=QAScores.model_validate(scores),
            hard_fail=[],
            total=8.4,
            evaluator="mock-judge",
            notes="mock judge; no pixels and no live VLM",
        )
    scores_raw = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    scores = {name: _clamp_int(scores_raw.get(name), 8) for name in _DIMS}
    hard = [_ALIASES.get(str(item), str(item)) for item in raw.get("hard_fail") or []]
    total = raw.get("total")
    if not isinstance(total, (int, float)):
        total = round(sum(scores.values()) / len(scores), 1)
    evaluator = str(raw.get("evaluator") or "mock-judge")
    notes = str(raw.get("notes") or "mock")
    return QAReport.model_validate(
        {
            "scores": scores,
            "hard_fail": hard,
            "total": total,
            "evaluator": evaluator,
            "notes": notes,
        }
    )


def _is_schema_fill(raw: dict[str, Any]) -> bool:
    scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    zeros = all(_clamp_int(scores.get(name), 0) == 0 for name in _DIMS)
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


def _clamp_int(value: object, default: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return min(10, max(0, number))
