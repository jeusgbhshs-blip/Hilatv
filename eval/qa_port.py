"""Review port for T12.

Scores come only from ``workers.qa.service.review_shot``. A shot is reviewed
only when that result has ``visual_reviewed is True``. If the function cannot
be imported, the shot is ``review_error``. Storyboard text alone is not a score.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from workers.qa.service import VIDEO_SUFFIXES
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
_NOT_REVIEWED_FAILS = frozenset({"not_reviewed", "judge_unavailable", "unreviewed"})


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


def _t12_kwargs(fn: Any, gateway: Any) -> dict[str, Any]:
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    if "gateway" in parameters:
        return {"gateway": gateway}
    return {}


def review_port() -> str:
    return "t12" if t12_review_shot() is not None else "unavailable"


def review_shot(payload: dict[str, Any], *, gateway: Any) -> ShotReview:
    """Score one shot. ``payload`` is the T12 request, not free text.

    A score is kept only after a keyframe or video file exists and opens.
    T12 is not called otherwise: a storyboard-only 8.4 is not a review.
    """

    media_uri = readable_media(payload, gateway)
    if not media_uri:
        return ShotReview(
            status="not_reviewed",
            source="unreviewed",
            basis="text",
            report=None,
            media_uri="",
            note=TEXT_ONLY_LABEL,
        )
    fn = t12_review_shot()
    if fn is not None:
        try:
            raw_obj = fn(dict(payload), **_t12_kwargs(fn, gateway))
            raw = _as_dict(raw_obj)
        except Exception as exc:
            return _review_error("t12", media_uri, exc)
        if raw is None:
            return _invalid("t12", media_uri, "review_shot did not return an object")
        if not _visually_reviewed(raw):
            return _not_reviewed("t12", media_uri, _refusal_note(raw))
        try:
            report = coerce_judge(raw)
        except JudgeInvalid as exc:
            return _invalid("t12", media_uri, str(exc))
        return ShotReview(
            status="reviewed",
            source="t12",
            basis="media",
            report=report,
            media_uri=media_uri,
            note=report.notes,
        )
    return _review_error(
        "t12",
        media_uri,
        RuntimeError("workers.qa.service.review_shot is unavailable"),
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
    judges_used = raw.get("judges_used")
    if isinstance(judges_used, bool) or not isinstance(judges_used, int):
        judges_used = 0
    try:
        return QAReport.model_validate(
            {
                "scores": scores,
                "hard_fail": hard,
                "total": total,
                "evaluator": evaluator.strip(),
                "notes": notes,
                "visual_reviewed": raw.get("visual_reviewed") is True,
                "judges_used": judges_used,
                "degraded": raw.get("degraded") is True,
            }
        )
    except ValidationError as exc:
        raise JudgeInvalid("judge payload is invalid") from exc


def readable_media(payload: dict[str, Any], gateway: Any) -> str:
    """First reference T12 can open. ``gateway`` is unused; opening is local."""

    del gateway
    for uri in _media_uris(payload):
        if _opens(uri):
            return uri
    return ""


def _media_uris(payload: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key in ("candidate_uri", "uri"):
        text = str(payload.get(key) or "").strip()
        if text:
            found.append(text)
    frames = payload.get("frame_uris")
    if isinstance(frames, list):
        for item in frames:
            text = str(item or "").strip()
            if text:
                found.append(text)
    return found


def _opens(uri: str) -> bool:
    """Same gate as T12: no http(s), no mock, and the file stays in the project dir."""

    from workers.qa.pixels import MediaLoad, load_image, resolve_project_file

    text = uri.strip()
    if not text or text.startswith("mock://") or text.startswith(("http://", "https://")):
        return False
    if text.lower().endswith(VIDEO_SUFFIXES):
        from workers.qa.frames import sample_frames

        path_text = text[7:] if text.startswith("file://") else text
        located = resolve_project_file(Path(path_text))
        if isinstance(located, MediaLoad) or not located.is_file():
            return False
        try:
            return bool(sample_frames(located))
        except Exception:
            return False
    return load_image(text).ok


def _as_dict(raw: Any) -> dict[str, Any] | None:
    if hasattr(raw, "model_dump"):
        dumped = raw.model_dump(mode="json")
        if not isinstance(dumped, dict):
            return None
        if hasattr(raw, "visual_reviewed"):
            dumped["visual_reviewed"] = getattr(raw, "visual_reviewed")
        for flag in ("degraded", "mock"):
            if hasattr(raw, flag):
                dumped[flag] = getattr(raw, flag)
        return dumped
    if isinstance(raw, dict):
        return raw
    return None


def _visually_reviewed(raw: dict[str, Any]) -> bool:
    """True only for an explicit visual review. A missing field stays False."""

    return raw.get("visual_reviewed") is True


def _refusal_tokens(raw: dict[str, Any]) -> set[str]:
    hard = raw.get("hard_fail") or []
    if not isinstance(hard, list):
        return set()
    found: set[str] = set()
    for item in hard:
        token = str(item).strip().lower().replace("-", "_").replace(" ", "_")
        if token in _NOT_REVIEWED_FAILS:
            found.add(token)
    return found


def _refusal_note(raw: dict[str, Any]) -> str:
    tokens = sorted(_refusal_tokens(raw))
    if tokens:
        return f"{UNREVIEWED_LABEL}：{', '.join(tokens)}"
    if raw.get("degraded") is True or str(raw.get("evaluator") or "").lower().startswith("mock"):
        return f"{UNREVIEWED_LABEL}：评审模型是 mock 或已降级"
    return f"{UNREVIEWED_LABEL}：没有真实视觉评审"


def _not_reviewed(source: str, media_uri: str, note: str) -> ShotReview:
    return ShotReview(
        status="not_reviewed",
        source=source,
        basis="media" if media_uri else "text",
        report=None,
        media_uri=media_uri,
        note=note,
    )


def _review_error(source: str, media_uri: str, exc: Exception) -> ShotReview:
    detail = f"{type(exc).__name__}: {exc}"[:300]
    return ShotReview(
        status="review_error",
        source=source,
        basis="media" if media_uri else "none",
        report=None,
        media_uri=media_uri,
        note=f"review_error: {detail}",
    )


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
