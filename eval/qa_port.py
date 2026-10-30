"""Review port for T12.

T12 is expected to expose ``workers.qa.service.review_shot(payload) -> QAReport``.
Until that function exists, a shot is reviewed only when a keyframe or video
reference is passed through ``gateway.judge`` and the gateway returns a real
score. A mock schema fill (all zeros, ``evaluator=mock``) is not a review.
Storyboard text alone is not a score.
"""

from __future__ import annotations

import importlib
import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from workers.schemas.asset import QAReport

_DIMS = (
    "product_fidelity",
    "motion_quality",
    "aesthetics",
    "prompt_match",
    "artifact_free",
)

_ALIASES = {
    "产品变形": "产品变形",
    "文字乱码": "文字乱码",
    "人物崩坏": "人物崩坏",
    "穿帮": "穿帮",
    "product_deform": "产品变形",
    "garbled_text": "文字乱码",
    "extra_text": "文字乱码",
    "face_collapse": "人物崩坏",
    "continuity": "穿帮",
}

TEXT_ONLY_LABEL = "只评了文字，不计入质量结论"
UNREVIEWED_LABEL = "未评审"
_NOT_REVIEWED_FAILS = frozenset({"not_reviewed", "judge_unavailable", "unreviewed"})
_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v"})
_MIN_VIDEO_BYTES = 1024

_PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(_PROMPTS),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


class JudgeInvalid(ValueError):
    """The judge payload is missing a dimension or is not a real score."""


@dataclass(frozen=True)
class ShotReview:
    status: str
    source: str
    basis: str
    report: QAReport | None
    media_uri: str
    note: str


def t12_review_shot() -> Any | None:
    try:
        module = importlib.import_module("workers.qa.service")
    except ImportError:
        return None
    fn = getattr(module, "review_shot", None)
    if callable(fn):
        return fn
    return None


def review_port() -> str:
    return "t12" if t12_review_shot() is not None else "gateway-judge"


def review_shot(payload: dict[str, Any], *, gateway: Any) -> ShotReview:
    """Score one shot. ``payload`` is the T12 request, not free text.

    A score is kept only after a keyframe or video file exists and opens.
    T12 is not called otherwise: a storyboard-only 8.4 is not a review.
    """

    media_uri = readable_media(payload, gateway)
    if not media_uri:
        return ShotReview(
            status="not_reviewed",
            source="unreviewed",
            basis="text",
            report=None,
            media_uri="",
            note=TEXT_ONLY_LABEL,
        )
    fn = t12_review_shot()
    if fn is not None:
        try:
            raw_obj = fn(dict(payload))
            raw = _as_dict(raw_obj)
        except Exception as exc:
            return _review_error("t12", media_uri, exc)
        if raw is None:
            return _invalid("t12", media_uri, "review_shot did not return an object")
        if not _visually_reviewed(raw):
            return _not_reviewed("t12", media_uri, _refusal_note(raw))
        try:
            report = coerce_judge(raw)
        except JudgeInvalid as exc:
            return _invalid("t12", media_uri, str(exc))
        return ShotReview(
            status="reviewed",
            source="t12",
            basis="media",
            report=report,
            media_uri=media_uri,
            note=report.notes,
        )
    kind = "video" if str(payload.get("node") or "") == "n11_video" else "keyframe"
    prompt = _ENV.get_template("judge.j2").render(
        shot_id=payload.get("shot_id") or "",
        purpose=payload.get("purpose") or "",
        shot_size=payload.get("shot_size") or "",
        camera=payload.get("shot_type") or "",
        generation_mode=payload.get("generation_mode") or "",
        visual=payload.get("visual") or "",
        voiceover=payload.get("voiceover") or "",
        media_kind=kind,
        media_uri=media_uri,
    )
    try:
        raw = gateway.judge(
            prompt,
            schema=QAReport,
            project_id=payload.get("project_id"),
            node=str(payload.get("node") or "n09_keyframe"),
            shot_id=payload.get("shot_id"),
            shot_type=payload.get("shot_type") or None,
            attempt=1,
            params={"media_uri": media_uri, "media_kind": kind},
        )
    except Exception as exc:
        return _review_error("gateway-judge", media_uri, exc)
    if not isinstance(raw, dict) or _not_a_review(raw):
        return _not_reviewed(
            "unreviewed",
            media_uri,
            f"{UNREVIEWED_LABEL}：网关返回的是 mock 填表，没有真实视觉评审",
        )
    try:
        report = coerce_judge(raw)
    except JudgeInvalid as exc:
        return _invalid("gateway-judge", media_uri, str(exc))
    return ShotReview(
        status="reviewed",
        source="gateway-judge",
        basis="media",
        report=report,
        media_uri=media_uri,
        note=report.notes,
    )


def coerce_judge(raw: dict[str, Any]) -> QAReport:
    """Validate a judge payload. Missing dimensions are an error, not an 8."""

    if not isinstance(raw, dict) or not raw:
        raise JudgeInvalid("judge payload is empty")
    if _is_schema_fill(raw):
        raise JudgeInvalid("gateway mock schema fill is not a review")
    scores_raw = raw.get("scores")
    if not isinstance(scores_raw, dict):
        raise JudgeInvalid("judge payload is missing scores")
    missing = [name for name in _DIMS if name not in scores_raw]
    if missing:
        raise JudgeInvalid("judge payload is missing " + ", ".join(missing))
    scores = {name: _require_score(scores_raw[name], name) for name in _DIMS}
    hard_raw = raw.get("hard_fail")
    if hard_raw is None:
        hard_raw = []
    if not isinstance(hard_raw, list):
        raise JudgeInvalid("hard_fail must be a list")
    hard = [_ALIASES.get(str(item), str(item)) for item in hard_raw]
    total = raw.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        total = round(sum(scores.values()) / len(scores), 1)
    evaluator = raw.get("evaluator")
    if not isinstance(evaluator, str) or not evaluator.strip() or evaluator.strip() == "mock":
        raise JudgeInvalid("judge payload is missing a real evaluator")
    notes = raw.get("notes")
    if not isinstance(notes, str):
        raise JudgeInvalid("judge payload is missing notes")
    try:
        return QAReport.model_validate(
            {
                "scores": scores,
                "hard_fail": hard,
                "total": total,
                "evaluator": evaluator.strip(),
                "notes": notes,
            }
        )
    except ValidationError as exc:
        raise JudgeInvalid("judge payload is invalid") from exc


def readable_media(payload: dict[str, Any], gateway: Any) -> str:
    """First keyframe or video reference that exists and opens, else ``""``."""

    for uri in _media_uris(payload):
        if _opens(uri, gateway):
            return uri
    return ""


def _media_uris(payload: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key in ("candidate_uri", "uri"):
        text = str(payload.get(key) or "").strip()
        if text:
            found.append(text)
    frames = payload.get("frame_uris")
    if isinstance(frames, list):
        for item in frames:
            text = str(item or "").strip()
            if text:
                found.append(text)
    return found


def _opens(uri: str, gateway: Any) -> bool:
    if not uri or uri.startswith("mock://"):
        return False
    if uri.startswith("data:image"):
        return _image_opens(_data_image_bytes(uri))
    if uri.startswith(("oss://", "s3://")):
        return _bytes_open(uri, _store_bytes(gateway, uri))
    path = Path(uri[7:] if uri.startswith("file://") else uri)
    if not path.is_file():
        return False
    try:
        if path.suffix.lower() in _VIDEO_SUFFIXES:
            return _video_file_opens(path)
        data = path.read_bytes()
    except OSError:
        return False
    return _image_opens(data)


def _store_bytes(gateway: Any, uri: str) -> bytes | None:
    store = getattr(gateway, "store", None)
    getter = getattr(store, "get", None)
    if not callable(getter):
        return None
    try:
        data = getter(uri)
    except Exception:
        return None
    if isinstance(data, bytes) and data:
        return data
    return None


def _data_image_bytes(uri: str) -> bytes | None:
    import base64
    import binascii

    raw = uri.split(",", 1)[-1]
    try:
        return base64.b64decode(raw)
    except (binascii.Error, ValueError):
        return None


def _bytes_open(uri: str, data: bytes | None) -> bool:
    if not data:
        return False
    suffix = Path(uri.split("?", 1)[0]).suffix.lower()
    if suffix in _VIDEO_SUFFIXES or _is_isom(data[:32]):
        return _video_bytes_open(data, suffix or ".mp4")
    return _image_opens(data)


def _image_opens(data: bytes | None) -> bool:
    if not data:
        return False
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return False
    return True


def _video_file_opens(path: Path) -> bool:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(32)
    except OSError:
        return False
    if size < _MIN_VIDEO_BYTES or not _container_header(header, path.suffix.lower()):
        return False
    return _probe_opens(path)


def _video_bytes_open(data: bytes, suffix: str) -> bool:
    if len(data) < _MIN_VIDEO_BYTES or not _container_header(data[:32], suffix):
        return False
    ending = suffix if suffix in _VIDEO_SUFFIXES else ".mp4"
    fd, name = tempfile.mkstemp(suffix=ending)
    os_path = Path(name)
    try:
        os.write(fd, data)
        os.close(fd)
        fd = -1
        return _probe_opens(os_path)
    except OSError:
        return False
    finally:
        if fd >= 0:
            os.close(fd)
        os_path.unlink(missing_ok=True)


def _container_header(header: bytes, suffix: str) -> bool:
    if suffix in {".webm", ".mkv"}:
        return header.startswith(b"\x1a\x45\xdf\xa3")
    return _is_isom(header)


def _is_isom(header: bytes) -> bool:
    return len(header) >= 12 and header[4:8] == b"ftyp"


def _probe_opens(path: Path) -> bool:
    try:
        from workers.media.ffmpeg import probe

        info = probe(path)
    except Exception:
        return False
    return bool(info.get("width")) and bool(info.get("height"))


def _as_dict(raw: Any) -> dict[str, Any] | None:
    if hasattr(raw, "model_dump"):
        dumped = raw.model_dump(mode="json")
        if not isinstance(dumped, dict):
            return None
        if hasattr(raw, "visual_reviewed"):
            dumped["visual_reviewed"] = getattr(raw, "visual_reviewed")
        for flag in ("degraded", "mock"):
            if hasattr(raw, flag):
                dumped[flag] = getattr(raw, flag)
        return dumped
    if isinstance(raw, dict):
        return raw
    return None


def _visually_reviewed(raw: dict[str, Any]) -> bool:
    """True only for an explicit visual review. A missing field stays False."""

    return raw.get("visual_reviewed") is True


def _not_a_review(raw: dict[str, Any]) -> bool:
    if _is_schema_fill(raw):
        return True
    if raw.get("degraded") is True or raw.get("mock") is True:
        return True
    status = str(raw.get("status") or raw.get("review_status") or "").strip().lower()
    if status in {"not_reviewed", "unreviewed", "degraded", "mock", "judge_unavailable"}:
        return True
    evaluator = str(raw.get("evaluator") or "").strip().lower()
    if not evaluator or evaluator == "mock" or evaluator.startswith("mock"):
        return True
    return bool(_refusal_tokens(raw))


def _refusal_tokens(raw: dict[str, Any]) -> set[str]:
    hard = raw.get("hard_fail") or []
    if not isinstance(hard, list):
        return set()
    found: set[str] = set()
    for item in hard:
        token = str(item).strip().lower().replace("-", "_").replace(" ", "_")
        if token in _NOT_REVIEWED_FAILS:
            found.add(token)
    return found


def _refusal_note(raw: dict[str, Any]) -> str:
    tokens = sorted(_refusal_tokens(raw))
    if tokens:
        return f"{UNREVIEWED_LABEL}：{', '.join(tokens)}"
    if raw.get("degraded") is True or str(raw.get("evaluator") or "").lower().startswith("mock"):
        return f"{UNREVIEWED_LABEL}：评审模型是 mock 或已降级"
    return f"{UNREVIEWED_LABEL}：没有真实视觉评审"


def _not_reviewed(source: str, media_uri: str, note: str) -> ShotReview:
    return ShotReview(
        status="not_reviewed",
        source=source,
        basis="media" if media_uri else "text",
        report=None,
        media_uri=media_uri,
        note=note,
    )


def _review_error(source: str, media_uri: str, exc: Exception) -> ShotReview:
    detail = f"{type(exc).__name__}: {exc}"[:300]
    return ShotReview(
        status="review_error",
        source=source,
        basis="media" if media_uri else "none",
        report=None,
        media_uri=media_uri,
        note=f"review_error: {detail}",
    )


def _invalid(source: str, media_uri: str, note: str) -> ShotReview:
    return ShotReview(
        status="invalid",
        source=source,
        basis="media" if media_uri else "none",
        report=None,
        media_uri=media_uri,
        note=note,
    )


def _is_schema_fill(raw: dict[str, Any]) -> bool:
    scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    if not scores:
        return False
    zeros = all(_is_zero(scores.get(name)) for name in _DIMS)
    try:
        total = float(raw.get("total") or 0)
    except (TypeError, ValueError):
        total = 0.0
    return (
        raw.get("evaluator") == "mock"
        and raw.get("notes") == "mock"
        and not raw.get("hard_fail")
        and zeros
        and total == 0.0
    )


def _is_zero(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return float(value) == 0.0


def _require_score(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise JudgeInvalid(f"{name} is missing or not an integer")
    if value < 0 or value > 10:
        raise JudgeInvalid(f"{name} is outside 0-10")
    return value
