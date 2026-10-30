"""N13 subtitles. N6 timestamps become lines; the render layer draws every glyph.

No image or video model is called. Prices, phones, and logos stay off the
generated frames and are composited later.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from workers.logging import log_event
from workers.media.packaging import (
    SUBTITLE_FONT_RATIO,
    SUBTITLE_LINE_RATIO,
    canvas_size,
    lexicon_words,
    safe_insets,
)
from workers.media.raster import load_font
from workers.nodes.n06_voiceover.schema import WordStamp
from workers.nodes.n13_subtitle.layout import Box, place_subtitle
from workers.nodes.n13_subtitle.qa import QAError, check
from workers.nodes.n13_subtitle.schema import (
    HighlightSpan,
    N13Input,
    NodeRequest,
    NodeResult,
    SubjectBox,
    SubtitleCue,
)
from workers.nodes.n13_subtitle.segment import (
    alignment_error_ms,
    break_lines,
    highlight_spans,
)
from workers.nodes.runtime import Deadline
from workers.schemas.asset import Asset, AssetKind
from workers.schemas.script import Script, Shot

NODE = "n13_subtitle"
ASSET_NS = uuid.UUID("6f1c0a1e-7b2d-4e5a-9c31-0c0a6e6e0713")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 60.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N13Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    _ = gateway
    deadline = Deadline(timeout_s, node=NODE)
    last_error: QAError | None = None
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
        return result
    message = f"n13_subtitle failed after {max_attempts} attempts: {last_error}"
    raise QAError(message) from last_error


def _execute(request: NodeRequest, *, attempt: int) -> NodeResult:
    payload = N13Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    script = payload.script
    language = _language(script, payload)
    width, height = _canvas(payload)
    font = load_font("regular", max(12, round(height * SUBTITLE_FONT_RATIO)))
    terms = _terms(payload)
    insets = safe_insets(list(payload.brief.platform) if payload.brief else [])
    takes = {item.shot_id: item for item in payload.voiceovers}
    boxes = {item.shot_id: item for item in payload.subject_boxes}
    cues: list[SubtitleCue] = []
    offset = 0.0
    for shot in script.shots:
        take = takes.get(shot.shot_id)
        selected = request.shot_id in (None, shot.shot_id)
        if selected and shot.voiceover.strip() and take is not None:
            cues.extend(
                _shot_cues(
                    shot,
                    list(take.timestamps),
                    language=language,
                    offset=offset,
                    terms=terms,
                    accent=_accent(payload),
                    box=boxes.get(shot.shot_id),
                    font=font,
                    width=width,
                    insets=insets,
                    project_id=request.project_id,
                )
            )
        offset += float(shot.duration_s)
    fallback = Path("/tmp") / "hilatv-n13" / request.project_id
    work = Path(payload.work_dir) if payload.work_dir else fallback
    work.mkdir(parents=True, exist_ok=True)
    path = work / "subtitles.json"
    path.write_text(
        json.dumps(
            {"language": language, "cues": [item.model_dump(mode="json") for item in cues]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    asset = Asset(
        asset_id=str(uuid.uuid5(ASSET_NS, f"{request.project_id}:subtitles")),
        kind=AssetKind.subtitle,
        uri=path.resolve().as_uri(),
        brand_id=payload.brand_kit.brand_id if payload.brand_kit else None,
        mime_type="application/json",
        license_source="render-layer",
    )
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        cues=len(cues),
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        attempt=attempt,
        payload={
            "script": script.model_dump(mode="json"),
            "voiceovers": [item.model_dump(mode="json") for item in payload.voiceovers],
            "cues": [item.model_dump(mode="json") for item in cues],
            "assets": [asset.model_dump(mode="json")],
            "language": language,
            "protected_words": sorted(_protected(terms)),
            "width": width,
            "height": height,
        },
    )


def _shot_cues(
    shot: Shot,
    stamps: list[WordStamp],
    *,
    language: str,
    offset: float,
    terms: list[str],
    accent: str,
    box: SubjectBox | None,
    font: Any,
    width: int,
    insets: Any,
    project_id: str,
) -> list[SubtitleCue]:
    lines = break_lines(shot.voiceover, stamps, language=language, lexicon=terms)
    subject = None if box is None else Box(x=box.x, y=box.y, w=box.w, h=box.h)
    cues: list[SubtitleCue] = []
    for index, line in enumerate(lines, start=1):
        spans = highlight_spans(line.text, terms)
        text_w = float(font.getlength(line.text)) / float(width) if width else 0.4
        placed = place_subtitle(
            safe=insets,
            subject=subject,
            text_w_ratio=min(0.92, max(0.05, text_w)),
            line_h_ratio=SUBTITLE_LINE_RATIO,
        )
        start = round(line.start_s, 3)
        end = round(max(line.end_s, start + 0.001), 3)
        error = alignment_error_ms(start, end, line.start_s, line.end_s)
        cues.append(
            SubtitleCue(
                cue_id=_cue_id(project_id, shot.shot_id, index, line.text),
                shot_id=shot.shot_id,
                text=line.text,
                lines=[line.text],
                start_s=round(offset + start, 3),
                end_s=round(offset + end, 3),
                audio_start_s=start,
                audio_end_s=end,
                alignment_error_ms=round(error, 3),
                x_ratio=round(placed.x_ratio, 4),
                y_ratio=round(placed.y_ratio, 4),
                highlights=[
                    HighlightSpan(start=start_at, end=end_at, text=snippet, color=accent)
                    for start_at, end_at, snippet in spans
                ],
                language=language,
            )
        )
    return cues


def _cue_id(project_id: str, shot_id: str, index: int, text: str) -> str:
    return str(uuid.uuid5(ASSET_NS, f"{project_id}:{shot_id}:{index}:{text}"))


def _language(script: Script, payload: N13Input) -> str:
    if script.language:
        return script.language
    if payload.brief and payload.brief.languages:
        return payload.brief.languages[0]
    return "zh"


def _canvas(payload: N13Input) -> tuple[int, int]:
    aspect = None
    if payload.brief and payload.brief.aspect_ratios:
        aspect = payload.brief.aspect_ratios[0]
    return canvas_size(aspect, width=payload.width, height=payload.height)


def _accent(payload: N13Input) -> str:
    if payload.brand_kit is not None:
        return payload.brand_kit.colors.accent
    return "#F5A623"


def _terms(payload: N13Input) -> list[str]:
    words = list(lexicon_words())
    brand = payload.brand_kit
    if brand is not None:
        words.append(brand.company_name)
        if brand.cta.phone.strip():
            words.append(brand.cta.phone.strip())
        if brand.cta.website.strip():
            words.append(brand.cta.website.strip())
        for product in brand.products:
            words.append(product.name)
            words.extend(product.selling_points)
    if payload.brief is not None:
        words.extend(payload.brief.must_include)
    return [item.strip() for item in words if item and item.strip()]


def _protected(terms: list[str]) -> set[str]:
    return {item for item in terms if len(item) >= 2}
