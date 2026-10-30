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

from workers.qa.frames import sample_frames
from workers.qa.pixels import open_image
from workers.qa.rules import Finding, inspect_frames, inspect_image
from workers.qa.scores import apply_findings
from workers.qa.vlm import cross_review
from workers.schemas.asset import QAReport


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
    data = dict(payload)
    gateway = gateway if gateway is not None else _default_gateway()
    loaded, clip = _load(data, image=image, frames=frames)
    anchor = open_image(_text(data.get("anchor_uri")))
    expected = _expected_faces(data)
    findings: list[Finding] = []
    has_pixels = loaded is not None or bool(clip)
    if clip:
        findings, _good = inspect_frames(clip, anchor=anchor, expected_faces=expected)
    elif loaded is not None:
        findings = inspect_image(loaded, anchor=anchor, expected_faces=expected)
    notes = "; ".join(f"{item.code}: {item.detail}" for item in findings) or "none"
    sheet = loaded if loaded is not None else (clip[0] if clip else None)
    image_b64 = _png_b64(sheet) if sheet is not None and _live() else None
    opinion = cross_review(gateway, data, rule_notes=notes, image_b64=image_b64)
    return apply_findings(opinion, findings, has_pixels=has_pixels)


def _load(
    payload: dict[str, Any],
    *,
    image: Image.Image | None,
    frames: list[Image.Image] | None,
) -> tuple[Image.Image | None, list[Image.Image]]:
    if frames:
        return None, [frame.convert("RGB") for frame in frames]
    if image is not None:
        return image.convert("RGB"), []
    listed: list[Image.Image] = []
    for uri in payload.get("frame_uris") or []:
        opened = open_image(str(uri))
        if opened is not None:
            listed.append(opened)
    if listed:
        return None, listed
    uri = _text(payload.get("candidate_uri")) or _text(payload.get("uri")) or ""
    if uri.lower().endswith((".mp4", ".mov", ".webm")):
        path = uri[7:] if uri.startswith("file://") else uri
        return None, sample_frames(Path(path))
    return open_image(uri), []


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
