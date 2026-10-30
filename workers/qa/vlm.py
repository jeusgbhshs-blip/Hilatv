"""Two judge calls. A wide gap keeps the stricter scores.

Pixel hard fails are applied later and cannot be voted away. A call that
errors, times out, or omits a dimension is not an opinion.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from workers.logging import log_event
from workers.qa.scores import JudgeReview, ParsedOpinion, combine_judges, parse_opinion
from workers.schemas.asset import QAReport

_N9 = Path(__file__).resolve().parents[1] / "nodes" / "n09_keyframe_qa" / "prompts"
_N11 = Path(__file__).resolve().parents[1] / "nodes" / "n11_video_qa" / "prompts"


def render_judge(payload: dict[str, Any], rule_notes: str) -> str:
    folder = _N11 if _video_node(payload) else _N9
    env = Environment(
        loader=FileSystemLoader(folder),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("judge.j2").render(
        shot_id=payload.get("shot_id") or "",
        purpose=payload.get("purpose") or "",
        visual=payload.get("visual") or "",
        voiceover=payload.get("voiceover") or "",
        shot_size=payload.get("shot_size") or "",
        shot_type=payload.get("shot_type") or "",
        generation_mode=payload.get("generation_mode") or "",
        rule_notes=rule_notes or "none",
    )


@dataclass
class _RawJudge:
    payload: dict[str, Any] | None
    error: str | None


def cross_review(
    gateway: Any,
    payload: dict[str, Any],
    *,
    rule_notes: str,
    image_b64: str | None = None,
) -> JudgeReview:
    prompt = render_judge(payload, rule_notes)
    primary = _classify(
        _call(
            gateway,
            prompt,
            payload,
            shot_type=_shot_type(payload.get("shot_type")),
            seed=11,
            reviewer="primary",
            image_b64=image_b64,
        )
    )
    cross = _classify(
        _call(
            gateway,
            prompt,
            payload,
            shot_type="cross_review",
            seed=29,
            reviewer="cross",
            image_b64=image_b64,
        )
    )
    live = os.getenv("HILATV_LIVE", "0").strip() == "1"
    return combine_judges(primary, cross, live=live)


def _classify(raw: _RawJudge) -> ParsedOpinion:
    if raw.error:
        return ParsedOpinion(None, raw.error)
    return parse_opinion(raw.payload)


def _video_node(payload: dict[str, Any]) -> bool:
    node = str(payload.get("node") or "").lower()
    return "11" in node or node.endswith("video")


def _shot_type(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "cross_review":
        return None
    return text


def _call(
    gateway: Any,
    prompt: str,
    payload: dict[str, Any],
    *,
    shot_type: str | None,
    seed: int,
    reviewer: str,
    image_b64: str | None,
) -> _RawJudge:
    judge = getattr(gateway, "judge", None)
    node = "n11_video_qa" if _video_node(payload) else "n09_keyframe_qa"
    if not callable(judge):
        return _RawJudge(None, "judge_error")
    params: dict[str, Any] = {"reviewer": reviewer}
    if image_b64:
        params["image_b64"] = image_b64
    try:
        raw = judge(
            prompt,
            schema=QAReport,
            seed=seed,
            shot_type=shot_type,
            project_id=payload.get("project_id"),
            node=node,
            shot_id=payload.get("shot_id"),
            attempt=1,
            params=params,
        )
    except TimeoutError as exc:
        _log_judge_failure(payload, node, reviewer, "timeout", exc)
        return _RawJudge(None, "timeout")
    except Exception as exc:
        _log_judge_failure(payload, node, reviewer, "judge_error", exc)
        return _RawJudge(None, "judge_error")
    if not isinstance(raw, dict):
        return _RawJudge(None, "parse_failure")
    return _RawJudge(raw, None)


def _log_judge_failure(
    payload: dict[str, Any],
    node: str,
    reviewer: str,
    kind: str,
    exc: BaseException,
) -> None:
    log_event(
        "qa_judge_failed",
        project_id=_text(payload.get("project_id")),
        node=node,
        shot_id=_text(payload.get("shot_id")),
        attempt=1,
        error=f"{kind}: {exc}"[:300],
        reviewer=reviewer,
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
