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

from app.delivery_gate import media_response, public_readiness, public_rights
from app.identity import owned_project, require_frame_identity, require_identity
from app.logging import log_event
from gateway import get_gateway
from workers.assets.validation import validate_upload
from workers.expert.charge import BudgetExhausted, reserve
from workers.identity.access import Conflict, NotFound, audit_human_release
from workers.identity.session import (
    Identity,
    SessionError,
    bearer_token,
    canonical_enterprise,
    verify_session,
)
from workers.nodes.n01_brief.schema import AttachmentRef
from workers.nodes.n18_revision.concept_gate import classify_concept, read_project_concept
from workers.schemas.generation import GenerationSettings, generation_settings
from workers.workflow.brand import BrandReadError, resolve_brand_kit
from workers.workflow.contract import PIPELINE
from workers.workflow.drafts import (
    DraftError,
    claim_submission,
    confirm_submission,
    create_draft,
    draft_id,
    existing_submission,
    save_draft,
    submission_response,
)
from workers.workflow.readiness import readiness
from workers.workflow.revise import RevisionError, revise_project
from workers.workflow.runtime import get_runtime
from workers.workflow.service import release_film, start_film
from workers.workflow.store import (
    init_project,
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
    generation_settings: GenerationSettings = Field(default_factory=GenerationSettings)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    # Omitted means 直接出片, so unattended clients still finish. The page sends false to wait.
    skip_storyboard: bool = True


class DraftFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: str = Field(default="", max_length=4000)
    brand_kit: dict[str, Any] | None = None
    brand_id: str | None = None
    concept_selection: str | None = Field(default=None, max_length=80)
    generation_settings: GenerationSettings = Field(default_factory=GenerationSettings)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    skip_storyboard: bool = False


class CreateDraft(DraftFields):
    operation_id: uuid.UUID


class SaveDraft(DraftFields):
    draft_revision: int = Field(ge=1, strict=True)


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
    body: CreateProject | DraftFields,
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


def _checked(body: CreateProject | DraftFields, *, enterprise_id: str) -> list[dict[str, Any]]:
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
    owner = (
        owner_path.read_text(encoding="utf-8").strip()
        if owner_path.is_file() and not owner_path.is_symlink()
        else ""
    )
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
    folder = root / upload_id
    if folder.is_symlink() or not _is_inside(folder.resolve(), root) or not folder.is_dir():
        raise _invalid_attachment()
    found = [
        item
        for item in folder.iterdir()
        if (item.is_file() or item.is_symlink()) and not item.name.startswith(".")
    ]
    if len(found) != 1:
        raise _invalid_attachment()
    path = found[0].resolve()
    if found[0].is_symlink() or not _is_inside(path, folder.resolve()) or not path.is_file():
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
    if valid_project_id(project_id) and not snapshot.get("concept_preview_invalidated"):
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
    body = {key: value for key, value in snapshot.items() if not key.startswith("_")}
    body["generation_settings"] = generation_settings(
        snapshot.get("generation_settings")
    ).model_dump(mode="json")
    if body.get("concept_preview") is not None:
        body["concept_preview_generation_settings"] = generation_settings(
            snapshot.get("concept_preview_generation_settings")
        ).model_dump(mode="json")
    if body.get("status") == "running" and body.get("started_at"):
        body["elapsed_s"] = round(time.time() - float(body["started_at"]), 3)
    if "attachments" in body:
        body["attachments"] = _public_attachments(body.get("attachments"))
    body.update(_concept_public(str(body.get("project_id") or ""), body))
    project_id = str(body.get("project_id") or "")
    if "storyboard" in body:
        body["storyboard"] = public_cards(body.get("storyboard"), project_id)
    view = readiness(snapshot)
    body.update(public_readiness(view))
    for key in (
        "media_path",
        "master_plate",
        "previous_deliverable",
        "held_deliverable",
        "work_dir",
    ):
        body.pop(key, None)
    body["preview_path"] = (
        f"/v1/projects/{project_id}/preview" if view["preview_available"] else None
    )
    body["download_path"] = (
        f"/v1/projects/{project_id}/download" if view["delivery_status"] == "ready" else None
    )
    body["deliverable"] = body["download_path"]
    if "rights" in body:
        body["rights"] = public_rights(body["rights"])
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
    try:
        with path.open("wb") as handle:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail="文件过大")
                handle.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="文件是空的")
        try:
            validate_upload(filename, path.read_bytes())
        except ValueError as exc:
            raise HTTPException(status_code=415, detail="文件内容与格式不匹配") from exc
        (folder / ".enterprise").write_text(identity.enterprise_id, encoding="utf-8")
    except BaseException:
        _discard_upload(path, folder)
        raise
    finally:
        await file.close()
    log_event("upload_stored", service="hilatv-api", kind=kind, size=size)
    return {"upload_id": upload_id, "kind": kind, "filename": filename}


class BlankProject(BaseModel):
    """LibTV 式入口：先开一块空白画布，生成在画布上做。"""

    model_config = ConfigDict(extra="forbid")

    sentence: str = Field(default="", max_length=4000)


@router.post("/v1/projects/blank")
def create_blank_project(
    body: BlankProject,
    identity: Identity = Depends(require_identity),
) -> JSONResponse:
    project_id = str(uuid.uuid4())
    init_project(
        project_id,
        sentence=body.sentence.strip(),
        status="draft",
        phase="画布",
        message="空白画布：双击加节点",
        shots=[],
        events=[],
        draft_revision=1,
        attachments=[],
        concept_selection=None,
        generation_settings=GenerationSettings().model_dump(mode="json"),
        skip_storyboard=True,
        enterprise_id=identity.enterprise_id,
        owner_member_id=identity.member_id,
        work_dir=str(project_path(project_id)),
    )
    log_event("blank_project_created", service="hilatv-api", project_id=project_id)
    return JSONResponse(
        status_code=201,
        content={"project_id": project_id, "status": "draft"},
    )


def _draft_error(exc: DraftError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if exc.snapshot:
        detail.update(
            draft_revision=int(exc.snapshot.get("draft_revision") or 1),
            snapshot=_public_snapshot(exc.snapshot),
        )
    return HTTPException(status_code=exc.status, detail=detail)


def _draft_fields(body: DraftFields, project_id: str, identity: Identity) -> dict[str, Any]:
    attachments = _checked(body, enterprise_id=identity.enterprise_id)
    loaded = brand_for_request(body, project_id=project_id, enterprise_id=identity.enterprise_id)
    return {
        "sentence": body.sentence.strip(),
        "brand_kit": loaded if body.brand_kit is not None else None,
        "brand_id": body.brand_id,
        "attachments": attachments,
        "concept_selection": body.concept_selection,
        "generation_settings": body.generation_settings.model_dump(mode="json"),
        "skip_storyboard": body.skip_storyboard,
    }


def _draft_response(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": snapshot["project_id"],
        "draft_id": snapshot["project_id"],
        "draft_revision": int(snapshot.get("draft_revision") or 1),
        "status": snapshot["status"],
        "snapshot": _public_snapshot(snapshot),
    }


def _refuse_unconfirmed_submission(snapshot: dict[str, Any]) -> None:
    if snapshot.get("submission_state") in {"pending", "unknown_external_result"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "submission_pending", "message": "原任务提交结果待确认，请勿重复生成"},
        )


@router.post("/v1/projects/drafts")
def create_project_draft(
    body: CreateDraft,
    identity: Identity = Depends(require_identity),
) -> JSONResponse:
    operation_id = str(body.operation_id)
    project_id = draft_id(identity.enterprise_id, operation_id)
    fields = _draft_fields(body, project_id, identity)
    try:
        snapshot, created = create_draft(
            operation_id=operation_id,
            enterprise_id=identity.enterprise_id,
            member_id=identity.member_id,
            fields=fields,
        )
    except DraftError as exc:
        raise _draft_error(exc) from exc
    return JSONResponse(status_code=201 if created else 200, content=_draft_response(snapshot))


@router.put("/v1/projects/{project_id}/draft")
def save_project_draft(
    project_id: str,
    body: SaveDraft,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    _snapshot_or_404(project_id, identity)
    fields = _draft_fields(body, project_id, identity)
    try:
        snapshot = save_draft(
            project_id,
            enterprise_id=identity.enterprise_id,
            revision=body.draft_revision,
            fields=fields,
        )
    except DraftError as exc:
        raise _draft_error(exc) from exc
    return _draft_response(snapshot)


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
        owner_member_id=identity.member_id,
        concept_selection=body.concept_selection,
        generation_settings=body.generation_settings,
        attachments=attachments,
        skip_storyboard=body.skip_storyboard,
    )
    return JSONResponse(
        status_code=202,
        content={"project_id": project_id, "workflow_id": workflow_id, "status": "running"},
    )


@router.get("/v1/projects")
def list_projects(identity: Identity = Depends(require_identity)) -> dict[str, Any]:
    """This enterprise's projects, newest first. Each one has its own canvas."""

    owner = canonical_enterprise(identity.enterprise_id)
    rows: list[dict[str, Any]] = []
    root = project_root()
    if root.is_dir():
        for entry in root.iterdir():
            if not entry.is_dir() or not valid_project_id(entry.name):
                continue
            snapshot = read_snapshot(entry.name)
            if not snapshot:
                continue
            stored = snapshot.get("enterprise_id")
            if not isinstance(stored, str) or canonical_enterprise(stored) != owner:
                continue
            media_view = readiness(snapshot)
            started = snapshot.get("created_at") or snapshot.get("started_at")
            finished = snapshot.get("finished_at")
            updated = snapshot.get("updated_at") or finished
            rows.append(
                {
                    "project_id": entry.name,
                    "sentence": str(snapshot.get("sentence") or "")[:200],
                    "status": str(snapshot.get("status") or ""),
                    "phase": str(snapshot.get("phase") or ""),
                    "message": str(snapshot.get("message") or ""),
                    "created_at": started if isinstance(started, (int, float)) else 0,
                    "updated_at": updated
                    if isinstance(updated, (int, float))
                    else (started if isinstance(started, (int, float)) else 0),
                    "shot_count": len(snapshot.get("shots") or []),
                    "has_film": media_view["preview_available"],
                    **public_readiness(media_view),
                }
            )
    rows.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"projects": rows[:50]}


class FilmStart(BaseModel):
    """Agent 入口：在已有项目（通常是空白画布）上直接跑完整条片。"""

    model_config = ConfigDict(extra="forbid")

    sentence: str = Field(default="", max_length=4000)
    operation_id: uuid.UUID | None = None
    draft_revision: int | None = Field(default=None, ge=1, strict=True)


async def _read_submission(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Resolve an unknown acknowledgement with a read; never resend a start."""
    submission = snapshot.get("_submission") or {}
    if submission.get("state") not in {"pending", "unknown_external_result"}:
        return snapshot
    try:
        runtime = await get_runtime()
        handle = runtime.client.get_workflow_handle(str(submission["workflow_id"]))
        await handle.describe()
    except Exception:
        return snapshot
    return confirm_submission(snapshot["project_id"], submission["operation_id"], confirmed=True)


@router.post("/v1/projects/{project_id}/film/start")
async def start_film_on_project(
    project_id: str,
    body: FilmStart,
    identity: Identity = Depends(require_identity),
) -> JSONResponse:
    snapshot = _snapshot_or_404(project_id, identity)
    modern = body.operation_id is not None or body.draft_revision is not None
    if modern:
        if body.operation_id is None or body.draft_revision is None or body.sentence.strip():
            raise HTTPException(status_code=422, detail="提交需要操作编号和已保存草稿版本")
        operation_id, revision = str(body.operation_id), body.draft_revision
        legacy_sentence = None
    else:
        if snapshot.get("_draft_create"):
            raise HTTPException(
                status_code=422, detail="请先保存草稿，并提供提交操作编号和草稿版本"
            )
        revision = int(snapshot.get("draft_revision") or 1)
        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"hilatv:{project_id}:{revision}"))
        legacy_sentence = body.sentence.strip() or str(snapshot.get("sentence") or "").strip()
    try:
        previous = existing_submission(snapshot, operation_id, revision)
    except DraftError as exc:
        raise _draft_error(exc) from exc
    if previous is not None:
        return JSONResponse(
            status_code=202, content=submission_response(await _read_submission(snapshot))
        )
    if snapshot.get("status") != "draft":
        raise HTTPException(
            status_code=409,
            detail={"code": "project_not_editable", "message": "项目已开始，请查看原任务"},
        )
    if revision != int(snapshot.get("draft_revision") or 1):
        raise _draft_error(DraftError("draft_conflict", "草稿版本已变化，请先保存再提交", snapshot))
    sentence = legacy_sentence if legacy_sentence is not None else snapshot.get("sentence")
    if not isinstance(sentence, str) or not sentence.strip():
        raise HTTPException(status_code=422, detail="先写一句话")
    # Revalidate the saved tenant-bound uploads and brand, never take a second
    # unsaved payload at submit time. This is read-only and cannot invoke models.
    _draft_fields(
        DraftFields.model_validate(
            {key: snapshot.get(key) for key in DraftFields.model_fields if key in snapshot}
        ),
        project_id,
        identity,
    )
    try:
        runtime = await get_runtime()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "submission_unavailable",
                "message": "生成服务暂不可用，草稿完整保留，请稍后重试",
            },
        ) from exc
    try:
        claimed, fresh = claim_submission(
            project_id,
            enterprise_id=identity.enterprise_id,
            operation_id=operation_id,
            revision=revision,
            legacy_sentence=legacy_sentence,
        )
    except DraftError as exc:
        raise _draft_error(exc) from exc
    if not fresh:
        return JSONResponse(status_code=202, content=submission_response(claimed))
    confirmed = False
    try:
        await start_film(
            project_id=project_id,
            sentence=str(claimed["sentence"]),
            brand_kit=claimed.get("brand_kit"),
            brand_id=claimed.get("brand_id"),
            enterprise_id=str(claimed["enterprise_id"]),
            owner_member_id=claimed.get("owner_member_id"),
            attachments=claimed.get("attachments") or [],
            concept_selection=claimed.get("concept_selection"),
            generation_settings=claimed.get("generation_settings"),
            skip_storyboard=claimed.get("skip_storyboard") is not False,
            workflow_id=claimed["workflow_id"],
            preserve_project=True,
            runtime=runtime,
        )
        confirmed = True
    except Exception as exc:
        from temporalio.exceptions import WorkflowAlreadyStartedError

        confirmed = isinstance(exc, WorkflowAlreadyStartedError)
        log_event("film_submission_uncertain", service="hilatv-api", project_id=project_id)
    final = confirm_submission(project_id, operation_id, confirmed=confirmed)
    return JSONResponse(status_code=202, content=submission_response(final))


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
        _refuse_unconfirmed_submission(snapshot)
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
        generation_settings=snapshot.get("generation_settings"),
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
    _refuse_unconfirmed_submission(_snapshot_or_404(project_id, identity))
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
                **_public_snapshot(snapshot),
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
        generation_settings=snapshot.get("generation_settings"),
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
    return media_response(snapshot)


@router.get("/v1/projects/{project_id}/preview")
@router.head("/v1/projects/{project_id}/preview", include_in_schema=False)
def preview_master(
    project_id: str,
    identity: Identity = Depends(require_frame_identity),
) -> FileResponse:
    return media_response(_snapshot_or_404(project_id, identity), preview=True)


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
