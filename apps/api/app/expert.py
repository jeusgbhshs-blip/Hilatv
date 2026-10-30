"""Expert-mode canvas: candidates, selection, timeline edits, and re-runs."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from workers.expert.canvas import build_canvas, media_file
from workers.expert.gates import GateError
from workers.expert.rerun import rerun_span, save_timeline, select_candidate
from workers.qa.budget_store import BudgetExhausted

router = APIRouter()

_MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/mp4",
    ".webm": "video/webm",
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


def _gate(exc: GateError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/v1/projects/{project_id}/canvas")
def project_canvas(project_id: str) -> dict:
    try:
        return build_canvas(project_id)
    except GateError as exc:
        raise _gate(exc) from exc


@router.post("/v1/projects/{project_id}/expert/rerun")
def project_rerun_node(project_id: str, body: ExpertRerun) -> dict:
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
def project_select(project_id: str, body: ExpertSelect) -> dict:
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
def project_timeline(project_id: str, body: TimelineEdit) -> dict:
    try:
        return save_timeline(project_id, body.model_dump())
    except GateError as exc:
        raise _gate(exc) from exc


@router.get("/v1/projects/{project_id}/expert/media/{candidate_id}")
def project_media(project_id: str, candidate_id: str) -> FileResponse:
    path = media_file(project_id, candidate_id)
    if path is None:
        raise HTTPException(status_code=404, detail="没有可看的画面")
    media_type = _MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=Path(path).name)
