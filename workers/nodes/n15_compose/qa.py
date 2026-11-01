"""Quality check for N15. The master must be H.264 at 30 fps and replayable."""

from __future__ import annotations

from pathlib import Path

from workers.media.ffmpeg import playable, probe
from workers.media.packaging import FPS
from workers.nodes.n15_compose.graph import filter_complex
from workers.nodes.n15_compose.schema import NodeResult, Timeline
from workers.schemas.asset import Asset, AssetKind


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> Timeline:
    if result.node != "n15_compose":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n15_compose result is not ok")
    timeline = Timeline.model_validate(result.payload.get("timeline"))
    exports = result.payload.get("exports") or {}
    filters = result.payload.get("filters") or {}
    for name in ("master", "nosub", "novo"):
        path = Path(str(exports.get(name) or ""))
        if not path.is_file():
            raise QAError(f"missing {name} export")
        info = probe(path)
        if info["codec"] != "h264":
            raise QAError(f"{name} codec is {info['codec']}")
        if abs(float(info["fps"]) - FPS) > 0.05:
            raise QAError(f"{name} fps is {info['fps']}")
        if int(info["width"]) != timeline.width or int(info["height"]) != timeline.height:
            raise QAError(f"{name} frame size does not match the timeline")
        playable(path)
        graph = filter_complex(timeline, name)
        if filters.get(name) != graph:
            raise QAError(f"{name} filter graph does not match the timeline")
        if graph.count("lut3d=") != len(timeline.clips):
            raise QAError("each shot must use the same LUT")
        if "colorchannelmixer=" not in graph or "eq=brightness=0.02" not in graph:
            raise QAError("the grade is missing")
    master = probe(Path(exports["master"]))
    novo = probe(Path(exports["novo"]))
    if not master["audio_codecs"]:
        raise QAError("master export has no audio")
    if novo["audio_codecs"]:
        raise QAError("the no-voiceover export still has audio")
    nosub = str(filters["nosub"])
    burned = [item for item in timeline.overlays if item.kind == "subtitle" and item.path in nosub]
    if burned:
        raise QAError("no-subtitle export still burns subtitles")
    kinds = {item.kind for item in timeline.overlays}
    preview_without_logo = timeline.logo_status in {"missing", "mock"}
    if (not preview_without_logo and "outro_logo" not in kinds) or "outro_cta" not in kinds:
        raise QAError("the ending overlay is missing a logo or a CTA")
    if preview_without_logo and any("logo" in kind for kind in kinds):
        raise QAError("missing/simulated branding cannot use a replacement logo")
    if not any(item.kind is AssetKind.deliverable for item in _assets(result)):
        raise QAError("deliverable asset is missing")
    _check_soundtrack(result, timeline)
    hard_cut = all(clip.transition_out.lower() in {"", "cut"} for clip in timeline.clips[:-1])
    if hard_cut and "xfade=" in filters["master"]:
        raise QAError("default transition must be a hard cut")
    return timeline


def _check_soundtrack(result: NodeResult, timeline: Timeline) -> None:
    raw = result.payload.get("audio_track")
    if not raw:
        return
    source = str(raw.get("source") or "").strip()
    license_name = str(raw.get("license") or "").strip()
    if not source or not license_name:
        raise QAError("audio track is missing a source or a license")
    path = str(raw.get("path") or "")
    if path not in {clip.path for clip in timeline.audio}:
        raise QAError("audio track was not placed on the timeline")
    for item in result.payload.get("licenses") or []:
        if not isinstance(item, dict):
            raise QAError("license record is not an object")
        if not str(item.get("source") or "").strip() or not str(item.get("license") or "").strip():
            raise QAError("a music or sound-effect license record is incomplete")


def _assets(result: NodeResult) -> list[Asset]:
    return [Asset.model_validate(item) for item in result.payload.get("assets") or []]
