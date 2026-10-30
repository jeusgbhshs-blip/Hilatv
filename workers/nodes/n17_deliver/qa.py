"""N17 checks: subject inside the frame, safe-area type, language matches the dub."""

from __future__ import annotations

from pathlib import Path

from workers.media.ffmpeg import playable, probe
from workers.media.packaging import FPS
from workers.nodes.n17_deliver.detect import boxes_match, read_rgb, subject_bbox
from workers.nodes.n17_deliver.reframe import geometry_from_record
from workers.nodes.n17_deliver.schema import DeliveryVersion, NodeResult, OverlayBox
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
    verify_pixels = bool(result.payload.get("verify_pixels"))
    for version in versions:
        _version(version, seen, verify_pixels=verify_pixels)
    return versions


def _version(version: DeliveryVersion, seen_pictures: set[str], *, verify_pixels: bool) -> None:
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
    if not info["audio_codecs"]:
        raise QAError(f"{version.language} export has no audio")
    playable(path)
    _language(version)
    _safe(version)
    _geometry(version)
    if verify_pixels and version.picture_path not in seen_pictures:
        _pixels(version)
        seen_pictures.add(version.picture_path)


def _language(version: DeliveryVersion) -> None:
    family = language_family(version.language)
    if not version.spoken:
        raise QAError(f"{version.language} export has no spoken lines")
    for line in version.spoken:
        if _compact(line.subtitle) != _compact(line.voiceover):
            raise QAError(f"{line.shot_id} subtitles do not match the {version.language} dub")
        if family == "zh" and not _cjk(line.voiceover):
            raise QAError(f"{line.shot_id} Chinese dub has no Chinese")
        if family != "zh" and not _latin(line.voiceover):
            raise QAError(f"{line.shot_id} {version.language} dub has no Latin text")
    texts = {line.voiceover for line in version.spoken}
    if family != "zh" and all(_cjk(text) and not _latin(text) for text in texts):
        raise QAError(f"{version.language} dub is still Chinese")


def _safe(version: DeliveryVersion) -> None:
    insets = version.safe
    for box in version.overlays:
        if not _inside_safe(box, version.width, version.height, insets):
            raise QAError(f"{box.kind} leaves the safe area on {version.aspect_ratio}")


def _geometry(version: DeliveryVersion) -> None:
    if not version.geometry:
        raise QAError("reframe geometry is missing")
    for record in version.geometry:
        geo = geometry_from_record(record)
        for local in (0.0, geo.duration_s * 0.5, max(0.0, geo.duration_s - 0.04)):
            if not geo.contains(local):
                raise QAError(f"{geo.shot_id} subject leaves the {version.aspect_ratio} frame")


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
