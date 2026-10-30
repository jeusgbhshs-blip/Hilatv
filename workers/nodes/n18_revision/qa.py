"""N18 checks the change set, not the pixels."""

from __future__ import annotations

from workers.nodes.n18_revision.schema import NodeResult, RevisionPlan
from workers.schemas.director import RevisionDirective
from workers.schemas.script import Script


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> RevisionPlan | None:
    if result.node != "n18_revision":
        raise QAError(f"unexpected node {result.node}", retryable=False)
    if not result.ok:
        raise QAError("n18_revision result is not ok")
    status = str(result.payload.get("status") or "apply")
    if status != "apply":
        if result.payload.get("video_shots"):
            raise QAError("a question must not schedule video")
        question = str(result.payload.get("question") or "").strip()
        if status == "needs_clarification" and not question:
            raise QAError("clarification needs a question")
        if status == "not_supported" and not str(result.payload.get("notice") or "").strip():
            raise QAError("an unsupported edit needs an explanation")
        return None
    script = Script.model_validate(result.payload.get("script"))
    directive = RevisionDirective.model_validate(result.payload.get("directive"))
    plan = RevisionPlan.model_validate(
        {
            "nodes": result.payload.get("nodes") or [],
            "video_shots": result.payload.get("video_shots") or [],
            "reuse_shots": result.payload.get("reuse_shots") or [],
            "directive": directive,
        }
    )
    known = {shot.shot_id for shot in script.shots}
    if not known:
        raise QAError("script has no shots", retryable=False)
    if any(shot_id not in known for shot_id in directive.targets):
        raise QAError("directive names an unknown shot", retryable=False)
    if any(shot_id not in set(directive.targets) for shot_id in plan.video_shots):
        raise QAError("video rerun is outside the change targets")
    overlay_only = set(directive.change).issubset({"logo", "price", "phone"})
    if overlay_only and plan.video_shots:
        raise QAError("logo, price, or phone edits must not regenerate video")
    for shot in script.shots:
        if shot.shot_id in directive.targets and (
            "lighting" in directive.change or directive.change.get("visual") == "regenerate"
        ):
            if "无文字" not in shot.visual and "无任何文字" not in shot.visual:
                raise QAError(f"{shot.shot_id} visual is missing the no-text constraint")
    return plan
