"""Create a film from one sentence, then read per-shot progress."""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.identity import owned_project, require_frame_identity, require_identity
from app.logging import log_event
from gateway import get_gateway
from workers.expert.charge import BudgetExhausted, reserve
from workers.identity.access import Conflict, NotFound, audit_human_release
from workers.identity.session import Identity, SessionError, bearer_token, verify_session
from workers.nodes.n01_brief.schema import AttachmentRef
from workers.nodes.n18_revision.concept_gate import classify_concept, read_project_concept
from workers.workflow.brand import BrandReadError, resolve_brand_kit
from workers.workflow.contract import PIPELINE
from workers.workflow.revise import RevisionError, revise_project
from workers.workflow.service import release_film, start_film
from workers.workflow.store import (
    load_checkpoint,
    locked_project,
    project_path,
    project_root,
    read_events,
    read_snapshot,
    valid_project_id,
)
from workers.workflow.storyboard import (
    StoryboardError,
    claim_continue,
    edit_voiceover,
    frame_file,
    public_cards,
)
from workers.workflow.versions import VersionError, list_versions, restore_version

router = APIRouter()

_ALLOWED_TYPES = {
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".webp": frozenset({"image/webp"}),
    ".gif": frozenset({"image/gif"}),
    ".pdf": frozenset({"application/pdf"}),
}
_FILENAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")
_UPLOAD_ID = re.compile(r"^[a-f0-9]{32}$")
_CHUNK = 64 * 1024


class CreateProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: str = Field(min_length=1, max_length=4000)
    brand_kit: dict[str, Any] | None = None
    brand_id: str | None = None
    concept_selection: str | None = Field(default=None, max_length=80)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    # Omitted means 直接出片, so unattended clients still finish. The page sends false to wait.
    skip_storyboard: bool = True


class StoryboardEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voiceover: str = Field(min_length=1, max_length=400)


class RerunProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: str = Field(min_length=1)


class ReviseProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=4000)
    shot_id: str | None = None


def brand_for_request(
    body: CreateProject,
    *,
    project_id: str,
    enterprise_id: str,
) -> dict[str, Any] | None:
    """Inline kit is for this project only and is never written into the archive.

    ``enterprise_id`` is the session's enterprise, or the enterprise already stored
    on the project. It is not read from the request.
    """

    try:
        return resolve_brand_kit(
            inline=body.brand_kit,
            brand_id=body.brand_id,
            enterprise_id=enterprise_id,
            project_id=project_id,
            attempt=1,
        )
    except (ValidationError, BrandReadError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="品牌资料无效") from exc


def _checked(body: CreateProject, *, enterprise_id: str) -> list[dict[str, Any]]:
    return [_bind_attachment(item, enterprise_id=enterprise_id) for item in body.attachments]


def _invalid_attachment() -> HTTPException:
    return HTTPException(status_code=422, detail="附件无效")


def _bind_attachment(item: Any, *, enterprise_id: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise _invalid_attachment()
    kind = item.get("kind")
    if kind == "url":
        return _bind_url(item)
    if kind in {"image", "pdf"}:
        return _bind_upload(item, str(kind), enterprise_id=enterprise_id)
    raise _invalid_attachment()


def _bind_url(item: dict[str, Any]) -> dict[str, Any]:
    uri = item.get("uri")
    if not isinstance(uri, str) or not uri.startswith(("http://", "https://")):
        raise _invalid_attachment()
    filename = item.get("filename")
    if filename is not None and not isinstance(filename, str):
        raise _invalid_attachment()
    return AttachmentRef(kind="url", uri=uri, filename=filename).model_dump(mode="json")


def _bind_upload(item: dict[str, Any], kind: str, *, enterprise_id: str) -> dict[str, Any]:
    upload_id = item.get("upload_id")
    if not isinstance(upload_id, str):
        raise _invalid_attachment()
    path = _resolve_upload(upload_id)
    owner_path = path.parent / ".enterprise"
    owner = owner_path.read_text(encoding="utf-8").strip() if owner_path.is_file() else ""
    if owner != enterprise_id:
        raise _invalid_attachment()
    stored = "pdf" if path.suffix.lower() == ".pdf" else "image"
    if stored != kind:
        raise _invalid_attachment()
    bound = AttachmentRef(kind=kind, uri=str(path), filename=path.name).model_dump(mode="json")
    bound["upload_id"] = upload_id
    return bound


def _uploads_root() -> Path:
    root = (project_root() / "uploads").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_inside(path: Path, root: Path) -> bool:
    if ".." in path.parts or path == root:
        return False
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_upload(upload_id: str) -> Path:
    """Map an opaque id to one file under uploads/. Reject paths and symlinks out."""

    if ".." in upload_id or _UPLOAD_ID.fullmatch(upload_id) is None:
        raise _invalid_attachment()
    root = _uploads_root()
    folder = (root / upload_id).resolve()
    if not _is_inside(folder, root) or not folder.is_dir():
        raise _invalid_attachment()
    found = [
        item
        for item in folder.iterdir()
        if (item.is_file() or item.is_symlink()) and not item.name.startswith(".")
    ]
    if len(found) != 1:
        raise _invalid_attachment()
    path = found[0].resolve()
    if not _is_inside(path, root) or not path.is_file():
        raise _invalid_attachment()
    return path


def _snapshot_or_404(project_id: str, identity: Identity) -> dict[str, Any]:
    return owned_project(project_id, identity)


def prepare_human_release(project_id: str, identity: Identity) -> dict[str, Any]:
    """Auth, ownership, and the audit line. The film restart stays with the caller."""

    from app.identity import http_access

    try:
        return audit_human_release(identity, project_id)
    except (NotFound, Conflict) as exc:
        raise http_access(exc) from exc


def _upload_limit() -> int:
    raw = os.getenv("HILATV_UPLOAD_MAX_BYTES", "").strip() or str(8 * 1024 * 1024)
    try:
        value = int(raw)
    except ValueError:
        value = 8 * 1024 * 1024
    return max(1, value)


def _safe_filename(name: str) -> str:
    base = Path(name or "").name.replace("\x00", "")
    cleaned = _FILENAME.sub("_", base).strip("._")
    return (cleaned or "upload")[:80]


def _attachment_kind(content_type: str, filename: str) -> str:
    media = content_type.split(";", 1)[0].strip().lower()
    suffix = Path(filename).suffix.lower()
    allowed = _ALLOWED_TYPES.get(suffix)
    if allowed is None or media not in allowed:
        raise HTTPException(status_code=415, detail="只接收图片或 PDF")
    if suffix == ".pdf":
        return "pdf"
    return "image"


def _public_filename(value: Any) -> str:
    if not isinstance(value, str) or not value or ".." in value:
        return ""
    name = Path(value).name
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return ""
    return name


def _public_attachments(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    public: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        filename = _public_filename(item.get("filename"))
        if kind == "url":
            uri = item.get("uri")
            entry: dict[str, Any] = {"kind": "url", "filename": filename or None}
            if isinstance(uri, str) and uri.startswith(("http://", "https://")):
                entry["uri"] = uri
            public.append(entry)
            continue
        entry = {"kind": kind, "filename": filename}
        upload_id = item.get("upload_id")
        if isinstance(upload_id, str) and _UPLOAD_ID.fullmatch(upload_id):
            entry["upload_id"] = upload_id
        public.append(entry)
    return public


def _concept_public(project_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Surface a degraded concept. A 200 from /v1/concepts can still be a fallback."""

    file_view = classify_concept(None)
    if valid_project_id(project_id):
        file_view = classify_concept(read_project_concept(project_root() / project_id))
    text_source = file_view.text_source or str(snapshot.get("concept_text_source") or "")
    degraded = (
        file_view.degraded
        or snapshot.get("concept_degraded") is True
        or snapshot.get("concept_ok") is False
        or text_source == "template_fallback"
    )
    ok: bool | None = False if degraded else file_view.ok
    return {
        "concept_degraded": degraded,
        "concept_ok": ok,
        "concept_text_source": text_source,
    }


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    body = dict(snapshot)
    if body.get("status") == "running" and body.get("started_at"):
        body["elapsed_s"] = round(time.time() - float(body["started_at"]), 3)
    if "attachments" in body:
        body["attachments"] = _public_attachments(body.get("attachments"))
    body.update(_concept_public(str(body.get("project_id") or ""), body))
    project_id = str(body.get("project_id") or "")
    if "storyboard" in body:
        body["storyboard"] = public_cards(body.get("storyboard"), project_id)
    return body


def _discard_upload(path: Path, folder: Path) -> None:
    path.unlink(missing_ok=True)
    try:
        folder.rmdir()
    except OSError:
        return


@router.post("/v1/uploads")
async def upload_asset(
    request: Request,
    file: UploadFile = File(),
    identity: Identity = Depends(require_identity),
) -> dict[str, str]:
    """Store a picture or PDF and return an opaque id. Never a filesystem path."""

    form = await request.form()
    if "enterprise_id" in form:
        raise HTTPException(status_code=422, detail="enterprise_id 不能由请求指定")
    filename = _safe_filename(file.filename or "")
    kind = _attachment_kind(file.content_type or "", filename)
    upload_id = uuid.uuid4().hex
    root = _uploads_root()
    folder = root / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    path = (folder / filename).resolve()
    if not _is_inside(path, root):
        _discard_upload(path, folder)
        raise HTTPException(status_code=400, detail="文件名无效")
    limit = _upload_limit()
    size = 0
    too_big = False
    with path.open("wb") as handle:
        while True:
            chunk = await file.read(_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                too_big = True
                break
            handle.write(chunk)
    if too_big or size == 0:
        _discard_upload(path, folder)
        if too_big:
            raise HTTPException(status_code=413, detail="文件过大")
        raise HTTPException(status_code=400, detail="文件是空的")
    (folder / ".enterprise").write_text(identity.enterprise_id, encoding="utf-8")
    log_event("upload_stored", service="hilatv-api", kind=kind, size=size)
    return {"upload_id": upload_id, "kind": kind, "filename": filename}


@router.post("/v1/projects")
async def create_project(
    body: CreateProject,
    identity: Identity = Depends(require_identity),
) -> JSONResponse:
    attachments = _checked(body, enterprise_id=identity.enterprise_id)
    project_id = str(uuid.uuid4())
    loaded = brand_for_request(body, project_id=project_id, enterprise_id=identity.enterprise_id)
    kit = loaded if body.brand_kit is not None else None
    workflow_id = await start_film(
        project_id=project_id,
        sentence=body.sentence,
        brand_kit=kit,
        brand_id=body.brand_id,
        enterprise_id=identity.enterprise_id,
        concept_selection=body.concept_selection,
        attachments=attachments,
        skip_storyboard=body.skip_storyboard,
    )
    return JSONResponse(
        status_code=202,
        content={"project_id": project_id, "workflow_id": workflow_id, "status": "running"},
    )


@router.get("/v1/projects/{project_id}")
def project_status(
    project_id: str,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    return _public_snapshot(_snapshot_or_404(project_id, identity))


@router.post("/v1/projects/{project_id}/rerun")
async def rerun_project(
    project_id: str,
    body: RerunProject,
    identity: Identity = Depends(require_identity),
) -> JSONResponse:
    if body.node not in PIPELINE:
        raise HTTPException(status_code=400, detail="未知节点")
    with locked_project(project_id):
        snapshot = _snapshot_or_404(project_id, identity)
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
        script = checkpoint.get("script") if isinstance(checkpoint, dict) else None
        shots = None
        if isinstance(script, dict) and isinstance(script.get("shots"), list):
            shots = [item for item in script["shots"] if isinstance(item, dict)]
        try:
            reserve(project_id, body.node, shots=shots)
        except BudgetExhausted as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    workflow_id = await start_film(
        project_id=project_id,
        sentence=str(snapshot.get("sentence") or ""),
        brand_kit=snapshot.get("brand_kit"),
        brand_id=snapshot.get("brand_id"),
        enterprise_id=snapshot.get("enterprise_id"),
        concept_selection=snapshot.get("concept_selection"),
        attachments=snapshot.get("attachments") or [],
        keyframe_candidates=snapshot.get("keyframe_candidates"),
        video_candidates=snapshot.get("video_candidates"),
        start_from=body.node,
        checkpoint=checkpoint,
        skip_storyboard=snapshot.get("skip_storyboard") is not False,
    )
    return JSONResponse(
        status_code=202,
        content={"project_id": project_id, "workflow_id": workflow_id, "status": "running"},
    )


@router.get("/v1/projects/{project_id}/revisions")
def project_revisions(
    project_id: str,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    _snapshot_or_404(project_id, identity)
    try:
        return list_versions(project_id)
    except VersionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/v1/projects/{project_id}/revisions/{version_id}/restore")
def project_restore(
    project_id: str,
    version_id: str,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    _snapshot_or_404(project_id, identity)
    try:
        return restore_version(project_id, version_id)
    except VersionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/v1/projects/{project_id}/revisions")
def project_revision(
    project_id: str,
    body: ReviseProject,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    _snapshot_or_404(project_id, identity)
    try:
        return revise_project(
            project_id,
            body.instruction,
            shot_id=body.shot_id,
            gateway=get_gateway(),
        )
    except (RevisionError, VersionError) as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/v1/projects/{project_id}/human-review/release")
async def release_human_review(
    project_id: str,
    identity: Identity = Depends(require_identity),
) -> JSONResponse:
    """Explicit human release. This is the only way past needs_review."""

    snapshot = prepare_human_release(project_id, identity)
    if snapshot.get("status") == "completed" and snapshot.get("deliverable"):
        return JSONResponse(
            status_code=202,
            content={
                "project_id": project_id,
                "status": "completed",
                "deliverable": snapshot.get("deliverable"),
            },
        )
    from workers.workflow.service import start_film
    from workers.workflow.store import load_checkpoint

    workflow_id = await start_film(
        project_id=project_id,
        sentence=str(snapshot.get("sentence") or ""),
        brand_kit=snapshot.get("brand_kit"),
        brand_id=snapshot.get("brand_id"),
        enterprise_id=snapshot.get("enterprise_id"),
        concept_selection=snapshot.get("concept_selection"),
        attachments=snapshot.get("attachments") or [],
        keyframe_candidates=snapshot.get("keyframe_candidates"),
        video_candidates=snapshot.get("video_candidates"),
        start_from="n12_music",
        checkpoint=load_checkpoint(project_id),
        human_release=True,
    )
    return JSONResponse(
        status_code=202,
        content={
            "project_id": project_id,
            "workflow_id": workflow_id,
            "status": "running",
        },
    )


@router.post("/v1/projects/{project_id}/storyboard/continue")
async def continue_storyboard(
    project_id: str,
    identity: Identity = Depends(require_identity),
) -> dict[str, str]:
    _snapshot_or_404(project_id, identity)
    try:
        workflow_id = claim_continue(project_id)
    except StoryboardError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    await release_film(workflow_id)
    return {"project_id": project_id, "status": "running"}


@router.post("/v1/projects/{project_id}/storyboard/{shot_id}")
def edit_storyboard(
    project_id: str,
    shot_id: str,
    body: StoryboardEdit,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    _snapshot_or_404(project_id, identity)
    if shot_id == "continue":
        raise HTTPException(status_code=404, detail="镜头编号无效")
    try:
        return edit_voiceover(project_id, shot_id, body.voiceover, gateway=get_gateway())
    except StoryboardError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/v1/projects/{project_id}/storyboard/{shot_id}/frame")
def storyboard_frame(
    project_id: str,
    shot_id: str,
    identity: Identity = Depends(require_frame_identity),
) -> FileResponse:
    _snapshot_or_404(project_id, identity)
    path = frame_file(project_id, shot_id)
    if path is None:
        raise HTTPException(status_code=404, detail="这一镜没有可看的画面")
    return FileResponse(path, media_type="image/png")


@router.get("/v1/projects/{project_id}/download")
def download_master(
    project_id: str,
    identity: Identity = Depends(require_identity),
) -> FileResponse:
    snapshot = _snapshot_or_404(project_id, identity)
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
    if "enterprise_id" in websocket.query_params:
        await websocket.send_json({"type": "error", "message": "enterprise_id 不能由请求指定"})
        await websocket.close(code=4422)
        return
    header = websocket.headers.get("authorization")
    token = bearer_token(header) or websocket.query_params.get("session")
    if not token:
        await websocket.send_json({"type": "error", "message": "需要登录"})
        await websocket.close(code=4401)
        return
    try:
        identity = verify_session(token)
    except SessionError:
        await websocket.send_json({"type": "error", "message": "会话无效"})
        await websocket.close(code=4401)
        return
    try:
        owned_project(project_id, identity)
    except HTTPException:
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
            terminal = snapshot.get("status") in {"completed", "failed", "needs_human_review"}
            if terminal and sent >= len(read_events(project_id)):
                await websocket.close()
                return
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return
