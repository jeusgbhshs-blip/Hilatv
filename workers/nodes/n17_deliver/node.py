"""N17 delivery. A clean master becomes aspect, language, and duration versions.

Text, logos, prices, and phones are burned by the render layer after the reframe.
Localization and dubbing go through the gateway. No vendor SDK is imported here.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image

from gateway.constants import NO_RENDERED_TEXT
from gateway.media_bytes import render_png
from workers.logging import log_event
from workers.media.audio import combine_provenance
from workers.media.ffmpeg import RenderError, probe, run_ffmpeg
from workers.media.packaging import safe_insets
from workers.media.timing import DurationBudget, duration_budget
from workers.nodes.n15_compose.schema import Timeline
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
    OverlayBox,
    SubjectTrack,
    TrackSource,
)
from workers.nodes.n17_deliver.source import file_hash, pin_source, source_key
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
    from workers.compliance.gate import open_delivery

    root = project_path(request.project_id, create=True).resolve()
    master, source_timeline = _clean_picture(root, payload)
    exact = (
        duration_budget(payload.target_duration_s, intro_s=payload.intro_s, outro_s=payload.outro_s)
        if payload.target_duration_s is not None
        else None
    )
    if exact and source_timeline is None:
        raise QAError("an explicit duration export requires its clean source timeline")
    open_delivery(
        request.project_id,
        payload,
        request.payload,
        gateway=gateway,
        attempt=attempt,
    )
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
    if exact:
        if abs(picture_s - exact.body_s) > 1 / 30 + 0.001:
            raise QAError("source story does not match the explicit export duration")
        if payload.durations_s and any(
            abs(value - exact.total_s) > 1 / 30 for value in payload.durations_s
        ):
            raise QAError("a different duration needs a separately planned story, not a hard trim")
        targets = [exact.body_s]
    base_work = _contained_dir(root, payload.work_dir)
    source_media_hash = file_hash(master)
    soundtrack = _soundtrack(root, payload.audio_track)
    identity = source_key(
        payload,
        source_media_hash,
        source_timeline,
        {
            "aspects": sorted(aspects),
            "languages": sorted(languages),
            "durations_s": sorted(targets),
            "long_edge": long_edge,
            "regenerate_vertical": regenerate,
            "audio_track_hash": file_hash(Path(soundtrack[0])) if soundtrack else None,
        },
    )
    work = _contained_dir(root, str(base_work / "sources" / identity))
    master = pin_source(master, work, source_media_hash)
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
                    enterprise_id=payload.enterprise_id,
                    strict_duration=exact is not None,
                ),
            )
    versions: list[DeliveryVersion] = []
    assets: list[Asset] = []
    pictures: dict[tuple[str, float], tuple[Path, list[ShotGeometry], str, list[TrackSource]]] = {}
    for aspect in aspects:
        out_w, out_h = output_size(aspect, long_edge)
        for duration, kept in cuts.items():
            deadline.check()
            placed_kept = _source_spans(kept, source_timeline)
            geometries, track_sources = _geometries(
                placed_kept,
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
            if exact:
                geometries = _with_packaging_geometry(
                    geometries, source_timeline, exact, src_w, src_h, out_w, out_h
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
            body_geometries = [
                item
                for item in geometries
                if item.shot_id in {shot.shot_id for shot in board.shots}
            ]
            boxes, placed, spoken = burn_overlays(
                board,
                takes,
                body_geometries,
                brief=payload.brief.model_copy(update={"aspect_ratios": [aspect]}),
                brand=payload.brand_kit,
                project_id=f"{request.project_id}-{language}-{_slug(aspect, duration)}",
                work=version_dir,
                width=out_w,
                height=out_h,
            )
            audios = _audios(takes, board)
            total_duration = exact.total_s if exact else duration
            if exact:
                boxes, placed = _package_export(
                    payload,
                    board,
                    boxes,
                    placed,
                    work=version_dir,
                    project_id=request.project_id,
                    width=out_w,
                    height=out_h,
                    aspect=aspect,
                    budget=exact,
                    gateway=gateway,
                )
                audios = [(path, delay + exact.intro_s) for path, delay in audios]
            if soundtrack is not None:
                audios = [soundtrack, *audios]
            dest = work / "versions" / f"{_slug(aspect, total_duration)}_{language}.mp4"
            dest.parent.mkdir(parents=True, exist_ok=True)
            _args, burn = burn_command(str(silent), audios, placed, str(dest), total_duration)
            run_ffmpeg(_args)
            version_id = str(
                uuid.uuid5(
                    ASSET_NS,
                    f"{request.project_id}:{identity}:{aspect}:{language}:{total_duration:.3f}",
                )
            )
            provided = all(item.provided for item in track_sources)
            versions.append(
                DeliveryVersion(
                    version_id=version_id,
                    aspect_ratio=aspect,
                    language=language,
                    duration_s=total_duration,
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
                    subject_box_source="provided" if provided and not exact else "default",
                    qa_status="pass" if provided and not exact else "needs_review",
                    target_duration_s=payload.target_duration_s,
                    source_key=identity,
                    source_media_hash=source_media_hash,
                    media_provenance=combine_provenance(
                        [
                            source_timeline.audio_provenance if source_timeline else "unknown",
                            "mock"
                            if source_timeline
                            and any(clip.placeholder for clip in source_timeline.clips)
                            else "unknown",
                            *[take.provenance for take in takes],
                        ]
                    ),
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
    from workers.compliance.gate import close_delivery

    compliance = close_delivery(
        request.project_id,
        payload,
        versions,
        gateway=gateway,
        attempt=attempt,
        root=root,
    )
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
                "picture": (
                    "Clean picture source reframed in the render layer. Models do not paint text."
                ),
                "voice": "gateway tts",
                "subtitles": "render-layer PNG, Noto Sans CJK SC (OFL 1.1)",
                "fonts": "Noto Sans CJK SC, SIL OFL 1.1",
                "music": "not included in this export",
                "materials_note": compliance["materials_note"],
                "explicit_label": compliance["explicit_label"],
                "implicit_label": compliance["implicit_label"],
                "manual_review": compliance["manual_review"],
            },
            "compliance": compliance,
            "languages": languages,
            "source_key": identity,
            "source_media_hash": source_media_hash,
            "aspect_ratios": aspects,
            "durations_s": [exact.total_s] if exact else targets,
            "verify_pixels": bool(versions)
            and all(item.subject_box_source == "provided" for item in versions),
        },
    )


def _clean_picture(root: Path, payload: N17Input) -> tuple[Path, Timeline | None]:
    saved = {}
    state = root / "nodes" / "n15_compose.json"
    if state.is_file() and state.resolve().is_relative_to(root):
        try:
            saved = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise QAError("composition source record is unreadable") from None
    exports = saved.get("exports") or {}
    raw = payload.picture_path or saved.get("clean_picture_path") or exports.get("clean_picture")
    if not raw:
        raise QAError("clean picture source is missing; recompose before exporting new overlays")
    timeline = payload.source_timeline
    if timeline is None and saved.get("timeline"):
        timeline = Timeline.model_validate(saved["timeline"])
    return _contained_file(root, raw), timeline


def _source_spans(kept: list[KeptShot], timeline: Timeline | None) -> list[KeptShot]:
    if timeline is None:
        return kept
    clips = {clip.clip_id: clip for clip in timeline.clips}
    rows = []
    for item in kept:
        clip = clips.get(item.shot.shot_id)
        if clip is None or item.duration_s > clip.duration_s + 1 / 30:
            raise QAError("clean source timeline does not contain the requested shot")
        rows.append(replace(item, source_start=clip.start_s))
    return rows


def _with_packaging_geometry(
    body: list[ShotGeometry],
    timeline: Timeline,
    budget: DurationBudget,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
) -> list[ShotGeometry]:
    if abs(timeline.duration_s - budget.total_s) > 1 / 30 + 0.001:
        raise QAError("clean source timeline does not match the explicit total duration")
    result = list(body)
    for name, duration in (("intro", budget.intro_s), ("outro", budget.outro_s)):
        if duration <= 0:
            continue
        clip = next((item for item in timeline.clips if item.clip_id == name), None)
        if clip is None or abs(clip.duration_s - duration) > 1 / 30 + 0.001:
            raise QAError("clean source packaging does not match its reserved duration")
        geo = plan_shot(
            shot_id=name,
            track=_full_frame(name),
            src_w=src_w,
            src_h=src_h,
            out_w=out_w,
            out_h=out_h,
            start_s=clip.start_s,
            duration_s=clip.duration_s,
            motion_s=0,
            regenerate=False,
        )
        if name == "intro":
            result.insert(0, replace(geo, mode="blur"))
        else:
            result.append(replace(geo, mode="blur"))
    return result


def _package_export(
    payload: N17Input,
    board: Script,
    boxes: list[OverlayBox],
    placed: list,
    *,
    work: Path,
    project_id: str,
    width: int,
    height: int,
    aspect: str,
    budget: DurationBudget,
    gateway: Any,
) -> tuple[list[OverlayBox], list]:
    from workers.nodes.n14_packaging.node import run as run_packaging

    shifted_boxes = [
        item.model_copy(
            update={
                "start_s": 0 if item.kind == "ai_label" else item.start_s + budget.intro_s,
                "end_s": budget.total_s if item.kind == "ai_label" else item.end_s + budget.intro_s,
            }
        )
        for item in boxes
    ]
    shifted = []
    for item, box in zip(placed, shifted_boxes, strict=True):
        shifted.append((item[0], box.start_s, box.end_s, item[3], item[4]))
    result = run_packaging(
        {
            "project_id": project_id,
            "payload": {
                "script": board.model_dump(mode="json"),
                "brief": payload.brief.model_copy(update={"aspect_ratios": [aspect]}).model_dump(
                    mode="json"
                ),
                "brand_kit": payload.brand_kit.model_dump(mode="json")
                if payload.brand_kit
                else None,
                "enterprise_id": payload.enterprise_id,
                "width": width,
                "height": height,
                "work_dir": str(work / "packaging"),
                "target_duration_s": budget.total_s,
                "intro_s": budget.intro_s,
                "outro_s": budget.outro_s,
            },
        },
        gateway=gateway,
    )
    for element in result.payload["elements"]:
        if element["kind"] not in {"intro_logo", "corner_logo", "outro_logo", "outro_cta"}:
            continue
        with Image.open(element["png_path"]) as image:
            w, h = image.size
        center = element["anchor"] == "center"
        x = round((width - w) / 2) if center else round(element["x_ratio"] * width)
        y = round(element["y_ratio"] * height - (h / 2 if center else 0))
        shifted_boxes.append(
            OverlayBox(
                kind=element["kind"],
                text=element["text"],
                language=board.language,
                x=x,
                y=y,
                w=w,
                h=h,
                start_s=element["start_s"],
                end_s=element["end_s"],
            )
        )
        shifted.append((element["png_path"], element["start_s"], element["end_s"], x, y))
    return shifted_boxes, shifted


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


def _soundtrack(root: Path, raw: str | None) -> tuple[str, float] | None:
    if not raw:
        return None
    path = _contained(root, raw, label="audio track")
    if not path.is_file():
        raise QAError("audio track must stay inside the project directory")
    return str(path), 0.0


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


def _contained(root: Path, raw: str, *, label: str = "master") -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise QAError(f"{label} must stay inside the project directory")
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
