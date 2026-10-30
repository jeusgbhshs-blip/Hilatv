"""Pairwise rank agreement for the 200-image calibration set.

The set is not in the repo. Until ``calibration/manifest.json`` lists 200
labeled images, the status stays ``pending_team`` and the 80% gate is not run.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any

EXPECTED_IMAGES = 200
AGREEMENT_MIN = 0.80
MANIFEST = Path(__file__).resolve().parent / "calibration" / "manifest.json"


def calibration_status(*, manifest: Path | None = None) -> dict[str, Any]:
    path = manifest or MANIFEST
    if not path.is_file():
        return _pending(0, None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _pending(0, None)
    if not isinstance(data, dict):
        return _pending(0, None)
    images = data.get("images") if isinstance(data.get("images"), list) else []
    have = int(data["count"]) if isinstance(data.get("count"), int) else len(images)
    rankings = data.get("rankings") if isinstance(data.get("rankings"), list) else []
    agreement = _agreement(rankings)
    if have < EXPECTED_IMAGES:
        return _pending(have, agreement)
    passed = agreement is not None and agreement >= AGREEMENT_MIN
    return {
        "status": "pass" if passed else "fail",
        "expected": EXPECTED_IMAGES,
        "have": have,
        "agreement": agreement,
        "threshold": AGREEMENT_MIN,
    }


def pairwise_agreement(human: list[str], judge: list[str]) -> float:
    """Share of pairs that keep the same order. ``human`` is best to worst."""

    rank_h = {item: index for index, item in enumerate(human)}
    rank_j = {item: index for index, item in enumerate(judge)}
    shared = [item for item in human if item in rank_j]
    pairs = 0
    agreed = 0
    for left, right in combinations(shared, 2):
        pairs += 1
        human_order = rank_h[left] - rank_h[right]
        judge_order = rank_j[left] - rank_j[right]
        if human_order == 0 or judge_order == 0 or human_order * judge_order > 0:
            agreed += 1
    if pairs == 0:
        return 1.0
    return agreed / pairs


def _agreement(rankings: list[object]) -> float | None:
    scores: list[float] = []
    for item in rankings:
        if not isinstance(item, dict):
            continue
        human = item.get("human")
        judge = item.get("judge")
        if not isinstance(human, list) or not isinstance(judge, list):
            continue
        scores.append(
            pairwise_agreement([str(value) for value in human], [str(value) for value in judge])
        )
    if not scores:
        return None
    return sum(scores) / len(scores)


def _pending(have: int, agreement: float | None) -> dict[str, Any]:
    return {
        "status": "pending_team",
        "expected": EXPECTED_IMAGES,
        "have": have,
        "agreement": agreement,
        "threshold": AGREEMENT_MIN,
    }
