"""Version list for the delivery page. The web player is T11."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from workers.nodes.n17_deliver.node import run
from workers.nodes.n17_deliver.qa import QAError
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import Script
from workers.workflow.store import (
    project_path,
    project_root,
    read_snapshot,
    update_snapshot,
    valid_project_id,
)

router = APIRouter()


class DeliverBody(BaseModel):
    aspect_ratios: list[str] | None = None
    languages: list[str] | None = None
    durations_s: list[float] | None = None
    long_edge: int | None = Field(default=None, ge=64, le=3840)
    regenerate_vertical: bool | None = None
    master_path: str | None = None
    script: dict[str, Any] | None = None
    brief: dict[str, Any] | None = None
    brand_kit: dict[str, Any] | None = None
    subject_tracks: list[dict[str, Any]] | None = None


def _snapshot_or_404(project_id: str) -> dict[str, Any]:
    if not valid_project_id(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    snapshot = read_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return snapshot


def _pick(body: dict[str, Any] | None, snapshot: dict[str, Any], key: str) -> Any:
    if body is not None:
        return body
    return snapshot.get(key)


@router.post("/v1/projects/{project_id}/deliveries")
def create_delivery(project_id: str, body: DeliverBody) -> dict[str, Any]:
    snapshot = _snapshot_or_404(project_id)
    payload = _payload(project_id, snapshot, body)
    try:
        result = run({"project_id": project_id, "payload": payload})
    except QAError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    versions = [_public(project_id, item) for item in result.payload["versions"]]
    record = {
        "versions": versions,
        "files": {item["version_id"]: item["path"] for item in result.payload["versions"]},
        "rights": result.payload["rights"],
    }
    path = project_path(project_id) / "deliveries.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_snapshot(project_id, versions=versions, rights=result.payload["rights"])
    return {"project_id": project_id, "versions": versions, "rights": result.payload["rights"]}


@router.get("/v1/projects/{project_id}/versions")
def list_versions(project_id: str) -> dict[str, Any]:
    _snapshot_or_404(project_id)
    record = _read(project_id)
    return {
        "project_id": project_id,
        "versions": record.get("versions") or [],
        "rights": record.get("rights") or {},
    }


@router.get("/v1/projects/{project_id}/versions/{version_id}")
def read_version(project_id: str, version_id: str) -> dict[str, Any]:
    _snapshot_or_404(project_id)
    found = _find(project_id, version_id)
    return found


@router.get("/v1/projects/{project_id}/versions/{version_id}/download")
def download_version(project_id: str, version_id: str) -> FileResponse:
    _snapshot_or_404(project_id)
    return _file(project_id, version_id)


@router.post("/v1/projects/{project_id}/versions/{version_id}/share")
def share_version(project_id: str, version_id: str) -> dict[str, str]:
    _snapshot_or_404(project_id)
    _find(project_id, version_id)
    token = secrets.token_urlsafe(18)
    folder = project_root() / "shares"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{token}.json").write_text(
        json.dumps({"project_id": project_id, "version_id": version_id}) + "\n",
        encoding="utf-8",
    )
    share_path = f"/v1/shares/{token}"
    record = _read(project_id)
    for item in record.get("versions") or []:
        if item.get("version_id") == version_id:
            item["share_path"] = share_path
    _write(project_id, record)
    update_snapshot(project_id, versions=record.get("versions") or [])
    return {"version_id": version_id, "share_path": share_path, "token": token}


@router.get("/v1/shares/{token}")
def open_share(token: str) -> FileResponse:
    if not token.isalnum() and not all(char.isalnum() or char in "-_" for char in token):
        raise HTTPException(status_code=404, detail="分享不存在")
    path = project_root() / "shares" / f"{token}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="分享不存在")
    body = json.loads(path.read_text(encoding="utf-8"))
    return _file(str(body["project_id"]), str(body["version_id"]))


def _payload(project_id: str, snapshot: dict[str, Any], body: DeliverBody) -> dict[str, Any]:
    script = _pick(body.script, snapshot, "script")
    brief = _pick(body.brief, snapshot, "brief")
    master = body.master_path or snapshot.get("master_plate")
    tracks = body.subject_tracks
    if tracks is None:
        tracks = snapshot.get("subject_tracks")
    if not isinstance(script, dict) or not isinstance(brief, dict) or not isinstance(master, str):
        raise HTTPException(status_code=409, detail="成片母版或脚本还没准备好")
    try:
        Script.model_validate(script)
        Brief.model_validate(brief)
        brand = _pick(body.brand_kit, snapshot, "brand_kit")
        if brand is not None:
            BrandKit.model_validate(brand)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    work = project_path(project_id) / "deliveries"
    work.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "script": script,
        "brief": brief,
        "brand_kit": brand,
        "master_path": master,
        "subject_tracks": tracks or [],
        "work_dir": str(work),
    }
    if body.aspect_ratios is not None:
        payload["aspect_ratios"] = body.aspect_ratios
    elif isinstance(brief.get("aspect_ratios"), list):
        payload["aspect_ratios"] = brief["aspect_ratios"]
    if body.languages is not None:
        payload["languages"] = body.languages
    if body.durations_s is not None:
        payload["durations_s"] = body.durations_s
    if body.long_edge is not None:
        payload["long_edge"] = body.long_edge
    if body.regenerate_vertical is not None:
        payload["regenerate_vertical"] = body.regenerate_vertical
    return payload


def _public(project_id: str, version: dict[str, Any]) -> dict[str, Any]:
    version_id = version["version_id"]
    return {
        "version_id": version_id,
        "aspect_ratio": version["aspect_ratio"],
        "language": version["language"],
        "duration_s": version["duration_s"],
        "width": version["width"],
        "height": version["height"],
        "modes": version["modes"],
        "download_path": f"/v1/projects/{project_id}/versions/{version_id}/download",
        "share_path": None,
    }


def _read(project_id: str) -> dict[str, Any]:
    path = project_path(project_id) / "deliveries.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write(project_id: str, record: dict[str, Any]) -> None:
    path = project_path(project_id) / "deliveries.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _find(project_id: str, version_id: str) -> dict[str, Any]:
    for item in _read(project_id).get("versions") or []:
        if item.get("version_id") == version_id:
            return item
    raise HTTPException(status_code=404, detail="版本不存在")


def _file(project_id: str, version_id: str) -> FileResponse:
    record = _read(project_id)
    raw = (record.get("files") or {}).get(version_id)
    if not isinstance(raw, str):
        raise HTTPException(status_code=404, detail="版本不存在")
    path = Path(raw).resolve()
    root = project_path(project_id).resolve()
    if not path.is_file() or not path.is_relative_to(root):
        raise HTTPException(status_code=404, detail="成片文件不存在")
    return FileResponse(path, media_type="video/mp4", filename=f"{version_id}.mp4")
