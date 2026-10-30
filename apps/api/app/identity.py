"""Bind each request to the enterprise named by its session token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from workers.identity.access import AccessError, Conflict, NotFound, project_for
from workers.identity.session import (
    Identity,
    SessionError,
    bearer_token,
    open_session,
    verify_session,
)

router = APIRouter()


class SessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def require_identity(
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[str | None, Query()] = None,
) -> Identity:
    token = bearer_token(authorization) or (session.strip() if isinstance(session, str) else "")
    if not token:
        raise HTTPException(status_code=401, detail="需要登录")
    try:
        return verify_session(token)
    except SessionError as exc:
        raise HTTPException(status_code=401, detail="会话无效") from exc


def owned_project(project_id: str, identity: Identity) -> dict:
    try:
        return project_for(identity, project_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc
    except AccessError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc


def http_access(exc: AccessError) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail="项目不存在")
    if isinstance(exc, Conflict):
        return HTTPException(status_code=409, detail=exc.detail)
    return HTTPException(status_code=403, detail=exc.detail)


@router.post("/v1/session")
def create_session(body: SessionBody | None = None) -> dict[str, str]:
    """Issue a new enterprise. The body cannot name one."""

    del body
    identity = open_session()
    return {
        "token": identity.token,
        "enterprise_id": identity.enterprise_id,
        "member_id": identity.member_id,
    }
