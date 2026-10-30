"""Filter graph: one LUT, hard cuts, and a dissolve when a shot asks for one."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from workers.media.ffmpeg import encode_plate, probe
from workers.media.packaging import lut_path
from workers.nodes.n15_compose.graph import filter_complex
from workers.nodes.n15_compose.node import render_timeline
from workers.nodes.n15_compose.schema import OverlayItem, Timeline, VideoClip


def _timeline(transitions: list[str]) -> Timeline:
    clips = []
    cursor = 0.0
    for index, transition in enumerate(transitions):
        clips.append(
            VideoClip(
                clip_id=f"c{index}",
                path=f"/tmp/c{index}.mp4",
                duration_s=1.0,
                start_s=cursor,
                transition_out=transition,
                grade_rr=1.0 if index == 0 else 0.8,
                grade_gg=1.0,
                grade_bb=1.0,
            )
        )
        cursor += 1.0
    return Timeline(
        width=320,
        height=180,
        fps=30,
        lut_path="/tmp/unified.cube",
        duration_s=cursor,
        clips=clips,
        audio=[],
        overlays=[],
        work_dir="/tmp",
    )


def test_hard_cuts_share_one_lut_and_do_not_dissolve() -> None:
    graph = filter_complex(_timeline(["cut", "cut"]), "master")
    assert graph.count("lut3d=") == 2
    assert "xfade=" not in graph
    assert "concat=n=2" in graph
    assert "eq=brightness=0.02" in graph
    assert "colorchannelmixer=rr=0.8000" in graph


def test_dissolve_uses_xfade() -> None:
    graph = filter_complex(_timeline(["dissolve", "cut"]), "nosub")
    assert "xfade=transition=fade" in graph


def test_no_voiceover_variant_has_no_audio_mix() -> None:
    graph = filter_complex(_timeline(["cut"]), "novo")
    assert "amix=" not in graph
    assert "[vout]" in graph


def test_logo_motions_encode(tmp_path: Path) -> None:
    plate = tmp_path / "plate.mp4"
    encode_plate(plate, rgb=(20, 30, 50), width=320, height=180, frames=15, fps=30)
    logo = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    ImageDraw.Draw(logo).ellipse((4, 4, 44, 44), fill=(255, 255, 255, 255))
    logo_path = tmp_path / "logo.png"
    logo.save(logo_path)
    for animate in ("fade", "rise", "scale"):
        timeline = Timeline(
            width=320,
            height=180,
            fps=30,
            lut_path=str(lut_path()),
            duration_s=0.5,
            clips=[
                VideoClip(
                    clip_id="a",
                    path=str(plate),
                    duration_s=0.5,
                    start_s=0,
                    transition_out="cut",
                )
            ],
            audio=[],
            overlays=[
                OverlayItem(
                    kind="intro_logo",
                    path=str(logo_path),
                    start_s=0,
                    end_s=0.5,
                    anchor="center",
                    y_ratio=0.5,
                    animate=animate,
                )
            ],
            work_dir=str(tmp_path),
        )
        dest = tmp_path / f"{animate}.mp4"
        render_timeline(timeline, dest, variant="novo")
        info = probe(dest)
        assert info["codec"] == "h264"
        assert abs(float(info["fps"]) - 30) < 0.05
