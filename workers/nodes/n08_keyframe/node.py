"""N8 keyframes. One storyboard in, Candidate rows out.

Each generative shot gets four opening frames by default. Orbit, push, pull,
and rise moves also get a closing frame at the same seed. Motion-graphics shots
are left for the render layer. One shot failing does not cancel the others.
"""

from __future__ import annotations

from typing import Any

from workers.logging import log_event
from workers.nodes.n05_storyboard.presets import ShotPreset, load_presets
from workers.nodes.n08_keyframe.persist import persist_candidates
from workers.nodes.n08_keyframe.prompts import negative_text, render_keyframe
from workers.nodes.n08_keyframe.qa import QAError, check
from workers.nodes.n08_keyframe.schema import N8Input, NodeRequest, NodeResult
from workers.nodes.runtime import (
    Deadline,
    apply_selection,
    candidate_uuid,
    choose_id,
    intended_model,
    model_from_logs,
    placeholder_qa,
    run_parallel,
    variant_seeds,
    with_prompt_suffix,
    workers_for,
)
from workers.nodes.shot_meta import describe, motion_strength, needs_end_frame, shot_family
from workers.schemas.asset import Candidate
from workers.schemas.script import GenerationMode, Script, Shot, ShotStatus

NODE = "n08_keyframe"
CANDIDATE_NODE = "N8"


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 120.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    payload = N8Input.model_validate(request.payload)
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
    raise QAError(f"n08_keyframe failed after {max_attempts} attempts") from last_error


def _fill(
    request: NodeRequest,
    payload: N8Input,
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
    payload: N8Input,
    attempt: int,
    gateway: Any,
    deadline: Deadline,
) -> list[Candidate]:
    deadline.check()
    if shot.generation_mode is GenerationMode.motion_graphics:
        return []
    family = shot_family(shot)
    language = payload.script.language
    intended = intended_model(gateway, "image", family, language)
    preset = _preset(shot.camera)
    subject, scene, style = describe(
        shot,
        payload.brand_kit,
        payload.brief,
        payload.scene_anchors,
        payload.style_anchor,
    )
    negative = negative_text(preset.negative_fragment if preset else "")
    frames = ["first"]
    if needs_end_frame(shot):
        frames.append("last")
    seeds = variant_seeds(shot.shot_id, "keyframe", payload.keyframe_candidates)
    built: list[Candidate] = []
    for frame in frames:
        camera = _camera_line(preset, frame)
        prompt = with_prompt_suffix(
            render_keyframe(
                model=intended,
                camera=camera,
                subject=subject,
                scene=scene,
                style=style,
                negative=negative,
            ),
            payload.prompt_suffix,
        )
        for seed in seeds:
            deadline.check()
            output = gateway.generate_image(
                prompt,
                seed=seed,
                shot_type=family,
                language=language,
                project_id=request.project_id,
                node=NODE,
                shot_id=shot.shot_id,
                attempt=attempt,
                params={"frame": frame},
            )
            uri = output.get("uri") if isinstance(output, dict) else None
            if not isinstance(uri, str) or not uri:
                raise RuntimeError(f"{shot.shot_id} image result has no uri")
            model = model_from_logs(
                gateway,
                project_id=request.project_id,
                node=NODE,
                shot_id=shot.shot_id,
                seed=seed,
                task="image",
            ) or str(output.get("model") or "mock-image")
            built.append(
                Candidate(
                    candidate_id=candidate_uuid(
                        request.project_id, shot.shot_id, CANDIDATE_NODE, frame, seed
                    ),
                    shot_id=shot.shot_id,
                    node=CANDIDATE_NODE,
                    model=model,
                    params={
                        "seed": seed,
                        "prompt": prompt,
                        "negative_prompt": negative,
                        "frame": frame,
                        "prompt_model": intended,
                        "shot_type": family,
                        "motion_strength": motion_strength(
                            shot, preset.motion_strength if preset else "low"
                        ),
                    },
                    uri=uri,
                    qa=placeholder_qa(selected=False),
                    selected=False,
                )
            )
    return _select(built, preferred_model=intended)


def _select(built: list[Candidate], *, preferred_model: str) -> list[Candidate]:
    first = [item for item in built if item.params.get("frame") == "first"]
    if not first:
        return built
    chosen = {choose_id(first, preferred_model=preferred_model)}
    seed = next(item.params.get("seed") for item in first if item.candidate_id in chosen)
    for item in built:
        if item.params.get("frame") == "last" and item.params.get("seed") == seed:
            chosen.add(item.candidate_id)
            break
    return apply_selection(built, chosen)


def _result(
    request: NodeRequest,
    payload: N8Input,
    targets: list[Shot],
    done: dict[str, list[Candidate]],
    attempt: int,
) -> NodeResult:
    rows = _rows(done, targets)
    skipped = [
        shot.shot_id for shot in targets if shot.generation_mode is GenerationMode.motion_graphics
    ]
    script = _mark(payload.script, done)
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
            "script": script.model_dump(mode="json"),
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
    rows.sort(
        key=lambda item: (
            order.get(item.shot_id, 0),
            0 if item.params.get("frame") == "first" else 1,
            int(item.params.get("seed") or 0),
        )
    )
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


def _camera_line(preset: ShotPreset | None, frame: str) -> str:
    camera = (
        preset.prompt_fragment if preset is not None else "The camera follows the storyboard move."
    )
    if frame == "last":
        camera = (
            f"{camera} The move has finished. "
            "Subject, light, and layout still match the opening frame."
        )
    return camera


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
