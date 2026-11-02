"""画布多镜头合成：把当前所有镜头、配音、字幕和包装重新合成为一条 MP4。

只重跑 N13 字幕 → N14 包装 → N15 合成；不重做画面生成，不花图片/视频的钱。
被人工复核拦住时拒绝合成（和流水线交付门一致）。
"""

from __future__ import annotations

from typing import Any

from workers.expert.gates import GateError
from workers.expert.invoke import invoke_node
from workers.expert.operations import GenerationOperation, run_generation
from workers.logging import log_event
from workers.workflow.film import needs_human_review
from workers.workflow.store import (
    load_checkpoint,
    read_snapshot,
    save_node,
    update_snapshot,
    valid_project_id,
)

_BASE_SPAN = ("n14_packaging", "n15_compose")


def compose_from_canvas(
    project_id: str, body: dict[str, Any] | None = None, *, gateway: Any | None = None
) -> dict[str, Any]:
    """Re-compose the film from the current canvas state."""

    payload = body or {}
    return run_generation(
        project_id,
        operation_id=payload.get("operation_id"),
        kind="canvas_compose",
        target=project_id,
        request={"version": 1},
        action=lambda operation: _compose(project_id, operation, gateway=gateway),
    )


def _compose(
    project_id: str,
    operation: GenerationOperation,
    *,
    gateway: Any | None = None,
) -> dict[str, Any]:
    if not valid_project_id(project_id):
        raise GateError("项目不存在", status=404)
    snapshot = read_snapshot(project_id)
    if snapshot is None:
        raise GateError("项目不存在", status=404)
    if snapshot.get("status") == "running":
        raise GateError("项目仍在运行", status=409)
    state = load_checkpoint(project_id)
    script = state.get("script")
    if not isinstance(script, dict) or not script.get("shots"):
        raise GateError("还没有分镜，先生成分镜", status=409)
    released = any(
        isinstance(item, dict) and item.get("type") == "human_review_released"
        for item in (snapshot.get("events") or [])
    )
    if needs_human_review(state, {}) and not released:
        raise GateError("有镜头未经视觉评审，先人工放行再合成", status=409)
    enterprise_id = snapshot.get("enterprise_id")
    owner = enterprise_id if isinstance(enterprise_id, str) else None
    from gateway import get_gateway

    engine = operation.gateway(gateway or get_gateway())
    operation.capture(
        int(snapshot.get("operation_revision") or 0),
        {"script_hash": len(str(script.get("script_id") or "")), "at": "canvas"},
    )
    span = (("n13_subtitle",) if state.get("voiceovers") else ()) + _BASE_SPAN
    for name in span:
        patch = invoke_node(
            name,
            project_id=project_id,
            state=state,
            snapshot=snapshot,
            gateway=engine,
            enterprise_id=owner,
            released=released,
        )
        save_node(project_id, name, patch)
        state.update(patch)
        completed = [item for item in (state.get("completed") or []) if item != name]
        completed.append(name)
        state["completed"] = completed
        log_event(
            "canvas_compose_node",
            project_id=project_id,
            node=name,
            attempt=1,
        )
    deliverable = state.get("deliverable")
    if not isinstance(deliverable, str) or not deliverable:
        exports = state.get("exports") if isinstance(state.get("exports"), dict) else {}
        master = exports.get("master")
        deliverable = master if isinstance(master, str) else None
    if deliverable is None:
        raise GateError("合成没有产出成片", status=502)
    update_snapshot(
        project_id,
        status="completed",
        phase="成片",
        node="n15_compose",
        message="画布合成完成",
        deliverable=deliverable,
        error=None,
    )
    from workers.expert.canvas import build_canvas

    return {
        "project_id": project_id,
        "deliverable": deliverable,
        "exports": state.get("exports"),
        "canvas": build_canvas(project_id),
    }
