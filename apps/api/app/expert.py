"""Expert-mode canvas: candidates, selection, timeline edits, and re-runs."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.identity import owned_project, require_frame_identity, require_identity
from workers.expert.canvas import build_canvas, media_file
from workers.expert.canvas_audio import generate_voiceover, voiceover_wav
from workers.expert.canvas_compose import compose_from_canvas
from workers.expert.charge import BudgetExhausted
from workers.expert.desk import (
    VersionConflict,
    add_edge,
    add_node,
    delete_edge,
    delete_node,
    load_doc,
    patch_node,
    put_layout,
)
from workers.expert.gates import GateError
from workers.expert.node_generate import generate_node
from workers.expert.rerun import rerun_span, save_timeline, select_candidate
from workers.expert.script_edit import (
    add_shot,
    bind_reference,
    delete_shot,
    load_script,
    patch_shot,
    reorder_shots,
    update_meta,
)
from workers.expert.script_flow import build_storyboard
from workers.expert.shot_action import regenerate_shot, set_reference
from workers.expert.timeline_edit import save_structured_timeline
from workers.expert.uploads import resolve_upload
from workers.identity.session import Identity

router = APIRouter()

_MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".mov": "video/mp4",
    ".webm": "video/webm",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}


class ExpertRerun(BaseModel):
    """Bypass flags are stored on the model so they can be sent, then ignored."""

    model_config = ConfigDict(extra="ignore")

    node: str = Field(min_length=1)
    shot_id: str | None = None
    prompt_suffix: str = ""
    voice_id: str | None = None
    qa_passed: bool | None = None
    visual_reviewed: bool | None = None
    consent: bool | None = None
    skip_ai_label: bool | None = None
    licensed: bool | None = None


class ExpertSelect(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node: str = Field(min_length=1)
    shot_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    qa_passed: bool | None = None
    visual_reviewed: bool | None = None


class TimelineEdit(BaseModel):
    model_config = ConfigDict(extra="allow")

    overlays: list[dict]
    clips: list[dict] = Field(default_factory=list)


class PositionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class ViewportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = 0
    y: float = 0
    zoom: float = 1


class LayoutBody(BaseModel):
    """Optimistic layout save. ``layout_version`` must match the last GET."""

    model_config = ConfigDict(extra="forbid")

    layout_version: int = Field(ge=0)
    positions: dict[str, PositionBody]
    viewport: ViewportBody


class NodeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    position: PositionBody
    data: dict


class NodePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict | None = None
    position: PositionBody | None = None


class EdgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    role: str
    source_handle: str | None = None
    target_handle: str | None = None


class RegenerateBody(BaseModel):
    """Ignored review flags cannot mark a new candidate as passed."""

    model_config = ConfigDict(extra="ignore")

    narration: str | None = None
    prompt_suffix: str | None = None
    operation_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
    )
    qa_passed: bool | None = None
    visual_reviewed: bool | None = None


class ReferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: str = Field(min_length=1)


class TimelineClipBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    candidate_id: str
    in_s: float
    out_s: float


class TimelinePut(BaseModel):
    """Shot order and trims. The AI label is not a writable field."""

    model_config = ConfigDict(extra="allow")

    clips: list[TimelineClipBody]


class VoiceoverBody(BaseModel):
    """Optional text replaces this shot's line before the take is generated."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=400)
    operation_id: str | None = Field(default=None, max_length=128)


class ComposeBody(BaseModel):
    """Re-compose the current canvas into one MP4."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str | None = Field(default=None, max_length=128)


def _gate(exc: GateError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=getattr(exc, "detail", str(exc)))


def _call(fn):
    try:
        return fn()
    except VersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "layout_version": exc.layout_version},
        ) from exc
    except BudgetExhausted as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GateError as exc:
        raise _gate(exc) from exc


def _owned(project_id: str, identity: Identity) -> None:
    owned_project(project_id, identity)


@router.get("/v1/projects/{project_id}/canvas")
def project_canvas(
    project_id: str,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    try:
        return build_canvas(project_id)
    except GateError as exc:
        raise _gate(exc) from exc


@router.post("/v1/projects/{project_id}/expert/rerun")
def project_rerun_node(
    project_id: str,
    body: ExpertRerun,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    try:
        return rerun_span(
            project_id,
            body.node,
            shot_id=body.shot_id,
            prompt_suffix=body.prompt_suffix,
            voice_id=body.voice_id,
            qa_passed=body.qa_passed,
            visual_reviewed=body.visual_reviewed,
            consent=body.consent,
            skip_ai_label=body.skip_ai_label,
            licensed=body.licensed,
        )
    except BudgetExhausted as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GateError as exc:
        raise _gate(exc) from exc


@router.post("/v1/projects/{project_id}/expert/select")
def project_select(
    project_id: str,
    body: ExpertSelect,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    try:
        return select_candidate(
            project_id,
            body.node,
            body.shot_id,
            body.candidate_id,
            qa_passed=body.qa_passed,
            visual_reviewed=body.visual_reviewed,
        )
    except GateError as exc:
        raise _gate(exc) from exc


@router.post("/v1/projects/{project_id}/expert/timeline")
def project_timeline(
    project_id: str,
    body: TimelineEdit,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    try:
        return save_timeline(project_id, body.model_dump())
    except GateError as exc:
        raise _gate(exc) from exc


@router.get("/v1/projects/{project_id}/expert/media/{candidate_id}")
def project_media(
    project_id: str,
    candidate_id: str,
    identity: Identity = Depends(require_frame_identity),
) -> FileResponse:
    _owned(project_id, identity)
    path = media_file(project_id, candidate_id)
    if path is None:
        raise HTTPException(status_code=404, detail="没有可看的画面")
    media_type = _MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        filename=Path(path).name,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


class GenerateBody(BaseModel):
    """节点上直接生成：图片节点出图、视频节点出视频。"""

    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(default=None, max_length=4000)
    count: int | None = Field(default=None, ge=1, le=4)
    operation_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
    )


@router.post("/v1/projects/{project_id}/canvas/nodes/{node_id}/generate")
def project_canvas_generate(
    project_id: str,
    node_id: str,
    body: GenerateBody,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    from gateway import get_gateway

    return _call(
        lambda: generate_node(
            project_id,
            node_id,
            body.model_dump(exclude_none=True),
            gateway=get_gateway(),
        )
    )


class ScriptBody(BaseModel):
    """画布上的脚本入口：一句话长出分镜，不跑完整条片。"""

    model_config = ConfigDict(extra="forbid")

    sentence: str = Field(default="", max_length=4000)


@router.post("/v1/projects/{project_id}/canvas/script")
def project_canvas_script(
    project_id: str,
    body: ScriptBody,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    from gateway import get_gateway

    return _call(lambda: build_storyboard(project_id, body.sentence, gateway=get_gateway()))


@router.put("/v1/projects/{project_id}/canvas/layout")
def project_layout(
    project_id: str,
    body: LayoutBody,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: put_layout(project_id, body.model_dump()))


@router.post("/v1/projects/{project_id}/canvas/nodes")
def project_add_node(
    project_id: str,
    body: NodeBody,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(
        lambda: add_node(
            project_id,
            body.model_dump(),
            enterprise_id=identity.enterprise_id,
        )
    )


@router.patch("/v1/projects/{project_id}/canvas/nodes/{node_id}")
def project_patch_node(
    project_id: str,
    node_id: str,
    body: NodePatch,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(
        lambda: patch_node(
            project_id,
            node_id,
            body.model_dump(exclude_unset=True),
            enterprise_id=identity.enterprise_id,
        )
    )


@router.delete("/v1/projects/{project_id}/canvas/nodes/{node_id}")
def project_delete_node(
    project_id: str,
    node_id: str,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: delete_node(project_id, node_id))


@router.post("/v1/projects/{project_id}/canvas/edges")
def project_add_edge(
    project_id: str,
    body: EdgeBody,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: add_edge(project_id, body.model_dump()))


@router.delete("/v1/projects/{project_id}/canvas/edges/{edge_id}")
def project_delete_edge(
    project_id: str,
    edge_id: str,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: delete_edge(project_id, edge_id))


@router.post("/v1/projects/{project_id}/shots/{shot_id}/regenerate")
def project_regenerate_shot(
    project_id: str,
    shot_id: str,
    body: RegenerateBody,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: regenerate_shot(project_id, shot_id, body.model_dump()))


@router.post("/v1/projects/{project_id}/shots/{shot_id}/reference")
def project_shot_reference(
    project_id: str,
    shot_id: str,
    body: ReferenceBody,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(
        lambda: set_reference(
            project_id,
            shot_id,
            body.upload_id,
            enterprise_id=identity.enterprise_id,
        )
    )


@router.put("/v1/projects/{project_id}/timeline")
def project_put_timeline(
    project_id: str,
    body: TimelinePut,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: save_structured_timeline(project_id, body.model_dump()))


@router.get("/v1/projects/{project_id}/expert/uploads/{upload_id}")
def project_upload(
    project_id: str,
    upload_id: str,
    identity: Identity = Depends(require_frame_identity),
) -> FileResponse:
    _owned(project_id, identity)
    doc = load_doc(project_id)
    linked = any(node.data.get("upload_id") == upload_id for node in doc.user_nodes) or any(
        item.reference_upload_id == upload_id for item in doc.shots.values()
    )
    if not linked:
        raise HTTPException(status_code=404, detail="没有可看的画面")
    try:
        path = resolve_upload(upload_id, enterprise_id=identity.enterprise_id)
    except GateError as exc:
        raise _gate(exc) from exc
    media_type = _MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("/v1/projects/{project_id}/canvas/shots/{shot_id}/voiceover")
def project_canvas_voiceover(
    project_id: str,
    shot_id: str,
    body: VoiceoverBody | None = None,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    payload = body.model_dump() if body is not None else {}
    return _call(lambda: generate_voiceover(project_id, shot_id, payload))


@router.get("/v1/projects/{project_id}/canvas/shots/{shot_id}/voiceover")
def project_canvas_voiceover_audio(
    project_id: str,
    shot_id: str,
    identity: Identity = Depends(require_frame_identity),
) -> Response:
    _owned(project_id, identity)
    try:
        data = voiceover_wav(project_id, shot_id)
    except GateError as exc:
        raise _gate(exc) from exc
    return Response(content=data, media_type="audio/wav")


@router.post("/v1/projects/{project_id}/canvas/compose")
def project_canvas_compose(
    project_id: str,
    body: ComposeBody | None = None,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    payload = body.model_dump() if body is not None else {}
    return _call(lambda: compose_from_canvas(project_id, payload))


@router.get("/v1/projects/{project_id}/script")
def project_script(
    project_id: str,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: load_script(project_id))


@router.put("/v1/projects/{project_id}/script/meta")
def project_script_meta(
    project_id: str,
    body: dict,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: update_meta(project_id, body))


@router.patch("/v1/projects/{project_id}/script/shots/{shot_id}")
def project_script_shot(
    project_id: str,
    shot_id: str,
    body: dict,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: patch_shot(project_id, shot_id, body))


@router.post("/v1/projects/{project_id}/script/shots")
def project_script_add_shot(
    project_id: str,
    body: dict | None = None,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: add_shot(project_id, body or {}))


@router.delete("/v1/projects/{project_id}/script/shots/{shot_id}")
def project_script_delete_shot(
    project_id: str,
    shot_id: str,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    return _call(lambda: delete_shot(project_id, shot_id))


@router.post("/v1/projects/{project_id}/script/reorder")
def project_script_reorder(
    project_id: str,
    body: dict,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    shot_ids = body.get("shot_ids")
    if not isinstance(shot_ids, list) or not all(isinstance(item, str) for item in shot_ids):
        raise HTTPException(status_code=422, detail="排序要传镜头编号列表")
    return _call(lambda: reorder_shots(project_id, shot_ids))


@router.post("/v1/projects/{project_id}/script/shots/{shot_id}/generate")
def project_script_generate_shot(
    project_id: str,
    shot_id: str,
    body: dict | None = None,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    payload = body or {}
    narration = payload.get("narration")
    prompt_suffix = str(payload.get("prompt_suffix") or "")
    if not isinstance(narration, str):
        narration = ""
    return _call(
        lambda: regenerate_shot(
            project_id,
            shot_id,
            {
                "narration": narration,
                "prompt_suffix": prompt_suffix,
                "operation_id": payload.get("operation_id"),
            },
        )
    )


@router.post("/v1/projects/{project_id}/script/shots/{shot_id}/reference")
def project_script_bind_reference(
    project_id: str,
    shot_id: str,
    body: dict,
    identity: Identity = Depends(require_identity),
) -> dict:
    _owned(project_id, identity)
    upload_id = body.get("upload_id")
    slot = body.get("slot") or "first_frame"
    if not isinstance(upload_id, str) or not upload_id:
        raise HTTPException(status_code=422, detail="缺少参考图标识")
    if not isinstance(slot, str):
        raise HTTPException(status_code=422, detail="参考图槽位不对")
    try:
        resolve_upload(upload_id, enterprise_id=identity.enterprise_id)
    except GateError as exc:
        raise _gate(exc) from exc
    return _call(lambda: bind_reference(project_id, shot_id, slot, upload_id))


@router.post("/v1/projects/{project_id}/script/generate")
def project_script_generate_batch(
    project_id: str,
    body: dict,
    identity: Identity = Depends(require_identity),
) -> dict:
    """按分镜表批量重生成（逐镜串行，遇到预算不足就停）。"""

    _owned(project_id, identity)
    shot_ids = body.get("shot_ids")
    if (
        not isinstance(shot_ids, list)
        or not shot_ids
        or not all(isinstance(item, str) for item in shot_ids)
    ):
        raise HTTPException(status_code=422, detail="要传镜头编号列表")
    if len(shot_ids) > 8:
        raise HTTPException(status_code=422, detail="一次最多批量 8 个镜头")
    results: list[dict] = []
    for shot_id in shot_ids:
        entry: dict = {"shot_id": shot_id, "ok": False}
        try:
            payload = load_script(project_id)
            shot = next((item for item in payload["shots"] if item["shot_id"] == shot_id), None)
            if shot is None:
                entry["error"] = "没有这个镜头"
            else:
                reference = (shot.get("ext") or {}).get("reference") or {}
                first_frame = reference.get("first_frame")
                if isinstance(first_frame, str) and first_frame:
                    set_reference(
                        project_id, shot_id, first_frame, enterprise_id=identity.enterprise_id
                    )
                regenerate_shot(
                    project_id,
                    shot_id,
                    {"narration": shot.get("voiceover") or "", "prompt_suffix": ""},
                )
                entry["ok"] = True
        except BudgetExhausted as exc:
            entry["error"] = str(exc)
            results.append(entry)
            break
        except GateError as exc:
            entry["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - 批量里单镜失败不拖垮其它镜头
            entry["error"] = str(exc)[:200]
        results.append(entry)
    return {"project_id": project_id, "results": results}
