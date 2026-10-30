"""Project ownership. The enterprise id comes from the session or the stored project."""

from __future__ import annotations

import time

from workers.identity.session import Identity, canonical_enterprise
from workers.workflow.store import append_audit_event, read_snapshot, valid_project_id


class AccessError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(AccessError):
    pass


class Conflict(AccessError):
    pass


def project_for(identity: Identity, project_id: str) -> dict:
    """Return the project only when it was stored under this session's enterprise."""

    if not valid_project_id(project_id):
        raise NotFound("项目不存在")
    snapshot = read_snapshot(project_id)
    owner = snapshot.get("enterprise_id") if isinstance(snapshot, dict) else None
    if not isinstance(snapshot, dict) or not isinstance(owner, str):
        raise NotFound("项目不存在")
    if canonical_enterprise(owner) != identity.enterprise_id:
        raise NotFound("项目不存在")
    return snapshot


def audit_human_release(identity: Identity, project_id: str) -> dict:
    """Record who released a held film. Does not start the workflow."""

    snapshot = project_for(identity, project_id)
    if snapshot.get("status") != "needs_human_review":
        raise Conflict("项目不在人工复核")
    append_audit_event(
        project_id,
        {
            "type": "human_review_released",
            "enterprise_id": identity.enterprise_id,
            "releaser": identity.member_id,
            "at": time.time(),
        },
    )
    return snapshot
