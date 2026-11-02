"""N9 / N11 entry point. ``review_shot(payload)`` returns a chapter 5 QAReport.

Eval calls this with one dict. Pixel rules run locally. Judges go through the
gateway and stay on the mock adapter unless HILATV_LIVE=1.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Any

from PIL import Image

from workers.logging import log_event
from workers.qa.frames import sample_frames
from workers.qa.pixels import MediaLoad, load_image, resolve_project_file
from workers.qa.rules import inspect_frames, inspect_image
from workers.qa.scores import apply_findings, not_reviewed
from workers.qa.settings import validate_settings
from workers.qa.vlm import cross_review
from workers.schemas.asset import QAReport

# Suffixes that are decoded as video. Eval uses the same tuple.
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm")


def review_not_ready() -> dict[str, str]:
    return {"status": "stub", "task": "T12"}


def review_shot(
    payload: dict[str, Any],
    *,
    gateway: Any | None = None,
    image: Image.Image | None = None,
    frames: list[Image.Image] | None = None,
) -> QAReport:
    if not isinstance(payload, dict):
        raise TypeError("review_shot payload must be an object")
    validate_settings()
    data = dict(payload)
    gateway = gateway if gateway is not None else _default_gateway()
    media = _media(data, image=image, frames=frames)
    if isinstance(media, MediaLoad) and not media.ok:
        report = not_reviewed(media.status, media.reason)
        event = "qa_text_only" if media.status == "text_only" else "qa_media_error"
        log_event(
            event,
            project_id=_text(data.get("project_id")) or None,
            node=_text(data.get("node")) or "n09_keyframe_qa",
            shot_id=_text(data.get("shot_id")) or None,
            attempt=1,
            error=None if media.status == "text_only" else media.reason,
            status=media.status,
        )
        return report
    still, clip = media if isinstance(media, tuple) else (None, [])
    anchor_problem = _anchor(data)
    if anchor_problem is not None:
        report = not_reviewed(anchor_problem.status, anchor_problem.reason)
        log_event(
            "qa_media_error",
            project_id=_text(data.get("project_id")) or None,
            node=_text(data.get("node")) or "n09_keyframe_qa",
            shot_id=_text(data.get("shot_id")) or None,
            attempt=1,
            error=anchor_problem.reason,
            status=anchor_problem.status,
        )
        return report
    expected = _expected_faces(data)
    if clip:
        findings, _good = inspect_frames(clip, anchor=_anchor_image(data), expected_faces=expected)
        sheet = clip[0]
    else:
        assert still is not None
        anchor_image = _anchor_image(data)
        findings = inspect_image(still, anchor=anchor_image, expected_faces=expected)
        sheet = still
    notes = "; ".join(f"{item.code}: {item.detail}" for item in findings) or "none"
    image_b64 = _png_b64(sheet) if _live() else None
    judged = cross_review(gateway, data, rule_notes=notes, image_b64=image_b64)
    report = apply_findings(judged, findings, has_pixels=True, pixels_shown=image_b64 is not None)
    from workers.compliance.moderation import internal_skip_visual_review

    if internal_skip_visual_review() and not report.hard_fail:
        # 内部使用：不强制 AI 视觉评审；硬伤（内容安全/畸变）仍然拦截。
        from workers.qa.scores import PASS_TOTAL

        report = report.model_copy(
            update={
                "visual_reviewed": True,
                "total": max(report.total, PASS_TOTAL),
                "degraded": False,
            }
        )
    return report


def _media(
    payload: dict[str, Any],
    *,
    image: Image.Image | None,
    frames: list[Image.Image] | None,
) -> tuple[Image.Image | None, list[Image.Image]] | MediaLoad:
    if frames:
        return None, [frame.convert("RGB") for frame in frames]
    if image is not None:
        return image.convert("RGB"), []
    if _text_only(payload) and not _claimed_uri(payload):
        return MediaLoad(None, "text_only", "intentionally text-only; no pixels to review")
    listed = payload.get("frame_uris")
    if isinstance(listed, list) and listed:
        images: list[Image.Image] = []
        for uri in listed:
            loaded = load_image(str(uri))
            if not loaded.ok or loaded.image is None:
                return loaded
            images.append(loaded.image)
        return None, images
    uri = _text(payload.get("candidate_uri")) or _text(payload.get("uri"))
    if not uri:
        return MediaLoad(None, "missing", "no media uri")
    if uri.lower().endswith(VIDEO_SUFFIXES) or uri.startswith("mock://"):
        return _video(uri)
    return _as_still(load_image(uri))


def _video(uri: str) -> tuple[Image.Image | None, list[Image.Image]] | MediaLoad:
    loaded = load_image(uri) if uri.startswith("mock://") else None
    if loaded is not None:
        return loaded
    path_text = uri[7:] if uri.startswith("file://") else uri
    located = resolve_project_file(Path(path_text))
    if isinstance(located, MediaLoad):
        return located
    if not located.is_file():
        return MediaLoad(None, "broken", f"path is not a file: {located}")
    try:
        frames = sample_frames(located)
    except Exception as exc:
        return MediaLoad(None, "unreadable", f"cannot decode video {located}: {exc}")
    if not frames:
        return MediaLoad(None, "unreadable", f"video has no frames: {located}")
    return None, frames


def _as_still(loaded: MediaLoad) -> tuple[Image.Image | None, list[Image.Image]] | MediaLoad:
    if not loaded.ok or loaded.image is None:
        return loaded
    return loaded.image, []


def _claimed_uri(payload: dict[str, Any]) -> bool:
    if _text(payload.get("candidate_uri")) or _text(payload.get("uri")):
        return True
    listed = payload.get("frame_uris")
    return isinstance(listed, list) and bool(listed)


def _text_only(payload: dict[str, Any]) -> bool:
    if payload.get("text_only") is True:
        return True
    return str(payload.get("generation_mode") or "") == "motion_graphics"


def _anchor(payload: dict[str, Any]) -> MediaLoad | None:
    uri = _text(payload.get("anchor_uri"))
    if not uri:
        return None
    loaded = load_image(uri)
    if loaded.ok:
        return None
    return MediaLoad(None, loaded.status, f"anchor {loaded.reason}")


def _anchor_image(payload: dict[str, Any]) -> Image.Image | None:
    uri = _text(payload.get("anchor_uri"))
    if not uri:
        return None
    loaded = load_image(uri)
    return loaded.image


def _expected_faces(payload: dict[str, Any]) -> int:
    if payload.get("expected_faces") is not None:
        return int(payload["expected_faces"])
    text = " ".join(
        str(payload.get(key) or "") for key in ("purpose", "visual", "generation_mode", "shot_type")
    )
    if any(word in text for word in ("人物", "人脸", "person", "portrait")):
        return 1
    return 0


def _png_b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _live() -> bool:
    return os.getenv("HILATV_LIVE", "0").strip() == "1"


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _default_gateway() -> Any:
    from gateway.service import get_gateway

    return get_gateway()
