"""AI label ink, not its font em, scales with actual export pixels."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from workers.compliance.label_measure import glyph_ink_height, minimum_glyph_px
from workers.media.ffmpeg import encode_plate, playable, probe
from workers.media.packaging import Insets, aspect_size, safe_insets
from workers.nodes.n17_deliver.layout import _ai_mark, _place_label
from workers.nodes.n17_deliver.node import run
from workers.nodes.n17_deliver.qa import QAError
from workers.nodes.n17_deliver.sample import acceptance_request

ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "4:5", "21:9")


@pytest.mark.parametrize("aspect", ASPECTS)
@pytest.mark.parametrize("edge", [1280, 3840])
def test_default_and_4k_labels_meet_real_ink_height_inside_platform_safe_area(aspect, edge):
    width, height = aspect_size(aspect, edge)
    safe = safe_insets(["视频号", "抖音"])
    image = _ai_mark(width, height, safe)
    assert glyph_ink_height(image) >= minimum_glyph_px(min(width, height))
    x, y = _place_label(image, width, height, safe)
    assert x >= int(safe.left * width)
    assert y >= int(safe.top * height)
    assert x + image.width <= (1 - safe.right) * width
    assert y + image.height <= (1 - safe.bottom) * height


def test_an_impossible_safe_area_still_fails_instead_of_shrinking_the_label():
    with pytest.raises(QAError, match="5%"):
        _ai_mark(1280, 960, Insets(top=0.1, bottom=0.1, left=0.49, right=0.49))


def test_portrait_fifteen_second_source_exports_full_size_four_by_three_with_valid_ink(
    tmp_path, gateway, monkeypatch
):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    raw = acceptance_request(
        tmp_path,
        project_id="large-label",
        languages=["zh"],
        aspect_ratios=["4:3"],
        long_edge=1280,
        with_tracks=False,
    )
    payload = raw["payload"]
    clean = Path(payload["picture_path"])
    encode_plate(clean, rgb=(24, 36, 52), width=720, height=1280, frames=450, fps=30)
    for index, shot in enumerate(payload["script"]["shots"], start=1):
        shot.update(order=index, duration_s=6.3, on_screen_text=[])
    payload["brief"].update(duration_s=15, aspect_ratios=["9:16"], platform=["视频号", "抖音"])
    payload.update(
        brand_kit=None,
        target_duration_s=15,
        intro_s=0,
        outro_s=2.4,
        durations_s=[15],
        source_timeline={
            "width": 720,
            "height": 1280,
            "fps": 30,
            "duration_s": 15,
            "target_duration_s": 15,
            "lut_path": "unused",
            "work_dir": str(clean.parent),
            "audio": [],
            "overlays": [],
            "audio_provenance": "mock",
            "logo_status": "missing",
            "clips": [
                {
                    "clip_id": "S01",
                    "path": str(clean),
                    "start_s": 0,
                    "duration_s": 6.3,
                    "placeholder": True,
                },
                {
                    "clip_id": "S02",
                    "path": str(clean),
                    "start_s": 6.3,
                    "duration_s": 6.3,
                    "placeholder": True,
                },
                {"clip_id": "outro", "path": str(clean), "start_s": 12.6, "duration_s": 2.4},
            ],
        },
    )
    version = run(raw, gateway=gateway, max_attempts=1).payload["versions"][0]
    path = Path(version["path"])
    info = probe(path)
    assert (info["width"], info["height"]) == (1280, 960)
    assert abs(info["duration_s"] - 15) <= 1 / 30
    playable(path)
    box = next(item for item in version["overlays"] if item["kind"] == "ai_label")
    decoded = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.1",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"crop={box['w']}:{box['h']}:{box['x']}:{box['y']}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout
    image = Image.frombytes("RGB", (box["w"], box["h"]), decoded)
    assert glyph_ink_height(image) >= minimum_glyph_px(960)
    assert version["qa_status"] == "needs_review"
    assert version["media_provenance"] == "mock"
