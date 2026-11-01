"""N14 brand packaging. Logo, badges, CTA, and the AI mark are drawn here.

Nothing is sent to an image model. On-screen words stay the cards N5 already wrote.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from gateway.storage import StorageError, object_store_from_env, read_asset_bytes
from workers.brand_kit.store import read_asset
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
from workers.media.raster import fitting_text, render_logo, render_overlay, save_png
from workers.media.timing import duration_budget
from workers.nodes.n14_packaging.qa import QAError, check
from workers.nodes.n14_packaging.schema import N14Input, NodeRequest, NodeResult, PackageElement
from workers.nodes.runtime import Deadline
from workers.qa.settings import project_dir
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
    deadline = Deadline(timeout_s, node=NODE)
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            deadline.check()
            result = _execute(request, attempt=attempt, gateway=gateway)
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


def _execute(request: NodeRequest, *, attempt: int, gateway: Any = None) -> NodeResult:
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
    source, logo_status = _logo_source(payload, gateway)
    has_logo = logo_status == "ready"
    show_logo = True if payload.brand_logo is None else payload.brand_logo
    template = (
        "none"
        if not show_logo or not has_logo
        else _intro_template(payload.intro, payload, board_s)
    )
    opening = min(float(intro_spec()["default_s"]), float(intro_spec()["max_s"]))
    intro_s = 0.0 if template == "none" else quantize_s(opening)
    outro_s = quantize_s(float(outro_spec()["duration_s"]))
    if payload.target_duration_s is not None:
        budget = duration_budget(
            payload.target_duration_s,
            intro_s=0.0 if payload.intro_s is None else payload.intro_s,
            outro_s=payload.outro_s,
        )
        if abs(board_s - budget.body_s) > 1 / 30 + 1e-6:
            raise QAError(
                "story duration does not match the reserved whole-film budget", retryable=False
            )
        intro_s, outro_s = budget.intro_s, budget.outro_s
    else:
        if payload.intro_s is not None:
            intro_s = 0.0 if payload.intro_s == 0 else quantize_s(payload.intro_s)
        if payload.outro_s is not None:
            outro_s = 0.0 if payload.outro_s == 0 else quantize_s(payload.outro_s)
    if intro_s == 0:
        template = "none"
    elif template == "none":
        if not show_logo or not has_logo:
            raise QAError("an explicit logo intro requires a real authorized logo", retryable=False)
        template = "fade"
    total = intro_s + board_s + outro_s
    primary, _secondary, accent = _colors(payload)
    phone = payload.brand_kit.cta.phone.strip() if payload.brand_kit else ""
    website = payload.brand_kit.cta.website.strip() if payload.brand_kit else ""
    corner = (
        (True if payload.corner_logo is None else payload.corner_logo) and show_logo and has_logo
    )
    fallback = Path("/tmp") / "hilatv-n14" / request.project_id
    work = Path(payload.work_dir) if payload.work_dir else fallback
    work.mkdir(parents=True, exist_ok=True)
    logo_path = work / "logo.png"
    corner_path = work / "corner.png"
    logo_spec: dict[str, Any] = {}
    corner_spec: dict[str, Any] = {}
    corner_width = 0
    if has_logo:
        ratio = payload.brand_kit.logo.safe_area_ratio
        spec = {
            "logo": True,
            "source_uri": payload.brand_kit.logo.primary,
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "safe_area_ratio": ratio,
            "logo_status": logo_status,
        }
        logo_spec = {
            **spec,
            "max_width": round(width * min(0.45, 1 - 2 * max(insets.left, insets.right))),
            "max_height": round(height * 0.2),
        }
        corner_spec = {**spec, "max_width": round(width * 0.22), "max_height": round(height * 0.09)}
        try:
            logo = render_logo(source, **_render_bounds(logo_spec))
            corner_image = render_logo(source, **_render_bounds(corner_spec))
        except ValueError as exc:
            raise QAError(str(exc), retryable=False) from exc
        save_png(logo, logo_path)
        save_png(corner_image, corner_path)
        corner_width = corner_image.width
    elements: list[PackageElement] = []
    if template != "none" and show_logo:
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
    if has_logo:
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
            logo_status=logo_status,
        )
    )
    if corner:
        elements.append(
            _element(
                request.project_id,
                kind="corner_logo",
                start_s=round(intro_s, 3),
                end_s=round(body_end, 3),
                x_ratio=max(insets.left, 1 - insets.right - corner_width / width),
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
    _fit_elements(elements, width, height, insets)
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
    assets = []
    if has_logo:
        assets.append(
            Asset(
                asset_id=str(uuid.uuid5(ASSET_NS, f"{request.project_id}:logo")),
                kind=AssetKind.logo,
                uri=logo_path.resolve().as_uri(),
                brand_id=brand_id,
                mime_type="image/png",
                license_source="render-layer",
            )
        )
    assets.append(
        Asset(
            asset_id=str(uuid.uuid5(ASSET_NS, f"{request.project_id}:packaging")),
            kind=AssetKind.deliverable,
            uri=plan.resolve().as_uri(),
            brand_id=brand_id,
            mime_type="application/json",
            license_source="render-layer",
        )
    )
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
            "brand_logo": show_logo,
            "logo_status": logo_status,
            "logo_source": payload.brand_kit.logo.primary if payload.brand_kit else "",
            "preview_only": logo_status != "ready",
            "width": width,
            "height": height,
        },
    )


def _render_bounds(spec: dict[str, Any]) -> dict[str, Any]:
    return {key: spec[key] for key in ("max_width", "max_height", "safe_area_ratio")}


def _logo_source(payload: N14Input, gateway: Any) -> tuple[bytes, str]:
    if payload.brand_kit is None:
        return b"", "missing"
    uri = payload.brand_kit.logo.primary
    if uri.startswith("mock://"):
        return b"", "mock"
    if uri.startswith("brand://"):
        if not payload.enterprise_id:
            raise QAError("brand logo requires its enterprise identity", retryable=False)
        data = read_asset(uri, enterprise_id=payload.enterprise_id)
        if not data:
            raise QAError("brand logo is missing or not owned by this enterprise", retryable=False)
        return data, "ready"
    stores = [None]
    if uri.startswith(("oss://", "s3://")):
        stores = [
            getattr(adapter, "store", None)
            for adapter in (getattr(gateway, "registry", None) or {}).values()
        ]
        stores.append(object_store_from_env())
    for store in stores:
        try:
            return read_asset_bytes(
                uri, store=store, allowed_roots=[project_dir()], max_bytes=8 * 1024 * 1024
            ), "ready"
        except StorageError:
            continue
    raise QAError(
        "brand logo is missing, unreadable, or outside authorized storage", retryable=False
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


def _fit_elements(elements: list[PackageElement], width: int, height: int, insets: Any) -> None:
    left, right = round(insets.left * width), round((1 - insets.right) * width)
    top, bottom = round(insets.top * height), round((1 - insets.bottom) * height)
    for item in elements:
        if item.text:
            room_w = right - left
            if item.anchor == "center":
                room_w = round(width * (1 - 2 * max(insets.left, insets.right)))
            try:
                image, spec = fitting_text(item.spec, room_w, bottom - top)
            except ValueError as exc:
                raise QAError(str(exc), retryable=False) from exc
            save_png(image, Path(item.png_path))
            item.spec = spec
            if item.kind == "ai_label":
                from workers.compliance.label_measure import glyph_ink_height, minimum_glyph_px

                if glyph_ink_height(image) < minimum_glyph_px(min(width, height)):
                    raise QAError("AI label cannot meet its minimum ink height in the safe area")
        with Image.open(item.png_path) as image:
            w, h = image.size
        if w > right - left or h > bottom - top:
            raise QAError("brand overlay does not fit the platform safe area", retryable=False)
        if item.anchor == "center":
            y = round(item.y_ratio * height - h / 2)
            y = min(max(y, top), bottom - h)
            item.y_ratio = (y + h / 2) / height
        else:
            x = min(max(round(item.x_ratio * width), left), right - w)
            y = min(max(round(item.y_ratio * height), top), bottom - h)
            item.x_ratio, item.y_ratio = x / width, y / height


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
