"""Activities. Each one validates input, calls one node, and can be rerun alone.

Node-internal retries stay at 1. Temporal retries the activity (timeout, crash,
or a failed quality check) up to three times.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from workers.logging import log_event
from workers.workflow.bookkeeping import mark_failed
from workers.workflow.contract import NODE_MESSAGE, PHASE, SHOT_ACTION, TIMEOUT_S
from workers.workflow.messages import shot_message
from workers.workflow.store import publish, read_snapshot, save_node, update_snapshot


def node_timeout(node: str) -> float:
    return max(5.0, float(TIMEOUT_S[node]) - 5)


def _request(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("request") or {}
    if not isinstance(raw, dict):
        raise ApplicationError("activity request must be an object", non_retryable=True)
    return raw


def _state(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("state") or {}
    if not isinstance(raw, dict):
        raise ApplicationError("activity state must be an object", non_retryable=True)
    return raw


def _project(payload: dict[str, Any]) -> str:
    return str(payload["project_id"])


def _attempt() -> int:
    return min(int(activity.info().attempt), 5)


def _guard(payload: dict[str, Any], node: str) -> None:
    fail = _request(payload).get("fail_nodes") or []
    if node in fail:
        raise ApplicationError(f"injected failure at {node}", non_retryable=True)


def _emit(
    project_id: str,
    node: str,
    *,
    message: str,
    attempt: int,
    shot_id: str | None = None,
    shot_index: int | None = None,
    status: str = "running",
    phase: str | None = None,
    **extra: Any,
) -> None:
    event: dict[str, Any] = {
        "node": node,
        "phase": phase or PHASE[node],
        "message": message,
        "status": status,
        "attempt": attempt,
        "shot_id": shot_id,
        "shot_index": shot_index,
    }
    event.update(extra)
    publish(project_id, event)


def _announce(payload: dict[str, Any], node: str) -> int:
    _guard(payload, node)
    project_id = _project(payload)
    attempt = _attempt()
    action = SHOT_ACTION.get(node)
    shots: list[dict[str, Any]] = []
    if action:
        script = _state(payload).get("script") or {}
        if isinstance(script, dict):
            shots = [item for item in script.get("shots") or [] if isinstance(item, dict)]
    if shots and action:
        for shot in shots:
            order = int(shot.get("order") or 0)
            _emit(
                project_id,
                node,
                message=shot_message(order, action),
                attempt=attempt,
                shot_id=str(shot.get("shot_id") or "") or None,
                shot_index=order,
            )
    else:
        _emit(project_id, node, message=NODE_MESSAGE[node], attempt=attempt)
    log_event("activity_started", project_id=project_id, node=node, attempt=attempt)
    return attempt


def _finish(project_id: str, node: str, patch: dict[str, Any], attempt: int) -> dict[str, Any]:
    save_node(project_id, node, patch)
    log_event("activity_finished", project_id=project_id, node=node, attempt=attempt)
    return {"patch": patch}


def _require_dict(state: dict[str, Any], key: str) -> dict[str, Any]:
    value = state.get(key)
    if not isinstance(value, dict):
        raise ApplicationError(f"missing {key}", non_retryable=True)
    return value


def _work(payload: dict[str, Any], name: str) -> str:
    root = Path(str(_request(payload)["work_dir"])) / name
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def _soundtrack(state: dict[str, Any]) -> dict[str, Any]:
    """N12's mix, placed by N15 at the start of the shots. Absent until N12 has run."""

    extra: dict[str, Any] = {}
    track = state.get("audio_track")
    if isinstance(track, dict):
        extra["audio_track"] = track
    summary = state.get("licensing_summary")
    records = summary.get("records") if isinstance(summary, dict) else None
    if isinstance(records, list):
        extra["licenses"] = records
    return extra


def music_state_patch(payload: dict[str, Any]) -> dict[str, Any]:
    """What N12 writes onto the project. The storyboard script stays on N6 durations."""

    summary = payload.get("licensing_summary") or {}
    return {
        "audio_track": payload["audio_track"],
        "licensing_summary": summary,
        "aligned_script": payload["aligned_script"],
    }


def timeline_fields(state: dict[str, Any]) -> dict[str, Any]:
    """Soundtrack plus the beat-aligned storyboard, once N12 has stored one."""

    fields = _soundtrack(state)
    aligned = state.get("aligned_script")
    shots = aligned.get("shots") if isinstance(aligned, dict) else None
    if isinstance(shots, list) and shots:
        fields["aligned_script"] = aligned
    return fields


def _count(payload: dict[str, Any], key: str) -> int:
    raw = _request(payload).get(key) or 3
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 3
    return min(8, max(3, value))


def _call(run: Any, raw: dict[str, Any], node: str) -> Any:
    try:
        return run(raw, timeout_s=node_timeout(node), max_attempts=1)
    except Exception as exc:
        if getattr(exc, "retryable", True) is False:
            raise ApplicationError(str(exc)[:500], non_retryable=True) from exc
        raise


@activity.defn(name="n01_brief")
def n01_brief(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n01_brief")
    project_id = _project(payload)
    request = _request(payload)
    from workers.nodes.n01_brief.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "raw_input": request["sentence"],
                "attachments": request.get("attachments") or [],
                "brand_kit": request.get("brand_kit"),
            },
            "attempt": attempt,
        },
        "n01_brief",
    )
    return _finish(project_id, "n01_brief", {"brief": result.payload["brief"]}, attempt)


@activity.defn(name="n02_brand_kit")
def n02_brand_kit(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n02_brand_kit")
    project_id = _project(payload)
    request = _request(payload)
    from workers.nodes.n02_brand_kit.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "mode": "resolve",
                "inline": request.get("brand_kit"),
                "brand_id": request.get("brand_id"),
                "enterprise_id": request.get("enterprise_id"),
            },
            "attempt": attempt,
        },
        "n02_brand_kit",
    )
    kit = result.payload.get("brand_kit")
    message = "已读取品牌资料" if kit else "未找到品牌资料，按行业默认继续"
    _emit(project_id, "n02_brand_kit", message=message, attempt=attempt)
    return _finish(project_id, "n02_brand_kit", {"brand_kit": kit}, attempt)


@activity.defn(name="n03_concept")
def n03_concept(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n03_concept")
    project_id = _project(payload)
    request = _request(payload)
    state = _state(payload)
    from workers.nodes.n03_concept.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "brief": _require_dict(state, "brief"),
                "brand_kit": state.get("brand_kit"),
                "selection": request.get("concept_selection"),
            },
            "attempt": attempt,
        },
        "n03_concept",
    )
    concept = result.payload["concept"]
    if concept.get("auto"):
        message = f"已自动选定：{concept['selection']}"
    else:
        message = f"已选定方案：{concept.get('title') or concept['selection']}"
    _emit(project_id, "n03_concept", message=message, attempt=attempt)
    return _finish(project_id, "n03_concept", {"concept": concept}, attempt)


@activity.defn(name="n04_script")
def n04_script(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n04_script")
    project_id = _project(payload)
    state = _state(payload)
    from workers.nodes.n04_script.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "brief": _require_dict(state, "brief"),
                "brand_kit": state.get("brand_kit"),
            },
            "attempt": attempt,
        },
        "n04_script",
    )
    patch = {
        "script": result.payload["script"],
        "brief": result.payload.get("brief") or state.get("brief"),
        "brand_kit": result.payload.get("brand_kit", state.get("brand_kit")),
    }
    return _finish(project_id, "n04_script", patch, attempt)


@activity.defn(name="n05_storyboard")
def n05_storyboard(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n05_storyboard")
    project_id = _project(payload)
    state = _state(payload)
    from workers.nodes.n05_storyboard.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "brief": _require_dict(state, "brief"),
                "script": _require_dict(state, "script"),
                "brand_kit": state.get("brand_kit"),
            },
            "attempt": attempt,
        },
        "n05_storyboard",
    )
    script = result.payload["script"]
    shots = [
        {
            "shot_id": shot["shot_id"],
            "order": shot["order"],
            "purpose": shot.get("purpose") or "",
        }
        for shot in script.get("shots") or []
    ]
    update_snapshot(project_id, shots=shots)
    patch = {
        "script": script,
        "brief": result.payload.get("brief") or state.get("brief"),
        "brand_kit": result.payload.get("brand_kit", state.get("brand_kit")),
        "shot_summaries": shots,
    }
    return _finish(project_id, "n05_storyboard", patch, attempt)


@activity.defn(name="n06_voiceover")
def n06_voiceover(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n06_voiceover")
    project_id = _project(payload)
    state = _state(payload)
    from workers.expert.shot_draft import apply_saved_narration
    from workers.nodes.n06_voiceover.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "script": apply_saved_narration(project_id, _require_dict(state, "script")),
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "enterprise_id": _request(payload).get("enterprise_id"),
            },
            "attempt": attempt,
        },
        "n06_voiceover",
    )
    patch = {
        "script": result.payload["script"],
        "voiceovers": result.payload["voiceovers"],
        "brief": result.payload.get("brief") or state.get("brief"),
        "brand_kit": result.payload.get("brand_kit", state.get("brand_kit")),
    }
    return _finish(project_id, "n06_voiceover", patch, attempt)


@activity.defn(name="n08_keyframe")
def n08_keyframe(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n08_keyframe")
    project_id = _project(payload)
    state = _state(payload)
    from workers.expert.uploads import materialize_attachments
    from workers.nodes.n08_keyframe.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "script": _require_dict(state, "script"),
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "enterprise_id": _request(payload).get("enterprise_id"),
                "keyframe_candidates": _count(payload, "keyframe_candidates"),
                "reference_images": materialize_attachments(
                    _request(payload).get("attachments") or [],
                    enterprise_id=str(_request(payload).get("enterprise_id") or ""),
                    project_id=project_id,
                ),
            },
            "attempt": attempt,
        },
        "n08_keyframe",
    )
    return _finish(
        project_id,
        "n08_keyframe",
        {"keyframes": result.payload["candidates"]},
        attempt,
    )


@activity.defn(name="n09_keyframe_qa")
def n09_keyframe_qa(payload: dict[str, Any]) -> dict[str, Any]:
    """Record whether each selected frame was really reviewed, then the workflow may wait."""

    attempt = _announce(payload, "n09_keyframe_qa")
    project_id = _project(payload)
    state = _state(payload)
    from gateway import get_gateway
    from workers.workflow.storyboard import StoryboardError, prepare_gate

    try:
        patch = prepare_gate(
            project_id,
            state,
            skip=bool(_request(payload).get("skip_storyboard")),
            gateway=get_gateway(),
        )
    except StoryboardError as exc:
        raise ApplicationError(str(exc), non_retryable=True) from exc
    return _finish(project_id, "n09_keyframe_qa", patch, attempt)


@activity.defn(name="storyboard_sync")
def storyboard_sync(payload: dict[str, Any]) -> dict[str, Any]:
    """Reload narration edits made while the storyboard cards were open."""

    from workers.workflow.storyboard import sync_patch

    return {"patch": sync_patch(_project(payload))}


@activity.defn(name="storyboard_expire")
def storyboard_expire(payload: dict[str, Any]) -> dict[str, Any]:
    """The card wait timed out. Leave the film unproduced and cancellable."""

    from workers.workflow.storyboard import mark_expired

    mark_expired(_project(payload))
    return {"patch": {}}


@activity.defn(name="n10_video")
def n10_video(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n10_video")
    project_id = _project(payload)
    state = _state(payload)
    from workers.nodes.n10_video.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "script": _require_dict(state, "script"),
                "candidates": state.get("keyframes") or [],
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "enterprise_id": _request(payload).get("enterprise_id"),
                "video_candidates": _count(payload, "video_candidates"),
            },
            "attempt": attempt,
        },
        "n10_video",
    )
    return _finish(
        project_id,
        "n10_video",
        {
            "videos": result.payload["candidates"],
            "generation_failed": result.payload.get("generation_failed") or [],
        },
        attempt,
    )


@activity.defn(name="shot_director")
def shot_director(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "shot_director")
    project_id = _project(payload)
    state = _state(payload)
    from workers.fallback.direct import direct_shots
    from workers.media.packaging import canvas_size
    from workers.schemas.asset import Candidate
    from workers.schemas.brand import BrandKit
    from workers.schemas.brief import Brief
    from workers.schemas.script import Script

    script = Script.model_validate(_require_dict(state, "script"))
    brief_raw = state.get("brief")
    brief = Brief.model_validate(brief_raw) if isinstance(brief_raw, dict) else None
    kit_raw = state.get("brand_kit")
    kit = BrandKit.model_validate(kit_raw) if isinstance(kit_raw, dict) else None
    aspect = brief.aspect_ratios[0] if brief and brief.aspect_ratios else None
    width, height = canvas_size(aspect)
    videos = [Candidate.model_validate(item) for item in state.get("videos") or []]
    keyframes = [Candidate.model_validate(item) for item in state.get("keyframes") or []]
    from gateway import get_gateway

    result = direct_shots(
        project_id=project_id,
        script=script,
        videos=videos,
        keyframes=keyframes,
        brand_kit=kit,
        width=width,
        height=height,
        gateway=get_gateway(),
    )
    return _finish(
        project_id,
        "shot_director",
        {
            "shot_clips": [item.model_dump(mode="json") for item in result.clips],
            "shot_quality": [item.model_dump(mode="json") for item in result.notes],
        },
        attempt,
    )


@activity.defn(name="n12_music")
def n12_music(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n12_music")
    project_id = _project(payload)
    state = _state(payload)
    from workers.nodes.n12_music.node import run

    brief = state.get("brief") if isinstance(state.get("brief"), dict) else {}
    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "script": _require_dict(state, "script"),
                "voiceovers": state.get("voiceovers") or [],
                "brief": state.get("brief"),
                "mood": str(brief.get("style") or ""),
                "work_dir": _work(payload, "n12"),
            },
            "attempt": attempt,
        },
        "n12_music",
    )
    return _finish(project_id, "n12_music", music_state_patch(result.payload), attempt)


@activity.defn(name="n13_subtitle")
def n13_subtitle(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n13_subtitle")
    project_id = _project(payload)
    state = _state(payload)
    from workers.nodes.n13_subtitle.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "script": _require_dict(state, "script"),
                "voiceovers": state.get("voiceovers") or [],
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "work_dir": _work(payload, "n13"),
            },
            "attempt": attempt,
        },
        "n13_subtitle",
    )
    return _finish(project_id, "n13_subtitle", {"cues": result.payload["cues"]}, attempt)


@activity.defn(name="n14_packaging")
def n14_packaging(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n14_packaging")
    project_id = _project(payload)
    state = _state(payload)
    from workers.nodes.n14_packaging.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "script": _require_dict(state, "script"),
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "work_dir": _work(payload, "n14"),
            },
            "attempt": attempt,
        },
        "n14_packaging",
    )
    patch = {
        "elements": result.payload["elements"],
        "intro_s": result.payload.get("intro_s") or 0,
        "outro_s": result.payload.get("outro_s") or 0,
    }
    return _finish(project_id, "n14_packaging", patch, attempt)


@activity.defn(name="hold_for_review")
def hold_for_review(payload: dict[str, Any]) -> dict[str, Any]:
    """Stop before compose. No master file and no delivery record."""

    project_id = _project(payload)
    notes = _state(payload).get("shot_quality") or []
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
    update_snapshot(
        project_id,
        status="needs_human_review",
        phase="待人工复核",
        node="shot_director",
        message="有镜头未经视觉评审，成片暂停，需要人工放行",
        paused=True,
        deliverable=None,
        shot_quality=notes,
    )
    log_event(
        "human_review_held",
        project_id=project_id,
        node="shot_director",
        attempt=1,
        shots=len(notes) if isinstance(notes, list) else 0,
    )
    return {"patch": {"held_for_review": True}}


@activity.defn(name="n15_compose")
def n15_compose(payload: dict[str, Any]) -> dict[str, Any]:
    attempt = _announce(payload, "n15_compose")
    project_id = _project(payload)
    state = _state(payload)
    from workers.workflow.film import needs_human_review

    if needs_human_review(state, _request(payload)):
        raise ApplicationError(
            "needs_human_review blocks delivery until a person releases the project",
            non_retryable=True,
        )
    from workers.nodes.n15_compose.node import run

    result = _call(
        run,
        {
            "project_id": project_id,
            "payload": {
                "script": _require_dict(state, "script"),
                "voiceovers": state.get("voiceovers") or [],
                "cues": state.get("cues") or [],
                "elements": state.get("elements") or [],
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "intro_s": float(state.get("intro_s") or 0),
                "outro_s": float(state.get("outro_s") or 0),
                "work_dir": _work(payload, "n15"),
                "shot_clips": state.get("shot_clips") or [],
                **timeline_fields(state),
            },
            "attempt": attempt,
        },
        "n15_compose",
    )
    exports = result.payload["exports"]
    deliverable = exports["master"]
    snapshot = read_snapshot(project_id) or {}
    started = float(snapshot.get("started_at") or time.time())
    elapsed = round(time.time() - started, 3)
    _emit(
        project_id,
        "n15_compose",
        message="成片已就绪",
        attempt=attempt,
        status="completed",
        phase="成片",
        deliverable=deliverable,
        elapsed_s=elapsed,
    )
    patch = {
        "deliverable": deliverable,
        "exports": exports,
        "timeline_path": result.payload.get("timeline_path"),
        "elapsed_s": elapsed,
    }
    return _finish(project_id, "n15_compose", patch, attempt)


ACTIVITIES = [
    n01_brief,
    n02_brand_kit,
    n03_concept,
    n04_script,
    n05_storyboard,
    n06_voiceover,
    n08_keyframe,
    n09_keyframe_qa,
    storyboard_sync,
    storyboard_expire,
    n10_video,
    shot_director,
    n12_music,
    n13_subtitle,
    n14_packaging,
    n15_compose,
    hold_for_review,
    mark_failed,
]
