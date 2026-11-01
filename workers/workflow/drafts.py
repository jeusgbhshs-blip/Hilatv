"""Durable drafts and single-submit claims, using the existing project lock/store.

No network calls run in a project transaction. A submission with an uncertain
external result remains claimed; a retry reads that claim instead of starting
another potentially billable workflow.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from workers.identity.session import canonical_enterprise
from workers.workflow.store import (
    init_project,
    locked_project,
    read_snapshot,
    update_snapshot,
    valid_project_id,
)

_NAMESPACE = uuid.UUID("f8071054-d0ad-4f78-9db4-8047b9933994")


class DraftError(ValueError):
    def __init__(self, code: str, message: str, snapshot: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.snapshot = snapshot
        self.status = 404 if code == "not_found" else 409


def owned_draft(project_id: str, enterprise_id: str) -> dict[str, Any]:
    snapshot = read_snapshot(project_id)
    owner = (snapshot or {}).get("enterprise_id")
    if not isinstance(owner, str) or canonical_enterprise(owner) != canonical_enterprise(
        enterprise_id
    ):
        raise DraftError("not_found", "项目不存在")
    return snapshot or {}


def draft_id(enterprise_id: str, operation_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{canonical_enterprise(enterprise_id)}:{operation_id}"))


def create_draft(
    *,
    operation_id: str,
    enterprise_id: str,
    member_id: str,
    fields: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    project_id = draft_id(enterprise_id, operation_id)
    fingerprint = hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    with locked_project(project_id):
        current = read_snapshot(project_id)
        if current is not None:
            current = owned_draft(project_id, enterprise_id)
            initial = current.get("_draft_create") or {}
            if (
                initial.get("operation_id") != operation_id
                or initial.get("fingerprint") != fingerprint
            ):
                raise DraftError("operation_conflict", "同一创建操作不能改写为另一份草稿", current)
            return current, False
        now = time.time()
        return (
            init_project(
                project_id,
                **fields,
                status="draft",
                phase="草稿",
                message="草稿已保存",
                started_at=None,
                created_at=now,
                updated_at=now,
                draft_revision=1,
                enterprise_id=enterprise_id,
                owner_member_id=member_id,
                submission_state="none",
                _draft_create={"operation_id": operation_id, "fingerprint": fingerprint},
            ),
            True,
        )


def save_draft(
    project_id: str,
    *,
    enterprise_id: str,
    revision: int,
    fields: dict[str, Any],
) -> dict[str, Any]:
    if not valid_project_id(project_id):
        raise DraftError("not_found", "项目不存在")
    with locked_project(project_id):
        current = owned_draft(project_id, enterprise_id)
        _editable(current)
        if revision != int(current.get("draft_revision") or 1):
            raise DraftError("draft_conflict", "草稿已在其他页面修改，请先核对已保存内容", current)
        updated = {
            **current,
            **fields,
            "draft_revision": revision + 1,
            "updated_at": time.time(),
            "message": "草稿已保存",
        }
        update_snapshot(
            project_id, **{key: value for key, value in updated.items() if key != "project_id"}
        )
        return updated


def _editable(snapshot: dict[str, Any]) -> None:
    if snapshot.get("_submission"):
        raise DraftError("submission_pending", "项目已提交，请等待提交结果", snapshot)
    if snapshot.get("status") != "draft":
        raise DraftError("project_not_editable", "只有尚未提交的草稿可以修改", snapshot)


def existing_submission(
    snapshot: dict[str, Any], operation_id: str, revision: int
) -> dict[str, Any] | None:
    submission = snapshot.get("_submission")
    if not isinstance(submission, dict):
        return None
    if submission.get("operation_id") != operation_id:
        raise DraftError("submission_pending", "这个项目已经提交，请等待原任务结果", snapshot)
    if submission.get("draft_revision") != revision:
        raise DraftError("operation_conflict", "同一提交操作不能引用不同的草稿版本", snapshot)
    return submission


def claim_submission(
    project_id: str,
    *,
    enterprise_id: str,
    operation_id: str,
    revision: int,
    legacy_sentence: str | None = None,
) -> tuple[dict[str, Any], bool]:
    with locked_project(project_id):
        current = owned_draft(project_id, enterprise_id)
        if existing_submission(current, operation_id, revision) is not None:
            return current, False
        _editable(current)
        if revision != int(current.get("draft_revision") or 1):
            raise DraftError("draft_conflict", "草稿版本已变化，请先保存再提交", current)
        sentence = legacy_sentence if legacy_sentence is not None else current.get("sentence")
        if not isinstance(sentence, str) or not sentence.strip():
            error = DraftError("sentence_required", "先写一句话", current)
            error.status = 422
            raise error
        workflow_id = f"{project_id}__film__{uuid.UUID(operation_id).hex}"
        claimed = {
            **current,
            "sentence": sentence.strip(),
            "workflow_id": workflow_id,
            "status": "submitting",
            "phase": "正在提交",
            "message": "正在确认生成任务，请勿重复提交",
            "submission_state": "pending",
            "submission_operation_id": operation_id,
            "submission_message": "正在确认生成任务，请勿重复提交",
            "_submission": {
                "operation_id": operation_id,
                "draft_revision": revision,
                "workflow_id": workflow_id,
                "state": "pending",
                "claimed_at": time.time(),
            },
        }
        update_snapshot(
            project_id, **{key: value for key, value in claimed.items() if key != "project_id"}
        )
        return claimed, True


def confirm_submission(project_id: str, operation_id: str, *, confirmed: bool) -> dict[str, Any]:
    with locked_project(project_id):
        snapshot = read_snapshot(project_id) or {}
        submission = snapshot.get("_submission") or {}
        if submission.get("operation_id") != operation_id:
            raise DraftError("operation_conflict", "提交操作已变化", snapshot)
        # A query failure must never regress an already acknowledged submission.
        confirmed = confirmed or submission.get("state") == "submitted"
        state = "submitted" if confirmed else "unknown_external_result"
        message = "生成任务已提交" if confirmed else "提交结果待确认，已保留草稿，请勿重复提交"
        snapshot["_submission"] = {**submission, "state": state}
        snapshot.update(submission_state=state, submission_message=message)
        if snapshot.get("status") == "submitting":
            snapshot.update(
                status="running" if confirmed else "submitting",
                message=message,
                phase="理解需求" if confirmed else "正在确认提交结果",
            )
            if confirmed:
                snapshot["started_at"] = time.time()
        update_snapshot(
            project_id, **{key: value for key, value in snapshot.items() if key != "project_id"}
        )
        return snapshot


def submission_response(snapshot: dict[str, Any]) -> dict[str, Any]:
    submission = snapshot.get("_submission") or {}
    return {
        "project_id": snapshot["project_id"],
        "workflow_id": submission.get("workflow_id"),
        "status": snapshot.get("status"),
        "operation_id": submission.get("operation_id"),
        "draft_revision": submission.get("draft_revision"),
        "submission_state": submission.get("state"),
        "message": snapshot.get("submission_message"),
    }
