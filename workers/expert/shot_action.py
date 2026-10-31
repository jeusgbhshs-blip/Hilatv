"""Redo one shot, or replace the picture that shot reads.

The call runs the keyframe node and the video node for that shot only.
Music, subtitles, packaging, and the compose node are not invoked.
New candidates are stored with ``visual_reviewed`` false, so they cannot
be treated as a pass.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from workers.expert.charge import reserve_picture
from workers.expert.desk import (
    CanvasDoc,
    ShotDesk,
    shot_node_id,
    update_document,
)
from workers.expert.gates import GateError, refuse_label_bypass
from workers.expert.invoke import invoke_node
from workers.expert.uploads import resolve_upload
from workers.identity.session import canonical_enterprise
from workers.logging import log_event
from workers.schemas.asset import Candidate
from workers.schemas.script import Script
from workers.workflow.store import project_path, save_node

_MAX_SUFFIX = 500
_PICTURE = ("n08_keyframe", "n10_video")


def regenerate_shot(
    project_id: str,
    shot_id: str,
    body: dict[str, Any] | None = None,
    *,
    gateway: Any | None = None,
) -> dict[str, Any]:
    """Regenerate one shot from the current upstream wires."""

    payload = body or {}
    refuse_label_bypass(payload)
    user_suffix = _optional_text(payload.get("prompt_suffix"), "补充提示词过长")
    narration = _optional_text(payload.get("narration"), "旁白过长")
    box: dict[str, Any] = {}

    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> None:
        if snapshot.get("status") == "running":
            raise GateError("项目仍在运行", status=409)
        row = _shot_row(state, shot_id)
        desk = doc.shots.get(shot_id) or ShotDesk()
        if user_suffix is not None:
            desk.prompt_suffix = user_suffix
        if narration is not None:
            desk.narration = narration
            _write_narration(project_id, state, shot_id, narration)
        suffix = desk.prompt_suffix
        spoken = desk.narration if desk.narration is not None else str(row.get("voiceover") or "")
        texts, uploads = _upstream(doc, shot_node_id(shot_id))
        if desk.reference_upload_id:
            uploads.append(desk.reference_upload_id)
        uploads = list(dict.fromkeys(uploads))
        enterprise_id = snapshot.get("enterprise_id")
        owner = enterprise_id if isinstance(enterprise_id, str) else ""
        for item in uploads:
            _check_upload(item, owner)
        for text in texts:
            refuse_label_bypass(text)
        model_suffix = _model_suffix(suffix, spoken, texts, uploads)
        refuse_label_bypass(model_suffix)
        rows = _script_rows(state)
        charged = reserve_picture(project_id, rows, shot_id)
        log_event(
            "shot_regenerate",
            project_id=project_id,
            node="n08_keyframe",
            shot_id=shot_id,
            attempt=1,
            charged=charged,
        )
        for name in _PICTURE:
            key = "keyframes" if name == "n08_keyframe" else "videos"
            previous = [item for item in (state.get(key) or []) if isinstance(item, dict)]
            patch = invoke_node(
                name,
                project_id=project_id,
                state=state,
                snapshot=snapshot,
                shot_id=shot_id,
                prompt_suffix=model_suffix,
                gateway=gateway,
                enterprise_id=owner or None,
            )
            fresh = [
                item
                for item in (patch.get(key) or [])
                if isinstance(item, dict) and item.get("shot_id") == shot_id
            ]
            kept = [item for item in previous if item.get("shot_id") != shot_id]
            rows_out = kept + _demote(fresh, shot_id)
            _store(project_id, name, {key: rows_out})
            state[key] = rows_out
        desk.regen_count += charged
        doc.shots[shot_id] = desk
        doc.layout_version += 1
        box["charged"] = charged
        box["nodes"] = list(_PICTURE)
        box["prompt_suffix"] = model_suffix

    update_document(project_id, mutate)
    from workers.expert.canvas import build_canvas

    return {
        "project_id": project_id,
        "shot_id": shot_id,
        "nodes": box.get("nodes") or list(_PICTURE),
        "charged": box.get("charged") or 0,
        "canvas": build_canvas(project_id),
    }


def set_reference(
    project_id: str,
    shot_id: str,
    upload_id: str,
    *,
    enterprise_id: str,
) -> dict[str, Any]:
    """Point this shot at a picture from ``POST /v1/uploads``."""

    resolve_upload(upload_id, enterprise_id=enterprise_id)

    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> None:
        owner = snapshot.get("enterprise_id")
        if not isinstance(owner, str) or canonical_enterprise(owner) != canonical_enterprise(
            enterprise_id
        ):
            raise GateError("项目不存在", status=404)
        _shot_row(state, shot_id)
        desk = doc.shots.get(shot_id) or ShotDesk()
        desk.reference_upload_id = upload_id
        doc.shots[shot_id] = desk
        doc.layout_version += 1
        log_event(
            "shot_reference",
            project_id=project_id,
            node="n08_keyframe",
            shot_id=shot_id,
            attempt=1,
        )

    update_document(project_id, mutate)
    from workers.expert.canvas import build_canvas

    return {
        "project_id": project_id,
        "shot_id": shot_id,
        "upload_id": upload_id,
        "canvas": build_canvas(project_id),
    }


def _upstream(doc: CanvasDoc, shot_node: str) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    uploads: list[str] = []
    by_id = {node.id: node for node in doc.user_nodes}
    edges = doc.edges or []
    for edge in edges:
        if edge.target != shot_node:
            continue
        node = by_id.get(edge.source)
        if node is None:
            continue
        if edge.role == "text" and node.kind == "brief":
            text = str(node.data.get("text") or "").strip()
            if text:
                texts.append(text)
        elif edge.role == "reference" and node.kind == "ref_image":
            upload_id = node.data.get("upload_id")
            if isinstance(upload_id, str) and upload_id:
                uploads.append(upload_id)
    return texts, uploads


def _model_suffix(suffix: str, narration: str, texts: list[str], uploads: list[str]) -> str:
    parts: list[str] = []
    if suffix:
        parts.append(suffix)
    if narration:
        parts.append(f"旁白：{narration}")
    if texts:
        parts.append("参考说明：" + " ".join(texts))
    if uploads:
        parts.append("参考图 " + " ".join(uploads))
    return "\n".join(parts)


def _check_upload(upload_id: str, enterprise_id: str) -> str:
    if not enterprise_id:
        raise GateError("参考图不存在", status=404)
    return str(resolve_upload(upload_id, enterprise_id=enterprise_id))


def _demote(rows: list[dict[str, Any]], shot_id: str) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict) or raw.get("shot_id") != shot_id:
            changed.append(raw)
            continue
        candidate = Candidate.model_validate(raw)
        qa = candidate.qa.model_copy(update={"visual_reviewed": False})
        changed.append(candidate.model_copy(update={"qa": qa}).model_dump(mode="json"))
    return changed


def _write_narration(project_id: str, state: dict[str, Any], shot_id: str, narration: str) -> None:
    script = state.get("script")
    if not isinstance(script, dict):
        raise GateError("缺少上游结果：script", status=409)
    found = None
    for item in script.get("shots") or []:
        if isinstance(item, dict) and item.get("shot_id") == shot_id:
            found = item
            break
    if found is None:
        raise GateError("镜头不存在", status=404)
    found["voiceover"] = narration
    try:
        Script.model_validate(script)
    except ValidationError as exc:
        raise GateError("旁白无法写入脚本") from exc
    state["script"] = script
    _store(project_id, "n05_storyboard", {"script": script})


def _store(project_id: str, node: str, patch: dict[str, Any]) -> None:
    path = project_path(project_id) / "nodes" / f"{node}.json"
    current: dict[str, Any] = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            current = loaded
    current.update(patch)
    save_node(project_id, node, current)


def _shot_row(state: dict[str, Any], shot_id: str) -> dict[str, Any]:
    for item in _script_rows(state):
        if item.get("shot_id") == shot_id:
            return item
    raise GateError("镜头不存在", status=404)


def _script_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    script = state.get("script") if isinstance(state.get("script"), dict) else {}
    rows = script.get("shots") if isinstance(script.get("shots"), list) else []
    return [item for item in rows if isinstance(item, dict)]


def _optional_text(raw: Any, too_long: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise GateError("文本无效")
    text = " ".join(raw.split())
    if len(text) > _MAX_SUFFIX:
        raise GateError(too_long)
    refuse_label_bypass(text)
    return text
