"""只读分享链接与项目复制（企业隔离；分享链接不需要登录）。"""

from __future__ import annotations

import json
import secrets
import shutil
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.identity import owned_project, require_identity
from workers.expert.canvas import media_file
from workers.identity.session import Identity
from workers.logging import log_event
from workers.workflow.store import (
    init_project,
    load_checkpoint,
    project_path,
    read_snapshot,
    valid_project_id,
)

router = APIRouter()

_ROLES = {"view", "view_no_download"}


def _shares_path(project_id: str):
    return project_path(project_id, create=True) / "shares.json"


def _read_shares(project_id: str) -> dict[str, dict[str, Any]]:
    path = _shares_path(project_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_shares(project_id: str, data: dict[str, dict[str, Any]]) -> None:
    _shares_path(project_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class ShareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(default="view")


@router.post("/v1/projects/{project_id}/shares")
def create_share(
    project_id: str,
    body: ShareBody,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    owned_project(project_id, identity)
    if body.role not in _ROLES:
        raise HTTPException(status_code=422, detail="分享权限不对")
    token = secrets.token_urlsafe(18)
    data = _read_shares(project_id)
    data[token] = {"role": body.role, "created_at": time.time()}
    _write_shares(project_id, data)
    log_event("share_created", service="hilatv-api", project_id=project_id, role=body.role)
    return {"token": token, "role": body.role, "url": f"/share/{token}"}


@router.get("/v1/projects/{project_id}/shares")
def list_shares(project_id: str, identity: Identity = Depends(require_identity)) -> dict[str, Any]:
    owned_project(project_id, identity)
    rows = [
        {
            "token": token,
            "role": item.get("role"),
            "created_at": item.get("created_at"),
            "url": f"/share/{token}",
        }
        for token, item in _read_shares(project_id).items()
    ]
    return {"shares": rows}


@router.delete("/v1/projects/{project_id}/shares/{token}")
def delete_share(
    project_id: str, token: str, identity: Identity = Depends(require_identity)
) -> dict[str, Any]:
    owned_project(project_id, identity)
    data = _read_shares(project_id)
    if token not in data:
        raise HTTPException(status_code=404, detail="没有这个分享")
    data.pop(token, None)
    _write_shares(project_id, data)
    return {"deleted": token}


def _share_or_404(token: str) -> tuple[str, dict[str, Any]]:
    for project_id in _candidate_projects():
        data = _read_shares(project_id)
        if token in data:
            return project_id, data[token]
    raise HTTPException(status_code=404, detail="分享链接无效或已失效")


def _candidate_projects() -> list[str]:
    from workers.workflow.store import project_root

    root = project_root()
    if not root.is_dir():
        return []
    return [
        entry.name for entry in root.iterdir() if entry.is_dir() and valid_project_id(entry.name)
    ]


@router.get("/v1/share-links/{token}")
def read_share(token: str) -> dict[str, Any]:
    project_id, item = _share_or_404(token)
    snapshot = read_snapshot(project_id) or {}
    state = load_checkpoint(project_id)
    shots: list[dict[str, Any]] = []
    for row in (state.get("script") or {}).get("shots") or []:
        shot_id = str(row.get("shot_id") or "")
        if not shot_id:
            continue
        frames = [item for item in state.get("keyframes") or [] if item.get("shot_id") == shot_id]
        videos = [item for item in state.get("videos") or [] if item.get("shot_id") == shot_id]
        shots.append(
            {
                "shot_id": shot_id,
                "index": int(row.get("order") or len(shots) + 1),
                "duration_s": row.get("duration_s"),
                "voiceover": row.get("voiceover") or "",
                "frames": len(frames),
                "videos": len(videos),
            }
        )
    return {
        "role": item.get("role"),
        "sentence": snapshot.get("sentence") or "",
        "status": snapshot.get("status") or "",
        "phase": snapshot.get("phase") or "",
        "message": snapshot.get("message") or "",
        "shots": shots,
        "ai_label": True,
        "download_allowed": item.get("role") != "view_no_download",
        "has_film": bool(snapshot.get("deliverable")),
    }


@router.get("/v1/share-links/{token}/media/{candidate_id}")
def read_share_media(token: str, candidate_id: str) -> FileResponse:
    project_id, _item = _share_or_404(token)
    path = media_file(project_id, candidate_id)
    if path is None:
        raise HTTPException(status_code=404, detail="没有可看的画面")
    return FileResponse(path, filename=path.name)


@router.post("/v1/projects/{project_id}/copy")
async def copy_project(
    project_id: str, identity: Identity = Depends(require_identity)
) -> JSONResponse:
    owned_project(project_id, identity)
    snapshot = read_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    new_id = str(uuid.uuid4())
    init_project(
        new_id,
        sentence=f"{snapshot.get('sentence') or '未命名项目'}（副本）",
        status="draft",
        phase="画布",
        message="从另一个项目复制过来的画布",
        enterprise_id=identity.enterprise_id,
        shots=[],
        events=[],
        attachments=snapshot.get("attachments") or [],
        brand_kit=snapshot.get("brand_kit"),
        work_dir=str(project_path(new_id)),
    )
    source = project_path(project_id)
    target = project_path(new_id, create=True)
    nodes_dir = source / "nodes"
    if nodes_dir.is_dir():
        shutil.copytree(nodes_dir, target / "nodes", dirs_exist_ok=True)
    canvas = source / "canvas.json"
    if canvas.is_file():
        shutil.copy2(canvas, target / "canvas.json")
    return JSONResponse(status_code=201, content={"project_id": new_id, "copied_from": project_id})
