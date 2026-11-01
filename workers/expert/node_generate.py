"""画布节点直接生成：图片节点出图、视频节点出视频。

模型调用只走 gateway；HILATV_LIVE 关闭时是 mock，费用记 0。
新候选一律 unreviewed，不会被当成通过。
"""

from __future__ import annotations

import uuid
from typing import Any

from gateway import get_gateway
from workers.expert.desk import CanvasDoc, UserNode, update_document
from workers.expert.gates import GateError, refuse_label_bypass
from workers.expert.uploads import materialize_reference
from workers.logging import log_event

_CONTENT = frozenset({"image", "video", "audio"})
_MAX_COUNT = 4
_MAX_CANDIDATES = 24


def generate_node(
    project_id: str,
    node_id: str,
    body: dict[str, Any] | None = None,
    *,
    gateway: Any | None = None,
) -> dict[str, Any]:
    payload = body or {}
    refuse_label_bypass(payload)
    override = str(payload.get("prompt") or "").strip()
    count = payload.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= _MAX_COUNT:
        count = 1

    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> None:
        del state
        if snapshot.get("status") == "running":
            raise GateError("项目仍在运行", status=409)
        node = next((item for item in doc.user_nodes if item.id == node_id), None)
        if node is None:
            raise GateError("节点不存在", status=404)
        if node.kind not in _CONTENT:
            raise GateError("这个节点不能生成")
        prompt = override or str(node.data.get("prompt") or "").strip()
        if not prompt:
            prompt = _upstream_prompt(doc, node_id)
        if not prompt:
            raise GateError("先写提示词")
        rows = list(node.data.get("candidates") or [])
        if len(rows) >= _MAX_CANDIDATES:
            raise GateError("候选太多了，先选一张")
        engine = gateway or get_gateway()
        references = _upstream_images(doc, node, snapshot, project_id)
        for index in range(count):
            row = _generate_one(engine, node, prompt, project_id, index, references)
            rows.append(row)
        node.data = {
            **node.data,
            "prompt": prompt,
            "candidates": rows,
            "selected_candidate_id": rows[-1]["candidate_id"],
        }
        doc.layout_version += 1
        log_event(
            "canvas_generate",
            project_id=project_id,
            node="canvas",
            attempt=1,
            kind=node.kind,
            count=count,
        )

    update_document(project_id, mutate)
    from workers.expert.canvas import build_canvas

    return {"node_id": node_id, "canvas": build_canvas(project_id)}


def _generate_one(
    engine: Any,
    node: UserNode,
    prompt: str,
    project_id: str,
    index: int,
    references: list[str],
) -> dict[str, Any]:
    common = {"project_id": project_id, "node": "canvas", "params": {"seed": index}}
    if node.kind == "image":
        if references:
            common["params"]["reference_images"] = references
        result = engine.generate_image(prompt, **common)
    elif node.kind == "audio":
        result = engine.music(prompt, **common)
    else:
        if len(references) > 1:
            raise GateError("视频节点目前只接受一张首帧参考图")
        if references:
            common["params"].update(image_url=references[0], image_role="first_frame")
        duration = node.data.get("duration_s")
        seconds = (
            float(duration)
            if isinstance(duration, (int, float)) and not isinstance(duration, bool)
            else 4.0
        )
        result = engine.generate_video(prompt, duration_s=seconds, **common)
    uri = result.get("uri")
    kind = {"image": "image", "video": "video", "audio": "audio"}[node.kind]
    return {
        "candidate_id": str(uuid.uuid4()),
        "kind": kind,
        "uri": uri if isinstance(uri, str) else "",
        "model": str(
            result.get("model") or ("mock-image" if node.kind == "image" else "mock-video")
        ),
        "verdict": "unreviewed",
        "thumbnail_url": None,
        "duration_s": result.get("duration_s"),
    }


def _upstream_images(
    doc: CanvasDoc, node: UserNode, snapshot: dict[str, Any], project_id: str
) -> list[str]:
    references: list[str] = []
    by_id = {item.id: item for item in doc.user_nodes}
    owner = str(snapshot.get("enterprise_id") or "")
    for edge in doc.edges or []:
        if edge.target != node.id or edge.role != "reference":
            continue
        source = by_id.get(edge.source)
        if source is None:
            continue
        if source.kind == "ref_image":
            upload_id = source.data.get("upload_id")
            if not isinstance(upload_id, str):
                raise GateError("参考图不存在", status=404)
            references.append(
                materialize_reference(upload_id, enterprise_id=owner, project_id=project_id)
            )
        elif source.kind == "image" and node.kind == "video":
            selected = source.data.get("selected_candidate_id")
            candidate = next(
                (
                    row
                    for row in source.data.get("candidates", [])
                    if isinstance(row, dict) and row.get("candidate_id") == selected
                ),
                None,
            )
            if not candidate or not isinstance(candidate.get("uri"), str) or not candidate["uri"]:
                raise GateError("先在上游图片节点选一张候选")
            references.append(candidate["uri"])
        else:
            raise GateError("这个参考连线还不支持生成")
    if references and node.kind not in {"image", "video"}:
        raise GateError("这个节点不支持图片参考")
    if len(references) > 14:
        raise GateError("一次最多使用 14 张参考图")
    return list(dict.fromkeys(references))


def _upstream_prompt(doc: CanvasDoc, node_id: str) -> str:
    texts: list[str] = []
    by_id = {item.id: item for item in doc.user_nodes}
    for edge in doc.edges or []:
        if edge.target != node_id or edge.role != "text":
            continue
        source = by_id.get(edge.source)
        if source is not None and source.kind == "brief":
            text = str(source.data.get("text") or "").strip()
            if text:
                texts.append(text)
    return "\n".join(texts).strip()
