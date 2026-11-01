"""Editable expert canvas stored on the project.

Positions, user nodes, and edges live in ``canvas.json``. The fixed pipeline
is the default edge list until someone adds or deletes a wire. Optimistic
concurrency uses ``layout_version``.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from workers.expert.canvas import _EDGES
from workers.expert.canvas_db import mirror_canvas
from workers.expert.gates import GateError, refuse_label_bypass
from workers.identity.session import canonical_enterprise
from workers.logging import log_event
from workers.workflow.contract import PIPELINE
from workers.workflow.store import (
    load_checkpoint,
    locked_project,
    read_project_json,
    read_snapshot,
    valid_project_id,
    write_project_json,
)

_MAX_NODES = 40
_MAX_EDGES = 200
_MAX_TEXT = 4000
_USER_KINDS = frozenset({"brief", "ref_image", "image", "video", "script", "audio"})
_CONTENT_KINDS = frozenset({"image", "video", "audio"})
_LABELS = {
    "brief": "需求文本",
    "ref_image": "参考图",
    "image": "图片",
    "video": "视频",
    "script": "脚本",
    "audio": "音频",
}
_ROLES = frozenset({"reference", "text", "feeds_final", "pipeline"})


class VersionConflict(GateError):
    """The client edited a canvas that has already moved on."""

    def __init__(self, layout_version: int) -> None:
        super().__init__("画布版本冲突", status=409)
        self.layout_version = layout_version


class Position(BaseModel):
    model_config = ConfigDict(extra="ignore")

    x: float
    y: float

    def bounded(self) -> Position:
        if isinstance(self.x, bool) or isinstance(self.y, bool):
            raise ValueError("position")
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError("position")
        if abs(self.x) > 1_000_000 or abs(self.y) > 1_000_000:
            raise ValueError("position")
        return self


class Viewport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    x: float = 0
    y: float = 0
    zoom: float = 1

    def bounded(self) -> Viewport:
        for name in ("x", "y", "zoom"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("viewport")
            if not math.isfinite(float(value)):
                raise ValueError("viewport")
        if not 0.05 <= self.zoom <= 4:
            raise ValueError("zoom")
        if abs(self.x) > 1_000_000 or abs(self.y) > 1_000_000:
            raise ValueError("pan")
        return self


class UserNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: str
    position: Position
    data: dict[str, Any] = Field(default_factory=dict)


class DeskEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None
    role: str
    user_created: bool = False


class ShotDesk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    narration: str | None = None
    prompt_suffix: str = ""
    reference_upload_id: str | None = None
    regen_count: int = 0


class SavedClip(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: str
    candidate_id: str
    in_s: float
    out_s: float


class CanvasDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")

    layout_version: int = 0
    viewport: Viewport = Field(default_factory=Viewport)
    positions: dict[str, Position] = Field(default_factory=dict)
    user_nodes: list[UserNode] = Field(default_factory=list)
    edges: list[DeskEdge] | None = None
    shots: dict[str, ShotDesk] = Field(default_factory=dict)
    timeline_clips: list[SavedClip] | None = None


def shot_node_id(shot_id: str) -> str:
    return f"shot:{shot_id}"


def load_doc(project_id: str) -> CanvasDoc:
    if not valid_project_id(project_id):
        raise GateError("项目不存在", status=404)
    try:
        raw = read_project_json(project_id, "canvas.json")
    except ValueError as exc:
        raise GateError("画布数据无法读取") from exc
    if raw is None:
        return CanvasDoc()
    try:
        return CanvasDoc.model_validate(raw)
    except ValidationError as exc:
        raise GateError("画布数据无法读取") from exc


def update_document(
    project_id: str,
    mutator: Callable[[CanvasDoc, dict[str, Any], dict[str, Any]], Any],
) -> Any:
    """Read, mutate, and write the canvas while the project lock is held."""

    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    with locked_project(project_id):
        snapshot = read_snapshot(project_id) or {}
        state = load_checkpoint(project_id)
        doc = load_doc(project_id)
        result = mutator(doc, state, snapshot)
        payload = doc.model_dump(mode="json")
        payload.pop("ai_label", None)
        write_project_json(project_id, "canvas.json", payload)
        owner = snapshot.get("enterprise_id")
        mirror_canvas(project_id, owner if isinstance(owner, str) else None, payload)
        return result


def extend_canvas(
    project_id: str,
    state: dict[str, Any],
    snapshot: dict[str, Any],
    body: dict[str, Any],
) -> dict[str, Any]:
    """Add desk fields without dropping the pipeline list the current UI reads."""

    doc = load_doc(project_id)
    rows = _script_rows(state)
    by_shot = {str(item.get("shot_id") or ""): item for item in rows if item.get("shot_id")}
    positions = doc.positions
    for index, node in enumerate(body.get("nodes") or []):
        node_id = str(node.get("id") or "")
        node["kind"] = node_id
        node["position"] = _point(positions, node_id, _pipeline_point(index))
        node["data"] = {"node": node_id}
        node["user_created"] = False
    extras: list[dict[str, Any]] = []
    for shot in body.get("shots") or []:
        shot_id = str(shot.get("shot_id") or "")
        if not shot_id:
            continue
        script = by_shot.get(shot_id) or {}
        order = int(shot.get("order") or 0)
        extras.append(_shot_node(project_id, doc, shot, script, order, positions))
    for user in doc.user_nodes:
        extras.append(_user_node(project_id, user, positions))
    extras.append(_final_node(doc, snapshot, positions))
    body["nodes"] = list(body.get("nodes") or []) + extras
    body["edges"] = [_public_edge(edge) for edge in _resolved_edges(doc)]
    body["viewport"] = doc.viewport.model_dump(mode="json")
    body["layout_version"] = doc.layout_version
    timeline = body.get("timeline") if isinstance(body.get("timeline"), dict) else {}
    timeline["edit"] = _timeline_edit(doc)
    body["timeline"] = timeline
    return body


def put_layout(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    refuse_label_bypass(body)
    version = _version(body.get("layout_version"))
    try:
        viewport = Viewport.model_validate(body.get("viewport") or {}).bounded()
    except (ValidationError, ValueError) as exc:
        raise GateError("视口无效") from exc
    incoming = _positions(body.get("positions"))

    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        del snapshot
        if version != doc.layout_version:
            raise VersionConflict(doc.layout_version)
        known = _known_ids(doc, state)
        unknown = [item for item in incoming if item not in known]
        if unknown:
            raise GateError("未知节点")
        doc.positions.update(incoming)
        for node in doc.user_nodes:
            if node.id in incoming:
                node.position = incoming[node.id]
        doc.viewport = viewport
        doc.layout_version += 1
        log_event(
            "canvas_layout",
            project_id=project_id,
            node="canvas",
            attempt=1,
            layout_version=doc.layout_version,
        )
        return {
            "layout_version": doc.layout_version,
            "viewport": doc.viewport.model_dump(mode="json"),
            "positions": {
                key: value.model_dump(mode="json") for key, value in doc.positions.items()
            },
        }

    return update_document(project_id, mutate)


def add_node(project_id: str, body: dict[str, Any], *, enterprise_id: str) -> dict[str, Any]:
    refuse_label_bypass(body)
    kind = body.get("kind")
    if kind not in _USER_KINDS:
        raise GateError("只能新建需求文本或参考图")
    try:
        position = Position.model_validate(body.get("position") or {}).bounded()
    except (ValidationError, ValueError) as exc:
        raise GateError("节点位置无效") from exc
    data = body.get("data") if isinstance(body.get("data"), dict) else {}

    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        del state
        _owner_matches(snapshot, enterprise_id)
        if len(doc.user_nodes) >= _MAX_NODES:
            raise GateError("节点太多了")
        if kind == "brief":
            stored = {"text": _brief_text(data.get("text"))}
        elif kind == "ref_image":
            stored = {"upload_id": _upload_id(data.get("upload_id"), enterprise_id)}
        else:
            stored = {"prompt": _prompt_text(data.get("prompt")), "candidates": []}
        if kind == "script":
            stored = {"prompt": _prompt_text(data.get("prompt"))}
        if kind == "audio":
            stored = {
                "prompt": _prompt_text(data.get("prompt")),
                "mode": "music",
                "candidates": [],
            }
        prefix = {
            "brief": "brief",
            "ref_image": "ref",
            "image": "img",
            "video": "vid",
            "script": "scr",
            "audio": "aud",
        }[str(kind)]
        node = UserNode(
            id=_fresh_id(prefix),
            kind=str(kind),
            position=position,
            data=stored,
        )
        doc.user_nodes.append(node)
        doc.positions[node.id] = position
        doc.layout_version += 1
        log_event("canvas_node", project_id=project_id, node="canvas", attempt=1, kind=kind)
        public = _user_node(project_id, node, doc.positions)
        public["layout_version"] = doc.layout_version
        return public

    return update_document(project_id, mutate)


def patch_node(
    project_id: str,
    node_id: str,
    body: dict[str, Any],
    *,
    enterprise_id: str,
) -> dict[str, Any]:
    refuse_label_bypass(body)
    data = body.get("data") if isinstance(body.get("data"), dict) else None
    shot_data = None
    if node_id.startswith("shot:"):
        if "data" in body and not isinstance(body["data"], dict):
            raise GateError("镜头正文无效")
        shot_data = _checked_shot_data(data or {})
        if not shot_data and "position" not in body:
            raise GateError("请提供需要保存的镜头内容")
    position = None
    if "position" in body:
        try:
            position = Position.model_validate(body.get("position") or {}).bounded()
        except (ValidationError, ValueError) as exc:
            raise GateError("节点位置无效") from exc

    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        _owner_matches(snapshot, enterprise_id)
        if shot_data is not None:
            shot_id = node_id.split(":", 1)[1]
            row = next(
                (item for item in _script_rows(state) if item.get("shot_id") == shot_id), None
            )
            if row is None:
                raise GateError("镜头不存在", status=404)
            desk = doc.shots.get(shot_id) or ShotDesk()
            for key, value in shot_data.items():
                setattr(desk, key, value)
            doc.shots[shot_id] = desk
            if position is not None:
                doc.positions[node_id] = position
            doc.layout_version += 1
            public = _shot_node(
                project_id,
                doc,
                {"shot_id": shot_id},
                row,
                int(row.get("order") or 1),
                doc.positions,
            )
            public["layout_version"] = doc.layout_version
            public["data"]["edit_status"] = "saved_for_next_generation"
            return public
        node = _require_user(doc, state, node_id)
        if data is not None:
            if node.kind == "brief":
                node.data = {"text": _brief_text(data.get("text", node.data.get("text")))}
            elif node.kind == "ref_image":
                upload_id = _upload_id(
                    data.get("upload_id", node.data.get("upload_id")),
                    enterprise_id,
                )
                node.data = {"upload_id": upload_id}
            else:
                node.data = {
                    **node.data,
                    "prompt": _prompt_text(data.get("prompt", node.data.get("prompt"))),
                }
        if position is not None:
            node.position = position
            doc.positions[node.id] = position
        doc.layout_version += 1
        public = _user_node(project_id, node, doc.positions)
        public["layout_version"] = doc.layout_version
        return public

    return update_document(project_id, mutate)


def _checked_shot_data(data: dict[str, Any]) -> dict[str, str]:
    if set(data) - {"narration", "prompt_suffix"}:
        raise GateError("镜头正文只能保存旁白与补充提示词")
    checked: dict[str, str] = {}
    for key, value in data.items():
        maximum = 400 if key == "narration" else 500
        if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
            raise GateError("旁白或补充提示词无效")
        checked[key] = value.strip()
    return checked


def delete_node(project_id: str, node_id: str) -> dict[str, Any]:
    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        del snapshot
        node = next((item for item in doc.user_nodes if item.id == node_id), None)
        if node is None:
            if node_id in _known_ids(doc, state):
                raise GateError("只能删除自己添加的节点")
            raise GateError("节点不存在", status=404)
        doc.user_nodes = [item for item in doc.user_nodes if item.id != node_id]
        doc.positions.pop(node_id, None)
        edges = _materialize(doc)
        doc.edges = [edge for edge in edges if edge.source != node_id and edge.target != node_id]
        doc.layout_version += 1
        return {"deleted": node_id, "layout_version": doc.layout_version}

    return update_document(project_id, mutate)


def add_edge(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    refuse_label_bypass(body)
    source = str(body.get("source") or "")
    target = str(body.get("target") or "")
    role = str(body.get("role") or "")
    if not source or not target or role not in _ROLES:
        raise GateError("连线类型不匹配")
    source_handle = _handle(body.get("source_handle"))
    target_handle = _handle(body.get("target_handle"))

    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        del snapshot
        source_kind = _kind(source, doc, state)
        target_kind = _kind(target, doc, state)
        if source_kind is None or target_kind is None:
            raise GateError("未知节点", status=404)
        if not _compatible(source_kind, target_kind, role):
            raise GateError("连线类型不匹配")
        edges = _materialize(doc)
        if len(edges) >= _MAX_EDGES:
            raise GateError("连线太多了")
        if any(edge.source == source and edge.target == target for edge in edges):
            raise GateError("连线已存在")
        if _closes_cycle(edges, source, target):
            raise GateError("连线会成环")
        edge = DeskEdge(
            id=_fresh_id("edge"),
            source=source,
            target=target,
            source_handle=source_handle,
            target_handle=target_handle,
            role=role,
            user_created=True,
        )
        edges.append(edge)
        doc.edges = edges
        doc.layout_version += 1
        log_event(
            "canvas_edge",
            project_id=project_id,
            node="canvas",
            attempt=1,
            role=role,
        )
        public = _public_edge(edge)
        public["layout_version"] = doc.layout_version
        return public

    return update_document(project_id, mutate)


def delete_edge(project_id: str, edge_id: str) -> dict[str, Any]:
    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        del state, snapshot
        edges = _materialize(doc)
        kept = [edge for edge in edges if edge.id != edge_id]
        if len(kept) == len(edges):
            raise GateError("连线不存在", status=404)
        doc.edges = kept
        doc.layout_version += 1
        return {"deleted": edge_id, "layout_version": doc.layout_version}

    return update_document(project_id, mutate)


def default_edges() -> list[DeskEdge]:
    return [
        DeskEdge(
            id=f"pipe:{source}:{target}",
            source=source,
            target=target,
            role="pipeline",
            user_created=False,
        )
        for source, target in _EDGES
    ]


def _resolved_edges(doc: CanvasDoc) -> list[DeskEdge]:
    if doc.edges is None:
        return default_edges()
    return list(doc.edges)


def _materialize(doc: CanvasDoc) -> list[DeskEdge]:
    if doc.edges is None:
        doc.edges = default_edges()
    return doc.edges


def _closes_cycle(edges: list[DeskEdge], source: str, target: str) -> bool:
    if source == target:
        return True
    graph: dict[str, list[str]] = {}
    for edge in edges:
        graph.setdefault(edge.source, []).append(edge.target)
    seen: set[str] = set()
    stack = [target]
    while stack:
        node = stack.pop()
        if node == source:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, []))
    return False


def _compatible(source_kind: str, target_kind: str, role: str) -> bool:
    if role == "reference":
        if source_kind == "ref_image" and target_kind in {"shot", "image"}:
            return True
        return source_kind == "image" and target_kind == "video"
    if role == "text":
        return source_kind == "brief" and target_kind in {"shot", "image", "video"}
    if role == "feeds_final":
        return source_kind == "shot" and target_kind == "final"
    if role == "pipeline":
        return source_kind in PIPELINE and target_kind in PIPELINE
    return False


def _kind(node_id: str, doc: CanvasDoc, state: dict[str, Any]) -> str | None:
    if node_id in PIPELINE:
        return node_id
    if node_id == "final":
        return "final"
    shot_ids = _shot_ids(doc, state)
    if node_id.startswith("shot:") and node_id.split(":", 1)[1] in shot_ids:
        return "shot"
    for node in doc.user_nodes:
        if node.id == node_id:
            return node.kind
    return None


def _known_ids(doc: CanvasDoc, state: dict[str, Any]) -> set[str]:
    found = set(PIPELINE)
    found.add("final")
    for shot_id in _shot_ids(doc, state):
        found.add(shot_node_id(shot_id))
    for node in doc.user_nodes:
        found.add(node.id)
    return found


def _shot_ids(doc: CanvasDoc, state: dict[str, Any]) -> set[str]:
    del doc
    found: set[str] = set()
    for row in _script_rows(state):
        shot_id = str(row.get("shot_id") or "")
        if shot_id:
            found.add(shot_id)
    for key in ("keyframes", "videos"):
        for raw in state.get(key) or []:
            if isinstance(raw, dict) and raw.get("shot_id"):
                found.add(str(raw["shot_id"]))
    return found


def _script_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    script = state.get("script") if isinstance(state.get("script"), dict) else {}
    rows = script.get("shots") if isinstance(script.get("shots"), list) else []
    return [item for item in rows if isinstance(item, dict)]


def _shot_node(
    project_id: str,
    doc: CanvasDoc,
    shot: dict[str, Any],
    script: dict[str, Any],
    order: int,
    positions: dict[str, Position],
) -> dict[str, Any]:
    shot_id = str(shot["shot_id"])
    node_id = shot_node_id(shot_id)
    desk = doc.shots.get(shot_id) or ShotDesk()
    frames = list(shot.get("keyframes") or [])
    videos = list(shot.get("videos") or [])
    narration = str(script.get("voiceover") or "")
    if desk.narration is not None:
        narration = desk.narration
    duration = script.get("duration_s")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        duration_s = None
    else:
        duration_s = float(duration)
    selected = _selected_id(videos, frames)
    data: dict[str, Any] = {
        "shot_id": shot_id,
        "index": order if order else 1,
        "thumbnail_url": _thumbnail(videos, frames, selected),
        "duration_s": duration_s,
        "verdict": _shot_verdict(videos, frames, selected),
        "regen_count": desk.regen_count,
        "candidates": [_candidate_card(item, "keyframe") for item in frames]
        + [_candidate_card(item, "video") for item in videos],
        "selected_candidate_id": selected,
        "narration": narration,
        "prompt_suffix": desk.prompt_suffix,
    }
    if desk.reference_upload_id:
        data["reference_upload_id"] = desk.reference_upload_id
        data["reference_thumbnail_url"] = _upload_url(project_id, desk.reference_upload_id)
    return {
        "id": node_id,
        "kind": "shot",
        "label": f"镜头 {shot_id}",
        "completed": bool(frames or videos),
        "generative": True,
        "user_created": False,
        "position": _point(positions, node_id, {"x": 460, "y": max(order - 1, 0) * 560}),
        "data": data,
    }


def _final_node(
    doc: CanvasDoc,
    snapshot: dict[str, Any],
    positions: dict[str, Position],
) -> dict[str, Any]:
    version = snapshot.get("version_id")
    return {
        "id": "final",
        "kind": "final",
        "label": "成片",
        "completed": bool(snapshot.get("deliverable")),
        "generative": False,
        "user_created": False,
        "position": _point(positions, "final", {"x": 860, "y": 48}),
        "data": {
            "version_id": version if isinstance(version, str) and version else None,
            "ai_label": True,
        },
    }


def _user_node(project_id: str, node: UserNode, positions: dict[str, Position]) -> dict[str, Any]:
    data = dict(node.data)
    if node.kind == "ref_image" and isinstance(data.get("upload_id"), str):
        data["thumbnail_url"] = _upload_url(project_id, data["upload_id"])
    if node.kind in _CONTENT_KINDS:
        data["candidates"] = [
            _content_candidate(item, node.kind) for item in data.get("candidates") or []
        ]
        selected = data.get("selected_candidate_id")
        chosen = next(
            (item for item in data["candidates"] if item["candidate_id"] == selected), None
        )
        data["thumbnail_url"] = (chosen or {}).get("thumbnail_url")
    label = _LABELS.get(node.kind, "节点")
    return {
        "id": node.id,
        "kind": node.kind,
        "label": label,
        "completed": True,
        "generative": False,
        "user_created": True,
        "position": _point(positions, node.id, node.position.model_dump(mode="json")),
        "data": data,
    }


def _timeline_edit(doc: CanvasDoc) -> dict[str, Any] | None:
    if doc.timeline_clips is None:
        return None
    return {
        "ai_label": True,
        "clips": [item.model_dump(mode="json") for item in doc.timeline_clips],
    }


def _public_edge(edge: DeskEdge) -> dict[str, Any]:
    public: dict[str, Any] = {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "role": edge.role,
        "user_created": edge.user_created,
    }
    if edge.source_handle:
        public["source_handle"] = edge.source_handle
    if edge.target_handle:
        public["target_handle"] = edge.target_handle
    return public


def _candidate_card(item: dict[str, Any], kind: str) -> dict[str, Any]:
    return {
        "candidate_id": item.get("candidate_id"),
        "kind": kind,
        "thumbnail_url": item.get("media_url"),
        "model": item.get("model") or "",
        "verdict": _verdict_token(_verdict_dict(item)),
    }


def _verdict_token(verdict: dict[str, Any]) -> str:
    hard = verdict.get("hard_fail") if isinstance(verdict.get("hard_fail"), list) else []
    if verdict.get("blocked") or "sensitive" in hard:
        return "hard_fail"
    if verdict.get("visual_reviewed") is True and verdict.get("qa_passed") is True:
        return "pass"
    return "unreviewed"


def _shot_verdict(
    videos: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    selected: str | None,
) -> str:
    for group in (videos, frames):
        for item in group:
            if selected and item.get("candidate_id") == selected:
                return _verdict_token(_verdict_dict(item))
    tokens = [_verdict_token(_verdict_dict(item)) for item in videos + frames]
    if "hard_fail" in tokens:
        return "hard_fail"
    return "unreviewed"


def _selected_id(videos: list[dict[str, Any]], frames: list[dict[str, Any]]) -> str | None:
    for group in (videos, frames):
        for item in group:
            if item.get("selected") and item.get("candidate_id"):
                return str(item["candidate_id"])
    return None


def _thumbnail(
    videos: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    selected: str | None,
) -> str | None:
    ordered = videos + frames
    if selected:
        for item in ordered:
            if item.get("candidate_id") == selected and item.get("media_url"):
                return str(item["media_url"])
    for item in ordered:
        if item.get("media_url"):
            return str(item["media_url"])
    return None


def _verdict_dict(item: dict[str, Any]) -> dict[str, Any]:
    verdict = item.get("verdict")
    return verdict if isinstance(verdict, dict) else {}


def _point(
    positions: dict[str, Position],
    node_id: str,
    fallback: dict[str, float],
) -> dict[str, float]:
    found = positions.get(node_id)
    if found is None:
        return {"x": float(fallback["x"]), "y": float(fallback["y"])}
    return {"x": found.x, "y": found.y}


def _pipeline_point(index: int) -> dict[str, float]:
    return {"x": 48, "y": index * 120}


def _positions(raw: Any) -> dict[str, Position]:
    if not isinstance(raw, dict):
        raise GateError("缺少节点位置")
    parsed: dict[str, Position] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise GateError("未知节点")
        try:
            parsed[key] = Position.model_validate(value).bounded()
        except (ValidationError, ValueError) as exc:
            raise GateError("节点位置无效") from exc
    return parsed


def _version(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise GateError("画布版本无效")
    if raw < 0:
        raise GateError("画布版本无效")
    return raw


def _prompt_text(raw: Any) -> str:
    text = str(raw or "").strip()
    return text[:_MAX_TEXT]


def _content_candidate(raw: Any, kind: str) -> dict[str, Any]:
    item = raw if isinstance(raw, dict) else {}
    return {
        "candidate_id": str(item.get("candidate_id") or ""),
        "kind": str(item.get("kind") or kind),
        "thumbnail_url": item.get("thumbnail_url")
        if isinstance(item.get("thumbnail_url"), str)
        else None,
        "model": str(item.get("model") or ""),
        "verdict": str(item.get("verdict") or "unreviewed"),
        "uri": str(item.get("uri") or ""),
        "duration_s": item.get("duration_s"),
    }


def _brief_text(raw: Any) -> str:
    if not isinstance(raw, str):
        raise GateError("需求文本无效")
    text = " ".join(raw.split())
    if not text:
        raise GateError("需求文本无效")
    if len(text) > _MAX_TEXT:
        raise GateError("需求文本过长")
    refuse_label_bypass(text)
    return text


def _upload_id(raw: Any, enterprise_id: str) -> str:
    if not isinstance(raw, str):
        raise GateError("参考图不存在", status=404)
    from workers.expert.uploads import resolve_upload

    resolve_upload(raw, enterprise_id=enterprise_id)
    return raw


def _handle(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 40:
        raise GateError("连线类型不匹配")
    return raw.strip()


def _require_user(doc: CanvasDoc, state: dict[str, Any], node_id: str) -> UserNode:
    node = next((item for item in doc.user_nodes if item.id == node_id), None)
    if node is not None:
        return node
    if _kind(node_id, doc, state) is not None:
        raise GateError("只能修改自己添加的节点")
    raise GateError("节点不存在", status=404)


def _upload_url(project_id: str, upload_id: str) -> str:
    return f"/v1/projects/{project_id}/expert/uploads/{upload_id}"


def _owner_matches(snapshot: dict[str, Any], enterprise_id: str) -> None:
    owner = snapshot.get("enterprise_id")
    if not isinstance(owner, str):
        raise GateError("项目不存在", status=404)
    if canonical_enterprise(owner) != canonical_enterprise(enterprise_id):
        raise GateError("项目不存在", status=404)


def _fresh_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
