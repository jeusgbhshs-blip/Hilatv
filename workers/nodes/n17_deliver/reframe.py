"""Choose a crop or a contained frame so the subject never leaves the picture.

A 16:9 crop follows the subject center. When the box is wider than that window,
the whole master is fitted inside the new frame and the spare area is a blurred
plate, or a gateway image when vertical regeneration is requested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from workers.media.packaging import aspect_size
from workers.nodes.n17_deliver.schema import GeometryRecord, SubjectTrack


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def lerp(self, other: Rect, alpha: float) -> Rect:
        blend = min(1.0, max(0.0, alpha))
        return Rect(
            self.x + (other.x - self.x) * blend,
            self.y + (other.y - self.y) * blend,
            self.w + (other.w - self.w) * blend,
            self.h + (other.h - self.h) * blend,
        )

    def inside(self, width: float, height: float, eps: float = 1.0) -> bool:
        return (
            self.w > 1
            and self.h > 1
            and self.x >= -eps
            and self.y >= -eps
            and self.x + self.w <= width + eps
            and self.y + self.h <= height + eps
        )

    def as_list(self) -> list[float]:
        return [round(self.x, 3), round(self.y, 3), round(self.w, 3), round(self.h, 3)]


@dataclass(frozen=True)
class ShotGeometry:
    shot_id: str
    mode: str
    src_w: int
    src_h: int
    out_w: int
    out_h: int
    crop_w: int
    crop_h: int
    subject0: Rect
    subject1: Rect
    start_s: float
    duration_s: float
    motion_s: float

    def subject_at(self, local_t: float) -> Rect:
        span = self.motion_s if self.motion_s > 0 else self.duration_s
        if span <= 0:
            return self.subject0
        return self.subject0.lerp(self.subject1, local_t / span)

    def output_subject(self, local_t: float) -> Rect:
        subject = self.subject_at(local_t)
        if self.mode == "crop":
            origin_x, origin_y = crop_origin(
                subject, self.crop_w, self.crop_h, self.src_w, self.src_h
            )
            scale_x = self.out_w / self.crop_w
            scale_y = self.out_h / self.crop_h
            return Rect(
                (subject.x - origin_x) * scale_x,
                (subject.y - origin_y) * scale_y,
                subject.w * scale_x,
                subject.h * scale_y,
            )
        return contain_map(subject, self.src_w, self.src_h, self.out_w, self.out_h)

    def contains(self, local_t: float) -> bool:
        return self.output_subject(local_t).inside(self.out_w, self.out_h)

    def record(self) -> GeometryRecord:
        return GeometryRecord(
            shot_id=self.shot_id,
            mode=self.mode,
            src_w=self.src_w,
            src_h=self.src_h,
            out_w=self.out_w,
            out_h=self.out_h,
            crop_w=self.crop_w,
            crop_h=self.crop_h,
            subject0=self.subject0.as_list(),
            subject1=self.subject1.as_list(),
            start_s=round(self.start_s, 3),
            duration_s=round(self.duration_s, 3),
            motion_s=round(self.motion_s, 3),
        )


def output_size(aspect: str, long_edge: int) -> tuple[int, int]:
    """Even frame whose long side is ``long_edge`` and whose ratio is ``aspect``."""

    return aspect_size(aspect, long_edge)


def track_pixels(track: SubjectTrack, src_w: int, src_h: int) -> tuple[Rect, Rect]:
    """Integer box shared by the marked plate and the reframe plan."""

    width = max(2, int(round(track.w * src_w)))
    height = max(2, int(round(track.h * src_h)))
    start = _placed(track.x, track.y, width, height, src_w, src_h)
    end_x = track.x if track.x_end is None else track.x_end
    end_y = track.y if track.y_end is None else track.y_end
    end = _placed(end_x, end_y, width, height, src_w, src_h)
    return start, end


def plan_shot(
    *,
    shot_id: str,
    track: SubjectTrack,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    start_s: float,
    duration_s: float,
    motion_s: float,
    regenerate: bool,
) -> ShotGeometry:
    subject0, subject1 = track_pixels(track, src_w, src_h)
    crop_w, crop_h = crop_size(src_w, src_h, out_w, out_h)
    probe = ShotGeometry(
        shot_id=shot_id,
        mode="crop",
        src_w=src_w,
        src_h=src_h,
        out_w=out_w,
        out_h=out_h,
        crop_w=crop_w,
        crop_h=crop_h,
        subject0=subject0,
        subject1=subject1,
        start_s=start_s,
        duration_s=duration_s,
        motion_s=motion_s,
    )
    fits = all(_fits_crop(probe, local) for local in _sample_times(duration_s))
    if fits:
        mode = "crop"
    elif regenerate and out_h > out_w:
        mode = "regenerate"
    else:
        mode = "blur" if not fits else "crop"
    return ShotGeometry(
        shot_id=shot_id,
        mode=mode,
        src_w=src_w,
        src_h=src_h,
        out_w=out_w,
        out_h=out_h,
        crop_w=crop_w,
        crop_h=crop_h,
        subject0=subject0,
        subject1=subject1,
        start_s=start_s,
        duration_s=duration_s,
        motion_s=motion_s,
    )


def geometry_from_record(record: GeometryRecord) -> ShotGeometry:
    return ShotGeometry(
        shot_id=record.shot_id,
        mode=record.mode,
        src_w=record.src_w,
        src_h=record.src_h,
        out_w=record.out_w,
        out_h=record.out_h,
        crop_w=record.crop_w,
        crop_h=record.crop_h,
        subject0=_rect(record.subject0),
        subject1=_rect(record.subject1),
        start_s=record.start_s,
        duration_s=record.duration_s,
        motion_s=record.motion_s,
    )


def crop_size(src_w: int, src_h: int, out_w: int, out_h: int) -> tuple[int, int]:
    """Largest even window inside the master with the output's aspect."""

    if src_w / src_h >= out_w / out_h:
        height = src_h - (src_h % 2)
        width = int(round(height * out_w / out_h))
    else:
        width = src_w - (src_w % 2)
        height = int(round(width * out_h / out_w))
    if width % 2:
        width -= 1
    if height % 2:
        height -= 1
    width = max(2, min(width, src_w - (src_w % 2)))
    height = max(2, min(height, src_h - (src_h % 2)))
    return width, height


def crop_origin(subject: Rect, crop_w: int, crop_h: int, src_w: int, src_h: int) -> tuple[int, int]:
    """Window that prefers the subject center and still contains the whole box."""

    limit_x = src_w - crop_w
    limit_y = src_h - crop_h
    x = subject.x + subject.w / 2 - crop_w / 2
    y = subject.y + subject.h / 2 - crop_h / 2
    x = min(max(0.0, x), limit_x)
    y = min(max(0.0, y), limit_y)
    if subject.x < x:
        x = subject.x
    if subject.y < y:
        y = subject.y
    if subject.x + subject.w > x + crop_w:
        x = subject.x + subject.w - crop_w
    if subject.y + subject.h > y + crop_h:
        y = subject.y + subject.h - crop_h
    x = min(max(0.0, x), limit_x)
    y = min(max(0.0, y), limit_y)
    return math.floor(x + 1e-6), math.floor(y + 1e-6)


def contain_map(subject: Rect, src_w: int, src_h: int, out_w: int, out_h: int) -> Rect:
    """Where the box lands when the whole master is fitted inside the frame."""

    scale = min(out_w / src_w, out_h / src_h)
    fitted_w = src_w * scale
    fitted_h = src_h * scale
    offset_x = (out_w - fitted_w) / 2
    offset_y = (out_h - fitted_h) / 2
    return Rect(
        offset_x + subject.x * scale,
        offset_y + subject.y * scale,
        subject.w * scale,
        subject.h * scale,
    )


def _fits_crop(geo: ShotGeometry, local_t: float) -> bool:
    subject = geo.subject_at(local_t)
    if subject.w > geo.crop_w + 0.5 or subject.h > geo.crop_h + 0.5:
        return False
    origin_x, origin_y = crop_origin(subject, geo.crop_w, geo.crop_h, geo.src_w, geo.src_h)
    return (
        subject.x >= origin_x - 0.5
        and subject.y >= origin_y - 0.5
        and subject.x + subject.w <= origin_x + geo.crop_w + 0.5
        and subject.y + subject.h <= origin_y + geo.crop_h + 0.5
    )


def _sample_times(duration_s: float) -> tuple[float, ...]:
    if duration_s <= 0:
        return (0.0,)
    return (0.0, duration_s * 0.5, max(0.0, duration_s - 1e-3))


def _placed(
    x_ratio: float,
    y_ratio: float,
    width: int,
    height: int,
    src_w: int,
    src_h: int,
) -> Rect:
    x = int(round(x_ratio * src_w))
    y = int(round(y_ratio * src_h))
    x = min(max(0, x), max(0, src_w - width))
    y = min(max(0, y), max(0, src_h - height))
    return Rect(float(x), float(y), float(width), float(height))


def _rect(values: list[float]) -> Rect:
    return Rect(values[0], values[1], values[2], values[3])
