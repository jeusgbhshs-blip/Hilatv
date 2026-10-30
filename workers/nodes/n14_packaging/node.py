"""N14 brand packaging. Logo, badges, CTA, and the AI mark are drawn here.

Nothing is sent to an image model. On-screen words stay the cards N5 already wrote.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from workers.logging import log_event
from workers.media.packaging import (
    BADGE_FONT_RATIO,
    ai_label_text,
    canvas_size,
    intro_spec,
    outro_spec,
    quantize_s,
    safe_insets,
)
from workers.media.raster import render_logo, render_overlay, save_png
from workers.nodes.n14_packaging.qa import QAError, check
from workers.nodes.n14_packaging.schema import N14Input, NodeRequest, NodeResult, PackageElement
from workers.nodes.runtime import Deadline
from workers.schemas.asset import Asset, AssetKind

NODE = "n14_packaging"
ASSET_NS = uuid.UUID("6f1c0a1e-7b2d-4e5a-9c31-0c0a6e6e0714")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 60.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N14Input.model_validate(request.payload)
    from workers.schemas.label_lock import LabelLocked, walk_label_edits

    try:
        walk_label_edits(request.payload)
    except LabelLocked as exc:
        raise QAError(str(exc), retryable=False) from exc
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
    message = f"n14_packaging failed after {max_attempts} attempts: {last_error}"
    raise QAError(message) from last_error


def _execute(request: NodeRequest, *, attempt: int) -> NodeResult:
    payload = N14Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    script = payload.script
    width, height = _canvas(payload)
    insets = safe_insets(list(payload.brief.platform) if payload.brief else [])
    board_s = sum(float(shot.duration_s) for shot in script.shots)
    template = _intro_template(payload.intro, payload, board_s)
    opening = min(float(intro_spec()["default_s"]), float(intro_spec()["max_s"]))
    intro_s = 0.0 if template == "none" else quantize_s(opening)
    outro_s = quantize_s(float(outro_spec()["duration_s"]))
    total = intro_s + board_s + outro_s
    primary, secondary, accent = _colors(payload)
    phone = payload.brand_kit.cta.phone.strip() if payload.brand_kit else ""
    website = payload.brand_kit.cta.website.strip() if payload.brand_kit else ""
    corner = True if payload.corner_logo is None else payload.corner_logo
    fallback = Path("/tmp") / "hilatv-n14" / request.project_id
    work = Path(payload.work_dir) if payload.work_dir else fallback
    work.mkdir(parents=True, exist_ok=True)
    logo_size = max(48, round(height * 0.2))
    logo_spec = {"logo": True, "size": logo_size, "primary": primary, "secondary": secondary}
    logo_path = work / "logo.png"
    save_png(render_logo(logo_size, primary, secondary), logo_path)
    corner_size = max(28, round(height * 0.09))
    corner_spec = {"logo": True, "size": corner_size, "primary": primary, "secondary": secondary}
    corner_path = work / "corner.png"
    save_png(render_logo(corner_size, primary, secondary), corner_path)
    elements: list[PackageElement] = []
    if template != "none":
        elements.append(
            _element(
                request.project_id,
                kind="intro_logo",
                template=template,
                start_s=0.0,
                end_s=intro_s,
                x_ratio=0.5,
                y_ratio=0.5,
                anchor="center",
                png_path=logo_path,
                spec=logo_spec,
            )
        )
    badge_size = max(18, round(height * BADGE_FONT_RATIO))
    badge_index = 0
    offset = 0.0
    for shot in script.shots:
        if request.shot_id in (None, shot.shot_id):
            for card in shot.on_screen_text:
                start = intro_s + offset + float(card.in_)
                end = intro_s + offset + float(card.out)
                end = min(end, intro_s + offset + float(shot.duration_s))
                start = min(max(0.0, start), end)
                spec = {
                    "text": card.text,
                    "weight": "bold",
                    "font_size": badge_size,
                    "fill": "#FFFFFF",
                    "highlight": accent,
                    "background": primary,
                    "padding": 16,
                    "radius": 18,
                    "stroke": 0,
                }
                path = work / f"badge_{shot.shot_id}_{badge_index}.png"
                save_png(render_overlay(**spec), path)
                elements.append(
                    _element(
                        request.project_id,
                        kind="badge",
                        text=card.text,
                        start_s=round(start, 3),
                        end_s=round(max(end, start + 0.001), 3),
                        x_ratio=insets.left,
                        y_ratio=insets.top + 0.1 + badge_index * 0.14,
                        anchor="topleft",
                        png_path=path,
                        spec=spec,
                    )
                )
                badge_index += 1
        offset += float(shot.duration_s)
    body_end = intro_s + board_s
    elements.append(
        _element(
            request.project_id,
            kind="outro_logo",
            start_s=round(body_end, 3),
            end_s=round(body_end + outro_s, 3),
            x_ratio=0.5,
            y_ratio=0.34,
            anchor="center",
            png_path=logo_path,
            spec=logo_spec,
        )
    )
    cta_lines = [line for line in (phone, website) if line]
    if not cta_lines:
        cta_lines = ["联系我们"]
    cta_text = "\n".join(cta_lines)
    cta_spec = {
        "text": cta_text,
        "weight": "bold",
        "font_size": badge_size,
        "fill": "#FFFFFF",
        "highlight": accent,
        "background": primary,
        "padding": 18,
        "radius": 16,
        "stroke": 0,
    }
    cta_path = work / "cta.png"
    save_png(render_overlay(**cta_spec), cta_path)
    elements.append(
        _element(
            request.project_id,
            kind="outro_cta",
            text=cta_text,
            start_s=round(body_end, 3),
            end_s=round(body_end + outro_s, 3),
            x_ratio=0.5,
            y_ratio=0.62,
            anchor="center",
            png_path=cta_path,
            spec=cta_spec,
        )
    )
    if corner:
        elements.append(
            _element(
                request.project_id,
                kind="corner_logo",
                start_s=round(intro_s, 3),
                end_s=round(body_end, 3),
                x_ratio=max(0.0, 1 - insets.right - 0.12),
                y_ratio=insets.top,
                anchor="topleft",
                png_path=corner_path,
                spec=corner_spec,
            )
        )
    label = ai_label_text()
    label_spec = {
        "text": label,
        "weight": "bold",
        "font_size": max(28, round(min(width, height) * 0.06)),
        "fill": "#FFFFFF",
        "highlight": accent,
        "background": "#142033",
        "padding": 8,
        "radius": 8,
        "stroke": 0,
    }
    label_path = work / "ai_label.png"
    save_png(render_overlay(**label_spec), label_path)
    elements.append(
        _element(
            request.project_id,
            kind="ai_label",
            text=label,
            start_s=0.0,
            end_s=round(total, 3),
            x_ratio=insets.left,
            y_ratio=insets.top,
            anchor="topleft",
            png_path=label_path,
            spec=label_spec,
        )
    )
    plan = work / "packaging.json"
    plan.write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in elements],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    brand_id = payload.brand_kit.brand_id if payload.brand_kit else None
    assets = [
        Asset(
            asset_id=str(uuid.uuid5(ASSET_NS, f"{request.project_id}:logo")),
            kind=AssetKind.logo,
            uri=logo_path.resolve().as_uri(),
            brand_id=brand_id,
            mime_type="image/png",
            license_source="render-layer",
        ),
        Asset(
            asset_id=str(uuid.uuid5(ASSET_NS, f"{request.project_id}:packaging")),
            kind=AssetKind.deliverable,
            uri=plan.resolve().as_uri(),
            brand_id=brand_id,
            mime_type="application/json",
            license_source="render-layer",
        ),
    ]
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        elements=len(elements),
        intro=template,
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        attempt=attempt,
        payload={
            "script": script.model_dump(mode="json"),
            "elements": [item.model_dump(mode="json") for item in elements],
            "assets": [item.model_dump(mode="json") for item in assets],
            "intro_template": template,
            "intro_s": intro_s,
            "outro_s": outro_s,
            "duration_s": round(total, 3),
            "phone": phone,
            "corner_logo": corner,
            "width": width,
            "height": height,
        },
    )


def _element(
    project_id: str,
    *,
    kind: str,
    png_path: Path,
    spec: dict,
    **fields: Any,
) -> PackageElement:
    text = str(fields.get("text") or "")
    start = float(fields.get("start_s") or 0)
    template = fields.get("template", "")
    ident = str(uuid.uuid5(ASSET_NS, f"{project_id}:{kind}:{text}:{start}:{template}"))
    return PackageElement(element_id=ident, kind=kind, png_path=str(png_path), spec=spec, **fields)


def _intro_template(explicit: str | None, payload: N14Input, board_s: float) -> str:
    allowed = set(intro_spec()["templates"]) | {"none"}
    if explicit:
        if explicit not in allowed:
            raise QAError(f"unknown intro template {explicit}", retryable=False)
        return explicit
    if board_s <= float(intro_spec()["short_video_s"]):
        return "none"
    names = [item.lower() for item in (payload.brief.platform if payload.brief else [])]
    short = [item.lower() for item in intro_spec()["short_platforms"]]
    if any(alias in name for alias in short for name in names):
        return "none"
    return "fade"


def _canvas(payload: N14Input) -> tuple[int, int]:
    aspect = None
    if payload.brief and payload.brief.aspect_ratios:
        aspect = payload.brief.aspect_ratios[0]
    return canvas_size(aspect, width=payload.width, height=payload.height)


def _colors(payload: N14Input) -> tuple[str, str, str]:
    if payload.brand_kit is None:
        return "#0A3D91", "#FFFFFF", "#F5A623"
    colors = payload.brand_kit.colors
    return colors.primary, colors.secondary, colors.accent
