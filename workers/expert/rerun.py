"""Manual re-run of one node and everything downstream of it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers.expert.canvas import build_canvas, load_timeline_dict
from workers.expert.charge import BudgetExhausted, reserve, span
from workers.expert.gates import (
    GateError,
    assert_ai_label,
    consent_gate,
    refuse_label_bypass,
    scrub_brand,
)
from workers.expert.invoke import invoke_node
from workers.logging import log_event
from workers.nodes.n15_compose.node import render_timeline
from workers.nodes.n15_compose.schema import Timeline
from workers.qa.scores import content_blocked
from workers.schemas.asset import Candidate
from workers.workflow.contract import FINAL_NODE, PEERS, PHASE, PIPELINE
from workers.workflow.film import needs_human_review
from workers.workflow.store import (
    load_checkpoint,
    project_path,
    publish,
    read_snapshot,
    save_node,
    update_snapshot,
    valid_project_id,
)

_AFTER_HOLD = set(PEERS) | {FINAL_NODE}

_NEEDS = {
    "n03_concept": ("brief",),
    "n04_script": ("brief",),
    "n05_storyboard": ("brief", "script"),
    "n06_voiceover": ("script",),
    "n08_keyframe": ("script",),
    "n10_video": ("script", "keyframes"),
    "n13_subtitle": ("script",),
    "n14_packaging": ("script",),
    "n15_compose": ("script",),
}


def rerun_span(
    project_id: str,
    node: str,
    *,
    shot_id: str | None = None,
    prompt_suffix: str = "",
    voice_id: str | None = None,
    gateway: Any | None = None,
    qa_passed: bool | None = None,
    visual_reviewed: bool | None = None,
    consent: bool | None = None,
    skip_ai_label: bool | None = None,
    licensed: bool | None = None,
    human_release: bool | None = None,
) -> dict[str, Any]:
    """Re-run ``node`` and downstream nodes.

    ``qa_passed``, ``visual_reviewed``, ``consent``, ``skip_ai_label``,
    ``licensed`` and ``human_release`` are accepted so a caller can send them.
    They are not read. A re-run cannot release a held project.
    """

    _ = (qa_passed, visual_reviewed, consent, licensed, human_release)
    if node not in PIPELINE:
        raise GateError("未知节点", status=400)
    snapshot = _snapshot(project_id)
    if snapshot.get("status") == "running":
        raise GateError("项目仍在运行", status=409)
    state = load_checkpoint(project_id)
    _require_upstream(node, state, snapshot)
    enterprise_id = snapshot.get("enterprise_id")
    if not isinstance(enterprise_id, str):
        enterprise_id = None
    consent_gate(enterprise_id, voice_id)
    if isinstance(state.get("brand_kit"), dict):
        state["brand_kit"] = scrub_brand(state["brand_kit"], enterprise_id)
    if voice_id and isinstance(state.get("brand_kit"), dict):
        voice = dict(state["brand_kit"].get("voice") or {})
        voice["tts_voice"] = voice_id
        state["brand_kit"]["voice"] = voice
    suffix = " ".join(prompt_suffix.split())
    if len(suffix) > 500:
        raise GateError("补充提示词过长")
    refuse_label_bypass(
        {
            "prompt_suffix": suffix,
            "omit_ai_label": True if skip_ai_label else False,
        }
    )
    charged = reserve(project_id, node)
    log_event(
        "expert_rerun",
        project_id=project_id,
        node=node,
        shot_id=shot_id,
        attempt=1,
        charged=charged,
    )
    publish(
        project_id,
        {
            "node": node,
            "phase": PHASE[node],
            "message": f"正在重跑 {node}",
            "status": "running",
            "attempt": 1,
        },
    )
    nodes = span(node)
    ran_director = False
    try:
        for name in nodes:
            if name in _AFTER_HOLD and _delivery_blocked(
                snapshot, state, ran_director=ran_director
            ):
                return _hold_result(project_id, node, nodes, charged, state)
            patch = invoke_node(
                name,
                project_id=project_id,
                state=state,
                snapshot=snapshot,
                shot_id=shot_id if name == node else None,
                prompt_suffix=suffix if name == node else "",
                gateway=gateway,
                enterprise_id=enterprise_id,
            )
            _store(project_id, name, patch)
            state.update(patch)
            if name == "shot_director":
                ran_director = True
            completed = [item for item in (state.get("completed") or []) if item != name]
            completed.append(name)
            state["completed"] = completed
        if _delivery_blocked(snapshot, state, ran_director=ran_director):
            return _hold_result(project_id, node, nodes, charged, state)
    except (GateError, BudgetExhausted):
        update_snapshot(project_id, status="failed", error="重跑没有通过检查")
        raise
    except Exception as exc:
        update_snapshot(project_id, status="failed", error=str(exc)[:300])
        raise GateError(f"重跑失败：{exc}"[:300]) from exc
    deliverable = state.get("deliverable")
    publish(
        project_id,
        {
            "node": nodes[-1],
            "phase": "成片",
            "message": "重跑完成",
            "status": "completed",
            "attempt": 1,
            "deliverable": deliverable,
        },
    )
    if isinstance(state.get("shot_summaries"), list):
        update_snapshot(project_id, shots=state["shot_summaries"])
    return {
        "project_id": project_id,
        "node": node,
        "nodes": nodes,
        "charged": charged,
        "canvas": build_canvas(project_id),
    }


def _delivery_blocked(
    snapshot: dict[str, Any],
    state: dict[str, Any],
    *,
    ran_director: bool,
) -> bool:
    """A re-run cannot deliver while the human-review hold applies.

    ``human_release`` is never taken from the caller. Only a director pass
    in this same re-run can clear notes that still say ``needs_review``.
    """

    if needs_human_review(state, {}):
        return True
    if not ran_director and snapshot.get("status") == "needs_human_review":
        return True
    return False


def _hold_result(
    project_id: str,
    node: str,
    nodes: list[str],
    charged: int,
    state: dict[str, Any],
) -> dict[str, Any]:
    notes = state.get("shot_quality") if isinstance(state.get("shot_quality"), list) else []
    update_snapshot(
        project_id,
        status="needs_human_review",
        phase="待人工复核",
        node="shot_director",
        message="有镜头未经视觉评审，成片暂停，需要人工放行",
        paused=True,
        deliverable=None,
        shot_quality=notes,
        error=None,
    )
    publish(
        project_id,
        {
            "node": "shot_director",
            "phase": "待人工复核",
            "message": "有镜头未经视觉评审，成片暂停，需要人工放行",
            "status": "needs_human_review",
            "attempt": 1,
        },
    )
    log_event(
        "human_review_held",
        project_id=project_id,
        node="shot_director",
        attempt=1,
        shots=len(notes),
    )
    return {
        "project_id": project_id,
        "node": node,
        "nodes": nodes,
        "charged": charged,
        "held": True,
        "deliverable": None,
        "canvas": build_canvas(project_id),
    }


def select_candidate(
    project_id: str,
    node: str,
    shot_id: str,
    candidate_id: str,
    *,
    gateway: Any | None = None,
    qa_passed: bool | None = None,
    visual_reviewed: bool | None = None,
) -> dict[str, Any]:
    """Mark one candidate selected. Client QA flags are ignored."""

    _ = (qa_passed, visual_reviewed)
    key = {"n08_keyframe": "keyframes", "n10_video": "videos"}.get(node)
    if key is None:
        raise GateError("这个节点没有候选", status=400)
    snapshot = _snapshot(project_id)
    state = load_checkpoint(project_id)
    raw_rows = state.get(key) or []
    rows = [Candidate.model_validate(item) for item in raw_rows if isinstance(item, dict)]
    target = next(
        (item for item in rows if item.candidate_id == candidate_id and item.shot_id == shot_id),
        None,
    )
    if target is None:
        raise GateError("候选不存在", status=404)
    if content_blocked(target.qa):
        raise GateError("内容安全硬伤不能进入成片")
    frame = str(target.params.get("frame") or "")
    seed = target.params.get("seed")
    updated: list[Candidate] = []
    for item in rows:
        if item.shot_id != shot_id:
            updated.append(item)
            continue
        if content_blocked(item.qa):
            updated.append(item.model_copy(update={"selected": False}))
            continue
        chosen = item.candidate_id == candidate_id
        if (
            node == "n08_keyframe"
            and frame == "first"
            and item.params.get("frame") == "last"
            and item.params.get("seed") == seed
        ):
            chosen = True
        if node == "n08_keyframe" and str(item.params.get("frame") or "") == frame:
            chosen = item.candidate_id == candidate_id
        updated.append(item.model_copy(update={"selected": chosen, "qa": item.qa}))
    _replace_rows(project_id, node, key, updated)
    state[key] = [item.model_dump(mode="json") for item in updated]
    if (
        node == "n10_video"
        and isinstance(state.get("script"), dict)
        and state.get("elements")
        and not _delivery_blocked(snapshot, state, ran_director=False)
    ):
        _refresh_master(project_id, state, gateway=gateway)
    return {
        "project_id": project_id,
        "candidate_id": candidate_id,
        "canvas": build_canvas(project_id),
    }


def save_timeline(
    project_id: str,
    body: dict[str, Any],
    *,
    gateway: Any | None = None,
) -> dict[str, Any]:
    """Apply a timeline edit. Dropping 「AI生成」 or a blocked clip is refused."""

    _ = gateway
    snapshot = _snapshot(project_id)
    state = load_checkpoint(project_id)
    if _delivery_blocked(snapshot, state, ran_director=False):
        raise GateError("有镜头未经视觉评审，成片暂停，需要人工放行", status=409)
    raw = load_timeline_dict(project_id, state)
    if raw is None:
        raise GateError("还没有时间轴", status=404)
    submitted = body.get("overlays")
    if not isinstance(submitted, list):
        raise GateError("不能去掉「AI生成」标识")
    assert_ai_label([item for item in submitted if isinstance(item, dict)])
    current = Timeline.model_validate(raw)
    blocked = _blocked_uris(state)
    known = _known_paths(state, current)
    edits = {
        item.get("clip_id"): item
        for item in body.get("clips") or []
        if isinstance(item, dict) and item.get("clip_id")
    }
    clips = []
    for clip in current.clips:
        edit = edits.get(clip.clip_id) or {}
        path = clip.path
        new_path = edit.get("path")
        if isinstance(new_path, str) and new_path and new_path != clip.path:
            if new_path in blocked:
                raise GateError("内容安全硬伤不能进入成片")
            if new_path not in known:
                raise GateError("不能把未审核的文件放进成片")
            path = new_path
        transition = edit.get("transition_out")
        if not isinstance(transition, str) or not transition.strip():
            transition = clip.transition_out
        clips.append(clip.model_copy(update={"path": path, "transition_out": transition}))
    updated = current.model_copy(update={"clips": clips})
    assert_ai_label([item.model_dump() for item in updated.overlays])
    work = Path(updated.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    for variant in ("master", "nosub", "novo"):
        render_timeline(updated, work / f"{variant}.mp4", variant=variant)
    timeline_path = work / "timeline.json"
    timeline_path.write_text(
        json.dumps(updated.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    master = str((work / "master.mp4").resolve())
    _store(
        project_id,
        "n15_compose",
        {
            **_node_file(project_id, "n15_compose"),
            "deliverable": master,
            "timeline": updated.model_dump(mode="json"),
            "timeline_path": str(timeline_path.resolve()),
            "exports": {
                "master": master,
                "nosub": str((work / "nosub.mp4").resolve()),
                "novo": str((work / "novo.mp4").resolve()),
            },
        },
    )
    update_snapshot(project_id, deliverable=master, status="completed", phase="成片")
    return {"project_id": project_id, "ai_label": True, "canvas": build_canvas(project_id)}


def _refresh_master(project_id: str, state: dict[str, Any], *, gateway: Any | None) -> None:
    snapshot = read_snapshot(project_id) or {}
    patch = invoke_node(
        "n15_compose",
        project_id=project_id,
        state=state,
        snapshot=snapshot,
        gateway=gateway,
        enterprise_id=snapshot.get("enterprise_id")
        if isinstance(snapshot.get("enterprise_id"), str)
        else None,
    )
    _store(project_id, "n15_compose", {**_node_file(project_id, "n15_compose"), **patch})
    if isinstance(patch.get("deliverable"), str):
        update_snapshot(project_id, deliverable=patch["deliverable"], status="completed")


def _require_upstream(node: str, state: dict[str, Any], snapshot: dict[str, Any]) -> None:
    if node == "n01_brief" and not str(snapshot.get("sentence") or "").strip():
        raise GateError("缺少原话", status=409)
    for key in _NEEDS.get(node, ()):
        if key == "keyframes":
            if not state.get("keyframes"):
                raise GateError("缺少上游结果：keyframes", status=409)
            continue
        if not isinstance(state.get(key), dict):
            raise GateError(f"缺少上游结果：{key}", status=409)


def _snapshot(project_id: str) -> dict[str, Any]:
    if not valid_project_id(project_id):
        raise GateError("项目不存在", status=404)
    snapshot = read_snapshot(project_id)
    if snapshot is None:
        raise GateError("项目不存在", status=404)
    return snapshot


def _store(project_id: str, node: str, patch: dict[str, Any]) -> None:
    current = _node_file(project_id, node)
    current.update(patch)
    save_node(project_id, node, current)


def _replace_rows(project_id: str, node: str, key: str, rows: list[Candidate]) -> None:
    _store(project_id, node, {key: [item.model_dump(mode="json") for item in rows]})


def _node_file(project_id: str, node: str) -> dict[str, Any]:
    path = project_path(project_id) / "nodes" / f"{node}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _blocked_uris(state: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for raw in list(state.get("keyframes") or []) + list(state.get("videos") or []):
        if not isinstance(raw, dict):
            continue
        try:
            candidate = Candidate.model_validate(raw)
        except Exception:
            continue
        if content_blocked(candidate.qa):
            found.add(candidate.uri)
    return found


def _known_paths(state: dict[str, Any], timeline: Timeline) -> set[str]:
    found = {clip.path for clip in timeline.clips}
    for raw in list(state.get("videos") or []):
        if not isinstance(raw, dict):
            continue
        try:
            candidate = Candidate.model_validate(raw)
        except Exception:
            continue
        if not content_blocked(candidate.qa):
            found.add(candidate.uri)
    return found
