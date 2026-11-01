"""Original authorized pixels must survive packaging and an encoded master."""

from __future__ import annotations

import copy
import hashlib
import io
import subprocess
import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from workers.brand_kit.store import write_asset
from workers.media.packaging import safe_insets
from workers.media.raster import render_logo
from workers.nodes.n14_packaging.node import run
from workers.nodes.n14_packaging.qa import QAError
from workers.nodes.n14_packaging.tests.test_node import _brand, _brief, _script
from workers.nodes.n15_compose.node import run as compose


def original_logo() -> bytes:
    # This independent image is deliberately unlike the old circle-in-square mark.
    image = Image.new("RGBA", (100, 60))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 12, 43, 47), fill=(235, 31, 89, 255))
    draw.rectangle((44, 30, 79, 47), fill=(235, 31, 89, 255))
    draw.rectangle((55, 12, 79, 25), fill=(17, 201, 216, 255))
    draw.rectangle((25, 18, 35, 24), fill=(50, 80, 120, 120))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def payload(tmp_path: Path) -> dict:
    source = tmp_path / "authorized-logo.png"
    source.write_bytes(original_logo())
    brand = _brand()
    brand["logo"]["primary"] = str(source)
    script = _script(0.8, [])
    script["shots"][0]["voiceover"] = ""
    return {
        "script": script,
        "brand_kit": brand,
        "brief": _brief(12, ["抖音"]),
        "intro": "none",
        "width": 640,
        "height": 360,
        "work_dir": str(tmp_path / "packaging"),
    }


def test_native_logo_keeps_every_uploaded_pixel_and_its_source_evidence(tmp_path: Path) -> None:
    body = payload(tmp_path)
    result = run({"project_id": "logo", "payload": body})
    logo = next(item for item in result.payload["elements"] if item["kind"] == "outro_logo")
    with Image.open(logo["png_path"]) as actual, Image.open(io.BytesIO(original_logo())) as source:
        assert actual.size == source.size
        assert actual.tobytes() == source.tobytes()
    assert logo["spec"]["source_sha256"] == hashlib.sha256(original_logo()).hexdigest()
    assert result.payload["logo_status"] == "ready"
    assert not result.payload["preview_only"]
    corner = next(item for item in result.payload["elements"] if item["kind"] == "corner_logo")
    with Image.open(corner["png_path"]) as image:
        insets = safe_insets(["抖音"])
        assert corner["x_ratio"] + image.width / 640 <= 1 - insets.right + 1e-6
        assert corner["y_ratio"] >= insets.top
        assert abs(image.width / image.height - 100 / 60) < 0.06


def test_new_safety_padding_preserves_shape_and_alpha_without_upscaling() -> None:
    source = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
    ImageDraw.Draw(source).rectangle((0, 0, 119, 39), fill=(20, 160, 90, 170))
    stream = io.BytesIO()
    source.save(stream, format="PNG")
    image = render_logo(stream.getvalue(), max_width=500, max_height=500, safe_area_ratio=0.2)
    box = image.getchannel("A").getbbox()
    assert box is not None
    assert image.crop(box).tobytes() == source.tobytes()
    assert min(box[0] / image.width, box[1] / image.height) >= 0.2
    assert image.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize("fault", ["missing", "corrupt", "transparent", "outside", "unsafe_ratio"])
def test_declared_logo_failure_is_explicit_and_preserves_previous_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    body = payload(tmp_path)
    source = Path(body["brand_kit"]["logo"]["primary"])
    previous = tmp_path / "packaging" / "logo.png"
    previous.parent.mkdir()
    previous.write_bytes(b"previous-render")
    if fault == "missing":
        source.unlink()
    elif fault == "corrupt":
        source.write_bytes(b"broken image")
    elif fault == "transparent":
        Image.new("RGBA", (10, 10)).save(source)
    elif fault == "outside":
        monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "different-root"))
    else:
        body["brand_kit"]["logo"]["safe_area_ratio"] = 0.8
    with pytest.raises(QAError, match="logo"):
        run({"project_id": "logo", "payload": body}, max_attempts=1)
    assert previous.read_bytes() == b"previous-render"


def test_brand_scheme_requires_the_same_enterprise(tmp_path: Path) -> None:
    body = payload(tmp_path)
    owner = str(uuid.uuid4())
    body["brand_kit"]["logo"]["primary"] = write_asset(owner, "logo.png", original_logo())
    for enterprise in (None, str(uuid.uuid4())):
        body["enterprise_id"] = enterprise
        with pytest.raises(QAError, match="enterprise"):
            run({"project_id": "logo", "payload": body}, max_attempts=1)
    body["enterprise_id"] = owner
    assert run({"project_id": "logo", "payload": body}).payload["logo_status"] == "ready"


@pytest.mark.parametrize("mock", [False, True])
def test_missing_or_mock_brand_remains_an_explicit_unbranded_preview(
    tmp_path: Path, mock: bool
) -> None:
    body = payload(tmp_path)
    if mock:
        body["brand_kit"]["logo"]["primary"] = "mock://logo/default"
    else:
        body["brand_kit"] = None
    packed = run({"project_id": "logo", "payload": body})
    expected = "mock" if mock else "missing"
    assert packed.payload["logo_status"] == expected
    assert packed.payload["preview_only"]
    assert not any("logo" in item["kind"] for item in packed.payload["elements"])
    result = compose(
        {
            "project_id": "logo",
            "payload": {
                **body,
                "elements": packed.payload["elements"],
                "outro_s": packed.payload["outro_s"],
                "work_dir": str(tmp_path / "edit"),
            },
        },
        max_attempts=1,
    )
    assert result.payload["logo_status"] == expected
    assert result.payload["preview_only"]


def test_encoded_master_contains_original_colored_shape_and_transparent_holes(
    tmp_path: Path,
) -> None:
    body = payload(tmp_path)
    original = copy.deepcopy(body)
    packed = run({"project_id": "logo", "payload": body})
    result = compose(
        {
            "project_id": "logo",
            "payload": {
                **body,
                "elements": packed.payload["elements"],
                "outro_s": packed.payload["outro_s"],
                "work_dir": str(tmp_path / "edit"),
            },
        },
        max_attempts=1,
    )
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "1.3",
            "-i",
            result.payload["exports"]["master"],
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=20,
    ).stdout
    frame = Image.open(io.BytesIO(raw)).convert("RGB")
    x, y = (640 - 100) // 2, round(360 * 0.34 - 60 / 2)
    for dx, dy, rgb in ((25, 35, (235, 31, 89)), (65, 18, (17, 201, 216))):
        actual = frame.getpixel((x + dx, y + dy))
        assert max(abs(a - b) for a, b in zip(actual, rgb, strict=True)) < 16
    background = frame.getpixel((x - 5, y + 5))
    transparent = frame.getpixel((x + 5, y + 5))
    assert max(abs(a - b) for a, b in zip(background, transparent, strict=True)) < 6
    assert body == original
