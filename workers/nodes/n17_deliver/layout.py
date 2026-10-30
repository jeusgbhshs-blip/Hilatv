"""Place subtitles, spec cards, and the AI mark inside the platform safe area.

Every glyph is a PNG. The reframe graph does not draw text.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from workers.media.packaging import SUBTITLE_FONT_RATIO, Insets, ai_label_text, safe_insets
from workers.media.raster import render_overlay, save_png
from workers.nodes.n06_voiceover.schema import ShotVoiceover
from workers.nodes.n13_subtitle.node import run as run_subtitles
from workers.nodes.n13_subtitle.qa import QAError as SubtitleQAError
from workers.nodes.n13_subtitle.schema import SubjectBox, SubtitleCue
from workers.nodes.n17_deliver.qa import QAError
from workers.nodes.n17_deliver.reframe import Rect, ShotGeometry
from workers.nodes.n17_deliver.schema import OverlayBox, SpokenLine
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import Script


def burn_overlays(
    script: Script,
    takes: list[ShotVoiceover],
    geometries: list[ShotGeometry],
    *,
    brief: Brief | None,
    brand: BrandKit | None,
    project_id: str,
    work: Path,
    width: int,
    height: int,
) -> tuple[list[OverlayBox], list[tuple[str, float, float, int, int]], list[SpokenLine]]:
    safe = safe_insets(list(brief.platform) if brief else [])
    subjects = {item.shot_id: _union(item) for item in geometries}
    cues = _cues(
        script,
        takes,
        subjects,
        brief=brief,
        brand=brand,
        project_id=project_id,
        work=work,
        width=width,
        height=height,
    )
    boxes: list[OverlayBox] = []
    placed: list[tuple[str, float, float, int, int]] = []
    spoken: list[SpokenLine] = []
    font = max(12, round(height * SUBTITLE_FONT_RATIO))
    by_shot: dict[str, list[SubtitleCue]] = {}
    for cue in cues:
        by_shot.setdefault(cue.shot_id, []).append(cue)
        image = render_overlay(
            cue.text,
            weight="regular",
            font_size=font,
            fill="#FFFFFF",
            highlight=cue.highlights[0].color if cue.highlights else "#F5A623",
            spans=[(item.start, item.end) for item in cue.highlights],
            padding=4,
            stroke=2,
        )
        x, y, image = _fit(
            image,
            round(cue.x_ratio * width),
            round(cue.y_ratio * height),
            width,
            height,
            safe,
            subjects.get(cue.shot_id),
        )
        path = work / "overlays" / f"{cue.cue_id}.png"
        save_png(image, path)
        _remember(
            boxes,
            placed,
            "subtitle",
            cue.text,
            script.language,
            path,
            x,
            y,
            image,
            cue.start_s,
            cue.end_s,
        )
    heard = {item.shot_id: item.transcript for item in takes}
    for shot_id, rows in by_shot.items():
        voice = next(shot.voiceover for shot in script.shots if shot.shot_id == shot_id)
        joined = "".join(row.text for row in rows)
        spoken.append(
            SpokenLine(
                shot_id=shot_id,
                voiceover=voice,
                subtitle=joined,
                transcript=heard.get(shot_id, ""),
            )
        )
    offset = 0.0
    fill = brand.colors.primary if brand is not None else "#0A3D91"
    for shot, geo in zip(script.shots, geometries, strict=True):
        for card in shot.on_screen_text:
            if card.out <= card.in_:
                continue
            image = render_overlay(
                card.text,
                weight="bold",
                font_size=font,
                fill="#FFFFFF",
                background=fill,
                padding=6,
                radius=8,
            )
            x, y, image = _fit(
                image,
                int(round(safe.left * width)),
                int(round(safe.top * height)),
                width,
                height,
                safe,
                subjects.get(shot.shot_id),
            )
            path = work / "overlays" / f"{shot.shot_id}-{_slug(card.text)}.png"
            save_png(image, path)
            _remember(
                boxes,
                placed,
                "badge",
                card.text,
                script.language,
                path,
                x,
                y,
                image,
                offset + float(card.in_),
                offset + float(card.out),
            )
        offset += geo.duration_s
    label = render_overlay(
        ai_label_text(),
        weight="bold",
        font_size=max(12, font - 2),
        fill="#FFFFFF",
        background="#111111",
        padding=4,
        radius=4,
    )
    occupied = _occupied(list(subjects.values()))
    x = int(round((1 - safe.right) * width)) - label.width
    x, y, label = _fit(label, x, int(round(safe.top * height)), width, height, safe, occupied)
    path = work / "overlays" / "ai.png"
    save_png(label, path)
    _remember(
        boxes,
        placed,
        "ai_label",
        ai_label_text(),
        script.language,
        path,
        x,
        y,
        label,
        0.0,
        offset,
    )
    return boxes, placed, spoken


def _cues(
    script: Script,
    takes: list[ShotVoiceover],
    subjects: dict[str, Rect],
    *,
    brief: Brief | None,
    brand: BrandKit | None,
    project_id: str,
    work: Path,
    width: int,
    height: int,
) -> list[SubtitleCue]:
    boxes = []
    for shot_id, rect in subjects.items():
        boxes.append(
            SubjectBox(
                shot_id=shot_id,
                x=_unit(rect.x, width),
                y=_unit(rect.y, height),
                w=_unit(rect.w, width),
                h=_unit(rect.h, height),
            )
        )
    try:
        result = run_subtitles(
            {
                "project_id": project_id,
                "payload": {
                    "script": script.model_dump(mode="json"),
                    "voiceovers": [item.model_dump(mode="json") for item in takes],
                    "brand_kit": brand.model_dump(mode="json") if brand else None,
                    "brief": brief.model_dump(mode="json") if brief else None,
                    "subject_boxes": [item.model_dump(mode="json") for item in boxes],
                    "width": width,
                    "height": height,
                    "work_dir": str(work / "n13"),
                },
            }
        )
    except SubtitleQAError as exc:
        raise QAError(f"subtitles failed: {exc}") from exc
    return [SubtitleCue.model_validate(item) for item in result.payload["cues"]]


def _fit(
    image: Image.Image,
    x: int,
    y: int,
    frame_w: int,
    frame_h: int,
    safe: Insets,
    subject: Rect | None,
) -> tuple[int, int, Image.Image]:
    left = int(round(safe.left * frame_w))
    top = int(round(safe.top * frame_h))
    right = int(round(frame_w - safe.right * frame_w))
    bottom = int(round(frame_h - safe.bottom * frame_h))
    room_w = max(8, right - left)
    room_h = max(8, bottom - top)
    fitted = image
    if fitted.width > room_w or fitted.height > room_h:
        scale = min(room_w / fitted.width, room_h / fitted.height)
        fitted = fitted.resize(
            (max(1, int(fitted.width * scale)), max(1, int(fitted.height * scale))),
            Image.Resampling.LANCZOS,
        )
    x = min(max(x, left), max(left, right - fitted.width))
    y = min(max(y, top), max(top, bottom - fitted.height))
    if subject is not None and _hits(x, y, fitted.width, fitted.height, subject):
        lifted = int(subject.y) - fitted.height - 4
        y = min(max(lifted, top), max(top, bottom - fitted.height))
    if subject is not None and _hits(x, y, fitted.width, fitted.height, subject):
        dropped = int(subject.y + subject.h) + 4
        y = min(max(dropped, top), max(top, bottom - fitted.height))
    return x, y, fitted


def _hits(x: int, y: int, w: int, h: int, subject: Rect) -> bool:
    return not (
        x + w <= subject.x + 2
        or subject.x + subject.w <= x + 2
        or y + h <= subject.y + 2
        or subject.y + subject.h <= y + 2
    )


def _occupied(rects: list[Rect]) -> Rect | None:
    if not rects:
        return None
    x0 = min(item.x for item in rects)
    y0 = min(item.y for item in rects)
    x1 = max(item.x + item.w for item in rects)
    y1 = max(item.y + item.h for item in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _union(geo: ShotGeometry) -> Rect:
    samples = [geo.output_subject(0.0), geo.output_subject(geo.duration_s * 0.5)]
    if geo.duration_s > 0.05:
        samples.append(geo.output_subject(max(0.0, geo.duration_s - 0.04)))
    x0 = min(item.x for item in samples)
    y0 = min(item.y for item in samples)
    x1 = max(item.x + item.w for item in samples)
    y1 = max(item.y + item.h for item in samples)
    return Rect(x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0))


def _unit(value: float, size: int) -> float:
    if size <= 0:
        return 0.0
    ratio = value / size
    return min(0.99, max(0.0, ratio))


def _remember(
    boxes: list[OverlayBox],
    placed: list[tuple[str, float, float, int, int]],
    kind: str,
    text: str,
    language: str,
    path: Path,
    x: int,
    y: int,
    image: Image.Image,
    start_s: float,
    end_s: float,
) -> None:
    end = max(end_s, start_s + 0.04)
    boxes.append(
        OverlayBox(
            kind=kind,
            text=text,
            language=language,
            x=x,
            y=y,
            w=image.width,
            h=image.height,
            start_s=round(start_s, 3),
            end_s=round(end, 3),
        )
    )
    placed.append((str(path), round(start_s, 3), round(end, 3), x, y))


def _slug(text: str) -> str:
    cleaned = "".join(char if char.isalnum() else "-" for char in text)[:24]
    return cleaned or "card"
