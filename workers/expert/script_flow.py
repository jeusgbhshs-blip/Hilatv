"""画布上的一句话：从原话直接长出分镜（不跑完整条片）。"""

from __future__ import annotations

from typing import Any

from workers.expert.gates import GateError
from workers.expert.invoke import invoke_node
from workers.logging import log_event
from workers.workflow.store import (
    load_checkpoint,
    read_snapshot,
    save_node,
    update_snapshot,
    valid_project_id,
)


def build_storyboard(
    project_id: str, sentence: str, *, gateway: Any | None = None
) -> dict[str, Any]:
    """Run N1 brief → N4 script → N5 storyboard on a blank canvas project."""

    if not valid_project_id(project_id):
        raise GateError("项目不存在", status=404)
    snapshot = read_snapshot(project_id)
    if snapshot is None:
        raise GateError("项目不存在", status=404)
    if snapshot.get("status") == "running":
        raise GateError("项目仍在运行", status=409)
    state = load_checkpoint(project_id)
    if state.get("videos") or state.get("keyframes"):
        raise GateError("这个项目已经有画面了，请在镜头卡上重做", status=409)

    text = sentence.strip() or str(snapshot.get("sentence") or "").strip()
    if not text:
        raise GateError("先写一句话")
    if text != snapshot.get("sentence"):
        update_snapshot(project_id, sentence=text)
        snapshot = read_snapshot(project_id) or snapshot

    for name in ("n01_brief", "n04_script", "n05_storyboard"):
        patch = invoke_node(
            name,
            project_id=project_id,
            state=state,
            snapshot=snapshot,
            gateway=gateway,
        )
        save_node(project_id, name, patch)
        state.update(patch)

    shots = (state.get("script") or {}).get("shots") or []
    summaries = [
        {
            "shot_id": str(shot.get("shot_id") or ""),
            "order": int(shot.get("order") or index + 1),
            "purpose": str(shot.get("purpose") or ""),
        }
        for index, shot in enumerate(shots)
        if isinstance(shot, dict)
    ]
    state["shot_summaries"] = summaries
    update_snapshot(
        project_id,
        status="draft",
        phase="看分镜",
        message=f"分镜已生成：{len(shots)} 个镜头",
        shots=summaries,
    )
    log_event(
        "canvas_storyboard",
        project_id=project_id,
        node="n05_storyboard",
        attempt=1,
        shots=len(shots),
    )
    from workers.expert.canvas import build_canvas

    return build_canvas(project_id)
