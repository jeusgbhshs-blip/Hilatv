"""成员与角色（本地 mock）：团队设置页与离职交接用。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.identity import require_identity
from workers.identity import members as store
from workers.identity.session import Identity

router = APIRouter()


@router.get("/v1/members")
def list_members(identity: Identity = Depends(require_identity)) -> dict[str, Any]:
    return {"members": store.list_members(identity.enterprise_id, identity.member_id)}


class AddBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    role: str = Field(default="editor")


@router.post("/v1/members")
def add_member(body: AddBody, identity: Identity = Depends(require_identity)) -> dict[str, Any]:
    try:
        row = store.add_member(identity.enterprise_id, body.name, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return row


class PatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    status: str | None = None


@router.patch("/v1/members/{member_id}")
def patch_member(
    member_id: str, body: PatchBody, identity: Identity = Depends(require_identity)
) -> dict[str, Any]:
    try:
        return store.update_member(
            identity.enterprise_id, member_id, role=body.role, status=body.status
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/v1/members/{member_id}")
def delete_member(member_id: str, identity: Identity = Depends(require_identity)) -> dict[str, Any]:
    if member_id == identity.member_id:
        raise HTTPException(status_code=422, detail="不能删除自己")
    store.remove_member(identity.enterprise_id, member_id)
    return {"deleted": member_id}


class HandoverBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_member_id: str = Field(min_length=1)


@router.post("/v1/members/{member_id}/handover")
def handover(
    member_id: str, body: HandoverBody, identity: Identity = Depends(require_identity)
) -> dict[str, Any]:
    if member_id == body.to_member_id:
        raise HTTPException(status_code=422, detail="交接对象不能是自己")
    try:
        store.update_member(identity.enterprise_id, member_id, role=None, status="departed")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    moved = store.handover_projects(member_id, body.to_member_id, identity.enterprise_id)
    return {"departed": member_id, "to_member_id": body.to_member_id, "projects_moved": moved}
