"""N11 frame sampling, a half-second warp, and a splice across two clips."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from workers.qa.frames import sample_frames, write_mp4
from workers.qa.rules import inspect_frames
from workers.qa.samples import _plate
from workers.qa.service import review_shot
from workers.qa.splice import plan_splice
from workers.qa.tests.conftest import MockGateway
from workers.schemas.asset import QAReport


def test_half_second_warp_is_vetoed(tmp_path: Path) -> None:
    anchor = _plate("rect")
    frames = [_plate("rect") for _ in range(8)]
    frames[4] = _plate("shear")
    frames[5] = _plate("pinch")
    path = tmp_path / "warp.mp4"
    write_mp4(frames, path, fps=4)
    sampled = sample_frames(path, fps=4)
    assert len(sampled) >= 6
    findings, good = inspect_frames(sampled, anchor=anchor, expected_faces=0)
    assert any(item.code == "product_deform" for item in findings)
    assert any(not flag for flag in good)
    anchor_path = tmp_path / "anchor.png"
    anchor.save(anchor_path)
    report = review_shot(
        {
            "project_id": "p",
            "shot_id": "S03",
            "node": "n11_video",
            "candidate_uri": str(path),
            "anchor_uri": str(anchor_path),
            "expected_faces": 0,
        },
        gateway=MockGateway(),
    )
    assert isinstance(report, QAReport)
    assert "product_deform" in report.hard_fail
    assert report.total < 7.5


def test_isolated_flash_is_flicker(tmp_path: Path) -> None:
    frames = [_plate("rect") for _ in range(6)]
    frames[3] = Image.new("RGB", frames[0].size, (245, 245, 245))
    path = tmp_path / "flash.mp4"
    write_mp4(frames, path, fps=4)
    findings, _good = inspect_frames(sample_frames(path), anchor=_plate("rect"))
    assert any(item.code == "flicker" for item in findings)


def test_splice_joins_complementary_clean_halves() -> None:
    clean = _plate("rect")
    bad = _plate("shear")
    left = [clean] * 4 + [bad] * 4
    right = [bad] * 4 + [clean] * 4
    left_good = [True] * 4 + [False] * 4
    right_good = [False] * 4 + [True] * 4
    plan = plan_splice(
        [("A", left_good, left), ("B", right_good, right)],
        fps=4,
    )
    assert plan is not None
    assert [(item.candidate_id, item.start_s, item.end_s) for item in plan] == [
        ("A", 0.0, 1.0),
        ("B", 1.0, 2.0),
    ]
