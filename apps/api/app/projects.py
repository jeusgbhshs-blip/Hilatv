"""Create a film from one sentence, then read per-shot progress."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from workers.nodes.n01_brief.schema import AttachmentRef
from workers.schemas.brand import BrandKit
from workers.workflow.contract import PIPELINE
from workers.workflow.service import start_film
from workers.workflow.store import (
    load_checkpoint,
    project_path,
    read_events,
    read_snapshot,
    valid_project_id,
)

router = APIRouter()


class CreateProject(BaseModel):
    sentence: str = Field(min_length=1, max_length=4000)
    brand_kit: dict[str, Any] | None = None
    brand_id: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class RerunProject(BaseModel):
    node: str = Field(min_length=1)


def _checked(body: CreateProject) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        kit = None
        if body.brand_kit is not None:
            kit = BrandKit.model_validate(body.brand_kit).model_dump(mode="json")
        attachments = [
            AttachmentRef.model_validate(item).model_dump(mode="json") for item in body.attachments
        ]
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return kit, attachments


def _snapshot_or_404(project_id: str) -> dict[str, Any]:
    if not valid_project_id(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    snapshot = read_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return snapshot


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    body = dict(snapshot)
    if body.get("status") == "running" and body.get("started_at"):
        body["elapsed_s"] = round(time.time() - float(body["started_at"]), 3)
    return body


@router.post("/v1/projects")
async def create_project(body: CreateProject) -> JSONResponse:
    kit, attachments = _checked(body)
    project_id = str(uuid.uuid4())
    workflow_id = await start_film(
        project_id=project_id,
        sentence=body.sentence,
        brand_kit=kit,
        brand_id=body.brand_id,
        attachments=attachments,
    )
    return JSONResponse(
        status_code=202,
        content={"project_id": project_id, "workflow_id": workflow_id, "status": "running"},
    )


@router.get("/v1/projects/{project_id}")
def project_status(project_id: str) -> dict[str, Any]:
    return _public_snapshot(_snapshot_or_404(project_id))


@router.post("/v1/projects/{project_id}/rerun")
async def rerun_project(project_id: str, body: RerunProject) -> JSONResponse:
    snapshot = _snapshot_or_404(project_id)
    if body.node not in PIPELINE:
        raise HTTPException(status_code=400, detail="未知节点")
    if snapshot.get("status") == "running":
        raise HTTPException(status_code=409, detail="项目仍在运行")
    checkpoint = None
    if body.node != PIPELINE[0]:
        checkpoint = load_checkpoint(project_id)
        index = PIPELINE.index(body.node)
        missing = [
            name for name in PIPELINE[:index] if name not in (checkpoint.get("completed") or [])
        ]
        if missing:
            raise HTTPException(status_code=409, detail=f"缺少上游结果：{missing[0]}")
    workflow_id = await start_film(
        project_id=project_id,
        sentence=str(snapshot.get("sentence") or ""),
        brand_kit=snapshot.get("brand_kit"),
        brand_id=snapshot.get("brand_id"),
        attachments=snapshot.get("attachments") or [],
        keyframe_candidates=snapshot.get("keyframe_candidates"),
        video_candidates=snapshot.get("video_candidates"),
        start_from=body.node,
        checkpoint=checkpoint,
    )
    return JSONResponse(
        status_code=202,
        content={"project_id": project_id, "workflow_id": workflow_id, "status": "running"},
    )


@router.get("/v1/projects/{project_id}/download")
def download_master(project_id: str) -> FileResponse:
    snapshot = _snapshot_or_404(project_id)
    raw = snapshot.get("deliverable")
    if not isinstance(raw, str) or not raw:
        raise HTTPException(status_code=404, detail="成片尚未就绪")
    path = Path(raw).resolve()
    root = project_path(project_id).resolve()
    if not path.is_file() or not path.is_relative_to(root):
        raise HTTPException(status_code=404, detail="成片文件不存在")
    return FileResponse(path, media_type="video/mp4", filename="master.mp4")


@router.websocket("/v1/projects/{project_id}/progress")
async def project_progress(websocket: WebSocket, project_id: str) -> None:
    await websocket.accept()
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        await websocket.send_json({"type": "error", "message": "项目不存在"})
        await websocket.close(code=4404)
        return
    sent = 0
    try:
        while True:
            events = read_events(project_id)
            for event in events[sent:]:
                await websocket.send_json(event)
                sent += 1
            snapshot = read_snapshot(project_id) or {}
            terminal = snapshot.get("status") in {"completed", "failed"}
            if terminal and sent >= len(read_events(project_id)):
                await websocket.close()
                return
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return
