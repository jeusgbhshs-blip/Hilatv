"""N17 checks: subject inside the frame, safe-area type, language matches the dub."""

from __future__ import annotations

from pathlib import Path

from workers.media.ffmpeg import playable, probe
from workers.media.packaging import FPS, ai_label_text
from workers.nodes.n17_deliver.detect import boxes_match, read_rgb, subject_bbox
from workers.nodes.n17_deliver.reframe import Rect, geometry_from_record, plan_shot, track_pixels
from workers.nodes.n17_deliver.schema import (
    DeliveryVersion,
    NodeResult,
    OverlayBox,
    SubjectTrack,
    TrackSource,
)
from workers.qa.copycheck import language_family
from workers.schemas.asset import Asset, AssetKind


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> list[DeliveryVersion]:
    if result.node != "n17_deliver":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n17_deliver result is not ok")
    raw_versions = result.payload.get("versions") or []
    versions = [DeliveryVersion.model_validate(item) for item in raw_versions]
    if not versions:
        raise QAError("n17_deliver produced no versions")
    assets = [Asset.model_validate(item) for item in result.payload.get("assets") or []]
    if not any(item.kind is AssetKind.deliverable for item in assets):
        raise QAError("deliverable asset is missing")
    seen: set[str] = set()
    for version in versions:
        _version(version, seen)
    return versions


def _version(version: DeliveryVersion, seen_pictures: set[str]) -> None:
    for graph in (version.filters, version.burn_filters):
        if "drawtext" in graph or "subtitles=" in graph:
            raise QAError(f"{version.version_id} draws text inside the filter graph")
    path = Path(version.path)
    if not path.is_file():
        raise QAError(f"missing export {path}")
    info = probe(path)
    if info["codec"] != "h264":
        raise QAError(f"{version.aspect_ratio} codec is {info['codec']}")
    if int(info["width"]) != version.width or int(info["height"]) != version.height:
        raise QAError(f"{version.aspect_ratio} frame size does not match")
    if abs(float(info["fps"]) - FPS) > 0.2:
        raise QAError(f"{version.aspect_ratio} fps is {info['fps']}")
    if (
        version.target_duration_s is not None
        and abs(float(info["duration_s"]) - version.target_duration_s) > 1 / FPS + 0.001
    ):
        raise QAError("export does not match its explicit total duration")
    if not info["audio_codecs"]:
        raise QAError(f"{version.language} export has no audio")
    playable(path)
    _language(version)
    _safe(version)
    _label(version)
    _geometry(version)
    if version.subject_box_source == "provided" and version.picture_path not in seen_pictures:
        _pixels(version)
        seen_pictures.add(version.picture_path)


def _language(version: DeliveryVersion) -> None:
    """Subtitles must match the version language.

    A live ASR transcript is an independent hearing and must match the subtitle.
    Mock ASR repeats the reference line, so that path is not a hearing.
    """

    family = language_family(version.language)
    if not version.spoken:
        raise QAError(f"{version.language} export has no spoken lines")
    for line in version.spoken:
        _expect_language(family, line.subtitle, f"{line.shot_id} subtitles")
        if line.heard_check == "not_verified_in_mock":
            continue
        if line.heard_check != "verified":
            raise QAError(f"{line.shot_id} hearing was not checked")
        if not line.transcript.strip():
            raise QAError(f"{line.shot_id} has no heard transcript")
        if _compact(line.subtitle) != _compact(line.transcript):
            raise QAError(f"{line.shot_id} subtitles do not match the heard dub")
        _expect_language(family, line.transcript, f"{line.shot_id} heard dub")
    heard = [line.transcript for line in version.spoken if line.heard_check == "verified"]
    if heard and family != "zh" and all(_cjk(text) and not _latin(text) for text in heard):
        raise QAError(f"{version.language} dub is still Chinese")


def _expect_language(family: str, text: str, label: str) -> None:
    if family == "zh" and not _cjk(text):
        raise QAError(f"{label} has no Chinese")
    if family != "zh" and not _latin(text):
        raise QAError(f"{label} has no Latin text")


def _label(version: DeliveryVersion) -> None:
    text = ai_label_text()
    marks = [box for box in version.overlays if box.kind == "ai_label" and box.text == text]
    if not marks:
        raise QAError(f"{version.aspect_ratio} {version.language} is missing {text}")


def _safe(version: DeliveryVersion) -> None:
    insets = version.safe
    for box in version.overlays:
        if not _inside_safe(box, version.width, version.height, insets):
            raise QAError(f"{box.kind} leaves the safe area on {version.aspect_ratio}")


def _geometry(version: DeliveryVersion) -> None:
    if not version.geometry:
        raise QAError("reframe geometry is missing")
    supplied = {item.shot_id: item for item in version.tracks}
    if version.subject_box_source == "default":
        if version.qa_status != "needs_review":
            raise QAError("a missing subject box was reported as a pass")
        missing = {item.shot_id for item in version.tracks if not item.provided}
        if not version.tracks:
            missing = set(version.modes)
        cropped = [shot_id for shot_id in missing if version.modes.get(shot_id) != "blur"]
        if cropped:
            raise QAError("a shot without a subject box was cropped")
        return
    if version.qa_status != "pass":
        raise QAError("a measured subject box was not marked as checked")
    if not version.tracks or any(not item.provided for item in version.tracks):
        raise QAError("measured subject boxes are missing")
    for record in version.geometry:
        source = supplied.get(record.shot_id)
        if source is None or not source.provided:
            raise QAError(f"{record.shot_id} geometry has no supplied box")
        track = _as_track(source)
        measured = track_pixels(track, record.src_w, record.src_h)
        stored = Rect(
            record.subject0[0], record.subject0[1], record.subject0[2], record.subject0[3]
        )
        if not _near(stored, measured[0]):
            raise QAError(f"{record.shot_id} geometry does not use the supplied box")
        planned = plan_shot(
            shot_id=track.shot_id,
            track=track,
            src_w=record.src_w,
            src_h=record.src_h,
            out_w=record.out_w,
            out_h=record.out_h,
            start_s=record.start_s,
            duration_s=record.duration_s,
            motion_s=record.motion_s,
            regenerate=record.mode == "regenerate",
        )
        if planned.mode != record.mode and record.mode != "blur":
            raise QAError(f"{record.shot_id} crop does not match the supplied box")
        geo = geometry_from_record(record)
        for local in (0.0, geo.duration_s * 0.5, max(0.0, geo.duration_s - 0.04)):
            if not planned.contains(local):
                raise QAError(f"{record.shot_id} subject leaves the {version.aspect_ratio} frame")


def _as_track(source: TrackSource) -> SubjectTrack:
    return SubjectTrack(
        shot_id=source.shot_id,
        x=float(source.x or 0),
        y=float(source.y or 0),
        w=float(source.w or 0.01),
        h=float(source.h or 0.01),
        x_end=source.x_end,
        y_end=source.y_end,
    )


def _near(left: Rect, right: Rect) -> bool:
    return (
        abs(left.x - right.x) <= 1.5
        and abs(left.y - right.y) <= 1.5
        and abs(left.w - right.w) <= 1.5
        and abs(left.h - right.h) <= 1.5
    )


def _pixels(version: DeliveryVersion) -> None:
    picture = Path(version.picture_path)
    if not picture.is_file():
        picture = Path(version.path)
    width, height, frames = read_rgb(picture)
    if width != version.width or height != version.height:
        raise QAError("picture size does not match the version")
    geometries = [geometry_from_record(item) for item in version.geometry]
    offset = 0.0
    spans: list[tuple[float, float, object]] = []
    for geo in geometries:
        spans.append((offset, offset + geo.duration_s, geo))
        offset += geo.duration_s
    misses: list[str] = []
    for index, frame in enumerate(frames):
        timestamp = index / FPS
        if timestamp >= offset - (0.5 / FPS):
            break
        geo = None
        local = 0.0
        for start, end, item in spans:
            if start <= timestamp < end:
                geo = item
                local = timestamp - start
                break
        if geo is None:
            continue
        margin = 2 / FPS
        if local < margin or local > geo.duration_s - margin:
            continue
        expected = geo.output_subject(local)
        detected = subject_bbox(frame, width, height)
        if not boxes_match(detected, expected):
            misses.append(
                f"t={timestamp:.3f} {geo.shot_id} {geo.mode} expected "
                f"{expected.as_list()} got {detected}"
            )
            if len(misses) >= 3:
                break
    if misses:
        raise QAError("subject leaves the frame: " + "; ".join(misses))


def _inside_safe(box: OverlayBox, width: int, height: int, insets: dict[str, float]) -> bool:
    left = insets["left"] * width
    top = insets["top"] * height
    right = width - insets["right"] * width
    bottom = height - insets["bottom"] * height
    eps = 2
    return (
        box.x >= left - eps
        and box.y >= top - eps
        and box.x + box.w <= right + eps
        and box.y + box.h <= bottom + eps
    )


def _compact(text: str) -> str:
    return "".join(char for char in text if not char.isspace())


def _cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _latin(text: str) -> bool:
    return any("a" <= char.lower() <= "z" for char in text)
