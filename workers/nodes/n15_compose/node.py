"""N15 edit. The timeline JSON is the edit; FFmpeg only executes it.

Text, logos, prices, and phones are overlays. The shot plates are flat color
when no picture file was supplied, so a model never paints those words.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from gateway.media_bytes import render_wav
from workers.logging import log_event
from workers.media.ffmpeg import RenderError, encode_plate, run_ffmpeg
from workers.media.packaging import (
    FPS,
    SUBTITLE_FONT_RATIO,
    canvas_size,
    lut_path,
    outro_spec,
    quantize_s,
)
from workers.media.raster import render_overlay, save_png
from workers.nodes.n15_compose.graph import command
from workers.nodes.n15_compose.qa import QAError, check
from workers.nodes.n15_compose.schema import (
    AudioClip,
    MotionCard,
    N15Input,
    NodeRequest,
    NodeResult,
    OverlayItem,
    Timeline,
    VideoClip,
)
from workers.nodes.runtime import Deadline
from workers.qa.pixels import MediaLoad, resolve_project_file
from workers.qa.scores import content_blocked
from workers.qa.settings import project_dir
from workers.schemas.asset import Asset, AssetKind, Candidate

NODE = "n15_compose"
ASSET_NS = uuid.UUID("6f1c0a1e-7b2d-4e5a-9c31-0c0a6e6e0715")
_PALETTE = ((32, 48, 72), (58, 64, 70), (28, 44, 60), (44, 50, 58))
_EXPORTS = ("master", "nosub", "novo")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 180.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N15Input.model_validate(request.payload)
    from workers.schemas.label_lock import LabelLocked, walk_label_edits

    try:
        walk_label_edits(request.payload)
    except LabelLocked as exc:
        raise QAError(str(exc), retryable=False) from exc
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    _ = gateway
    deadline = Deadline(timeout_s, node=NODE)
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            deadline.check()
            result = _execute(request, attempt=attempt)
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
    message = f"n15_compose failed after {max_attempts} attempts: {last_error}"
    raise QAError(message, retryable=False) from last_error


def render_timeline(timeline: Timeline, dest: Path, *, variant: str = "master") -> str:
    """Replay one export from a timeline. Returns the filter graph that was run."""

    graph = command(timeline, str(dest), variant)
    run_ffmpeg(graph)
    from workers.nodes.n15_compose.graph import filter_complex

    return filter_complex(timeline, variant)


def _execute(request: NodeRequest, *, attempt: int) -> NodeResult:
    payload = N15Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    width, height = _canvas(payload)
    fallback = Path("/tmp") / "hilatv-n15" / request.project_id
    work = Path(payload.work_dir) if payload.work_dir else fallback
    work.mkdir(parents=True, exist_ok=True)
    _require_license(payload)
    intro_s = quantize_s(payload.intro_s)
    outro_s = quantize_s(payload.outro_s or float(outro_spec()["duration_s"]))
    timeline = _timeline(payload, work, width, height, intro_s, outro_s)
    path = work / "timeline.json"
    body = json.dumps(timeline.model_dump(mode="json"), ensure_ascii=False, indent=2)
    path.write_text(body + "\n", encoding="utf-8")
    exports: dict[str, str] = {}
    graphs: dict[str, str] = {}
    for variant in _EXPORTS:
        dest = work / f"{variant}.mp4"
        graphs[variant] = render_timeline(timeline, dest, variant=variant)
        exports[variant] = str(dest)
    assets = [
        Asset(
            asset_id=str(uuid.uuid5(ASSET_NS, f"{request.project_id}:{name}")),
            kind=AssetKind.deliverable,
            uri=Path(exports[name]).resolve().as_uri(),
            brand_id=payload.brand_kit.brand_id if payload.brand_kit else None,
            mime_type="video/mp4",
            license_source="render-layer",
        )
        for name in _EXPORTS
    ]
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        duration_s=timeline.duration_s,
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        attempt=attempt,
        payload={
            "script": payload.script.model_dump(mode="json"),
            "timeline": timeline.model_dump(mode="json"),
            "timeline_path": str(path),
            "exports": exports,
            "filters": graphs,
            "assets": [item.model_dump(mode="json") for item in assets],
            "width": width,
            "height": height,
            "fps": FPS,
            "placeholder_shots": [clip.clip_id for clip in timeline.clips if clip.placeholder],
            **_license_payload(payload),
        },
    )


def _timeline(
    payload: N15Input,
    work: Path,
    width: int,
    height: int,
    intro_s: float,
    outro_s: float,
) -> Timeline:
    shots = list(payload.script.shots)
    supplied = {item.shot_id: item for item in payload.shot_clips}
    pieces: list[tuple] = []
    if intro_s > 0:
        pieces.append(("intro", intro_s, "cut", (16, 32, 64), None, [], False))
    live = os.getenv("HILATV_LIVE", "0").strip() == "1"
    for index, shot in enumerate(shots):
        duration = quantize_s(float(shot.duration_s))
        media = supplied.get(shot.shot_id)
        if payload.shot_clips and media is None:
            raise QAError(f"{shot.shot_id} has no picture to edit", retryable=False)
        if media is None:
            if live:
                raise QAError(
                    f"{shot.shot_id} has no picture; live compose will not paint a color plate",
                    retryable=False,
                )
            color = _PALETTE[index % len(_PALETTE)]
            pieces.append((shot.shot_id, duration, shot.transition_out, color, None, [], True))
            continue
        source = _inside_project(media.path)
        pieces.append(
            (
                shot.shot_id,
                duration,
                shot.transition_out,
                (128, 128, 128),
                source,
                list(media.cards),
                False,
            )
        )
    pieces.append(("outro", outro_s, "cut", (12, 24, 48), None, [], False))
    colors = [item[3] for item in pieces]
    target = colors[0]
    cursor = 0.0
    clips: list[VideoClip] = []
    card_rows: list[tuple[MotionCard, float]] = []
    for clip_id, duration, transition, rgb, source, cards, placeholder in pieces:
        frames = max(1, int(round(duration * FPS)))
        duration = frames / FPS
        gains = _gains(rgb, target)
        plate = work / "plates" / f"{clip_id}.mp4"
        if source is not None and _blocked_plate(payload.videos, source):
            raise QAError("内容安全硬伤不能进入成片", retryable=False)
        if source is None:
            encode_plate(plate, rgb=rgb, width=width, height=height, frames=frames, fps=FPS)
        else:
            _fit_clip(source, plate, width=width, height=height, frames=frames)
        path = str(plate)
        clips.append(
            VideoClip(
                clip_id=clip_id,
                path=path,
                duration_s=duration,
                start_s=round(cursor, 3),
                transition_out=transition,
                grade_rr=gains[0],
                grade_gg=gains[1],
                grade_bb=gains[2],
                placeholder=placeholder,
            )
        )
        for card in cards:
            card_rows.append((card, cursor))
        cursor += duration
    audio = _audio(payload, work, intro_s)
    overlays = _overlays(payload, work, width, height, intro_s)
    overlays.extend(_motion_cards(card_rows, work, width, height))
    return Timeline(
        width=width,
        height=height,
        fps=FPS,
        lut_path=str(lut_path()),
        duration_s=round(cursor, 3),
        clips=clips,
        audio=audio,
        produce_ids={name: uuid.uuid4().hex for name in ("master", "nosub", "novo")},
        overlays=overlays,
        work_dir=str(work),
    )


def _fit_clip(source: Path, dest: Path, *, width: int, height: int, frames: int) -> None:
    """Cover the frame with a real clip. Pad is not used, so the edges are not bars."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-threads",
            "1",
            "-stream_loop",
            "-1",
            "-i",
            str(source),
            "-vf",
            (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps={FPS}"
            ),
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-preset",
            "ultrafast",
            "-fflags",
            "+bitexact",
            "-flags",
            "+bitexact",
            str(dest),
        ]
    )


def _motion_cards(
    rows: list[tuple[MotionCard, float]],
    work: Path,
    width: int,
    height: int,
) -> list[OverlayItem]:
    items: list[OverlayItem] = []
    folder = work / "motion"
    for index, (card, origin) in enumerate(rows):
        image = render_overlay(
            card.text,
            weight="bold",
            font_size=max(12, round(height * 0.08)),
            fill="#FFFFFF",
            padding=6,
            stroke=2,
        )
        path = folder / f"card_{index}.png"
        save_png(image, path)
        start = origin + card.start_s
        end = origin + card.end_s
        if end <= start:
            continue
        items.append(
            OverlayItem(
                kind="motion_card",
                path=str(path),
                text=card.text,
                start_s=round(start, 3),
                end_s=round(end, 3),
                y_ratio=card.y_ratio,
                anchor="center",
            )
        )
    return items


def _require_license(payload: N15Input) -> None:
    track = payload.audio_track
    if track is None:
        return
    if not track.source.strip() or not track.license.strip():
        raise QAError("audio track is missing a source or a license", retryable=False)
    resolved = _inside_project(track.path)
    track.path = str(resolved)
    for item in payload.licenses:
        if not item.source.strip() or not item.license.strip():
            raise QAError("a music or sound-effect license record is incomplete", retryable=False)


def _inside_project(raw: str) -> Path:
    root = project_dir()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise QAError(
            "audio track must stay inside the project directory",
            retryable=False,
        )
    return resolved


def _license_payload(payload: N15Input) -> dict[str, Any]:
    if payload.audio_track is None:
        return {}
    return {
        "audio_track": payload.audio_track.model_dump(mode="json"),
        "licenses": [item.model_dump(mode="json") for item in payload.licenses],
    }


def _audio(payload: N15Input, work: Path, intro_s: float) -> list[AudioClip]:
    track = payload.audio_track
    if track is not None:
        start = intro_s if track.start_s is None else track.start_s
        return [
            AudioClip(
                path=track.path,
                start_s=round(start, 3),
                duration_s=round(track.duration_s, 3),
            )
        ]
    takes = {item.shot_id: item for item in payload.voiceovers}
    clips: list[AudioClip] = []
    offset = intro_s
    language = payload.script.language
    for shot in payload.script.shots:
        take = takes.get(shot.shot_id)
        if take is None or not shot.voiceover.strip():
            offset += float(shot.duration_s)
            continue
        dest = work / "audio" / f"{shot.shot_id}.wav"
        dest.parent.mkdir(parents=True, exist_ok=True)
        seed = int(hashlib.sha256(shot.shot_id.encode()).hexdigest()[:6], 16)
        data, _stamps, duration = render_wav(
            shot.voiceover,
            seed,
            speed=take.speed,
            pause_s=take.pause_s,
            language=language,
        )
        dest.write_bytes(data)
        clips.append(
            AudioClip(
                path=str(dest),
                start_s=round(offset, 3),
                duration_s=round(min(float(duration), float(shot.duration_s)), 3),
            )
        )
        offset += float(shot.duration_s)
    return clips


def _overlays(
    payload: N15Input,
    work: Path,
    width: int,
    height: int,
    intro_s: float,
) -> list[OverlayItem]:
    items: list[OverlayItem] = []
    font_size = max(12, round(height * SUBTITLE_FONT_RATIO))
    sub_dir = work / "subtitles"
    for cue in payload.cues:
        highlight = cue.highlights[0].color if cue.highlights else "#F5A623"
        spec = {
            "text": cue.text,
            "weight": "regular",
            "font_size": font_size,
            "fill": "#FFFFFF",
            "highlight": highlight,
            "spans": [[item.start, item.end] for item in cue.highlights],
            "padding": 4,
            "radius": 0,
            "stroke": 2,
        }
        image = render_overlay(
            spec["text"],
            weight="regular",
            font_size=font_size,
            fill="#FFFFFF",
            highlight=highlight,
            spans=[(int(item[0]), int(item[1])) for item in spec["spans"]],
            padding=4,
            stroke=2,
        )
        path = sub_dir / f"{cue.cue_id}.png"
        save_png(image, path)
        x = min(max(0, round(cue.x_ratio * width)), max(0, width - image.width))
        y = min(max(0, round(cue.y_ratio * height)), max(0, height - image.height))
        items.append(
            OverlayItem(
                kind="subtitle",
                path=str(path),
                text=cue.text,
                start_s=round(cue.start_s + intro_s, 3),
                end_s=round(cue.end_s + intro_s, 3),
                x=x,
                y=y,
                anchor="topleft",
                spec=spec,
            )
        )
    for element in payload.elements:
        animate = element.template if element.kind == "intro_logo" else ""
        x = 0
        y = 0
        if element.anchor != "center":
            with Image.open(element.png_path) as image:
                x = min(max(0, round(element.x_ratio * width)), max(0, width - image.width))
                y = min(max(0, round(element.y_ratio * height)), max(0, height - image.height))
        items.append(
            OverlayItem(
                kind=element.kind,
                path=element.png_path,
                text=element.text,
                start_s=element.start_s,
                end_s=element.end_s,
                x=x,
                y=y,
                y_ratio=element.y_ratio,
                anchor=element.anchor,
                animate=animate,
                spec=element.spec,
            )
        )
    order = {
        "intro_logo": 0,
        "corner_logo": 1,
        "badge": 2,
        "subtitle": 3,
        "outro_logo": 4,
        "outro_cta": 5,
        "ai_label": 6,
    }
    items = _with_locked_label(items, work, width, height, intro_s, payload)
    items.sort(key=lambda item: order.get(item.kind, 9))
    return items


def _blocked_plate(videos: list[Candidate], source: Path) -> bool:
    """A content-safety hard fail never becomes the master plate."""

    for item in videos:
        if not content_blocked(item.qa):
            continue
        located = resolve_project_file(Path(item.uri))
        if isinstance(located, MediaLoad) or not located.is_file():
            continue
        if located.resolve() == source.resolve():
            return True
    return False


def _with_locked_label(
    items: list[OverlayItem],
    work: Path,
    width: int,
    height: int,
    intro_s: float,
    payload: N15Input,
) -> list[OverlayItem]:
    """Drop a caller-supplied mark and burn the canonical one for the whole film."""

    from workers.media.packaging import ai_label_text
    from workers.media.raster import render_overlay, save_png

    kept = [item for item in items if item.kind != "ai_label"]
    board = sum(float(shot.duration_s) for shot in payload.script.shots)
    end = max(intro_s + board + float(payload.outro_s), 0.04)
    for item in kept:
        end = max(end, float(item.end_s))
    text = ai_label_text()
    font_size = max(28, round(min(width, height) * 0.06))
    spec = {
        "text": text,
        "weight": "bold",
        "font_size": font_size,
        "fill": "#FFFFFF",
        "background": "#111111",
        "padding": 4,
        "radius": 4,
        "stroke": 0,
    }
    image = render_overlay(**spec)
    path = work / "ai_label.png"
    save_png(image, path)
    margin = max(8, round(min(width, height) * 0.04))
    kept.append(
        OverlayItem(
            kind="ai_label",
            path=str(path),
            text=text,
            start_s=0.0,
            end_s=round(end, 3),
            x=margin,
            y=margin,
            anchor="topleft",
            spec=spec,
        )
    )
    return kept


def _gains(src: tuple[int, int, int], target: tuple[int, int, int]) -> tuple[float, float, float]:
    values: list[float] = []
    for channel, aim in zip(src, target, strict=True):
        if channel <= 0:
            values.append(1.0)
        else:
            values.append(round(max(0.25, min(4.0, aim / channel)), 4))
    return values[0], values[1], values[2]


def _canvas(payload: N15Input) -> tuple[int, int]:
    aspect = None
    if payload.brief and payload.brief.aspect_ratios:
        aspect = payload.brief.aspect_ratios[0]
    return canvas_size(aspect, width=payload.width, height=payload.height)
