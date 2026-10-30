"""Two judge calls. A wide gap keeps the stricter scores.

Pixel hard fails are applied later and cannot be voted away.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from workers.logging import log_event
from workers.qa.scores import merge_opinions, parse_opinion
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


def cross_review(
    gateway: Any,
    payload: dict[str, Any],
    *,
    rule_notes: str,
    image_b64: str | None = None,
) -> QAReport | None:
    prompt = render_judge(payload, rule_notes)
    primary = _call(
        gateway,
        prompt,
        payload,
        shot_type=_shot_type(payload.get("shot_type")),
        seed=11,
        reviewer="primary",
        image_b64=image_b64,
    )
    cross = _call(
        gateway,
        prompt,
        payload,
        shot_type="cross_review",
        seed=29,
        reviewer="cross",
        image_b64=image_b64,
    )
    return merge_opinions(parse_opinion(primary), parse_opinion(cross))


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
) -> dict[str, Any] | None:
    judge = getattr(gateway, "judge", None)
    if not callable(judge):
        return None
    params: dict[str, Any] = {"reviewer": reviewer}
    if image_b64:
        params["image_b64"] = image_b64
    node = "n11_video_qa" if _video_node(payload) else "n09_keyframe_qa"
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
    except Exception as exc:
        log_event(
            "qa_judge_failed",
            project_id=_text(payload.get("project_id")),
            node=node,
            shot_id=_text(payload.get("shot_id")),
            attempt=1,
            error=str(exc)[:300],
            reviewer=reviewer,
        )
        return None
    return raw if isinstance(raw, dict) else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
