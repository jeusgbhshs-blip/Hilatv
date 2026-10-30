"""N10 image-to-video. Selected keyframes in, Candidate clips out.

The gateway route picks the model from the shot family. Generation uses 5 or 10
seconds, then the clip is cut to ``duration_s`` with head and tail handles left
for transitions. Product shots stay at low motion. One shot failing does not
cancel the others.
"""

from __future__ import annotations

from typing import Any

from workers.logging import log_event
from workers.media.trim import best_generation_s, margin_s, plan_trim, probe_duration_s, trim_mp4
from workers.nodes.n05_storyboard.presets import ShotPreset, load_presets
from workers.nodes.n08_keyframe.persist import persist_candidates
from workers.nodes.n08_keyframe.prompts import negative_text
from workers.nodes.n10_video.prompts import render_video
from workers.nodes.n10_video.qa import QAError, check
from workers.nodes.n10_video.schema import N10Input, NodeRequest, NodeResult
from workers.nodes.runtime import (
    Deadline,
    apply_selection,
    candidate_uuid,
    choose_id,
    intended_model,
    model_from_logs,
    placeholder_qa,
    read_bytes,
    run_parallel,
    variant_seeds,
    workers_for,
)
from workers.nodes.shot_meta import describe, motion_strength, shot_family
from workers.schemas.asset import Candidate
from workers.schemas.script import GenerationMode, Script, Shot, ShotStatus

NODE = "n10_video"
CANDIDATE_NODE = "N10"


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 180.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    payload = N10Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    targets = _targets(payload.script, request.shot_id)
    gateway = gateway or _default_gateway()
    done: dict[str, list[Candidate]] = {}
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            _fill(
                request,
                payload,
                targets,
                done,
                attempt=attempt,
                timeout_s=timeout_s,
                gateway=gateway,
            )
            result = _result(request, payload, targets, done, attempt)
            check(result)
        except QAError as exc:
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=request.shot_id,
                attempt=attempt,
                error=str(exc),
            )
            continue
        persist_candidates(
            _rows(done, targets),
            enterprise_id=payload.enterprise_id,
            project_id=request.project_id,
            node=NODE,
        )
        return result
    raise QAError(f"n10_video failed after {max_attempts} attempts") from last_error


def _fill(
    request: NodeRequest,
    payload: N10Input,
    targets: list[Shot],
    done: dict[str, list[Candidate]],
    *,
    attempt: int,
    timeout_s: float,
    gateway: Any,
) -> None:
    deadline = Deadline(timeout_s, node=NODE)
    pending = [shot for shot in targets if shot.shot_id not in done]
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        shots=len(pending),
    )

    def work(shot: Shot) -> list[Candidate]:
        return _shot(
            shot,
            request=request,
            payload=payload,
            attempt=attempt,
            gateway=gateway,
            deadline=deadline,
        )

    batch = run_parallel(pending, work, workers=workers_for(len(pending)))
    for shot_id, value, exc in batch:
        if exc is not None:
            from workers.brand_kit.people import ConsentError

            if isinstance(exc, ConsentError):
                raise exc
            log_event(
                "node_shot_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=shot_id,
                attempt=attempt,
                error=str(exc)[:300],
            )
            continue
        done[shot_id] = value
        log_event(
            "node_shot_finished",
            project_id=request.project_id,
            node=NODE,
            shot_id=shot_id,
            attempt=attempt,
            candidates=len(value),
        )


def _shot(
    shot: Shot,
    *,
    request: NodeRequest,
    payload: N10Input,
    attempt: int,
    gateway: Any,
    deadline: Deadline,
) -> list[Candidate]:
    deadline.check()
    if shot.generation_mode is GenerationMode.motion_graphics:
        return []
    from workers.compliance.consent_gate import assert_generation_allowed

    assert_generation_allowed(shot, payload.brand_kit, archived=payload.brand_archived)
    opening = _frame(payload.candidates, shot.shot_id, "first")
    if opening is None:
        raise RuntimeError(f"{shot.shot_id} has no selected opening frame")
    closing = _frame(payload.candidates, shot.shot_id, "last")
    family = shot_family(shot)
    language = payload.script.language
    intended = intended_model(gateway, "video", family, language)
    preset = _preset(shot.camera)
    motion = motion_strength(shot, preset.motion_strength if preset else "low")
    subject, scene, style = describe(
        shot,
        payload.brand_kit,
        payload.brief,
        payload.scene_anchors,
        payload.style_anchor,
    )
    negative = negative_text(preset.negative_fragment if preset else "")
    camera = _camera_line(preset, motion)
    prompt = render_video(
        model=intended,
        camera=camera,
        subject=subject,
        scene=scene,
        style=style,
        motion=motion,
        negative=negative,
        closing=closing is not None,
    )
    generation = best_generation_s(shot.duration_s, margin=margin_s())
    ratio = _ratio(payload)
    seeds = variant_seeds(shot.shot_id, "video", payload.video_candidates)
    built: list[Candidate] = []
    for seed in seeds:
        deadline.check()
        params = {
            "image_url": opening.uri,
            "image_role": "first_frame",
            "motion_strength": motion,
            "ratio": ratio,
        }
        if closing is not None:
            params["last_frame_url"] = closing.uri
        output = gateway.generate_video(
            prompt,
            duration_s=generation,
            seed=seed,
            shot_type=family,
            language=language,
            project_id=request.project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=attempt,
            params=params,
        )
        if not isinstance(output, dict) or not isinstance(output.get("uri"), str):
            raise RuntimeError(f"{shot.shot_id} video result has no uri")
        candidate_id = candidate_uuid(
            request.project_id, shot.shot_id, CANDIDATE_NODE, "video", seed
        )
        uri, window = _trim_clip(
            gateway,
            output,
            shot=shot,
            generation=generation,
            candidate_id=candidate_id,
        )
        model = model_from_logs(
            gateway,
            project_id=request.project_id,
            node=NODE,
            shot_id=shot.shot_id,
            seed=seed,
            task="video",
        ) or str(output.get("model") or "mock-video")
        built.append(
            Candidate(
                candidate_id=candidate_id,
                shot_id=shot.shot_id,
                node=CANDIDATE_NODE,
                model=model,
                params={
                    "seed": seed,
                    "prompt": prompt,
                    "negative_prompt": negative,
                    "duration": generation,
                    "generation_duration_s": generation,
                    "motion_strength": motion,
                    "shot_type": family,
                    "prompt_model": intended,
                    "image_url": opening.uri,
                    "frame": "video",
                    **window,
                },
                uri=uri,
                qa=placeholder_qa(selected=False),
                selected=False,
            )
        )
    chosen = {choose_id(built, preferred_model=intended)}
    return apply_selection(built, chosen)


def _trim_clip(
    gateway: Any,
    output: dict[str, Any],
    *,
    shot: Shot,
    generation: int,
    candidate_id: str,
) -> tuple[str, dict[str, Any]]:
    source_uri = str(output["uri"])
    loaded = read_bytes(gateway, source_uri)
    if loaded is None:
        claimed = float(output.get("duration_s") or generation)
        window = plan_trim(shot.duration_s, claimed, margin=margin_s())
        window["trimmed"] = False
        window["output_duration_s"] = round(shot.duration_s, 3)
        return source_uri, window
    store, data = loaded
    source_s = probe_duration_s(data)
    window = plan_trim(shot.duration_s, source_s, margin=margin_s())
    trimmed = trim_mp4(data, start_s=window["trim_start_s"], duration_s=shot.duration_s)
    measured = probe_duration_s(trimmed)
    uri = store.put(f"n10/video/{shot.shot_id}/{candidate_id}.mp4", trimmed, "video/mp4")
    window["source_duration_s"] = round(source_s, 3)
    window["output_duration_s"] = round(measured, 3)
    window["trimmed"] = True
    return uri, window


def _frame(candidates: list[Candidate], shot_id: str, frame: str) -> Candidate | None:
    rows = [
        item
        for item in candidates
        if item.shot_id == shot_id
        and item.selected
        and item.node == "N8"
        and item.params.get("frame", "first") == frame
    ]
    return rows[0] if rows else None


def _result(
    request: NodeRequest,
    payload: N10Input,
    targets: list[Shot],
    done: dict[str, list[Candidate]],
    attempt: int,
) -> NodeResult:
    rows = _rows(done, targets)
    skipped = [
        shot.shot_id for shot in targets if shot.generation_mode is GenerationMode.motion_graphics
    ]
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        candidates=len(rows),
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload={
            "script": _mark(payload.script, done).model_dump(mode="json"),
            "brief": payload.brief.model_dump(mode="json") if payload.brief else None,
            "brand_kit": (payload.brand_kit.model_dump(mode="json") if payload.brand_kit else None),
            "candidates": [row.model_dump(mode="json") for row in rows],
            "shot_ids": [shot.shot_id for shot in targets],
            "skipped": skipped,
        },
        attempt=attempt,
    )


def _rows(done: dict[str, list[Candidate]], targets: list[Shot]) -> list[Candidate]:
    order = {shot.shot_id: shot.order for shot in targets}
    rows: list[Candidate] = []
    for shot in targets:
        rows.extend(done.get(shot.shot_id, []))
    rows.sort(key=lambda item: (order.get(item.shot_id, 0), int(item.params.get("seed") or 0)))
    return rows


def _mark(script: Script, done: dict[str, list[Candidate]]) -> Script:
    shots: list[Shot] = []
    for shot in script.shots:
        rows = done.get(shot.shot_id)
        if rows and any(item.selected for item in rows):
            shots.append(shot.model_copy(update={"status": ShotStatus.passed}))
        else:
            shots.append(shot)
    return script.model_copy(update={"shots": shots})


def _targets(script: Script, shot_id: str | None) -> list[Shot]:
    if not script.shots:
        raise QAError("storyboard has no shots")
    if shot_id is None:
        return list(script.shots)
    found = [shot for shot in script.shots if shot.shot_id == shot_id]
    if not found:
        raise ValueError(f"unknown shot {shot_id}")
    return found


def _preset(camera: str) -> ShotPreset | None:
    return next((item for item in load_presets() if item.id == camera), None)


def _camera_line(preset: ShotPreset | None, motion: str) -> str:
    camera = (
        preset.prompt_fragment if preset is not None else "The camera follows the storyboard move."
    )
    if motion == "low":
        camera = f"{camera} Keep the move small so the subject does not deform."
    return camera


def _ratio(payload: N10Input) -> str:
    if payload.brief and payload.brief.aspect_ratios:
        return payload.brief.aspect_ratios[0]
    return "16:9"


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
