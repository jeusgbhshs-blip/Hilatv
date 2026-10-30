"""Per-shot scores, hard-injury rate, and the defect ledger.

SPEC §1.4 counts a hard injury per shot: product warp, garbled text,
a broken face, or a continuity break. Any non-empty ``QAReport.hard_fail``
is one injured shot. The rate is injured shots divided by all shots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from eval.qa_port import ShotReview, review_shot
from workers.schemas.asset import QAReport

HARD_INJURY_LIMIT = Decimal("0.05")


@dataclass
class ShotScore:
    shot_id: str
    shot_type: str
    node: str
    model: str
    purpose: str
    report: QAReport | None
    review_status: str = "reviewed"
    review_source: str = "t12"
    review_basis: str = "t12"
    media_uri: str = ""
    note: str = ""


@dataclass
class CaseScore:
    score: float | None
    hard_shots: int
    shot_count: int
    reviewed_shots: int = 0
    unreviewed_shots: int = 0
    text_only_shots: int = 0
    invalid_shots: int = 0
    shots: list[ShotScore] = field(default_factory=list)


def review_node(state: dict[str, Any]) -> str:
    """N11 when a video candidate exists, otherwise the N9 keyframe review."""

    videos = state.get("videos")
    if isinstance(videos, list) and videos:
        return "n11_video"
    return "n09_keyframe"


def generation_model(state: dict[str, Any], shot_id: str, node: str) -> str:
    pool_key = "videos" if node == "n11_video" else "keyframes"
    pool = state.get(pool_key)
    if not isinstance(pool, list):
        return "not-rendered"
    chosen: dict[str, Any] | None = None
    for item in pool:
        if not isinstance(item, dict) or str(item.get("shot_id") or "") != shot_id:
            continue
        if item.get("selected"):
            chosen = item
            break
        if chosen is None:
            chosen = item
    if chosen is None:
        return "not-rendered"
    model = str(chosen.get("model") or "").strip()
    return model or "not-rendered"


def score_state(state: dict[str, Any], *, project_id: str, gateway: Any) -> CaseScore:
    script = state.get("script") if isinstance(state.get("script"), dict) else {}
    shots = script.get("shots") if isinstance(script, dict) else None
    if not isinstance(shots, list) or not shots:
        raise RuntimeError("storyboard has no shots")
    node = review_node(state)
    scored: list[ShotScore] = []
    for shot in shots:
        if not isinstance(shot, dict):
            raise RuntimeError("shot is not an object")
        shot_id = str(shot.get("shot_id") or "")
        if not shot_id:
            raise RuntimeError("shot is missing shot_id")
        shot_type = str(shot.get("camera") or "unknown")
        model = generation_model(state, shot_id, node)
        review = review_shot(
            {
                "project_id": project_id,
                "shot_id": shot_id,
                "shot_type": shot_type,
                "purpose": shot.get("purpose") or "",
                "visual": shot.get("visual") or "",
                "voiceover": shot.get("voiceover") or "",
                "shot_size": shot.get("shot_size") or "",
                "generation_mode": shot.get("generation_mode") or "",
                "node": node,
                "model": model,
                "candidate_uri": _candidate_uri(state, shot_id, node),
            },
            gateway=gateway,
        )
        scored.append(_shot_score(shot_id, shot_type, node, model, shot, review))
    return _case_score(scored)


def hard_injury_rate(hard_shots: int, shot_count: int) -> Decimal:
    if shot_count <= 0:
        return Decimal("0")
    return (Decimal(hard_shots) / Decimal(shot_count)).quantize(Decimal("0.0001"))


def within_hard_injury_limit(hard_shots: int, shot_count: int) -> bool:
    if shot_count <= 0:
        return True
    return Decimal(hard_shots) * Decimal(100) <= Decimal(shot_count) * Decimal(5)


def _shot_score(
    shot_id: str,
    shot_type: str,
    node: str,
    model: str,
    shot: dict[str, Any],
    review: ShotReview,
) -> ShotScore:
    return ShotScore(
        shot_id=shot_id,
        shot_type=shot_type,
        node=node,
        model=model,
        purpose=str(shot.get("purpose") or ""),
        report=review.report,
        review_status=review.status,
        review_source=review.source,
        review_basis=review.basis,
        media_uri=review.media_uri,
        note=review.note,
    )


def _case_score(scored: list[ShotScore]) -> CaseScore:
    reviewed = [
        item for item in scored if item.review_status == "reviewed" and item.report is not None
    ]
    text_only = sum(1 for item in scored if item.review_status == "text_only")
    invalid = sum(1 for item in scored if item.review_status == "invalid")
    bare = sum(1 for item in scored if item.review_status == "unreviewed")
    fully = len(reviewed) == len(scored) and bool(scored)
    if fully:
        totals = [Decimal(str(item.report.total)) for item in reviewed if item.report is not None]
        mean = float((sum(totals, Decimal("0")) / Decimal(len(totals))).quantize(Decimal("0.01")))
    else:
        mean = None
    hard = sum(1 for item in reviewed if item.report is not None and item.report.hard_fail)
    return CaseScore(
        score=mean,
        hard_shots=hard,
        shot_count=len(scored),
        reviewed_shots=len(reviewed),
        unreviewed_shots=bare + text_only,
        text_only_shots=text_only,
        invalid_shots=invalid,
        shots=scored,
    )


def _candidate_uri(state: dict[str, Any], shot_id: str, node: str) -> str:
    pool_key = "videos" if node == "n11_video" else "keyframes"
    pool = state.get(pool_key)
    if not isinstance(pool, list):
        return ""
    fallback = ""
    for item in pool:
        if not isinstance(item, dict) or str(item.get("shot_id") or "") != shot_id:
            continue
        uri = str(item.get("uri") or "")
        if item.get("selected"):
            return uri
        if not fallback:
            fallback = uri
    return fallback
