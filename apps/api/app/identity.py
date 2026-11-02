"""Bind each request to the enterprise named by its session token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from workers.identity.access import AccessError, Conflict, NotFound, project_for
from workers.identity.session import (
    Identity,
    SessionError,
    admin_secret_matches,
    bearer_token,
    live_mode,
    open_session,
    revoke_session,
    verify_session,
)

router = APIRouter()


class SessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def require_identity(
    authorization: Annotated[str | None, Header()] = None,
) -> Identity:
    """Bearer token only. ``?session=`` is not a credential on ordinary routes."""

    return _identity_from_token(bearer_token(authorization))


def require_frame_identity(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Identity:
    """Frame images may send the session in the query. Other routes may not."""

    query = request.query_params.get("session", "")
    token = bearer_token(authorization) or (query.strip() if isinstance(query, str) else "")
    return _identity_from_token(token)


def _identity_from_token(token: str | None) -> Identity:
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
def create_session(
    request: Request,
    body: SessionBody | None = None,
) -> dict[str, str]:
    """Issue a new enterprise. The body cannot name one.

    Mock mode keeps open registration. Live mode returns 403 unless the
    caller presents ``HILATV_SESSION_ADMIN_SECRET``.
    """

    del body
    import os

    public_ok = os.getenv("HILATV_ALLOW_PUBLIC_SESSION", "0").strip() == "1"
    if (
        live_mode()
        and not public_ok
        and not admin_secret_matches(request.headers.get("x-hilatv-admin-secret", ""))
    ):
        raise HTTPException(status_code=403, detail="live 模式不能公开注册企业")
    identity = open_session()
    return {
        "token": identity.token,
        "enterprise_id": identity.enterprise_id,
        "member_id": identity.member_id,
    }


@router.post("/v1/session/revoke")
def revoke_current_session(identity: Identity = Depends(require_identity)) -> dict[str, bool]:
    """Drop this token. Later requests with it are rejected."""

    revoke_session(identity.token)
    return {"revoked": True}
