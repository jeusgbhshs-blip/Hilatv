"""Crop follows a narrow subject. A wide subject is fitted instead of clipped."""

from __future__ import annotations

from workers.nodes.n17_deliver.reframe import contain_map, output_size, plan_shot
from workers.nodes.n17_deliver.schema import SubjectTrack


def test_narrow_subject_is_cropped_inside_every_aspect() -> None:
    track = SubjectTrack(shot_id="S01", x=0.12, y=0.28, w=0.16, h=0.38, x_end=0.52, y_end=0.30)
    for aspect in ("16:9", "9:16", "1:1"):
        out_w, out_h = output_size(aspect, 320)
        geo = plan_shot(
            shot_id="S01",
            track=track,
            src_w=320,
            src_h=180,
            out_w=out_w,
            out_h=out_h,
            start_s=0,
            duration_s=1,
            motion_s=1,
            regenerate=False,
        )
        assert geo.mode == "crop"
        for local in (0.0, 0.25, 0.5, 0.9):
            assert geo.contains(local)


def test_wide_subject_uses_blur_and_stays_inside() -> None:
    track = SubjectTrack(shot_id="S02", x=0.06, y=0.32, w=0.84, h=0.28)
    tall = plan_shot(
        shot_id="S02",
        track=track,
        src_w=320,
        src_h=180,
        out_w=180,
        out_h=320,
        start_s=0,
        duration_s=1,
        motion_s=1,
        regenerate=False,
    )
    square = plan_shot(
        shot_id="S02",
        track=track,
        src_w=320,
        src_h=180,
        out_w=320,
        out_h=320,
        start_s=0,
        duration_s=1,
        motion_s=1,
        regenerate=False,
    )
    wide = plan_shot(
        shot_id="S02",
        track=track,
        src_w=320,
        src_h=180,
        out_w=320,
        out_h=180,
        start_s=0,
        duration_s=1,
        motion_s=1,
        regenerate=False,
    )
    assert tall.mode == "blur"
    assert square.mode == "blur"
    assert wide.mode == "crop"
    assert tall.contains(0.2)
    assert square.contains(0.2)
    mapped = contain_map(tall.subject0, 320, 180, 180, 320)
    assert mapped.inside(180, 320)


def test_vertical_regeneration_is_optional() -> None:
    track = SubjectTrack(shot_id="S02", x=0.06, y=0.32, w=0.84, h=0.28)
    geo = plan_shot(
        shot_id="S02",
        track=track,
        src_w=320,
        src_h=180,
        out_w=180,
        out_h=320,
        start_s=0,
        duration_s=1,
        motion_s=1,
        regenerate=True,
    )
    assert geo.mode == "regenerate"
    assert geo.contains(0.0)
