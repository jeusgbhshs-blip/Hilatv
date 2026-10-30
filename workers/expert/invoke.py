"""Run one existing node from a checkpoint. Model calls stay inside the node."""

from __future__ import annotations

from typing import Any

from workers.expert.gates import (
    GateError,
    assert_ai_label,
    check_voices,
    enforce_fonts,
    enforce_review,
)
from workers.qa.service import review_shot
from workers.schemas.asset import Candidate
from workers.workflow.activities import node_timeout
from workers.workflow.store import project_path

_REVIEW_NODE = {"n08_keyframe": "n09_keyframe", "n10_video": "n11_video"}


def invoke_node(
    name: str,
    *,
    project_id: str,
    state: dict[str, Any],
    snapshot: dict[str, Any],
    shot_id: str | None = None,
    prompt_suffix: str = "",
    gateway: Any | None = None,
    enterprise_id: str | None = None,
) -> dict[str, Any]:
    try:
        patch = _RUNNERS[name](
            project_id=project_id,
            state=state,
            snapshot=snapshot,
            shot_id=shot_id,
            prompt_suffix=prompt_suffix,
            gateway=gateway,
            enterprise_id=enterprise_id,
        )
    except GateError:
        raise
    except Exception as exc:
        raise GateError(f"{name} 失败：{exc}"[:400]) from exc
    if name in _REVIEW_NODE:
        key = "keyframes" if name == "n08_keyframe" else "videos"
        patch[key] = _review(
            patch.get(key) or [],
            project_id=project_id,
            node=_REVIEW_NODE[name],
            gateway=gateway,
        )
    return patch


def _run(node: str, runner: Any, raw: dict[str, Any], gateway: Any | None) -> Any:
    kwargs: dict[str, Any] = {"timeout_s": node_timeout(node), "max_attempts": 1}
    if gateway is not None:
        kwargs["gateway"] = gateway
    return runner(raw, **kwargs)


def _work(project_id: str, name: str) -> str:
    root = project_path(project_id, create=True) / "render" / name
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def _count(snapshot: dict[str, Any], key: str) -> int:
    raw = snapshot.get(key) or 3
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 3
    return min(8, max(3, value))


def _require(state: dict[str, Any], key: str) -> dict[str, Any]:
    value = state.get(key)
    if not isinstance(value, dict):
        raise GateError(f"缺少上游结果：{key}", status=409)
    return value


def _review(
    rows: list[dict[str, Any]],
    *,
    project_id: str,
    node: str,
    gateway: Any | None,
) -> list[dict[str, Any]]:
    reviewed: list[dict[str, Any]] = []
    for raw in rows:
        candidate = Candidate.model_validate(raw)
        report = review_shot(
            {
                "project_id": project_id,
                "shot_id": candidate.shot_id,
                "node": node,
                "candidate_uri": candidate.uri,
                "model": candidate.model,
                "prompt": str(candidate.params.get("prompt") or ""),
                "generation_mode": str(candidate.params.get("generation_mode") or ""),
            },
            gateway=gateway,
        )
        reviewed.append(enforce_review(candidate, report).model_dump(mode="json"))
    return reviewed


def _n01(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n01_brief.node import run

    snapshot = kwargs["snapshot"]
    sentence = str(snapshot.get("sentence") or "")
    if not sentence.strip():
        raise GateError("缺少原话", status=409)
    result = _run(
        "n01_brief",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "raw_input": sentence,
                "attachments": snapshot.get("attachments") or [],
                "brand_kit": kwargs["state"].get("brand_kit"),
            },
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    return {"brief": result.payload["brief"]}


def _n02(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n02_brand_kit.node import run

    snapshot = kwargs["snapshot"]
    result = _run(
        "n02_brand_kit",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "mode": "resolve",
                "inline": kwargs["state"].get("brand_kit") or snapshot.get("brand_kit"),
                "brand_id": snapshot.get("brand_id"),
                "enterprise_id": kwargs["enterprise_id"],
            },
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    return {"brand_kit": result.payload.get("brand_kit")}


def _n03(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n03_concept.node import run

    state = kwargs["state"]
    result = _run(
        "n03_concept",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "brief": _require(state, "brief"),
                "brand_kit": state.get("brand_kit"),
                "selection": kwargs["snapshot"].get("concept_selection"),
            },
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    return {"concept": result.payload["concept"]}


def _n04(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n04_script.node import run

    state = kwargs["state"]
    result = _run(
        "n04_script",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {"brief": _require(state, "brief"), "brand_kit": state.get("brand_kit")},
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    return {
        "script": result.payload["script"],
        "brief": result.payload.get("brief") or state.get("brief"),
        "brand_kit": result.payload.get("brand_kit", state.get("brand_kit")),
    }


def _n05(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n05_storyboard.node import run

    state = kwargs["state"]
    result = _run(
        "n05_storyboard",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "brief": _require(state, "brief"),
                "script": _require(state, "script"),
                "brand_kit": state.get("brand_kit"),
            },
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    script = result.payload["script"]
    shots = [
        {"shot_id": shot["shot_id"], "order": shot["order"], "purpose": shot.get("purpose") or ""}
        for shot in script.get("shots") or []
    ]
    return {
        "script": script,
        "brief": result.payload.get("brief") or state.get("brief"),
        "brand_kit": result.payload.get("brand_kit", state.get("brand_kit")),
        "shot_summaries": shots,
    }


def _n06(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n06_voiceover.node import run

    state = kwargs["state"]
    result = _run(
        "n06_voiceover",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "script": _require(state, "script"),
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
            },
            "shot_id": kwargs["shot_id"],
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    voiceovers = result.payload["voiceovers"]
    check_voices(
        voiceovers,
        enterprise_id=kwargs["enterprise_id"],
        brand=result.payload.get("brand_kit") or state.get("brand_kit"),
    )
    return {
        "script": result.payload["script"],
        "voiceovers": voiceovers,
        "brief": result.payload.get("brief") or state.get("brief"),
        "brand_kit": result.payload.get("brand_kit", state.get("brand_kit")),
    }


def _n08(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n08_keyframe.node import run

    state = kwargs["state"]
    result = _run(
        "n08_keyframe",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "script": _require(state, "script"),
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "keyframe_candidates": _count(kwargs["snapshot"], "keyframe_candidates"),
                "prompt_suffix": kwargs["prompt_suffix"],
                "enterprise_id": kwargs["enterprise_id"],
            },
            "shot_id": kwargs["shot_id"],
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    rows = _merge(state.get("keyframes"), result.payload["candidates"], kwargs["shot_id"])
    return {"keyframes": rows}


def _n09(**kwargs: Any) -> dict[str, Any]:
    from workers.workflow.storyboard import StoryboardError, prepare_gate

    gateway = kwargs["gateway"]
    if gateway is None:
        from gateway import get_gateway

        gateway = get_gateway()
    try:
        return prepare_gate(
            kwargs["project_id"],
            kwargs["state"],
            skip=True,
            gateway=gateway,
        )
    except StoryboardError as exc:
        raise GateError(str(exc), status=getattr(exc, "status", 422)) from exc


def _n10(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n10_video.node import run

    state = kwargs["state"]
    if not state.get("keyframes"):
        raise GateError("缺少上游结果：keyframes", status=409)
    result = _run(
        "n10_video",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "script": _require(state, "script"),
                "candidates": state.get("keyframes") or [],
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "video_candidates": _count(kwargs["snapshot"], "video_candidates"),
                "prompt_suffix": kwargs["prompt_suffix"],
                "enterprise_id": kwargs["enterprise_id"],
            },
            "shot_id": kwargs["shot_id"],
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    rows = _merge(state.get("videos"), result.payload["candidates"], kwargs["shot_id"])
    return {"videos": rows}


def _n12(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n12_music.node import run

    state = kwargs["state"]
    brief = state.get("brief") if isinstance(state.get("brief"), dict) else {}
    result = _run(
        "n12_music",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "script": _require(state, "script"),
                "voiceovers": state.get("voiceovers") or [],
                "brief": state.get("brief"),
                "mood": str(brief.get("style") or ""),
                "work_dir": _work(kwargs["project_id"], "n12"),
            },
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    return {
        "audio_track": result.payload["audio_track"],
        "licensing_summary": result.payload.get("licensing_summary") or {},
    }


def _n13(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n13_subtitle.node import run

    state = kwargs["state"]
    result = _run(
        "n13_subtitle",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "script": _require(state, "script"),
                "voiceovers": state.get("voiceovers") or [],
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "work_dir": _work(kwargs["project_id"], "n13"),
            },
            "shot_id": kwargs["shot_id"],
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    return {"cues": result.payload["cues"]}


def _n14(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n14_packaging.node import run

    state = kwargs["state"]
    result = _run(
        "n14_packaging",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "script": _require(state, "script"),
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "work_dir": _work(kwargs["project_id"], "n14"),
            },
            "shot_id": kwargs["shot_id"],
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    enforce_fonts()
    elements = result.payload["elements"]
    assert_ai_label(elements)
    return {
        "elements": elements,
        "intro_s": result.payload.get("intro_s") or 0,
        "outro_s": result.payload.get("outro_s") or 0,
    }


def _shot_director(**kwargs: Any) -> dict[str, Any]:
    from workers.fallback.direct import direct_shots
    from workers.media.packaging import canvas_size
    from workers.schemas.brand import BrandKit
    from workers.schemas.brief import Brief
    from workers.schemas.script import Script

    state = kwargs["state"]
    script = Script.model_validate(_require(state, "script"))
    brief_raw = state.get("brief")
    brief = Brief.model_validate(brief_raw) if isinstance(brief_raw, dict) else None
    kit_raw = state.get("brand_kit")
    kit = BrandKit.model_validate(kit_raw) if isinstance(kit_raw, dict) else None
    aspect = brief.aspect_ratios[0] if brief and brief.aspect_ratios else None
    width, height = canvas_size(aspect)
    videos = [
        Candidate.model_validate(item)
        for item in state.get("videos") or []
        if isinstance(item, dict)
    ]
    keyframes = [
        Candidate.model_validate(item)
        for item in state.get("keyframes") or []
        if isinstance(item, dict)
    ]
    gateway = kwargs["gateway"]
    if gateway is None:
        from gateway import get_gateway

        gateway = get_gateway()
    result = direct_shots(
        project_id=kwargs["project_id"],
        script=script,
        videos=videos,
        keyframes=keyframes,
        brand_kit=kit,
        width=width,
        height=height,
        gateway=gateway,
    )
    return {
        "shot_clips": [item.model_dump(mode="json") for item in result.clips],
        "shot_quality": [item.model_dump(mode="json") for item in result.notes],
    }


def _n15(**kwargs: Any) -> dict[str, Any]:
    from workers.nodes.n15_compose.node import run
    from workers.workflow.film import needs_human_review

    state = kwargs["state"]
    if needs_human_review(state, {}):
        raise GateError("有镜头未经视觉评审，成片暂停，需要人工放行", status=409)
    result = _run(
        "n15_compose",
        run,
        {
            "project_id": kwargs["project_id"],
            "payload": {
                "script": _require(state, "script"),
                "voiceovers": state.get("voiceovers") or [],
                "cues": state.get("cues") or [],
                "elements": state.get("elements") or [],
                "videos": state.get("videos") or [],
                "shot_clips": state.get("shot_clips") or [],
                "audio_track": state.get("audio_track"),
                "licenses": (
                    state["licensing_summary"].get("records") or []
                    if isinstance(state.get("licensing_summary"), dict)
                    else []
                ),
                "brief": state.get("brief"),
                "brand_kit": state.get("brand_kit"),
                "intro_s": float(state.get("intro_s") or 0),
                "outro_s": float(state.get("outro_s") or 0),
                "work_dir": _work(kwargs["project_id"], "n15"),
            },
            "attempt": 1,
        },
        kwargs["gateway"],
    )
    enforce_fonts()
    timeline = result.payload["timeline"]
    assert_ai_label(timeline.get("overlays") or [])
    exports = result.payload["exports"]
    return {
        "deliverable": exports["master"],
        "exports": exports,
        "timeline": timeline,
        "timeline_path": result.payload.get("timeline_path"),
    }


def _merge(
    previous: Any, updated: list[dict[str, Any]], shot_id: str | None
) -> list[dict[str, Any]]:
    if not shot_id or not isinstance(previous, list):
        return updated
    kept = [item for item in previous if isinstance(item, dict) and item.get("shot_id") != shot_id]
    return kept + updated


_RUNNERS = {
    "n01_brief": _n01,
    "n02_brand_kit": _n02,
    "n03_concept": _n03,
    "n04_script": _n04,
    "n05_storyboard": _n05,
    "n06_voiceover": _n06,
    "n08_keyframe": _n08,
    "n09_keyframe_qa": _n09,
    "n10_video": _n10,
    "shot_director": _shot_director,
    "n12_music": _n12,
    "n13_subtitle": _n13,
    "n14_packaging": _n14,
    "n15_compose": _n15,
}
