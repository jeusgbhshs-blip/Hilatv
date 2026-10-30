"""The reframe graph is code, and it does not draw words."""

from __future__ import annotations

from workers.nodes.n17_deliver.graph import reframe_graph
from workers.nodes.n17_deliver.reframe import plan_shot
from workers.nodes.n17_deliver.schema import SubjectTrack


def _geo(mode_wide: bool, regenerate: bool = False):
    track = (
        SubjectTrack(shot_id="S02", x=0.06, y=0.32, w=0.84, h=0.28)
        if mode_wide
        else SubjectTrack(shot_id="S01", x=0.2, y=0.3, w=0.16, h=0.3)
    )
    return plan_shot(
        shot_id=track.shot_id,
        track=track,
        src_w=320,
        src_h=180,
        out_w=180,
        out_h=320,
        start_s=0.0,
        duration_s=1.0,
        motion_s=1.0,
        regenerate=regenerate,
    )


def test_crop_and_blur_graphs_have_no_drawtext() -> None:
    crop = reframe_graph([_geo(False)], {})
    blur = reframe_graph([_geo(True)], {})
    assert "crop=" in crop
    assert "gblur" in blur
    assert "drawtext" not in crop
    assert "drawtext" not in blur
    assert "subtitles=" not in blur


def test_regenerate_graph_uses_the_plate_input() -> None:
    graph = reframe_graph([_geo(True, True)], {"S02": 1})
    assert "[1:v]" in graph
    assert "drawtext" not in graph
