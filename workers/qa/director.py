"""One director decision. The workflow applies it; this module does not render media."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from gateway.constants import NO_RENDERED_TEXT
from workers.logging import log_event
from workers.qa.scores import is_quality_pass
from workers.qa.settings import RetryBudget
from workers.schemas.asset import QAReport
from workers.schemas.director import DecisionAction, DecisionTarget, DirectorDecision

MAX_REVIEWS = 3
_MODEL_PROBLEMS = {
    "product_deform",
    "face_collapse",
    "face_count",
    "face_inconsistent",
    "flicker",
}
_N9 = Path(__file__).resolve().parents[1] / "nodes" / "n09_keyframe_qa" / "prompts"
_N11 = Path(__file__).resolve().parents[1] / "nodes" / "n11_video_qa" / "prompts"
_NEXT = (
    "kling-o3",
    "doubao-seedance-1-0-pro-250528",
    "doubao-seedream-4-0-250828",
    "mock-image",
)


def decide(
    report: QAReport,
    *,
    node: str,
    shot_id: str,
    attempt: int,
    model: str = "",
    prompt: str = "",
    gateway: Any | None = None,
    project_id: str | None = None,
    budget: RetryBudget | None = None,
) -> DirectorDecision:
    """Return one validated decision. A model cannot pass a failing shot or raise the cap."""

    if attempt < 1:
        raise ValueError("attempt starts at 1")
    from workers.compliance.moderation import internal_skip_visual_review

    if internal_skip_visual_review() and not report.hard_fail:
        return DirectorDecision(
            action=DecisionAction.pass_,
            target=DecisionTarget(node=node, shot_id=shot_id),
            reason="内部模式：跳过 AI 视觉评审",
            changes={},
            max_attempts_left=max(0, MAX_REVIEWS - attempt),
        )
    policy = _policy(
        report,
        node=node,
        shot_id=shot_id,
        attempt=attempt,
        model=model,
    )
    chosen = _from_model(
        gateway,
        policy,
        report=report,
        node=node,
        shot_id=shot_id,
        attempt=attempt,
        model=model,
        prompt=prompt,
        project_id=project_id,
    )
    chosen = _cap_project(chosen, budget)
    checked = DirectorDecision.model_validate(chosen.model_dump())
    log_event(
        "director_decision",
        project_id=project_id,
        node=node,
        shot_id=shot_id,
        attempt=attempt,
        action=checked.action.value,
        max_attempts_left=checked.max_attempts_left,
    )
    return checked


def generator_node(review_node: str) -> str:
    text = review_node.lower()
    if "11" in text or text in {"n10", "n10_video"}:
        return "N10"
    return "N8"


def _policy(
    report: QAReport,
    *,
    node: str,
    shot_id: str,
    attempt: int,
    model: str,
) -> DirectorDecision:
    left = max(0, MAX_REVIEWS - attempt)
    target = DecisionTarget(node=node, shot_id=shot_id)
    if "not_reviewed" in report.hard_fail and "media=text_only" in report.notes:
        return DirectorDecision(
            action=DecisionAction.fallback,
            target=target,
            reason="画面按设计没有像素，不能判通过",
            changes={"text_only": True},
            max_attempts_left=left,
        )
    if is_quality_pass(report):
        return DirectorDecision(
            action=DecisionAction.pass_,
            target=target,
            reason="质检通过",
            changes={},
            max_attempts_left=left,
        )
    if "sensitive" in report.hard_fail:
        return DirectorDecision(
            action=DecisionAction.ask_user,
            target=target,
            reason="疑似敏感内容，需要人工确认",
            changes={"question": "画面可能包含敏感内容，确认后才能继续。"},
            max_attempts_left=left,
        )
    if attempt >= MAX_REVIEWS:
        return DirectorDecision(
            action=DecisionAction.fallback,
            target=target,
            reason="已满 3 次仍不合格，交降级方案",
            changes={"plan": "degrade"},
            max_attempts_left=0,
        )
    if any(code in _MODEL_PROBLEMS for code in report.hard_fail):
        return DirectorDecision(
            action=DecisionAction.switch_model,
            target=target,
            reason="产品、人脸或闪烁硬伤，更换模型后重生",
            changes=_switch_changes(model),
            max_attempts_left=left,
        )
    return DirectorDecision(
        action=DecisionAction.regenerate,
        target=target,
        reason="最高分低于 7.5，调整提示词后重生",
        changes={"prompt_suffix": NO_RENDERED_TEXT, "candidates": 4},
        max_attempts_left=left,
    )


def _cap_project(decision: DirectorDecision, budget: RetryBudget | None) -> DirectorDecision:
    if decision.action not in {DecisionAction.regenerate, DecisionAction.switch_model}:
        return decision
    if budget is None:
        return decision
    if not budget.allow():
        return decision.model_copy(
            update={
                "action": DecisionAction.fallback,
                "reason": "项目重生次数已到上限",
                "changes": {"plan": "degrade", "project_retry_cap": budget.limit},
                "max_attempts_left": 0,
            }
        )
    budget.consume()
    return decision


def _switch_changes(model: str) -> dict[str, Any]:
    return {
        "model": _next_model(model),
        "motion_strength": "low",
        "candidates": 4,
        "prompt_suffix": NO_RENDERED_TEXT,
    }


def _next_model(model: str) -> str:
    if model in _NEXT:
        return _NEXT[(_NEXT.index(model) + 1) % len(_NEXT)]
    return _NEXT[0]


def _from_model(
    gateway: Any | None,
    policy: DirectorDecision,
    *,
    report: QAReport,
    node: str,
    shot_id: str,
    attempt: int,
    model: str,
    prompt: str,
    project_id: str | None,
) -> DirectorDecision:
    if gateway is None:
        return policy
    generate = getattr(gateway, "generate_text", None)
    if not callable(generate):
        return policy
    folder = _N11 if node == "N10" else _N9
    env = Environment(
        loader=FileSystemLoader(folder),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    text = env.get_template("director.j2").render(
        shot_id=shot_id,
        node=node,
        attempt=attempt,
        attempts_left=policy.max_attempts_left,
        total=report.total,
        hard_fail=", ".join(report.hard_fail) or "none",
        model=model or "unknown",
        prompt=prompt,
    )
    try:
        raw = generate(
            text,
            seed=attempt,
            project_id=project_id,
            node="n11_video_qa" if node == "N10" else "n09_keyframe_qa",
            shot_id=shot_id,
            attempt=attempt,
        )
    except Exception as exc:
        log_event(
            "director_model_failed",
            project_id=project_id,
            node=node,
            shot_id=shot_id,
            attempt=attempt,
            error=str(exc)[:300],
        )
        return policy
    parsed = _parse(raw)
    if parsed is None or not _allowed(parsed.action, policy.action):
        return policy
    return parsed.model_copy(
        update={
            "target": policy.target,
            "max_attempts_left": policy.max_attempts_left,
        }
    )


def _allowed(proposed: DecisionAction, policy: DecisionAction) -> bool:
    if policy is DecisionAction.pass_:
        return proposed is DecisionAction.pass_
    if policy is DecisionAction.ask_user:
        return proposed is DecisionAction.ask_user
    if policy is DecisionAction.fallback:
        return proposed is DecisionAction.fallback
    return proposed in {DecisionAction.regenerate, DecisionAction.switch_model}


def _parse(raw: object) -> DirectorDecision | None:
    if not isinstance(raw, dict):
        return None
    body: object = raw
    if "action" not in raw and isinstance(raw.get("text"), str):
        try:
            body = json.loads(raw["text"])
        except json.JSONDecodeError:
            return None
    try:
        return DirectorDecision.model_validate(body)
    except Exception:
        return None
