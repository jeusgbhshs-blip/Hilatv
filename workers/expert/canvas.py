"""Read-only expert canvas. Verdicts come from stored QA reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workers.expert.gates import GateError, verdict_of
from workers.media.assets import materialize_project_asset
from workers.media.packaging import ai_label_text
from workers.qa.budget_store import open_project_budget
from workers.qa.pixels import MediaLoad, resolve_project_file
from workers.qa.scores import content_blocked
from workers.schemas.asset import Candidate
from workers.workflow.contract import PIPELINE
from workers.workflow.store import load_checkpoint, read_snapshot, valid_project_id

LABELS = {
    "n01_brief": "需求理解",
    "n02_brand_kit": "品牌资料",
    "n03_concept": "方案",
    "n04_script": "脚本",
    "n05_storyboard": "分镜",
    "n06_voiceover": "配音",
    "n08_keyframe": "关键帧",
    "n09_keyframe_qa": "关键帧质检",
    "n10_video": "视频",
    "shot_director": "镜头检查",
    "n12_music": "音乐",
    "n13_subtitle": "字幕",
    "n14_packaging": "包装",
    "n15_compose": "合成",
}

_EDGES = (
    ("n01_brief", "n02_brand_kit"),
    ("n02_brand_kit", "n03_concept"),
    ("n03_concept", "n04_script"),
    ("n04_script", "n05_storyboard"),
    ("n05_storyboard", "n06_voiceover"),
    ("n06_voiceover", "n08_keyframe"),
    ("n08_keyframe", "n09_keyframe_qa"),
    ("n09_keyframe_qa", "n10_video"),
    ("n10_video", "shot_director"),
    ("shot_director", "n12_music"),
    ("shot_director", "n13_subtitle"),
    ("shot_director", "n14_packaging"),
    ("n12_music", "n15_compose"),
    ("n13_subtitle", "n15_compose"),
    ("n14_packaging", "n15_compose"),
)


def build_canvas(project_id: str) -> dict[str, Any]:
    if not valid_project_id(project_id):
        raise GateError("项目不存在", status=404)
    snapshot = read_snapshot(project_id)
    if snapshot is None:
        raise GateError("项目不存在", status=404)
    state = load_checkpoint(project_id)
    completed = set(state.get("completed") or [])
    keyframes = _candidates(state.get("keyframes"))
    videos = _candidates(state.get("videos"))
    budget = open_project_budget(project_id)
    shots = _shots(state, keyframes, videos, project_id)
    body = {
        "project_id": project_id,
        "sentence": snapshot.get("sentence") or "",
        "status": snapshot.get("status") or "",
        "budget": {
            "used": budget.used,
            "limit": budget.limit,
            "remaining": max(0, budget.limit - budget.used - budget.reserved),
        },
        "nodes": [
            {
                "id": name,
                "label": LABELS.get(name, name),
                "completed": name in completed,
                "generative": name in {"n06_voiceover", "n08_keyframe", "n10_video"},
            }
            for name in PIPELINE
        ],
        "edges": [{"source": source, "target": target} for source, target in _EDGES],
        "shots": shots,
        "timeline": _timeline_view(project_id, state),
        "master": _master(keyframes, videos, snapshot),
    }
    from workers.expert.desk import extend_canvas

    return extend_canvas(project_id, state, snapshot, body)


def media_file(project_id: str, candidate_id: str) -> Path | None:
    if not valid_project_id(project_id):
        return None
    state = load_checkpoint(project_id)
    from workers.expert.desk import load_doc

    content = [
        row
        for node in load_doc(project_id).user_nodes
        for row in node.data.get("candidates", [])
        if isinstance(row, dict)
    ]
    for raw in list(state.get("keyframes") or []) + list(state.get("videos") or []) + content:
        if not isinstance(raw, dict) or raw.get("candidate_id") != candidate_id:
            continue
        uri = raw.get("uri")
        if not isinstance(uri, str):
            return None
        return materialize_project_asset(project_id, uri)
    return None


def _candidates(raw: Any) -> list[Candidate]:
    if not isinstance(raw, list):
        return []
    found: list[Candidate] = []
    for item in raw:
        if isinstance(item, dict):
            found.append(Candidate.model_validate(item))
    return found


def _shots(
    state: dict[str, Any],
    keyframes: list[Candidate],
    videos: list[Candidate],
    project_id: str,
) -> list[dict[str, Any]]:
    script = state.get("script") if isinstance(state.get("script"), dict) else {}
    rows = script.get("shots") if isinstance(script.get("shots"), list) else []
    order: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "")
        if not shot_id or shot_id in seen:
            continue
        seen.add(shot_id)
        order.append((int(item.get("order") or 0), shot_id, str(item.get("purpose") or "")))
    for candidate in keyframes + videos:
        if candidate.shot_id not in seen:
            seen.add(candidate.shot_id)
            order.append((len(order) + 1, candidate.shot_id, ""))
    shots: list[dict[str, Any]] = []
    for index, shot_id, purpose in sorted(order):
        shots.append(
            {
                "shot_id": shot_id,
                "order": index,
                "purpose": purpose,
                "keyframes": [
                    _public(item, project_id) for item in keyframes if item.shot_id == shot_id
                ],
                "videos": [_public(item, project_id) for item in videos if item.shot_id == shot_id],
            }
        )
    return shots


def _public(candidate: Candidate, project_id: str) -> dict[str, Any]:
    verdict = verdict_of(candidate.qa)
    media_url, note = _media(candidate, project_id)
    prompt = str(candidate.params.get("prompt") or "")
    return {
        "candidate_id": candidate.candidate_id,
        "shot_id": candidate.shot_id,
        "node": candidate.node,
        "model": candidate.model,
        "seed": candidate.params.get("seed"),
        "frame": candidate.params.get("frame"),
        "prompt": prompt,
        "selected": bool(candidate.selected),
        "verdict": verdict,
        "media_url": media_url,
        "media_note": note,
    }


def _media(candidate: Candidate, project_id: str) -> tuple[str | None, str]:
    uri = candidate.uri
    if uri.startswith("mock://"):
        return None, "mock 无画面"
    if not uri.startswith(("oss://", "s3://")) and _servable(uri, project_id) is None:
        return None, "未测"
    return f"/v1/projects/{project_id}/expert/media/{candidate.candidate_id}", ""


def _servable(uri: str, project_id: str) -> Path | None:
    return materialize_project_asset(project_id, uri)


def _timeline_view(project_id: str, state: dict[str, Any]) -> dict[str, Any]:
    raw = load_timeline_dict(project_id, state)
    if raw is None:
        return {
            "present": False,
            "ai_label": None,
            "duration_s": None,
            "clips": [],
            "overlays": [],
        }
    overlays = [item for item in raw.get("overlays") or [] if isinstance(item, dict)]
    clips = [item for item in raw.get("clips") or [] if isinstance(item, dict)]
    label = ai_label_text()
    has_label = any(
        item.get("kind") == "ai_label" and item.get("text") == label for item in overlays
    )
    return {
        "present": True,
        "ai_label": has_label,
        "duration_s": raw.get("duration_s"),
        "clips": [
            {"clip_id": item.get("clip_id"), "transition_out": item.get("transition_out") or "cut"}
            for item in clips
        ],
        "overlays": [
            {"kind": item.get("kind"), "text": item.get("text") or ""} for item in overlays
        ],
    }


def load_timeline_dict(
    project_id: str, state: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if state is None:
        state = load_checkpoint(project_id)
    raw = state.get("timeline")
    if isinstance(raw, dict) and raw.get("overlays") is not None:
        return raw
    path_value = state.get("timeline_path")
    if isinstance(path_value, str) and path_value:
        located = resolve_project_file(Path(path_value))
        if not isinstance(located, MediaLoad) and located.is_file():
            import json

            data = json.loads(located.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    return None


def _master(
    keyframes: list[Candidate],
    videos: list[Candidate],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    selected = [item for item in keyframes + videos if item.selected]
    blocked = [item for item in selected if content_blocked(item.qa)]
    deliverable = isinstance(snapshot.get("deliverable"), str) and bool(snapshot.get("deliverable"))
    if blocked:
        return {
            "ready": deliverable,
            "qa_passed": False,
            "blocked": True,
            "reason": "内容安全硬伤不能进入成片",
        }
    if selected and all(verdict_of(item.qa)["qa_passed"] for item in selected):
        return {"ready": deliverable, "qa_passed": True, "blocked": False, "reason": "质检通过"}
    if not selected:
        reason = "没有选中的候选" if (keyframes or videos) else "还没有候选"
    else:
        reason = "未评审，不能标为质检通过"
    return {"ready": deliverable, "qa_passed": False, "blocked": False, "reason": reason}
