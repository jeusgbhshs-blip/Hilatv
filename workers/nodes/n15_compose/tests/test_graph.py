"""Filter graph: one LUT, hard cuts, and a dissolve when a shot asks for one."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from workers.media.ffmpeg import encode_plate, probe
from workers.media.packaging import lut_path
from workers.nodes.n15_compose.graph import filter_complex
from workers.nodes.n15_compose.node import _overlays, render_timeline, run
from workers.nodes.n15_compose.qa import QAError
from workers.nodes.n15_compose.schema import N15Input, OverlayItem, Timeline, VideoClip


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


def test_a_removed_ai_label_is_rejected_and_drawn_back(tmp_path: Path) -> None:
    script = {
        "script_id": "script-1",
        "brief_id": "brief-1",
        "language": "zh",
        "sections": [],
        "shots": [
            {
                "shot_id": "S01",
                "order": 1,
                "duration_s": 2,
                "purpose": "卖点",
                "visual": "泵体特写，没有文字",
                "shot_size": "close_up",
                "camera": "locked_off",
                "subject_refs": ["product:HP-300"],
                "scene_ref": "scene:workshop",
                "voiceover": "按资料说明。",
                "on_screen_text": [],
                "transition_out": "cut",
                "generation_mode": "image_to_video",
                "status": "pending",
            }
        ],
    }
    with pytest.raises(QAError, match="固定层"):
        run(
            {
                "project_id": "n15-lock",
                "payload": {
                    "script": script,
                    "elements": [],
                    "width": 320,
                    "height": 180,
                    "work_dir": str(tmp_path / "rejected"),
                    "instruction": "去掉 AI 标识",
                },
            }
        )
    payload = N15Input.model_validate(
        {"script": script, "elements": [], "width": 320, "height": 180}
    )
    items = _overlays(payload, tmp_path / "kept", 320, 180, 0)
    labels = [item for item in items if item.kind == "ai_label"]
    assert len(labels) == 1
    assert labels[0].text == "AI生成"
    assert labels[0].start_s == 0
    assert Path(labels[0].path).is_file()
