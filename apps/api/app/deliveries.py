"""Version list for the delivery page. The web player is T11."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.delivery_gate import media_response, public_readiness, public_rights
from app.identity import owned_project, require_frame_identity, require_identity
from workers.identity.session import Identity
from workers.nodes.n17_deliver.node import run
from workers.nodes.n17_deliver.qa import QAError
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import Script
from workers.workflow.readiness import readiness, state_from_directory
from workers.workflow.store import (
    contained_file,
    load_checkpoint,
    project_path,
    project_root,
    read_snapshot,
    update_snapshot,
    valid_project_id,
)
from workers.workflow.versions import VersionError
from workers.workflow.versions import list_versions as revision_versions

router = APIRouter()

_EXPORT_LOCK = threading.Lock()
_EXPORTS_IN_FLIGHT = 0
_SHARE_TTL_S = 7 * 24 * 60 * 60


class DeliverBody(BaseModel):
    """Export options. A master path is not a field: the body cannot name a file."""

    model_config = ConfigDict(extra="forbid")

    aspect_ratios: list[str] | None = None
    languages: list[str] | None = None
    durations_s: list[float] | None = None
    long_edge: int | None = Field(default=None, ge=64, le=3840)
    regenerate_vertical: bool | None = None
    script: dict[str, Any] | None = None
    brief: dict[str, Any] | None = None
    brand_kit: dict[str, Any] | None = None
    subject_tracks: list[dict[str, Any]] | None = None


def _snapshot_or_404(project_id: str, identity: Identity) -> dict[str, Any]:
    return owned_project(project_id, identity)


def _checkpoint(project_id: str) -> dict[str, Any]:
    try:
        found = load_checkpoint(project_id)
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _export_limit() -> int:
    raw = os.getenv("HILATV_N17_EXPORT_SLOTS", "2").strip() or "2"
    try:
        return max(0, int(raw))
    except ValueError:
        return 2


def _acquire_export() -> bool:
    global _EXPORTS_IN_FLIGHT
    with _EXPORT_LOCK:
        if _EXPORTS_IN_FLIGHT >= _export_limit():
            return False
        _EXPORTS_IN_FLIGHT += 1
        return True


def _release_export() -> None:
    global _EXPORTS_IN_FLIGHT
    with _EXPORT_LOCK:
        _EXPORTS_IN_FLIGHT = max(0, _EXPORTS_IN_FLIGHT - 1)


@router.post("/v1/projects/{project_id}/deliveries")
def create_delivery(
    project_id: str,
    body: DeliverBody,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    snapshot = _snapshot_or_404(project_id, identity)
    if not _acquire_export():
        raise HTTPException(status_code=429, detail="导出太多，请稍后再试")
    try:
        payload = _payload(project_id, snapshot, body)
        try:
            result = run({"project_id": project_id, "payload": payload})
        except QAError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        versions = [_public(project_id, item) for item in result.payload["versions"]]
        files = {
            item["version_id"]: item["path"]
            for item in result.payload["versions"]
            if isinstance(item.get("path"), str)
        }
        record = _merge_record(project_id, versions, files, result.payload.get("rights") or {})
    finally:
        _release_export()
    update_snapshot(project_id, versions=record.get("versions") or [], rights=record.get("rights"))
    return {
        "project_id": project_id,
        "exported_version_ids": [item["version_id"] for item in versions],
        "versions": [
            _version_public(project_id, item, snapshot) for item in record.get("versions") or []
        ],
        "rights": public_rights(record.get("rights")),
    }


@router.get("/v1/projects/{project_id}/versions")
def list_versions(
    project_id: str,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    snapshot = _snapshot_or_404(project_id, identity)
    record = _read(project_id)
    return {
        "project_id": project_id,
        "versions": [
            _version_public(project_id, item, snapshot) for item in record.get("versions") or []
        ],
        "rights": public_rights(record.get("rights")),
    }


@router.get("/v1/projects/{project_id}/versions/{version_id}")
def read_version(
    project_id: str,
    version_id: str,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    snapshot = _snapshot_or_404(project_id, identity)
    return _version_public(project_id, _find(project_id, version_id), snapshot)


@router.get("/v1/projects/{project_id}/versions/{version_id}/download")
def download_version(
    project_id: str,
    version_id: str,
    identity: Identity = Depends(require_identity),
) -> FileResponse:
    snapshot = _snapshot_or_404(project_id, identity)
    return _file(project_id, version_id, snapshot=snapshot)


@router.get("/v1/projects/{project_id}/versions/{version_id}/preview")
@router.head("/v1/projects/{project_id}/versions/{version_id}/preview", include_in_schema=False)
def preview_version(
    project_id: str,
    version_id: str,
    identity: Identity = Depends(require_frame_identity),
) -> FileResponse:
    snapshot = _snapshot_or_404(project_id, identity)
    return _file(project_id, version_id, snapshot=snapshot, preview=True)


@router.post("/v1/projects/{project_id}/versions/{version_id}/share")
def share_version(
    project_id: str,
    version_id: str,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    snapshot = _snapshot_or_404(project_id, identity)
    version = _version_public(project_id, _find(project_id, version_id), snapshot)
    token = secrets.token_urlsafe(18)
    expires_at = time.time() + _share_ttl()
    share_path = f"/v1/shares/{token}"
    with _locked(project_id) as directory:
        record = _read_unlocked(directory)
        if not any(item.get("version_id") == version_id for item in record.get("versions") or []):
            raise HTTPException(status_code=404, detail="版本不存在")
        shares = dict(record.get("shares") or {})
        shares[token] = {
            "version_id": version_id,
            "expires_at": expires_at,
            "enterprise_id": snapshot["enterprise_id"],
            "media_hash": version.get("media_hash"),
        }
        for item in record.get("versions") or []:
            if item.get("version_id") == version_id:
                item["share_path"] = share_path
                item["share_expires_at"] = expires_at
        record["shares"] = shares
        _write_unlocked(directory, record)
    folder = project_root() / "shares"
    folder.mkdir(parents=True, exist_ok=True)
    _replace_json(
        folder / f"{token}.json",
        {"project_id": project_id, **shares[token]},
    )
    update_snapshot(project_id, versions=record.get("versions") or [])
    return {
        "version_id": version_id,
        "share_path": share_path,
        "token": token,
        "expires_at": expires_at,
        "delivery_status": version["delivery_status"],
        "download_allowed": version["delivery_status"] == "ready",
        "owner_preview_path": version["preview_path"],
        "message": "分享原件需通过正式交付核验；项目成员可登录预览",
    }


@router.delete("/v1/projects/{project_id}/versions/{version_id}/share")
def revoke_share(
    project_id: str,
    version_id: str,
    identity: Identity = Depends(require_identity),
) -> Response:
    _snapshot_or_404(project_id, identity)
    with _locked(project_id) as directory:
        record = _read_unlocked(directory)
        if not any(item.get("version_id") == version_id for item in record.get("versions") or []):
            raise HTTPException(status_code=404, detail="版本不存在")
        shares = dict(record.get("shares") or {})
        removed = [token for token, item in shares.items() if item.get("version_id") == version_id]
        for token in removed:
            shares.pop(token, None)
        for item in record.get("versions") or []:
            if item.get("version_id") == version_id:
                item["share_path"] = None
                item.pop("share_expires_at", None)
        record["shares"] = shares
        _write_unlocked(directory, record)
    for token in removed:
        (project_root() / "shares" / f"{token}.json").unlink(missing_ok=True)
    update_snapshot(project_id, versions=record.get("versions") or [])
    return Response(status_code=204)


@router.get("/v1/shares/{token}")
def open_share(token: str) -> FileResponse:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", token) is None:
        raise HTTPException(status_code=404, detail="分享不存在")
    path = project_root() / "shares" / f"{token}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="分享不存在")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="分享不存在") from None
    expires_at = body.get("expires_at")
    if not isinstance(expires_at, int | float) or time.time() >= float(expires_at):
        raise HTTPException(status_code=410, detail="分享已过期")
    project_id = str(body.get("project_id") or "")
    if not valid_project_id(project_id):
        raise HTTPException(status_code=404, detail="分享不存在")
    snapshot = read_snapshot(project_id)
    stored = (_read(project_id).get("shares") or {}).get(token) or {}
    if (
        not snapshot
        or stored.get("version_id") != body.get("version_id")
        or stored.get("expires_at") != body.get("expires_at")
        or stored.get("enterprise_id") != body.get("enterprise_id")
        or stored.get("media_hash") != body.get("media_hash")
        or body.get("enterprise_id") != snapshot.get("enterprise_id")
        or not body.get("media_hash")
    ):
        raise HTTPException(status_code=410, detail="分享已更新，请负责人重新创建链接")
    return _file(
        project_id,
        str(body["version_id"]),
        snapshot=snapshot,
        expected_hash=str(body["media_hash"]),
    )


def _share_ttl() -> float:
    raw = os.getenv("HILATV_SHARE_TTL_S", str(_SHARE_TTL_S)).strip() or str(_SHARE_TTL_S)
    try:
        return float(raw)
    except ValueError:
        return float(_SHARE_TTL_S)


def _payload(project_id: str, snapshot: dict[str, Any], body: DeliverBody) -> dict[str, Any]:
    saved = _checkpoint(project_id)
    script = (
        body.script
        or saved.get("rendered_script")
        or saved.get("aligned_script")
        or snapshot.get("script")
        or saved.get("script")
    )
    brief = body.brief or snapshot.get("brief") or saved.get("brief")
    tracks = body.subject_tracks
    if tracks is None:
        tracks = snapshot.get("subject_tracks")
    if tracks is None:
        tracks = saved.get("subject_tracks")
    master = _master_in_project(project_id, snapshot, saved)
    if not isinstance(script, dict) or not isinstance(brief, dict):
        raise HTTPException(status_code=409, detail="成片母版或脚本还没准备好")
    try:
        Script.model_validate(script)
        Brief.model_validate(brief)
        brand = body.brand_kit
        if brand is None:
            brand = snapshot.get("brand_kit")
        if brand is None:
            brand = saved.get("brand_kit")
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
        "picture_path": saved.get("clean_picture_path")
        or (saved.get("exports") or {}).get("clean_picture"),
        "source_timeline": saved.get("timeline"),
        "target_duration_s": (saved.get("timeline") or {}).get("target_duration_s")
        or (saved.get("production_clock") or {}).get("target_duration_s")
        or (snapshot.get("generation_settings") or {}).get("duration_s"),
        "intro_s": saved.get("intro_s") or 0,
        "outro_s": saved.get("outro_s"),
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


def _master_in_project(project_id: str, snapshot: dict[str, Any], saved: dict[str, Any]) -> str:
    raw = (
        snapshot.get("preview_path")
        or snapshot.get("deliverable")
        or saved.get("deliverable")
        or snapshot.get("master_plate")
    )
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=409, detail="成片母版或脚本还没准备好")
    root = project_path(project_id).resolve()
    path = Path(raw).expanduser().resolve()
    if not path.is_file() or not path.is_relative_to(root):
        raise HTTPException(status_code=422, detail="成片母版不在项目目录内")
    return str(path)


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
        "subject_box_source": version.get("subject_box_source") or "default",
        "qa_status": version.get("qa_status") or "needs_review",
        "source_key": version.get("source_key"),
        "source_media_hash": version.get("source_media_hash"),
        "download_path": f"/v1/projects/{project_id}/versions/{version_id}/download",
        "preview_path": f"/v1/projects/{project_id}/versions/{version_id}/preview",
        "share_path": None,
    }


def _merge_record(
    project_id: str,
    versions: list[dict[str, Any]],
    files: dict[str, str],
    rights: dict[str, Any],
) -> dict[str, Any]:
    with _locked(project_id) as directory:
        record = _read_unlocked(directory)
        current = {item.get("version_id"): item for item in record.get("versions") or []}
        stored = dict(record.get("files") or {})
        stored.update(files)
        for item in versions:
            previous = current.get(item["version_id"]) or {}
            merged = dict(item)
            if previous.get("share_path"):
                merged["share_path"] = previous.get("share_path")
                merged["share_expires_at"] = previous.get("share_expires_at")
            current[item["version_id"]] = merged
        record["versions"] = [item for item in current.values() if item]
        record["files"] = stored
        record["rights"] = rights or record.get("rights") or {}
        record.setdefault("shares", {})
        _write_unlocked(directory, record)
        return record


def _read(project_id: str) -> dict[str, Any]:
    with _locked(project_id) as directory:
        return _read_unlocked(directory)


def _write(project_id: str, record: dict[str, Any]) -> None:
    with _locked(project_id) as directory:
        _write_unlocked(directory, record)


def _read_unlocked(directory: Path) -> dict[str, Any]:
    path = directory / "deliveries.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_unlocked(directory: Path, record: dict[str, Any]) -> None:
    _replace_json(directory / "deliveries.json", record)


def _replace_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@contextmanager
def _locked(project_id: str) -> Iterator[Path]:
    directory = project_path(project_id, create=True)
    handle = (directory / ".deliveries.lock").open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield directory
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _find(project_id: str, version_id: str) -> dict[str, Any]:
    for item in _read(project_id).get("versions") or []:
        if item.get("version_id") == version_id:
            return item
    if re.fullmatch(r"[a-f0-9]{32}", version_id):
        try:
            for item in revision_versions(project_id).get("versions") or []:
                if item.get("version_id") == version_id:
                    return item
        except VersionError:
            pass
    raise HTTPException(status_code=404, detail="版本不存在")


def _version_source(
    project_id: str, version_id: str
) -> tuple[Path, dict[str, Any] | None, dict[str, bool]]:
    record = _read(project_id)
    raw = (record.get("files") or {}).get(version_id)
    state = None
    flags = {}
    if not isinstance(raw, str) and re.fullmatch(r"[a-f0-9]{32}", version_id):
        _find(project_id, version_id)
        raw = str(project_path(project_id) / "versions" / version_id / "master.mp4")
        state = state_from_directory(Path(raw).parent)
        try:
            manifest = json.loads((Path(raw).parent / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(status_code=404, detail="版本记录不可读取") from None
        if not isinstance(manifest, dict):
            raise HTTPException(status_code=404, detail="版本记录不可读取")
        flags = {
            "concept_degraded": manifest.get("concept_degraded") is True,
            "revision_incomplete": manifest.get("revision_incomplete") is True,
        }
    located = contained_file(project_id, raw)
    if not located:
        raise HTTPException(status_code=404, detail="成片文件不存在")
    return Path(located), state, flags


def _version_public(
    project_id: str, item: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    public = {
        key: value
        for key, value in item.items()
        if key not in {"path", "media_path", "picture_path"}
    }
    version_id = str(item["version_id"])
    try:
        path, state, flags = _version_source(project_id, version_id)
        view = readiness({**snapshot, **flags}, state, path)
    except HTTPException:
        view = readiness(snapshot, {}, media=project_path(project_id) / ".missing-version")
    public.update(public_readiness(view))
    public["preview_path"] = f"/v1/projects/{project_id}/versions/{version_id}/preview"
    public["download_path"] = f"/v1/projects/{project_id}/versions/{version_id}/download"
    return public


def _file(
    project_id: str,
    version_id: str,
    *,
    snapshot: dict[str, Any],
    preview: bool = False,
    expected_hash: str | None = None,
) -> FileResponse:
    path, state, flags = _version_source(project_id, version_id)
    return media_response(
        snapshot,
        media=path,
        state=state,
        preview=preview,
        filename=f"{version_id}.mp4",
        expected_hash=expected_hash,
        version_flags=flags,
    )
