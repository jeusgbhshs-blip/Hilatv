"""N17 delivery. One 16:9 master becomes aspect, language, and duration versions.

Text, logos, prices, and phones are burned by the render layer after the reframe.
Localization and dubbing go through the gateway. No vendor SDK is imported here.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from gateway.constants import NO_RENDERED_TEXT
from gateway.media_bytes import render_png
from workers.logging import log_event
from workers.media.ffmpeg import RenderError, probe, run_ffmpeg
from workers.media.packaging import safe_insets
from workers.nodes.n17_deliver.cuts import (
    KeptShot,
    duration_targets,
    keep_for_duration,
    picture_length,
)
from workers.nodes.n17_deliver.graph import burn_command, reframe_command, reframe_graph
from workers.nodes.n17_deliver.layout import burn_overlays
from workers.nodes.n17_deliver.localize import PROMPTS, localize
from workers.nodes.n17_deliver.qa import QAError, check
from workers.nodes.n17_deliver.reframe import ShotGeometry, output_size, plan_shot
from workers.nodes.n17_deliver.schema import (
    DeliveryVersion,
    N17Input,
    NodeRequest,
    NodeResult,
    SubjectTrack,
    TrackSource,
)
from workers.nodes.n17_deliver.voice import dub
from workers.nodes.runtime import Deadline
from workers.schemas.asset import Asset, AssetKind
from workers.schemas.base import ASPECT_RATIO_PATTERN, LANGUAGE_PATTERN
from workers.schemas.script import Script, Shot
from workers.workflow.store import project_path

NODE = "n17_deliver"
ASSET_NS = uuid.UUID("6f1c0a1e-7b2d-4e5a-9c31-0c0a6e6e0717")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 180.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N17Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway or _default_gateway()
    deadline = Deadline(timeout_s, node=NODE)
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            deadline.check()
            result = _execute(request, attempt=attempt, gateway=gateway, deadline=deadline)
            check(result)
        except QAError as exc:
            if not exc.retryable:
                raise
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
        except RenderError as exc:
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
        return result
    message = f"n17_deliver failed after {max_attempts} attempts: {last_error}"
    raise QAError(message, retryable=False) from last_error


def _execute(
    request: NodeRequest,
    *,
    attempt: int,
    gateway: Any,
    deadline: Deadline,
) -> NodeResult:
    payload = N17Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    root = project_path(request.project_id, create=True).resolve()
    master = _contained_file(root, payload.master_path)
    info = probe(master)
    src_w, src_h = int(info["width"]), int(info["height"])
    if src_w < 16 or src_h < 16:
        raise QAError("master frame is too small")
    aspects = _aspects(payload.aspect_ratios)
    languages = _languages(payload)
    long_edge = _long_edge(payload, src_w, src_h)
    regenerate = _regenerate(payload)
    picture_s = picture_length(list(payload.script.shots))
    targets = duration_targets(
        requested=payload.durations_s,
        brief_s=float(payload.brief.duration_s),
        picture_s=picture_s,
        platforms=list(payload.brief.platform),
    )
    work = _contained_dir(root, payload.work_dir)
    ready = {item.language: item for item in payload.variants}
    scripts: dict[str, Script] = {}
    prompts: list[str] = []
    for language in languages:
        deadline.check()
        script, prompt = localize(
            payload.script,
            payload.brief,
            payload.brand_kit,
            language,
            gateway=gateway,
            project_id=request.project_id,
            attempt=attempt,
            ready=ready.get(language),
        )
        scripts[language] = script
        if prompt:
            prompts.append(prompt)
    tracks = {item.shot_id: item for item in payload.subject_tracks}
    cuts: dict[float, list[KeptShot]] = {}
    for target in targets:
        kept = keep_for_duration(list(payload.script.shots), target)
        cuts[round(sum(item.duration_s for item in kept), 3)] = kept
    dubbed: dict[tuple[str, float], tuple[Script, list[Any]]] = {}
    for language in languages:
        for duration, kept in cuts.items():
            deadline.check()
            board = _board(scripts[language], kept)
            dubbed[(language, duration)] = (
                board,
                dub(
                    board,
                    payload.brand_kit,
                    work,
                    gateway=gateway,
                    project_id=request.project_id,
                    attempt=attempt,
                ),
            )
    versions: list[DeliveryVersion] = []
    assets: list[Asset] = []
    pictures: dict[tuple[str, float], tuple[Path, list[ShotGeometry], str, list[TrackSource]]] = {}
    for aspect in aspects:
        out_w, out_h = output_size(aspect, long_edge)
        for duration, kept in cuts.items():
            deadline.check()
            geometries, track_sources = _geometries(
                kept,
                tracks,
                src_w=src_w,
                src_h=src_h,
                out_w=out_w,
                out_h=out_h,
                regenerate=regenerate,
                gateway=gateway,
                brief_style=payload.brief.style,
                script=payload.script,
                work=work / "plates",
                project_id=request.project_id,
                attempt=attempt,
            )
            backgrounds = _background_files(geometries, work / "plates")
            slug = _slug(aspect, duration)
            silent = work / "pictures" / f"{slug}.mp4"
            silent.parent.mkdir(parents=True, exist_ok=True)
            graph = reframe_graph(
                geometries,
                {shot_id: index + 1 for index, (shot_id, _path) in enumerate(backgrounds)},
            )
            run_ffmpeg(reframe_command(str(master), geometries, backgrounds, str(silent)))
            pictures[(aspect, duration)] = (silent, geometries, graph, track_sources)
            for geo in geometries:
                log_event(
                    "reframe_shot",
                    project_id=request.project_id,
                    node=NODE,
                    shot_id=geo.shot_id,
                    attempt=attempt,
                    aspect=aspect,
                    mode=geo.mode,
                )
    safe = safe_insets(list(payload.brief.platform))
    safe_dump = {"top": safe.top, "bottom": safe.bottom, "left": safe.left, "right": safe.right}
    for (aspect, duration), (silent, geometries, graph, track_sources) in pictures.items():
        out_w, out_h = geometries[0].out_w, geometries[0].out_h
        for language in languages:
            deadline.check()
            board, takes = dubbed[(language, duration)]
            version_dir = work / "burn" / _slug(aspect, duration) / language
            boxes, placed, spoken = burn_overlays(
                board,
                takes,
                geometries,
                brief=payload.brief,
                brand=payload.brand_kit,
                project_id=f"{request.project_id}-{language}-{_slug(aspect, duration)}",
                work=version_dir,
                width=out_w,
                height=out_h,
            )
            audios = _audios(takes, board)
            dest = work / "versions" / f"{_slug(aspect, duration)}_{language}.mp4"
            dest.parent.mkdir(parents=True, exist_ok=True)
            _args, burn = burn_command(str(silent), audios, placed, str(dest), duration)
            run_ffmpeg(_args)
            version_id = str(
                uuid.uuid5(ASSET_NS, f"{request.project_id}:{aspect}:{language}:{duration:.3f}")
            )
            provided = all(item.provided for item in track_sources)
            versions.append(
                DeliveryVersion(
                    version_id=version_id,
                    aspect_ratio=aspect,
                    language=language,
                    duration_s=duration,
                    width=out_w,
                    height=out_h,
                    path=str(dest),
                    picture_path=str(silent),
                    filters=graph,
                    burn_filters=burn,
                    geometry=[item.record() for item in geometries],
                    overlays=boxes,
                    spoken=spoken,
                    tracks=track_sources,
                    safe=safe_dump,
                    modes={item.shot_id: item.mode for item in geometries},
                    subject_box_source="provided" if provided else "default",
                    qa_status="pass" if provided else "needs_review",
                )
            )
            assets.append(
                Asset(
                    asset_id=version_id,
                    kind=AssetKind.deliverable,
                    uri=dest.resolve().as_uri(),
                    brand_id=payload.brand_kit.brand_id if payload.brand_kit else None,
                    mime_type="video/mp4",
                    license_source="render-layer",
                )
            )
    if prompts and NO_RENDERED_TEXT[:12] not in prompts[0] and "on-screen text" not in prompts[0]:
        raise QAError("localization prompt dropped the no-text constraint")
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        versions=len(versions),
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        attempt=attempt,
        payload={
            "versions": [item.model_dump(mode="json") for item in versions],
            "assets": [item.model_dump(mode="json") for item in assets],
            "prompts": prompts,
            "rights": {
                "picture": "16:9 master reframed in the render layer. Models do not paint text.",
                "voice": "gateway tts",
                "subtitles": "render-layer PNG, Noto Sans CJK SC (OFL 1.1)",
                "fonts": "Noto Sans CJK SC, SIL OFL 1.1",
                "music": "not included in this export",
            },
            "languages": languages,
            "aspect_ratios": aspects,
            "durations_s": targets,
            "verify_pixels": bool(versions)
            and all(item.subject_box_source == "provided" for item in versions),
        },
    )


def _geometries(
    kept: list[KeptShot],
    tracks: dict[str, SubjectTrack],
    *,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    regenerate: bool,
    gateway: Any,
    brief_style: str,
    script: Script,
    work: Path,
    project_id: str,
    attempt: int,
) -> tuple[list[ShotGeometry], list[TrackSource]]:
    visuals = {shot.shot_id: shot.visual for shot in script.shots}
    rows: list[ShotGeometry] = []
    sources: list[TrackSource] = []
    for item in kept:
        supplied = tracks.get(item.shot.shot_id)
        sources.append(_track_source(item.shot.shot_id, supplied))
        if supplied is None:
            # No measured box. Fit the whole master; do not invent a crop window.
            geo = plan_shot(
                shot_id=item.shot.shot_id,
                track=_full_frame(item.shot.shot_id),
                src_w=src_w,
                src_h=src_h,
                out_w=out_w,
                out_h=out_h,
                start_s=item.source_start,
                duration_s=item.duration_s,
                motion_s=item.motion_s,
                regenerate=False,
            )
            geo = replace(geo, mode="blur")
            rows.append(geo)
            continue
        geo = plan_shot(
            shot_id=item.shot.shot_id,
            track=supplied,
            src_w=src_w,
            src_h=src_h,
            out_w=out_w,
            out_h=out_h,
            start_s=item.source_start,
            duration_s=item.duration_s,
            motion_s=item.motion_s,
            regenerate=regenerate,
        )
        if geo.mode == "regenerate":
            path = _vertical_plate(
                geo,
                visual=visuals.get(item.shot.shot_id, ""),
                style=brief_style,
                gateway=gateway,
                work=work,
                project_id=project_id,
                attempt=attempt,
            )
            if path is None:
                geo = replace(geo, mode="blur")
            else:
                geo = replace(geo, mode="regenerate")
        rows.append(geo)
    return rows, sources


def _vertical_plate(
    geo: ShotGeometry,
    *,
    visual: str,
    style: str,
    gateway: Any,
    work: Path,
    project_id: str,
    attempt: int,
) -> Path | None:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(PROMPTS),
        autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    prompt = (
        env.get_template("vertical_plate.j2")
        .render(visual=visual or "A clean industrial background.", style=style or "neutral")
        .strip()
    )
    if "Do not render any on-screen text" not in prompt:
        raise QAError("vertical plate prompt is missing the no-text constraint")
    try:
        gateway.generate_image(
            prompt,
            seed=0,
            shot_type="atmosphere",
            language="zh",
            project_id=project_id,
            node=NODE,
            shot_id=geo.shot_id,
            attempt=attempt,
            params={"width": geo.out_w, "height": geo.out_h},
        )
    except Exception as exc:
        log_event(
            "vertical_plate_failed",
            project_id=project_id,
            node=NODE,
            shot_id=geo.shot_id,
            attempt=attempt,
            error=str(exc)[:300],
        )
        return None
    work.mkdir(parents=True, exist_ok=True)
    path = work / f"{geo.shot_id}-{geo.out_w}x{geo.out_h}.png"
    path.write_bytes(render_png(0, width=max(16, geo.out_w), height=max(16, geo.out_h)))
    return path


def _background_files(geometries: list[ShotGeometry], work: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for geo in geometries:
        if geo.mode != "regenerate":
            continue
        path = work / f"{geo.shot_id}-{geo.out_w}x{geo.out_h}.png"
        if path.is_file():
            found.append((geo.shot_id, str(path)))
    return found


def _board(script: Script, kept: list[KeptShot]) -> Script:
    shots: list[Shot] = []
    by_id = {shot.shot_id: shot for shot in script.shots}
    for item in kept:
        source = by_id[item.shot.shot_id]
        cards = []
        for card in source.on_screen_text:
            start = min(float(card.in_), item.duration_s)
            end = min(max(float(card.out), start), item.duration_s)
            cards.append(card.model_copy(update={"in_": start, "out": end}))
        shots.append(
            source.model_copy(update={"duration_s": item.duration_s, "on_screen_text": cards})
        )
    return script.model_copy(update={"shots": shots})


def _audios(takes: list[Any], script: Script) -> list[tuple[str, float]]:
    by_id = {item.shot_id: item for item in takes}
    rows: list[tuple[str, float]] = []
    offset = 0.0
    for shot in script.shots:
        take = by_id.get(shot.shot_id)
        if take is not None:
            rows.append((_file_uri(take.uri), offset))
        offset += float(shot.duration_s)
    return rows


def _file_uri(uri: str) -> str:
    if uri.startswith("file:"):
        return urlparse(uri).path
    return uri


def _full_frame(shot_id: str) -> SubjectTrack:
    return SubjectTrack(shot_id=shot_id, x=0, y=0, w=1, h=1)


def _track_source(shot_id: str, track: SubjectTrack | None) -> TrackSource:
    if track is None:
        return TrackSource(shot_id=shot_id, provided=False)
    return TrackSource(
        shot_id=shot_id,
        provided=True,
        x=track.x,
        y=track.y,
        w=track.w,
        h=track.h,
        x_end=track.x_end,
        y_end=track.y_end,
    )


def _contained_file(root: Path, raw: str) -> Path:
    path = _contained(root, raw)
    if not path.is_file():
        raise QAError("master must stay inside the project directory")
    return path


def _contained_dir(root: Path, raw: str | None) -> Path:
    if raw:
        path = _contained(root, raw)
    else:
        path = root / "deliveries"
        if not path.resolve().is_relative_to(root):
            raise QAError("work directory must stay inside the project directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _contained(root: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise QAError("master must stay inside the project directory")
    return resolved


def _aspects(values: list[str]) -> list[str]:
    found: list[str] = []
    for item in values:
        if re.fullmatch(ASPECT_RATIO_PATTERN, item) is None:
            raise QAError(f"aspect ratio must look like 16:9, got {item}")
        if item not in found:
            found.append(item)
    if not found:
        raise QAError("at least one aspect ratio is required")
    return found


def _languages(payload: N17Input) -> list[str]:
    if payload.languages:
        raw = list(payload.languages)
    else:
        raw = ["zh", "en"]
        for item in payload.brief.languages:
            if item not in raw:
                raw.append(item)
    for item in raw:
        if re.fullmatch(LANGUAGE_PATTERN, item) is None:
            raise QAError(f"language must be a short BCP 47 tag, got {item}")
    return raw


def _long_edge(payload: N17Input, src_w: int, src_h: int) -> int:
    if payload.long_edge:
        return int(payload.long_edge)
    raw = os.getenv("HILATV_N17_LONG_EDGE", "").strip()
    if raw:
        return max(64, int(raw))
    return max(src_w, src_h)


def _regenerate(payload: N17Input) -> bool:
    if payload.regenerate_vertical is not None:
        return payload.regenerate_vertical
    return os.getenv("HILATV_N17_REGENERATE", "0").strip().lower() in {"1", "true", "yes"}


def _slug(aspect: str, duration: float) -> str:
    return f"{aspect.replace(':', 'x')}_{duration:.1f}"


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
