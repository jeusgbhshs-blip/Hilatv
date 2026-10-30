"""Terminal progress events. Not a SPEC node."""

from __future__ import annotations

from typing import Any

from temporalio import activity

from workers.logging import log_event
from workers.workflow.contract import PHASE
from workers.workflow.store import publish


@activity.defn(name="mark_failed")
def mark_failed(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload["project_id"])
    node = str(payload.get("node") or "workflow")
    error = str(payload.get("error") or "节点失败")[:500]
    publish(
        project_id,
        {
            "node": node,
            "phase": PHASE.get(node, "生成中"),
            "message": error,
            "status": "failed",
            "error": error,
            "attempt": 1,
        },
    )
    log_event(
        "workflow_failed",
        project_id=project_id,
        node=node,
        attempt=1,
        error=error,
    )
    return {"patch": {}}
