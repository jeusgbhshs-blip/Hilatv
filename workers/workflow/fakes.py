"""In-memory activities for workflow tests. They do not call nodes or models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from workers.workflow.bookkeeping import mark_failed
from workers.workflow.contract import NODE_MESSAGE, PHASE, PIPELINE, SHOT_ACTION
from workers.workflow.messages import shot_message
from workers.workflow.store import publish, save_node

CALLS: list[str] = []
FAIL: set[str] = set()


def reset() -> None:
    CALLS.clear()
    FAIL.clear()


def _make(node: str) -> Any:
    action = SHOT_ACTION.get(node)

    @activity.defn(name=node)
    def _run(payload: dict[str, Any]) -> dict[str, Any]:
        CALLS.append(node)
        request = payload.get("request") or {}
        fail_nodes = request.get("fail_nodes") or []
        if node in FAIL or node in fail_nodes:
            raise ApplicationError(f"injected failure at {node}", non_retryable=True)
        project_id = str(payload["project_id"])
        if node == "n08_keyframe" and action:
            publish(
                project_id,
                {
                    "node": node,
                    "phase": PHASE[node],
                    "message": shot_message(3, action),
                    "status": "running",
                    "shot_id": "S03",
                    "shot_index": 3,
                    "attempt": 1,
                },
            )
        else:
            publish(
                project_id,
                {
                    "node": node,
                    "phase": PHASE[node],
                    "message": NODE_MESSAGE[node],
                    "status": "running",
                    "attempt": 1,
                },
            )
        patch: dict[str, Any] = {"touched": node}
        if node == "n15_compose":
            deliverable = Path(str(request["work_dir"])) / "n15" / "master.mp4"
            deliverable.parent.mkdir(parents=True, exist_ok=True)
            deliverable.write_bytes(b"")
            publish(
                project_id,
                {
                    "node": node,
                    "phase": "成片",
                    "message": "成片已就绪",
                    "status": "completed",
                    "attempt": 1,
                    "deliverable": str(deliverable),
                    "elapsed_s": 0.01,
                },
            )
            patch["deliverable"] = str(deliverable)
            patch["elapsed_s"] = 0.01
        save_node(project_id, node, patch)
        return {"patch": patch}

    _run.__name__ = node
    return _run


@activity.defn(name="storyboard_sync")
def storyboard_sync(payload: dict[str, Any]) -> dict[str, Any]:
    del payload
    CALLS.append("storyboard_sync")
    return {"patch": {}}


FAKE_ACTIVITIES = [_make(node) for node in PIPELINE] + [storyboard_sync, mark_failed]
