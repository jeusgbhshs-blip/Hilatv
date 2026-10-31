"""Structured timeline: shot order and in/out points.

This does not re-encode the master. The visible 「AI生成」 mark is not a field
the client can set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from workers.expert.desk import CanvasDoc, SavedClip, update_document
from workers.expert.gates import GateError, refuse_label_bypass
from workers.logging import log_event
from workers.media.ffmpeg import RenderError, probe
from workers.qa.pixels import MediaLoad, resolve_project_file
from workers.qa.scores import content_blocked
from workers.schemas.asset import Candidate

_LABEL_KEYS = frozenset(
    {
        "omit_ai_label",
        "hide_ai_label",
        "remove_ai_label",
        "show_ai_label",
        "ai_label",
        "drop_ai_label",
        "skip_ai_label",
    }
)
_EPSILON = 0.05


class ClipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    in_s: float = Field(ge=0)
    out_s: float = Field(gt=0)


def save_structured_timeline(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    refuse_label_bypass(body)
    extra = set(body) - {"clips"}
    if extra & _LABEL_KEYS:
        raise GateError("AI 标识不能修改")
    if extra:
        raise GateError("时间轴只接受镜头顺序和入出点")
    raw_clips = body.get("clips")
    if not isinstance(raw_clips, list) or not raw_clips:
        raise GateError("时间轴至少要有一个镜头")
    try:
        clips = [ClipIn.model_validate(item) for item in raw_clips]
    except ValidationError as exc:
        raise GateError("入点出点无效") from exc

    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        if snapshot.get("status") == "running":
            raise GateError("项目仍在运行", status=409)
        seen: set[str] = set()
        saved: list[SavedClip] = []
        for clip in clips:
            if clip.shot_id in seen:
                raise GateError("同一镜头不能在时间轴上出现两次")
            seen.add(clip.shot_id)
            if clip.out_s <= clip.in_s:
                raise GateError("出点必须晚于入点")
            if not _has_picture(state, clip.shot_id):
                # 没有候选画面的镜头（例如片尾合成段）：按分镜时长校验，保留为固定段。
                fixed = _shot_duration(state, clip.shot_id) or 0
                if fixed <= 0:
                    raise GateError("无法确认素材时长")
                if clip.out_s > fixed + _EPSILON:
                    raise GateError("入点出点超出素材时长")
                saved.append(
                    SavedClip(
                        shot_id=clip.shot_id,
                        candidate_id=clip.candidate_id,
                        in_s=clip.in_s,
                        out_s=clip.out_s,
                    )
                )
                continue
            candidate = _candidate(state, clip.shot_id, clip.candidate_id)
            if content_blocked(candidate.qa):
                raise GateError("内容安全硬伤不能进入成片")
            duration = _duration(candidate, _shot_duration(state, clip.shot_id))
            if duration <= 0:
                raise GateError("无法确认素材时长")
            if clip.out_s > duration + _EPSILON:
                raise GateError("入点出点超出素材时长")
            saved.append(
                SavedClip(
                    shot_id=clip.shot_id,
                    candidate_id=clip.candidate_id,
                    in_s=clip.in_s,
                    out_s=clip.out_s,
                )
            )
        doc.timeline_clips = saved
        doc.layout_version += 1
        log_event(
            "timeline_edit",
            project_id=project_id,
            node="n15_compose",
            attempt=1,
            clips=len(saved),
        )
        return {
            "project_id": project_id,
            "ai_label": True,
            "layout_version": doc.layout_version,
            "clips": [item.model_dump(mode="json") for item in saved],
        }

    saved_body = update_document(project_id, mutate)
    from workers.expert.canvas import build_canvas

    saved_body["canvas"] = build_canvas(project_id)
    return saved_body


def _has_picture(state: dict[str, Any], shot_id: str) -> bool:
    for key in ("keyframes", "videos"):
        for raw in state.get(key) or []:
            if isinstance(raw, dict) and raw.get("shot_id") == shot_id:
                return True
    return False


def _candidate(state: dict[str, Any], shot_id: str, candidate_id: str) -> Candidate:
    for raw in list(state.get("videos") or []) + list(state.get("keyframes") or []):
        if not isinstance(raw, dict):
            continue
        if raw.get("shot_id") != shot_id or raw.get("candidate_id") != candidate_id:
            continue
        try:
            return Candidate.model_validate(raw)
        except ValidationError as exc:
            raise GateError("候选不存在", status=404) from exc
    raise GateError("候选不存在", status=404)


def _shot_duration(state: dict[str, Any], shot_id: str) -> float | None:
    script = state.get("script") if isinstance(state.get("script"), dict) else {}
    for item in script.get("shots") or []:
        if isinstance(item, dict) and item.get("shot_id") == shot_id:
            raw = item.get("duration_s")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
                return float(raw)
    return None


def _duration(candidate: Candidate, shot_duration: float | None) -> float:
    if _still(candidate):
        return shot_duration or 0
    located = _local_file(candidate.uri)
    if located is not None:
        try:
            measured = float(probe(located).get("duration_s") or 0)
        except (RenderError, OSError, ValueError):
            measured = 0
        if measured > 0:
            return measured
    for key in ("duration_s", "duration"):
        raw = candidate.params.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return float(raw)
    return shot_duration or 0


def _still(candidate: Candidate) -> bool:
    if candidate.node == "N8":
        return True
    return candidate.uri.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))


def _local_file(uri: str) -> Path | None:
    if not uri or uri.startswith(("mock://", "oss://", "http://", "https://")):
        return None
    located = resolve_project_file(Path(uri))
    if isinstance(located, MediaLoad) or not located.is_file():
        return None
    return located
